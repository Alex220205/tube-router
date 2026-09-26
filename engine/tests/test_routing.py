"""Tests for the search."""

from fixtures import (
    change_is_worth_avoiding,
    diamond,
    equally_fast_one_needs_a_change,
    fastest_differs_from_fewest_changes,
    inaccessible_origin,
    one_way_pair,
    single_station,
    step_free_is_impossible,
    step_free_is_slower,
    straight_line,
    two_islands,
    two_lines,
)

from tube_engine import (
    Leg,
    Network,
    NoRoute,
    Objective,
    Route,
    RouteQuery,
    find_route,
)


def route_between(
    network: Network,
    origin: str,
    destination: str,
    objective: Objective = Objective.FASTEST,
    avoid: frozenset[str] = frozenset(),
) -> Route | NoRoute:
    """Plan a route between two stations with the given objective."""
    return find_route(
        network,
        RouteQuery(
            origin=origin,
            destination=destination,
            objective=objective,
            avoid_lines=avoid,
        ),
    )


def test_a_straight_line_is_one_leg_with_no_changes() -> None:
    """A straight line is one leg with no changes."""
    # A --60-- B --120-- C --60-- D, all on red. 60 + 120 + 60 = 240.
    result = route_between(straight_line(), "A", "D")

    assert isinstance(result, Route)
    assert result.total_seconds == 240
    assert result.changes == 0
    assert len(result.legs) == 1
    assert result.legs[0].line == "red"
    assert result.legs[0].stations == ("A", "B", "C", "D")


def test_the_cheaper_of_two_routes_wins() -> None:
    """The cheaper of two routes wins."""
    # Via B costs 120, via C costs 200. Both are on red, so this isolates the search's
    # choice from anything to do with changing.
    result = route_between(diamond(), "A", "D")

    assert isinstance(result, Route)
    assert result.total_seconds == 120
    assert result.legs[0].stations == ("A", "B", "D")


def test_a_change_costs_what_the_interchange_says() -> None:
    """A change costs what the interchange says."""
    # A --60-- B on red, B --60-- D on blue, changing at B costs 90.
    # 60 + 90 + 60 = 210. A station-only graph would answer 120 and be wrong
    # by the entire cost of changing - which is why nodes are (station, line).
    result = route_between(two_lines(), "A", "D")

    assert isinstance(result, Route)
    assert result.total_seconds == 210
    assert result.changes == 1


def test_legs_are_split_at_the_change_and_exclude_the_walk() -> None:
    """Legs are split at the change and exclude the walk."""
    result = route_between(two_lines(), "A", "D")

    assert isinstance(result, Route)
    assert [(leg.line, leg.stations, leg.seconds) for leg in result.legs] == [
        ("red", ("A", "B"), 60),
        ("blue", ("B", "D"), 60),
    ]
    # 60 + 60 riding, 90 walking. The interchange belongs to the total, not to either
    # leg - it is time spent walking rather than travelling.
    assert sum(leg.seconds for leg in result.legs) == 120
    assert result.total_seconds == 210
    assert result.changes == len(result.legs) - 1


def test_an_expensive_change_makes_the_longer_ride_the_faster_route() -> None:
    """An expensive change makes the longer ride the faster route."""
    # Staying on red costs 200. Changing at B costs 60 + 300 + 60 = 420. Only a search
    # that prices the change can tell, and getting this wrong is invisible - both
    # answers look like routes.
    result = route_between(change_is_worth_avoiding(), "A", "D")

    assert isinstance(result, Route)
    assert result.total_seconds == 200
    assert result.changes == 0
    assert result.legs[0].stations == ("A", "C", "D")


def test_the_same_network_can_be_searched_twice() -> None:
    """A search leaves the network intact for the next one."""
    network = straight_line()
    query = RouteQuery(origin="A", destination="D")

    first = find_route(network, query)
    second = find_route(network, query)

    assert first == second
    # And the graph is intact afterwards, not merely the answer.
    assert len(network) == 4
    assert network.edges_from("A") != ()


def test_two_islands_are_disconnected_not_an_error() -> None:
    """Two islands are disconnected, not an error."""
    result = route_between(two_islands(), "A", "C")

    assert result == NoRoute("disconnected")


