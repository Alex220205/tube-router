"""
Tests for the graph itself.

WHY THIS EXISTS
    Network has one job - answer adjacency questions quickly and never change
    - and the second half is the one worth testing. The 2021 search destroyed
    the graph it was searching: line 532 aliased it instead of copying, line
    557 popped from it, so a second search on the same object traversed
    nothing. Nobody noticed for five years because nothing ever searched
    twice.

    The full regression test for that lives in test_routing.py, because it
    needs a search to run. What is tested here is the property underneath it:
    lookups hand back tuples rather than the internal lists, so a caller
    cannot edit the graph by accident in the first place.

NO 2021 EQUIVALENT
    There were no tests. Create_graph opened a database cursor inside the
    graph builder, so writing one meant first building a SQLite file - which
    is exactly why none exists.

CONSTRAINT
    Runs with no database, no server and no Docker. If that ever stops being
    true, something has gone wrong in engine/.
"""

import pytest
from fixtures import (
    change,
    diamond,
    one_way_pair,
    ride,
    single_station,
    station,
    step_free_is_slower,
    straight_line,
    two_lines,
)

from tube_engine import Network


def test_adjacency_is_indexed_by_origin() -> None:
    network = straight_line()

    destinations = {edge.destination for edge in network.edges_from("B")}

    # B sits between A and C, so both directions leave it.
    assert destinations == {"A", "C"}


def test_edges_from_an_unknown_station_is_empty_not_an_error() -> None:
    # "What leaves from here" has a correct answer for a station that does not
    # exist, and it is "nothing". Raising would push a None check into every
    # caller for a case the search already handles.
    assert straight_line().edges_from("NOWHERE") == ()
    assert straight_line().interchanges_at("NOWHERE") == ()


def test_lines_at_includes_a_terminus() -> None:
    # The search seeds itself from lines_at(origin), so a station you can only
    # arrive at still has to report its line - otherwise every route ending at
    # a terminus would be unreachable.
    network = one_way_pair()

    assert network.lines_at("A") == frozenset({"red"})
    assert network.lines_at("B") == frozenset({"red"})


def test_lines_at_reports_every_line_serving_a_station() -> None:
    network = two_lines()

    assert network.lines_at("B") == frozenset({"red", "blue"})
    assert network.lines_at("D") == frozenset({"blue"})


def test_adjacency_cannot_be_mutated_through_what_is_returned() -> None:
    # Tuples rather than the internal lists. A caller appending to a returned
    # list would be editing the graph, which is the shape of the 2021 defect
    # even if the mechanism differs.
    network = straight_line()

    with pytest.raises(AttributeError):
        network.edges_from("A").append("anything")  # type: ignore[attr-defined]


def test_membership_and_size_report_the_stations_given() -> None:
    network = single_station()

    assert "A" in network
    assert "B" not in network
    assert len(network) == 1


def test_a_station_that_does_not_exist_raises_rather_than_returning_none() -> None:
    # Callers reach this only after find_route has already checked membership,
    # so a miss here means a bug in the engine rather than bad input. A None
    # would defer that failure to somewhere less informative.
    with pytest.raises(KeyError):
        diamond().station("NOWHERE")


def test_step_free_only_keeps_every_station_and_every_ride() -> None:
    """Rides survive the filter, which is the whole correction of Phase 6.

    You need no accessible route at a station you stay on the train through,
    so filtering rides by the accessibility of their endpoints removes
    journeys that are perfectly possible - it left 123 of 754 real rides.
    What a step-free journey needs is an accessible origin platform,
    accessible changes, and an accessible destination platform.

    Keeping every station matters for a second reason: dropping D would turn
    "you cannot get there step-free" into "that station does not exist".
    """
    network = step_free_is_slower()

    accessible = network.step_free_only()

    assert len(accessible) == len(network) == 4
    assert "D" in accessible
    # Every ride is still there, including the one into an inaccessible
    # platform - you simply will not be able to get out at the far end.
    assert {edge.destination for edge in accessible.edges_from("B")} == {"A", "D"}


def test_step_free_only_drops_a_change_that_is_not_step_free() -> None:
    # The changes are the part it does filter, and the part the search cannot
    # check for itself once the route is assembled.
    network = Network(
        stations=[station("A"), station("B")],
        edges=[*ride("A", "B", "red", 60), *ride("A", "B", "blue", 60)],
        interchanges=[
            *change("A", "red", "blue", 60, step_free=False),
            *change("B", "red", "blue", 60),
        ],
    )

    accessible = network.step_free_only()

    assert accessible.interchanges_at("A") == ()
    assert accessible.interchanges_at("B") != ()


def test_platform_accessibility_is_per_line_not_per_station() -> None:
    # Green Park is step-free on the Victoria line and not on the Piccadilly.
    # A station-level flag would have to pick one and be wrong about the
    # other, which is why Station lost its step_free field in Phase 6.
    network = step_free_is_slower()

    assert network.step_free_at("D", "blue") is True
    assert network.step_free_at("D", "red") is False
    assert network.step_free_lines_at("D") == frozenset({"blue"})
    assert network.step_free_lines_at("B") == frozenset()


def test_without_lines_drops_an_interchange_when_either_side_names_the_line() -> None:
    # The easy mistake is filtering on from_line alone, which leaves changes
    # that deposit you on a line that is not running.
    network = two_lines()
    assert network.interchanges_at("B") != ()

    without_blue = network.without_lines(["blue"])

    assert without_blue.interchanges_at("B") == ()
    assert all(edge.line != "blue" for edge in without_blue.edges_from("B"))


def test_filtering_leaves_the_original_network_untouched() -> None:
    """The 2021 regression, in the place Phase 5 could reintroduce it.

    A filter that edited in place would make the graph depend on which query
    ran last - line 532's aliasing bug with a new spelling.
    """
    network = two_lines()
    edges_before = network.edges_from("B")
    changes_before = network.interchanges_at("B")

    network.without_lines(["blue"])
    network.step_free_only()

    assert network.edges_from("B") == edges_before
    assert network.interchanges_at("B") == changes_before
    assert len(network) == 4


def test_excluding_nothing_returns_an_equivalent_network() -> None:
    # Skipping the rebuild is safe only because nothing mutates. Asserted as
    # identity deliberately: if the shortcut is ever removed, this should be
    # reconsidered rather than silently costing a copy per request.
    network = two_lines()

    assert network.without_lines([]) is network


def test_the_filters_compose_in_either_order() -> None:
    # find_route applies avoid_lines then step_free_only. Order must not
    # matter, or the result would depend on an implementation detail of the
    # dispatch rather than on the query.
    network = step_free_is_slower()

    one_way = network.without_lines(["red"]).step_free_only()
    other_way = network.step_free_only().without_lines(["red"])

    assert one_way.edges_from("A") == other_way.edges_from("A")
    assert one_way.edges_from("C") == other_way.edges_from("C")
    assert len(one_way) == len(other_way)
