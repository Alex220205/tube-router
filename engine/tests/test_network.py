"""
Tests for the graph itself.

WHY THIS EXISTS
    Network has one job — answer adjacency questions quickly and never change
    — and the second half is the one worth testing. The 2021 search destroyed
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
    graph builder, so writing one meant first building a SQLite file — which
    is exactly why none exists.

CONSTRAINT
    Runs with no database, no server and no Docker. If that ever stops being
    true, something has gone wrong in engine/.
"""

import pytest
from fixtures import diamond, one_way_pair, single_station, straight_line, two_lines


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
    # arrive at still has to report its line — otherwise every route ending at
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
