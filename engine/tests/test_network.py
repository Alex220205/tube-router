"""Tests for the graph itself."""

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
    """Adjacency is indexed by origin."""
    network = straight_line()

    destinations = {edge.destination for edge in network.edges_from("B")}

    # B sits between A and C, so both directions leave it.
    assert destinations == {"A", "C"}


def test_edges_from_an_unknown_station_is_empty_not_an_error() -> None:
    """edges_from() on an unknown station is empty, not an error."""
    # "What leaves from here" has a correct answer for a station that does not exist,
    # and it is "nothing". Raising would push a None check into every caller for a case
    # the search already handles.
    assert straight_line().edges_from("NOWHERE") == ()
    assert straight_line().interchanges_at("NOWHERE") == ()


def test_lines_at_includes_a_terminus() -> None:
    """lines_at() includes a terminus."""
    # The search seeds itself from lines_at(origin), so a station you can only arrive at
    # still has to report its line - otherwise every route ending at a terminus would be
    # unreachable.
    network = one_way_pair()

    assert network.lines_at("A") == frozenset({"red"})
    assert network.lines_at("B") == frozenset({"red"})


def test_lines_at_reports_every_line_serving_a_station() -> None:
    """lines_at() reports every line serving a station."""
    network = two_lines()

    assert network.lines_at("B") == frozenset({"red", "blue"})
    assert network.lines_at("D") == frozenset({"blue"})


def test_adjacency_cannot_be_mutated_through_what_is_returned() -> None:
    """Adjacency cannot be mutated through what is returned."""
    network = straight_line()

    with pytest.raises(AttributeError):
        network.edges_from("A").append("anything")


def test_membership_and_size_report_the_stations_given() -> None:
    """Membership and size report the stations given."""
    network = single_station()

    assert "A" in network
    assert "B" not in network
    assert len(network) == 1


def test_a_station_that_does_not_exist_raises_rather_than_returning_none() -> None:
    """A station that does not exist raises rather than returning None."""
    # Callers reach this only after find_route has already checked membership, so a miss
    # here means a bug in the engine rather than bad input. A None would defer that
    # failure to somewhere less informative.
    with pytest.raises(KeyError):
        diamond().station("NOWHERE")


# You need no accessible route at a station you stay on the train through, so filtering
# rides by the accessibility of their endpoints removes journeys that are perfectly
# possible - it left 123 of 754 real rides. What a step-free journey needs is an
# accessible origin platform, accessible changes, and an accessible destination
# platform.
def test_step_free_only_keeps_every_station_and_every_ride() -> None:
    """step_free_only() keeps every station and every ride."""
    network = step_free_is_slower()

    accessible = network.step_free_only()

    assert len(accessible) == len(network) == 4
    assert "D" in accessible
    # Every ride is still there, including the one into an inaccessible platform - you
    # simply will not be able to get out at the far end.
    assert {edge.destination for edge in accessible.edges_from("B")} == {"A", "D"}


def test_step_free_only_drops_a_change_that_is_not_step_free() -> None:
    """step_free_only() drops a change that is not step-free."""
    # The changes are the part it does filter, and the part the search cannot check for
    # itself once the route is assembled.
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
    """Platform accessibility is per line, not per station."""
    network = step_free_is_slower()

    assert network.step_free_at("D", "blue") is True
    assert network.step_free_at("D", "red") is False
    assert network.step_free_lines_at("D") == frozenset({"blue"})
    assert network.step_free_lines_at("B") == frozenset()


def test_without_lines_drops_an_interchange_when_either_side_names_the_line() -> None:
    """without_lines() drops an interchange when either side names the line."""
    # The easy mistake is filtering on from_line alone, which leaves changes that
    # deposit you on a line that is not running.
    network = two_lines()
    assert network.interchanges_at("B") != ()

    without_blue = network.without_lines(["blue"])

    assert without_blue.interchanges_at("B") == ()
    assert all(edge.line != "blue" for edge in without_blue.edges_from("B"))


# A filter that edited in place would make the graph depend on which query ran last.
def test_filtering_leaves_the_original_network_untouched() -> None:
    """Filtering returns a new network and leaves the original untouched."""
    network = two_lines()
    edges_before = network.edges_from("B")
    changes_before = network.interchanges_at("B")

    network.without_lines(["blue"])
    network.step_free_only()

    assert network.edges_from("B") == edges_before
    assert network.interchanges_at("B") == changes_before
    assert len(network) == 4


def test_excluding_nothing_returns_an_equivalent_network() -> None:
    """Excluding nothing returns an equivalent network."""
    # Skipping the rebuild is safe only because nothing mutates. Asserted as identity
    # deliberately: if the shortcut is ever removed, this should be reconsidered rather
    # than silently costing a copy per request.
    network = two_lines()

    assert network.without_lines([]) is network


def test_the_filters_compose_in_either_order() -> None:
    """The filters compose in either order."""
    # find_route applies avoid_lines then step_free_only. Order must not matter, or the
    # result would depend on an implementation detail of the dispatch rather than on the
    # query.
    network = step_free_is_slower()

    one_way = network.without_lines(["red"]).step_free_only()
    other_way = network.step_free_only().without_lines(["red"])

    assert one_way.edges_from("A") == other_way.edges_from("A")
    assert one_way.edges_from("C") == other_way.edges_from("C")
    assert len(one_way) == len(other_way)
