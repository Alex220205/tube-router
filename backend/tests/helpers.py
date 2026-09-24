"""
Builders shared by the database tests.

WHY THIS EXISTS
    So a test reads as its scenario rather than its setup. A line, a station
    and track in both directions are where nearly every database test starts,
    and building them in one place means a fix here reaches every test that
    uses them.

    Everything a test asserts on - a colour, a name, a coordinate - is passed
    by the test that asserts it, never left to a default here. A default is
    for the values nobody checks.

NO 2021 EQUIVALENT
    The old project had no tests.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Line, Segment, Station, TransportMode


async def a_line(
    db: AsyncSession, code: str = "victoria", *, colour: str = "#000000"
) -> Line:
    """Insert a tube line with the given code and return it."""
    line = Line(code=code, name=code.title(), mode=TransportMode.TUBE, colour=colour)
    db.add(line)
    await db.flush()
    return line


# Keyword-only past the id, because two floats in a row is exactly how
# longitude and latitude get swapped - and a swapped station is still a valid
# row, just one in the wrong hemisphere.
async def a_station(
    db: AsyncSession,
    naptan_id: str,
    *,
    name: str | None = None,
    lon: float = -0.1,
    lat: float = 51.5,
) -> Station:
    """Insert a station at the given point and return it."""
    station = Station(
        naptan_id=naptan_id,
        name=name or naptan_id,
        location=f"SRID=4326;POINT({lon} {lat})",
    )
    db.add(station)
    await db.flush()
    return station


# Both directions at the same time, as the real seed writes most track. A test
# about asymmetry adds its two segments itself.
async def both_ways(
    db: AsyncSession,
    line: Line,
    origin: Station,
    destination: Station,
    seconds: int = 120,
) -> None:
    """Join two stations on a line with track in both directions."""
    db.add_all(
        [
            Segment(
                line_id=line.id,
                origin_station_id=origin.id,
                destination_station_id=destination.id,
                seconds=seconds,
            ),
            Segment(
                line_id=line.id,
                origin_station_id=destination.id,
                destination_station_id=origin.id,
                seconds=seconds,
            ),
        ]
    )
    await db.flush()
