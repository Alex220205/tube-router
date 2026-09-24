"""
Populate the database from the TfL Unified API.

    cd backend && uv run python seed.py

WHY THIS EXISTS
    A one-off script, deliberately outside app/ because it is not part of the
    running service and nothing in app/ imports it. It fetches, transforms,
    writes and then checks - four steps in that order, each of which can be
    read on its own.

WHAT THE 2021 VERSION DID
    Where:  database[works].py, the Add*database methods
    How:    Data was fetched from TfL and inserted in the same functions that
            drew the user interface, with the SQL inline and no verification
            afterwards.
    Wrong:  docs/AUDIT.md has the full account. The short version: the
            database ended up 70.5% connected with two Central line branches
            unreachable, 12 links stored as zero minutes, no coordinates at
            all, and an Overground with 85 stations and no track. None of it
            was detectable, because nothing ever asked.

WHAT CHANGED AND WHY
    Drops and reloads, so it can be run as often as you like. Every insert is
    in one transaction, so a failure leaves the previous contents rather than
    a half-built network. And it refuses to report success unless the checks
    in services/seed_checks.py pass.

WHAT'S NEW
    The data source. The 2021 database is no longer the input - it is the
    artifact this is measured against.
"""

import asyncio
import sys

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.models import (
    Interchange,
    Line,
    Segment,
    Station,
    StationComplex,
    StationLine,
    TransportMode,
)
from app.services import graph_loader, seed_checks
from app.services.seed import (
    StationLineRow,
    StationRow,
    complexes_from_stations,
    durations_from_timetable,
    interchange_distances,
    interchanges_from_station_lines,
    lines_from_payload,
    segments_from_sequences,
    station_lines_from_sequences,
    stations_from_stop_points,
    step_free_by_station_line,
    stop_sequences,
)
from app.services.tfl import StationData, TfLClient, TfLError

DIRECTIONS = ("inbound", "outbound")


# The seed makes a few hundred requests, and silence during them is
# indistinguishable from a hang.
def log(message: str) -> None:
    """Print one line of progress, flushed immediately."""
    print(message, flush=True)


# One timetable per branch, requested from that branch's first station. A
# line's branches have separate timetables, and asking only from the terminus
# would leave every branch but one without durations.
async def _durations_for_payload(
    tfl: TfLClient, code: str, payload: dict
) -> dict[tuple[str, str], int]:
    """Adjacent-station durations for every branch in one route sequence."""
    found: dict[tuple[str, str], int] = {}
    for stops in stop_sequences([payload]):
        origin = stops[0]["id"]
        try:
            timetable = await tfl.timetable(code, origin)
        except TfLError as exc:
            # Some branch/direction combinations have no timetable. Those
            # segments fall back to a default, which the seed reports; they
            # are not a reason to abandon the run.
            log(f"  no timetable from {origin}: {exc}")
            continue
        found.update(durations_from_timetable(timetable, origin))
    return found


# The raw payloads, untransformed. Keeping fetch separate from
# transform is what lets the transforms be tested without a network.
async def fetch_everything(tfl: TfLClient) -> dict[str, object]:
    """Collect every payload the seed needs, in as few requests as possible."""
    log("fetching lines ...")
    lines_payload = await tfl.tube_lines()
    line_codes = [line["id"] for line in lines_payload]
    log(f"  {len(line_codes)} lines: {', '.join(line_codes)}")

    sequences: dict[str, list[dict]] = {}
    stop_points: dict[str, list[dict]] = {}
    durations: dict[tuple[str, str], int] = {}

    for code in line_codes:
        log(f"fetching {code} ...")
        stop_points[code] = await tfl.stop_points(code)
        payloads = []
        for direction in DIRECTIONS:
            payload = await tfl.route_sequence(code, direction)
            payloads.append(payload)
            durations.update(await _durations_for_payload(tfl, code, payload))

        sequences[code] = payloads

    log("fetching station accessibility data ...")
    station_data = await tfl.station_data()
    log(
        f"  {len(station_data.platform_services)} platform rows, "
        f"{len(station_data.step_free_interchanges)} measured interchanges"
    )

    return {
        "lines": lines_payload,
        "sequences": sequences,
        "stop_points": stop_points,
        "durations": durations,
        "station_data": station_data,
    }


# Delete in dependency order. CASCADE would do it, but naming the order makes
# the dependencies visible and means a new table cannot be quietly forgotten
# here.
async def _clear(session: AsyncSession) -> None:
    """Empty every network table, children first."""
    log("clearing existing data ...")
    for model in (Interchange, StationLine, Segment, Station, StationComplex, Line):
        await session.execute(delete(model))


