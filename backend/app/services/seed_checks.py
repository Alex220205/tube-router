"""The checks that run at the end of every seed."""

from collections import defaultdict, deque
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class CheckResult:
    """One post-seed check: its name, whether it passed, and why."""

    name: str
    passed: bool
    detail: str


async def run_all(session: AsyncSession) -> list[CheckResult]:
    """Run every post-seed check."""
    return [
        await _stations_have_coordinates(session),
        await _segments_reference_real_stations(session),
        await _every_line_has_segments(session),
        await _naptan_ids_are_unique(session),
        await _durations_are_positive(session),
        await _every_station_serves_a_line(session),
        await _graph_is_connected(session),
    ]


async def _scalar(session: AsyncSession, sql: str) -> int:
    """Run a counting query and return the single number it produces."""
    result = await session.execute(text(sql))
    return int(result.scalar_one())


async def _stations_have_coordinates(session: AsyncSession) -> CheckResult:
    """Check that every station has a location."""
    missing = await _scalar(
        session, "SELECT count(*) FROM stations WHERE location IS NULL"
    )
    return CheckResult(
        "every station has coordinates",
        missing == 0,
        f"{missing} without a location",
    )


async def _segments_reference_real_stations(session: AsyncSession) -> CheckResult:
    """Check that every segment starts and ends at a real station."""
    orphans = await _scalar(
        session,
        """
        SELECT count(*) FROM segments s
        LEFT JOIN stations o ON o.id = s.origin_station_id
        LEFT JOIN stations d ON d.id = s.destination_station_id
        WHERE o.id IS NULL OR d.id IS NULL
        """,
    )
    # Foreign keys make this impossible in Postgres. Checked anyway, because confirming
    # it costs one query.
    return CheckResult(
        "every segment points at two real stations", orphans == 0, f"{orphans} orphaned"
    )


async def _every_line_has_segments(session: AsyncSession) -> CheckResult:
    """Check that no line was written without any track."""
    empty = await _scalar(
        session,
        """
        SELECT count(*) FROM lines l
        WHERE NOT EXISTS (SELECT 1 FROM segments s WHERE s.line_id = l.id)
        """,
    )
    return CheckResult(
        "every line has at least one segment",
        empty == 0,
        f"{empty} lines with no track",
    )


async def _naptan_ids_are_unique(session: AsyncSession) -> CheckResult:
    """Check that no NaPTAN id appears twice."""
    duplicates = await _scalar(
        session,
        "SELECT count(*) FROM (SELECT naptan_id FROM stations "
        "GROUP BY naptan_id HAVING count(*) > 1) AS d",
    )
    return CheckResult(
        "no duplicate stations", duplicates == 0, f"{duplicates} duplicated NaPTAN ids"
    )


# A zero-second segment tells the router a journey is free.
async def _durations_are_positive(session: AsyncSession) -> CheckResult:
    """Check that every segment takes a positive number of seconds."""
    bad = await _scalar(
        session,
        "SELECT (SELECT count(*) FROM segments WHERE seconds <= 0) "
        "+ (SELECT count(*) FROM interchanges WHERE seconds <= 0)",
    )
    return CheckResult(
        "no free journeys", bad == 0, f"{bad} rows with a non-positive duration"
    )


async def _every_station_serves_a_line(session: AsyncSession) -> CheckResult:
    """Check that no station is stranded without a line."""
    stranded = await _scalar(
        session,
        """
        SELECT count(*) FROM stations s
        WHERE NOT EXISTS (SELECT 1 FROM station_lines sl WHERE sl.station_id = s.id)
        """,
    )
    return CheckResult(
        "every station is on a line",
        stranded == 0,
        f"{stranded} stations serve no line",
    )


# Treated as undirected: the question is whether the network hangs together, not whether
# every individual segment has a reverse. A station you can reach but never leave is
# caught by the directional checks elsewhere.
async def _graph_is_connected(session: AsyncSession) -> CheckResult:
    """Check that the network is one connected piece."""
    result = await session.execute(
        text("SELECT origin_station_id, destination_station_id FROM segments")
    )
    edges = result.all()
    total = await _scalar(session, "SELECT count(*) FROM stations")

    if total == 0:
        return CheckResult("the graph is one connected piece", False, "no stations")

    adjacency: dict[int, set[int]] = defaultdict(set)
    for origin, destination in edges:
        adjacency[origin].add(destination)
        adjacency[destination].add(origin)

    start = next(iter(adjacency), None)
    if start is None:
        return CheckResult("the graph is one connected piece", False, "no segments")

    seen = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for neighbour in adjacency[node]:
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)

    reachable = len(seen)
    percent = reachable / total * 100
    return CheckResult(
        "the graph is one connected piece",
        reachable == total,
        f"{reachable}/{total} stations reachable ({percent:.1f}%)",
    )
