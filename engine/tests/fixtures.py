"""Small networks with answers worked out by hand."""

from tube_engine.network import Network
from tube_engine.types import Edge, Interchange, Station


def station(station_id: str) -> Station:
    """A station at a throwaway position. Coordinates are not routed on."""
    return Station(
        id=station_id,
        name=f"{station_id} Station",
        lat=51.5,
        lon=-0.1,
    )


# Spelled out per fixture rather than defaulted to "all accessible", because a default
# here would make the step-free tests pass for the wrong reason - the interesting cases
# are the ones where a platform is missing.
def every_platform(network_lines: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Declare which platforms are step-free, as {station: [lines]}."""
    platforms = []
    for station_id, lines in network_lines.items():
        for line in lines:
            platforms.append((station_id, line))
    return platforms


# Mirrored by default because most track runs both ways and writing each direction out
# doubles the noise in every fixture. `both_ways=False` is for the cases where the
# asymmetry is the point.
def ride(
    origin: str,
    destination: str,
    line: str,
    seconds: int,
    *,
    both_ways: bool = True,
) -> list[Edge]:
    """One hop, mirrored unless told otherwise."""
    forward = Edge(
        origin=origin,
        destination=destination,
        line=line,
        seconds=seconds,
    )
    if not both_ways:
        return [forward]
    return [
        forward,
        Edge(
            origin=destination,
            destination=origin,
            line=line,
            seconds=seconds,
        ),
    ]


def change(
    at: str, from_line: str, to_line: str, seconds: int, *, step_free: bool = True
) -> list[Interchange]:
    """A line change, in both directions with the same cost."""
    return [
        Interchange(
            station=at,
            from_line=from_line,
            to_line=to_line,
            seconds=seconds,
            step_free=step_free,
        ),
        Interchange(
            station=at,
            from_line=to_line,
            to_line=from_line,
            seconds=seconds,
            step_free=step_free,
        ),
    ]


# A --60-- B --120-- C --60-- D        all on `red`
#
# A to D is the only route: 60 + 120 + 60 = 240 seconds, one leg, no changes.
def straight_line() -> Network:
    """Four stations on one line."""
    return Network(
        stations=[station(s) for s in "ABCD"],
        edges=[
            *ride("A", "B", "red", 60),
            *ride("B", "C", "red", 120),
            *ride("C", "D", "red", 60),
        ],
        interchanges=[],
    )


# --60-- B --60--
#          /                \
#         A                  D            all on `red`
#          \                /
#           -100-- C --100-
#
# A to D via B is 120. Via C it is 200. Nothing branches onto another line, so the only
# thing being tested is that the search picks the cheaper path rather than the first one
# it finds.
def diamond() -> Network:
    """Two routes between the same pair, one cheaper."""
    return Network(
        stations=[station(s) for s in "ABCD"],
        edges=[
            *ride("A", "B", "red", 60),
            *ride("B", "D", "red", 60),
            *ride("A", "C", "red", 100),
            *ride("C", "D", "red", 100),
        ],
        interchanges=[],
    )


# A --60-- B --60-- C          on `red`
#              B --60-- D          on `blue`
#     change at B: red <-> blue, 90 seconds
#
# A to D is 60 + 90 + 60 = 210 seconds, two legs, one change. A search on a station-only
# graph would report 120 and be wrong by the entire cost of changing - which is why
# nodes are (station, line) pairs.
def two_lines() -> Network:
    """A change is required, and it costs something."""
    return Network(
        stations=[station(s) for s in "ABCD"],
        edges=[
            *ride("A", "B", "red", 60),
            *ride("B", "C", "red", 60),
            *ride("B", "D", "blue", 60),
        ],
        interchanges=change("B", "red", "blue", 90),
    )


# A --100-- C --100-- D        on `red`,  total 200
#     A --60--- B                  on `red`
#               B --60--- D        on `blue`
#     change at B: red <-> blue, 300 seconds
#
# Staying on `red` costs 200. Changing at B costs 60 + 300 + 60 = 420. The
# direct-looking route is the slow one, and only a search that prices the change can
# tell.
def change_is_worth_avoiding() -> Network:
    """A longer ride that beats a shorter one because changing is expensive."""
    return Network(
        stations=[station(s) for s in "ABCD"],
        edges=[
            *ride("A", "C", "red", 100),
            *ride("C", "D", "red", 100),
            *ride("A", "B", "red", 60),
            *ride("B", "D", "blue", 60),
        ],
        interchanges=change("B", "red", "blue", 300),
    )


# A --60-- B          on `red`
#     C --60-- D          on `blue`
#
# A to C is unreachable.
def two_islands() -> Network:
    """Two pairs with no track between them."""
    return Network(
        stations=[station(s) for s in "ABCD"],
        edges=[*ride("A", "B", "red", 60), *ride("C", "D", "blue", 60)],
        interchanges=[],
    )


# A --60--> B          on `red`, outbound only
#
# Modelled on the Heathrow terminal loop. B to A has no route at all.
def one_way_pair() -> Network:
    """Track that runs in one direction only."""
    return Network(
        stations=[station("A"), station("B")],
        edges=ride("A", "B", "red", 60, both_ways=False),
        interchanges=[],
    )


def single_station() -> Network:
    """One station, no track. The degenerate case."""
    return Network(stations=[station("A")], edges=[], interchanges=[])


# A --30-- B --30-- C --30-- D     red, blue, yellow in turn
#     change at B: red <-> blue,   20 seconds
#     change at C: blue <-> yellow, 20 seconds
#
#     A ------------300------------ D  on `green`, one hop
#
# Fastest:         30 + 20 + 30 + 20 + 30 = 130 seconds, two changes.
# Fewest changes:  300 seconds, no changes.
#
# This is the fixture that proves the feature exists. If both objectives returned the
# same route here, FEWEST_CHANGES would be FASTEST wearing a different name and every
# test of it would still pass.
def fastest_differs_from_fewest_changes() -> Network:
    """The two objectives genuinely disagree."""
    return Network(
        stations=[station(s) for s in "ABCD"],
        edges=[
            *ride("A", "B", "red", 30),
            *ride("B", "C", "blue", 30),
            *ride("C", "D", "yellow", 30),
            *ride("A", "D", "green", 300),
        ],
        interchanges=[
            *change("B", "red", "blue", 20),
            *change("C", "blue", "yellow", 20),
        ],
        # Everything accessible, so all three objectives return a route here and the
        # invariants can be asserted across them. The interesting step-free cases live
        # in their own fixtures below.
        step_free_platforms=every_platform(
            {
                "A": ["red", "green"],
                "B": ["red", "blue"],
                "C": ["blue", "yellow"],
                "D": ["yellow", "green"],
            }
        ),
    )


# A --100-- B --100-- D            on `red`,   200 seconds, no change
#     A --90--- C                      on `blue`
#               C --90--- D            on `green`
#     change at C: blue <-> green, 20 seconds
#
# Both come to 200 seconds. Fastest has nothing to choose between them on time, so
# without a tie-break the answer depends on heap ordering - which means it depends on
# station ids rather than on the question.
def equally_fast_one_needs_a_change() -> Network:
    """Two routes of identical duration, one of which changes line."""
    return Network(
        stations=[station(s) for s in "ABCD"],
        edges=[
            *ride("A", "B", "red", 100),
            *ride("B", "D", "red", 100),
            *ride("A", "C", "blue", 90),
            *ride("C", "D", "green", 90),
        ],
        interchanges=change("C", "blue", "green", 20),
    )


# A --60--- B --60-- D     on `red`,   120 seconds
#     A --150-- C --150- D     on `blue`,  300 seconds
#
#     step-free platforms: A on both lines, C and D on blue.
#     D's `red` platform is NOT step-free, and B has nothing accessible.
#
# Fastest:    120 seconds on red, ending at a platform you cannot leave.
# Step-free:  300 seconds on blue, which you can. No change is needed -
#             A is on both lines, so the search simply starts on blue.
#
# Note that the red route is not removed from the graph. The rides are fine; you just
# cannot get out at the far end. That is exactly the distinction the both-ends edge
# model could not express, because it deleted the rides instead.
def step_free_is_slower() -> Network:
    """An accessible route exists, and costs more than the quick one."""
    return Network(
        stations=[station(s) for s in "ABCD"],
        edges=[
            *ride("A", "B", "red", 60),
            *ride("B", "D", "red", 60),
            *ride("A", "C", "blue", 150),
            *ride("C", "D", "blue", 150),
        ],
        interchanges=[],
        step_free_platforms=every_platform(
            {"A": ["red", "blue"], "C": ["blue"], "D": ["blue"]}
        ),
    )


# A --60-- B --60-- D     on `red`
#     A --60-- C --60-- D     on `blue`
#
#     step-free platforms: A and B on red, A and C on blue. D: none.
#
# The correct answer is NoRoute("disconnected") - not "unknown_destination", which would
# be the engine claiming a station that exists does not.
def step_free_is_impossible() -> Network:
    """D is real, reachable, and has no accessible platform."""
    return Network(
        stations=[station(s) for s in "ABCD"],
        edges=[
            *ride("A", "B", "red", 60),
            *ride("B", "D", "red", 60),
            *ride("A", "C", "blue", 60),
            *ride("C", "D", "blue", 60),
        ],
        interchanges=[],
        step_free_platforms=every_platform(
            {"A": ["red", "blue"], "B": ["red"], "C": ["blue"]}
        ),
    )


# A --60-- B     on `red`
#     step-free platforms: B only.
#
# You cannot board. The mirror of step_free_is_impossible, and the case a model that
# only checked the destination would get wrong.
def inaccessible_origin() -> Network:
    """The destination is accessible; the origin is not."""
    return Network(
        stations=[station("A"), station("B")],
        edges=ride("A", "B", "red", 60),
        interchanges=[],
        step_free_platforms=every_platform({"B": ["red"]}),
    )