# Each step returns the id map the later ones need. Postgres assigns those ids
# on flush, so they can only be learned by asking for them back.
async def _write_lines(session: AsyncSession, payload: object) -> dict[str, int]:
    """Write every line and return its code to database id."""
    line_rows = lines_from_payload(payload)
    session.add_all(
        [
            Line(
                code=row.code, name=row.name, mode=TransportMode.TUBE, colour=row.colour
            )
            for row in line_rows
        ]
    )
    await session.flush()
    line_ids = {
        code: id_
        for id_, code in (await session.execute(select(Line.id, Line.code))).all()
    }
    log(f"  {len(line_ids)} lines")
    return line_ids


async def _write_complexes(
    session: AsyncSession, station_rows: list[StationRow]
) -> dict[str, int]:
    """Write the station complexes and return each TfL hub id to its row id."""
    complex_rows = complexes_from_stations(station_rows)
    session.add_all(
        [
            StationComplex(name=row.name, tfl_hub_id=row.tfl_hub_id)
            for row in complex_rows
        ]
    )
    await session.flush()
    complex_ids = {
        hub: id_
        for id_, hub in (
            await session.execute(select(StationComplex.id, StationComplex.tfl_hub_id))
        ).all()
    }
    log(f"  {len(complex_ids)} station complexes")
    return complex_ids


async def _write_stations(
    session: AsyncSession, station_rows: list[StationRow], complex_ids: dict[str, int]
) -> dict[str, int]:
    """Write every station and return its NaPTAN id to database id."""
    session.add_all(
        [
            Station(
                naptan_id=row.naptan_id,
                name=row.name,
                # EWKT, which is what GeoAlchemy2 accepts for a geography
                # column. Longitude first: that is the axis order 4326 uses
                # here, and getting it backwards puts London in the Indian
                # Ocean without any error.
                location=f"SRID=4326;POINT({row.lon} {row.lat})",
                complex_id=complex_ids.get(row.hub_id) if row.hub_id else None,
            )
            for row in station_rows
        ]
    )
    await session.flush()
    station_ids = {
        naptan: id_
        for id_, naptan in (
            await session.execute(select(Station.id, Station.naptan_id))
        ).all()
    }
    log(f"  {len(station_ids)} stations")
    return station_ids


# The rows are returned as well as written, because the interchange step is
# derived from them rather than read back out of the table.
async def _write_station_lines(
    session: AsyncSession,
    sequences: dict[str, list[dict]],
    station_data: StationData,
    station_ids: dict[str, int],
    line_ids: dict[str, int],
) -> list[StationLineRow]:
    """Write which lines call at which stations."""
    step_free = step_free_by_station_line(station_data.platform_services)
    station_line_rows = station_lines_from_sequences(sequences, step_free)
    session.add_all(
        [
            StationLine(
                station_id=station_ids[row.naptan_id],
                line_id=line_ids[row.line_code],
                step_free_to_platform=row.step_free_to_platform,
            )
            for row in station_line_rows
            if row.naptan_id in station_ids and row.line_code in line_ids
        ]
    )
    await session.flush()
    accessible = sum(1 for row in station_line_rows if row.step_free_to_platform)
    log(f"  {len(station_line_rows)} station/line pairs, {accessible} step-free")
    return station_line_rows


# A segment with an end that is not among the stations just written is
# skipped rather than failing the run. Stations come from /StopPoints and
# segments from the route sequences, two separate TfL payloads, and
# seed_checks afterwards confirms every segment still joins two real stations
# and the network is one piece.
async def _write_segments(
    session: AsyncSession,
    sequences: dict[str, list[dict]],
    durations: dict[tuple[str, str], int],
    station_ids: dict[str, int],
    line_ids: dict[str, int],
) -> None:
    """Write the track between adjacent stations, line by line."""
    total_adjusted = 0
    segment_count = 0
    for code, payloads in sequences.items():
        rows, adjusted = segments_from_sequences(code, payloads, durations)
        total_adjusted += adjusted
        usable = [
            row
            for row in rows
            if row.origin_naptan in station_ids
            and row.destination_naptan in station_ids
        ]
        session.add_all(
            [
                Segment(
                    line_id=line_ids[code],
                    origin_station_id=station_ids[row.origin_naptan],
                    destination_station_id=station_ids[row.destination_naptan],
                    seconds=row.seconds,
                )
                for row in usable
            ]
        )
        segment_count += len(usable)
    await session.flush()
    log(f"  {segment_count} segments, {total_adjusted} floored or defaulted")


