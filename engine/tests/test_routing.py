"""
Tests for the search.

WHY THIS EXISTS
    Every expected number here was worked out on paper from the diagrams in
    fixtures.py. None was produced by running the search and writing down what
    it said — a test whose expectation came from the implementation proves
    only that the implementation agrees with itself, which is precisely the
    assurance the 2021 code appeared to have.

    The one that matters most is test_the_same_network_can_be_searched_twice.
    Line 532 was `unseenNodes = self.graph`, an alias rather than a copy, and
    line 557 popped from it — so one search emptied the graph and a second
    found nothing. It survived five years because nothing ever searched twice.

NO 2021 EQUIVALENT
    There were no tests, and writing one meant first building a SQLite file
    with the right tables, because the graph builder opened its own cursor.

CONSTRAINT
    No database, no server, no Docker. If that ever stops being true,
    something has gone wrong in engine/.
"""

from fixtures import (
    change_is_worth_avoiding,
    diamond,
    one_way_pair,
    single_station,
    straight_line,
    two_islands,
    two_lines,
)

from tube_engine import NoRoute, Route, RouteQuery, find_route


def route_between(network: object, origin: str, destination: str) -> Route | NoRoute:
    return find_route(network, RouteQuery(origin=origin, destination=destination))  # type: ignore[arg-type]


def test_a_straight_line_is_one_leg_with_no_changes() -> None:
    # A --60-- B --120-- C --60-- D, all on red. 60 + 120 + 60 = 240.
    result = route_between(straight_line(), "A", "D")

    assert isinstance(result, Route)
    assert result.total_seconds == 240
    assert result.changes == 0
    assert len(result.legs) == 1
    assert result.legs[0].line == "red"
    assert result.legs[0].stations == ("A", "B", "C", "D")


def test_the_cheaper_of_two_routes_wins() -> None:
    # Via B costs 120, via C costs 200. Both are on red, so this isolates the
    # search's choice from anything to do with changing.
    result = route_between(diamond(), "A", "D")

    assert isinstance(result, Route)
    assert result.total_seconds == 120
    assert result.legs[0].stations == ("A", "B", "D")


def test_a_change_costs_what_the_interchange_says() -> None:
    # A --60-- B on red, B --60-- D on blue, changing at B costs 90.
    # 60 + 90 + 60 = 210. A station-only graph would answer 120 and be wrong
    # by the entire cost of changing — which is why nodes are (station, line).
    result = route_between(two_lines(), "A", "D")

    assert isinstance(result, Route)
    assert result.total_seconds == 210
    assert result.changes == 1


def test_legs_are_split_at_the_change_and_exclude_the_walk() -> None:
    result = route_between(two_lines(), "A", "D")

    assert isinstance(result, Route)
    assert [(leg.line, leg.stations, leg.seconds) for leg in result.legs] == [
        ("red", ("A", "B"), 60),
        ("blue", ("B", "D"), 60),
    ]
    # 60 + 60 riding, 90 walking. The interchange belongs to the total, not to
    # either leg — it is time spent walking rather than travelling.
    assert sum(leg.seconds for leg in result.legs) == 120
    assert result.total_seconds == 210
    assert result.changes == len(result.legs) - 1


def test_an_expensive_change_makes_the_longer_ride_the_faster_route() -> None:
    # Staying on red costs 200. Changing at B costs 60 + 300 + 60 = 420.
    # Only a search that prices the change can tell, and getting this wrong is
    # invisible — both answers look like routes.
    result = route_between(change_is_worth_avoiding(), "A", "D")

    assert isinstance(result, Route)
    assert result.total_seconds == 200
    assert result.changes == 0
    assert result.legs[0].stations == ("A", "C", "D")


def test_the_same_network_can_be_searched_twice() -> None:
    """The regression test for the 2021 aliasing bug.

    `unseenNodes = self.graph` at line 532 aliased the graph; `pop` at line
    557 emptied it. The second search on the same object traversed nothing.
    """
    network = straight_line()
    query = RouteQuery(origin="A", destination="D")

    first = find_route(network, query)
    second = find_route(network, query)

    assert first == second
    # And the graph is intact afterwards, not merely the answer.
    assert len(network) == 4
    assert network.edges_from("A") != ()


def test_two_islands_are_disconnected_not_an_error() -> None:
    # The 2021 database in miniature: two Central line branches and the whole
    # Overground sat unreachable, and nothing ever asked.
    result = route_between(two_islands(), "A", "C")

    assert result == NoRoute("disconnected")


def test_one_way_track_has_no_route_back() -> None:
    # Modelled on the Heathrow terminal loop. Storing edges undirected would
    # have invented a return journey that does not exist.
    assert isinstance(route_between(one_way_pair(), "A", "B"), Route)
    assert route_between(one_way_pair(), "B", "A") == NoRoute("disconnected")


def test_unknown_stations_say_which_one_was_unknown() -> None:
    # A station that does not exist is a different problem from two that are
    # not connected, and a caller wants different words in front of a user.
    network = straight_line()

    assert route_between(network, "NOWHERE", "D") == NoRoute("unknown_origin")
    assert route_between(network, "A", "NOWHERE") == NoRoute("unknown_destination")


def test_origin_equal_to_destination_is_an_empty_route_not_an_error() -> None:
    # "You are already there" is a correct answer to a reasonable question —
    # the same reasoning that made an empty station search a 200 in Phase 3.
    result = route_between(straight_line(), "B", "B")

    assert result == Route(legs=(), total_seconds=0, changes=0, step_free=True)


def test_a_single_station_network_does_not_crash() -> None:
    network = single_station()

    assert route_between(network, "A", "A") == Route()
    assert route_between(network, "A", "B") == NoRoute("unknown_destination")


def test_a_route_is_step_free_only_if_every_part_of_it_is() -> None:
    # Reporting step-free is not the same as routing on it — routing on it is
    # Phase 5. But a route that used one inaccessible hop must not claim to be
    # step-free, because that is the error that strands someone.
    from fixtures import ride, station

    from tube_engine import Network

    accessible = Network(
        stations=[station("A"), station("B")],
        edges=ride("A", "B", "red", 60),
        interchanges=[],
    )
    with_a_step = Network(
        stations=[station("A"), station("B")],
        edges=ride("A", "B", "red", 60, step_free=False),
        interchanges=[],
    )

    assert route_between(accessible, "A", "B").step_free is True  # type: ignore[union-attr]
    assert route_between(with_a_step, "A", "B").step_free is False  # type: ignore[union-attr]