def test_one_way_track_has_no_route_back() -> None:
    """One-way track has no route back."""
    # Modelled on the Heathrow terminal loop. Storing edges undirected would have
    # invented a return journey that does not exist.
    assert isinstance(route_between(one_way_pair(), "A", "B"), Route)
    assert route_between(one_way_pair(), "B", "A") == NoRoute("disconnected")


def test_unknown_stations_say_which_one_was_unknown() -> None:
    """Unknown stations say which one was unknown."""
    # A station that does not exist is a different problem from two that are not
    # connected, and a caller wants different words in front of a user.
    network = straight_line()

    assert route_between(network, "NOWHERE", "D") == NoRoute("unknown_origin")
    assert route_between(network, "A", "NOWHERE") == NoRoute("unknown_destination")


def test_origin_equal_to_destination_is_an_empty_route_not_an_error() -> None:
    """Origin equal to destination is an empty route, not an error."""
    result = route_between(straight_line(), "B", "B")

    assert result == Route(legs=(), total_seconds=0, changes=0, step_free=True)


def test_a_single_station_network_does_not_crash() -> None:
    """A single station network does not crash."""
    network = single_station()

    assert route_between(network, "A", "A") == Route()
    assert route_between(network, "A", "B") == NoRoute("unknown_destination")


# Quick route: 30 + 20 + 30 + 20 + 30 = 130 seconds across three lines. Direct route:
# 300 seconds on one.
def test_fastest_and_fewest_changes_return_different_routes() -> None:
    """The test that proves FEWEST_CHANGES exists."""
    network = fastest_differs_from_fewest_changes()

    quickest = route_between(network, "A", "D")
    simplest = route_between(network, "A", "D", Objective.FEWEST_CHANGES)

    assert isinstance(quickest, Route)
    assert isinstance(simplest, Route)

    assert (quickest.total_seconds, quickest.changes) == (130, 2)
    assert (simplest.total_seconds, simplest.changes) == (300, 0)
    assert [leg.line for leg in quickest.legs] == ["red", "blue", "yellow"]
    assert [leg.line for leg in simplest.legs] == ["green"]


# Snaresbrook to Barons Court returned 48 minutes with three changes while a 48-minute
# route with one change existed. Both are optimal by time, so the search was returning
# whichever it reached first - an answer decided by heap ordering rather than by the
# question.
def test_fastest_breaks_ties_on_fewest_changes() -> None:
    """The mirror of the test below, and it came from the real network."""
    result = route_between(equally_fast_one_needs_a_change(), "A", "D")

    assert isinstance(result, Route)
    assert result.total_seconds == 200
    assert result.changes == 0
    assert [leg.line for leg in result.legs] == ["red"]


def test_fewest_changes_breaks_ties_on_time() -> None:
    """Fewest changes breaks ties on time."""
    # Both routes through the diamond stay on `red`, so both have zero changes. Without
    # a tie-break the answer would depend on heap ordering and could differ between
    # runs; the second element of the cost tuple is what makes it 120 every time.
    result = route_between(diamond(), "A", "D", Objective.FEWEST_CHANGES)

    assert isinstance(result, Route)
    assert result.total_seconds == 120
    assert result.legs[0].stations == ("A", "B", "D")


def test_fewest_changes_still_reports_the_real_journey_time() -> None:
    """Fewest changes still reports the real journey time."""
    result = route_between(
        fastest_differs_from_fewest_changes(), "A", "D", Objective.FEWEST_CHANGES
    )

    assert isinstance(result, Route)
    assert result.total_seconds == 300
    assert sum(leg.seconds for leg in result.legs) == 300


def test_changes_matches_the_leg_count_under_every_objective() -> None:
    """The changes count matches the leg count under every objective."""
    # Derived rather than counted, so the two cannot drift apart. Asserted for all three
    # because each takes a different path through _build_route.
    network = fastest_differs_from_fewest_changes()

    for objective in Objective:
        result = route_between(network, "A", "D", objective)

        assert isinstance(result, Route), objective
        assert result.changes == len(result.legs) - 1, objective