async def _write_interchanges(
    session: AsyncSession,
    station_data: StationData,
    station_line_rows: list[StationLineRow],
    station_ids: dict[str, int],
    line_ids: dict[str, int],
) -> None:
    """Write the cost of changing between every pair of lines at a station."""
    distances = interchange_distances(station_data.step_free_interchanges)
    interchange_rows = interchanges_from_station_lines(station_line_rows, distances)
    session.add_all(
        [
            Interchange(
                station_id=station_ids[row.naptan_id],
                from_line_id=line_ids[row.from_line_code],
                to_line_id=line_ids[row.to_line_code],
                seconds=row.seconds,
                step_free=row.step_free,
            )
            for row in interchange_rows
            if row.naptan_id in station_ids
            and row.from_line_code in line_ids
            and row.to_line_code in line_ids
        ]
    )
    await session.flush()
    measured = sum(1 for row in interchange_rows if row.step_free)
    log(f"  {len(interchange_rows)} interchanges, {measured} with a measured distance")


# Everything happens in the caller's transaction, so a failure anywhere leaves
# the previous contents intact rather than a half-built network.
#
# The order below is the dependency order. Nothing here moves without breaking
# the id map the next step reads.
async def write_everything(session: AsyncSession, raw: dict[str, object]) -> None:
    """Replace the contents of the database with a freshly built network."""
    sequences: dict[str, list[dict]] = raw["sequences"]
    durations: dict[tuple[str, str], int] = raw["durations"]
    station_data: StationData = raw["station_data"]

    await _clear(session)
    line_ids = await _write_lines(session, raw["lines"])

    station_rows = stations_from_stop_points(raw["stop_points"])
    complex_ids = await _write_complexes(session, station_rows)
    station_ids = await _write_stations(session, station_rows, complex_ids)

    station_line_rows = await _write_station_lines(
        session, sequences, station_data, station_ids, line_ids
    )
    await _write_segments(session, sequences, durations, station_ids, line_ids)
    await _write_interchanges(
        session, station_data, station_line_rows, station_ids, line_ids
    )


# 0 when every check passed, 1 otherwise. A non-zero exit is what makes
# this usable from a script or from CI.
async def main() -> int:
    """Fetch, write, check."""
    settings = get_settings()
    log(f"seeding {settings.database_url.rsplit('@', 1)[-1]}")

    async with TfLClient(
        base_url=settings.tfl_base_url,
        app_key=settings.tfl_app_key,
        timeout_seconds=settings.tfl_timeout_seconds,
        max_attempts=settings.tfl_max_attempts,
        # Without this the run gets through about a third of the lines and
        # then TfL starts returning 429.
        min_request_interval_seconds=settings.tfl_min_request_interval_seconds,
    ) as tfl:
        raw = await fetch_everything(tfl)

    async with SessionLocal() as session:
        async with session.begin():
            await write_everything(session, raw)
        log("committed")

        await _tell_running_api()

        log("\nchecks:")
        results = await seed_checks.run_all(session)

    await engine.dispose()
    return _report(results)


# The API holds a built routing graph. Deleting the row cache is not enough on
# its own - a process that has already built its graph never looks at Redis
# again, so Phase 6 shipped an invalidation that did nothing for a running
# service (docs/ISSUES.md #9).
#
# Bumping the generation is what a running process actually notices, within
# graph_loader.GENERATION_CHECK_SECONDS. The rows go too, or the rebuild would
# read the stale copy it was just told to discard.
async def _tell_running_api() -> None:
    """Make a running API rebuild its graph from what was just written."""
    await cache.delete(graph_loader.CACHE_KEY)
    generation = await cache.bump_generation()
    if generation is None:
        log("WARNING: could not reach Redis; a running API will serve the")
        log("         old network until it is restarted")
    else:
        log(f"network generation now {generation}")


def _report(results: list[seed_checks.CheckResult]) -> int:
    """Print each check and return the exit code: 0 if all passed, 1 if not."""
    failed = [result for result in results if not result.passed]
    for result in results:
        mark = "PASS" if result.passed else "FAIL"
        log(f"  [{mark}] {result.name} - {result.detail}")

    if failed:
        log(f"\n{len(failed)} check(s) failed. The data is not usable.")
        return 1
    log("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