def test_the_step_free_route_is_slower_and_both_are_real() -> None:
    """The step-free route is slower and both are real."""
    # 120 seconds via B crosses a step; 300 via C does not. Both are genuine routes,
    # which is the point - a step-free search that quietly returned the fastest one
    # would look correct until somebody relied on it.
    network = step_free_is_slower()

    quickest = route_between(network, "A", "D")
    accessible = route_between(network, "A", "D", Objective.STEP_FREE)

    assert isinstance(quickest, Route)
    assert isinstance(accessible, Route)

    assert quickest.total_seconds == 120
    assert quickest.step_free is False
    assert accessible.total_seconds == 300
    assert accessible.step_free is True
    assert accessible.legs[0].stations == ("A", "C", "D")


def test_step_free_that_cuts_the_destination_off_is_disconnected() -> None:
    """A step-free query that cuts the destination off is disconnected."""
    # Every way into D crosses a step. D still exists, so the honest answer is
    # "disconnected" - reporting "unknown_destination" would have the engine denying a
    # station it can see, and that is why step_free_only() keeps every station rather
    # than filtering them too.
    result = route_between(step_free_is_impossible(), "A", "D", Objective.STEP_FREE)

    assert result == NoRoute("disconnected")
    assert isinstance(route_between(step_free_is_impossible(), "A", "D"), Route)


def test_avoiding_a_line_forces_the_other_route() -> None:
    """Avoiding a line forces the other route."""
    network = fastest_differs_from_fewest_changes()

    unrestricted = route_between(network, "A", "D")
    detour = route_between(network, "A", "D", avoid=frozenset({"blue"}))

    assert isinstance(unrestricted, Route)
    assert isinstance(detour, Route)
    assert unrestricted.total_seconds == 130
    assert detour.total_seconds == 300
    assert [leg.line for leg in detour.legs] == ["green"]


def test_avoiding_every_line_is_a_no_route_rather_than_a_crash() -> None:
    """Avoiding every line is a NoRoute rather than a crash."""
    network = fastest_differs_from_fewest_changes()

    result = route_between(
        network, "A", "D", avoid=frozenset({"red", "blue", "yellow", "green"})
    )

    assert result == NoRoute("disconnected")


def test_a_fastest_route_reports_step_free_honestly() -> None:
    """A fastest route reports step-free honestly."""
    # step_free is reported for every objective, not only STEP_FREE, and it must not
    # over-claim. The fastest route here ends on red at D, whose red platform is
    # inaccessible - so the answer is a route that is not step-free, rather than no
    # answer.
    result = route_between(step_free_is_slower(), "A", "D")

    assert isinstance(result, Route)
    assert result.total_seconds == 120
    assert result.step_free is False


def test_an_inaccessible_origin_has_no_step_free_route() -> None:
    """An inaccessible origin has no step-free route."""
    # The mirror of the destination case. A model that only checked where you were going
    # would pass every test above and still tell someone who cannot reach the platform
    # that their journey is step-free.
    network = inaccessible_origin()

    assert isinstance(route_between(network, "A", "B"), Route)
    assert route_between(network, "A", "B", Objective.STEP_FREE) == NoRoute(
        "disconnected"
    )
    # And the other way round, where boarding is possible but alighting is not.
    assert route_between(network, "B", "A", Objective.STEP_FREE) == NoRoute(
        "disconnected"
    )


# Two of 6006 real routes reported a total their own legs could not account for. The
# cause was in the seed - interchange costs that did not obey the triangle inequality,
# so a chained walk undercut the direct one by a second and the zero-length leg it
# produced was silently dropped here.
def test_the_legs_and_the_changes_account_for_the_whole_total() -> None:
    """Every route's legs and changes account for its total."""
    network = fastest_differs_from_fewest_changes()

    for objective in Objective:
        result = route_between(network, "A", "D", objective)
        assert isinstance(result, Route), objective

        riding = sum(leg.seconds for leg in result.legs)
        changing = sum(
            _interchange_between(network, before, after)
            for before, after in zip(result.legs, result.legs[1:], strict=False)
        )

        assert riding + changing == result.total_seconds, objective


def _interchange_between(network: Network, before: Leg, after: Leg) -> int:
    """The cost of the change joining two legs, looked up from the graph."""
    station_id = before.stations[-1]
    for interchange in network.interchanges_at(station_id):
        if interchange.from_line == before.line and interchange.to_line == after.line:
            return interchange.seconds
    raise AssertionError(
        f"no interchange at {station_id} from {before.line} to {after.line}"
    )
