"""Tests for the TfL-payload-to-row transforms."""

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from app.services.seed import (
    DEFAULT_INTERCHANGE_SECONDS,
    DEFAULT_SEGMENT_SECONDS,
    MIN_SEGMENT_SECONDS,
    StationLineRow,
    StationRow,
    complexes_from_stations,
    durations_from_timetable,
    interchange_distances,
    interchanges_from_station_lines,
    lines_from_payload,
    parse_bool,
    parse_platform_id,
    segments_from_sequences,
    station_lines_from_sequences,
    stations_from_stop_points,
    step_free_by_station_line,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tfl"


def fixture(name: str) -> Any:
    """Load a recorded TfL response from the fixtures folder."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- booleans ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("TRUE", True),
        ("True", True),
        ("true", True),
        ("False", False),
        ("FALSE", False),
        # The two rows that actually exist in Platforms.csv with a trailing space. A
        # naive == "TRUE" comparison reads these correctly by luck; a naive == "FALSE"
        # would not.
        ("FALSE ", False),
        (" TRUE ", True),
        ("", False),
        (None, False),
        # Anything unrecognised is False. For step-free access that is the safe
        # direction: claiming a station is accessible when it is not is the failure that
        # strands someone.
        ("maybe", False),
    ],
)
def test_tfl_booleans_are_parsed_regardless_of_casing_or_padding(
    raw: str | None, expected: bool
) -> None:
    """TfL booleans are parsed regardless of casing or padding."""
    assert parse_bool(raw) is expected


# --- lines -------------------------------------------------------------------


def test_every_tube_line_becomes_a_row_with_a_colour() -> None:
    """Every tube line becomes a row with a colour."""
    rows = lines_from_payload(fixture("lines_tube.json"))

    assert len(rows) == 11
    assert {row.code for row in rows} >= {
        "victoria",
        "waterloo-city",
        "hammersmith-city",
    }
    # Colour is NOT NULL and has no API source, so every known line must be in the
    # hardcoded table.
    assert all(row.colour.startswith("#") for row in rows)
    victoria = next(row for row in rows if row.code == "victoria")
    assert victoria.colour == "#0098D4"
    assert victoria.name == "Victoria"


def test_an_unknown_line_gets_the_placeholder_colour_not_a_guess() -> None:
    """An unknown line gets the placeholder colour, not a guess."""
    rows = lines_from_payload([{"id": "monorail", "name": "Monorail"}])

    # Grey, so an unstyled line is visibly wrong on the map rather than quietly
    # plausible.
    assert rows[0].colour == "#767676"


# --- stations ----------------------------------------------------------------


def test_stations_are_deduplicated_by_naptan_across_lines() -> None:
    """Stations are deduplicated by NaPTAN across lines."""
    stops = fixture("stop_points_victoria.json")
    rows = stations_from_stop_points({"victoria": stops, "also-victoria": stops})

    assert len(rows) == len(stops)
    assert len({row.naptan_id for row in rows}) == len(rows)


def test_station_names_are_taken_verbatim() -> None:
    """Station names are taken verbatim."""
    rows = stations_from_stop_points({"victoria": fixture("stop_points_victoria.json")})
    names = {row.name for row in rows}

    assert "Green Park Underground Station" in names


def test_a_station_without_coordinates_fails_the_seed() -> None:
    """A station without coordinates fails the seed."""
    with pytest.raises(ValueError, match="no coordinates"):
        stations_from_stop_points(
            {
                "victoria": [
                    {"naptanId": "X", "commonName": "Nowhere", "lat": None, "lon": 1.0}
                ]
            }
        )


def test_an_empty_hub_code_becomes_null_not_an_empty_string() -> None:
    """An empty hub code becomes null, not an empty string."""
    rows = stations_from_stop_points(
        {
            "victoria": [
                {
                    "naptanId": "A",
                    "commonName": "A",
                    "lat": 1.0,
                    "lon": 2.0,
                    "hubNaptanCode": "",
                },
                {
                    "naptanId": "B",
                    "commonName": "B",
                    "lat": 1.0,
                    "lon": 2.0,
                    "hubNaptanCode": "HUBX",
                },
            ]
        }
    )

    assert rows[0].hub_id is None
    assert rows[1].hub_id == "HUBX"


# --- complexes ---------------------------------------------------------------


def test_stations_sharing_a_hub_become_one_complex() -> None:
    """Stations sharing a hub become one complex."""
    stations = [
        StationRow("A", "Bank Underground Station", 1.0, 1.0, "HUBBAN"),
        StationRow("B", "Monument Underground Station", 1.0, 1.0, "HUBBAN"),
        StationRow("C", "Pimlico Underground Station", 1.0, 1.0, None),
    ]

    complexes = complexes_from_stations(stations)

    assert len(complexes) == 1
    assert complexes[0].tfl_hub_id == "HUBBAN"
    # Named after its members, so it can be checked against TfL rather than being an
    # invented label.
    assert complexes[0].name == "Bank and Monument"


def test_real_victoria_stations_produce_real_hubs() -> None:
    """Real Victoria stations produce real hubs."""
    stations = stations_from_stop_points(
        {"victoria": fixture("stop_points_victoria.json")}
    )
    complexes = complexes_from_stations(stations)

    hubs = {row.tfl_hub_id for row in complexes}
    assert "HUBKGX" in hubs  # King's Cross St. Pancras


# --- step-free ---------------------------------------------------------------


def test_step_free_is_read_per_station_and_line() -> None:
    """Step-free is read per station and line."""
    # The finding that justifies putting the flag on station_lines rather than on
    # stations: two stations on the same line, different answers.
    rows = [
        {
            "StopAreaNaptanCode": "940GZZLUGPK",
            "Line": "victoria",
            "DesignatedLevelAccessPoint": "TRUE",
        },
        {
            "StopAreaNaptanCode": "940GZZLUPCO",
            "Line": "victoria",
            "DesignatedLevelAccessPoint": "False",
        },
    ]

    step_free = step_free_by_station_line(rows)

    assert step_free[("940GZZLUGPK", "victoria")] is True
    assert step_free[("940GZZLUPCO", "victoria")] is False


def test_one_accessible_platform_makes_the_station_step_free_for_that_line() -> None:
    """One accessible platform makes the station step-free for that line."""
    # A station has several platforms per line. One being a designated level access
    # point is what makes the journey possible.
    rows = [
        {
            "StopAreaNaptanCode": "X",
            "Line": "victoria",
            "DesignatedLevelAccessPoint": "False",
        },
        {
            "StopAreaNaptanCode": "X",
            "Line": "victoria",
            "DesignatedLevelAccessPoint": "TRUE",
        },
    ]

    assert step_free_by_station_line(rows)[("X", "victoria")] is True


def test_a_manual_ramp_counts_as_step_free() -> None:
    """A manual ramp counts as step-free."""
    # TfL publishes accessibility across two columns and treats both as step-free in its
    # own journey planner. Reading only DesignatedLevelAccessPoint drops roughly half
    # the accessible platforms and leaves the Central and Bakerloo with none at all,
    # which is not true of the real railway.
    rows = [
        {
            "StopAreaNaptanCode": "X",
            "Line": "central",
            "DesignatedLevelAccessPoint": "False",
            "LevelAccessByManualRamp": "TRUE",
        },
        {
            "StopAreaNaptanCode": "Y",
            "Line": "central",
            "DesignatedLevelAccessPoint": "False",
            "LevelAccessByManualRamp": "False",
        },
    ]

    result = step_free_by_station_line(rows)

    assert result[("X", "central")] is True
    # The counterweight: neither column set still means not step-free.
    assert result[("Y", "central")] is False


def test_step_free_from_the_real_csv() -> None:
    """Step-free platforms are read correctly from the real CSV."""
    text = (FIXTURES / "PlatformServices.csv").read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(text.splitlines()))

    step_free = step_free_by_station_line(rows)

    assert step_free[("940GZZLUGPK", "victoria")] is True
    assert step_free[("940GZZLUPCO", "victoria")] is False


# --- durations ---------------------------------------------------------------


def test_cumulative_arrival_times_become_adjacent_durations() -> None:
    """Cumulative arrival times become adjacent durations."""
    # timeToArrival counts from the origin, so adjacent gaps are differences. Reading
    # them as absolute would make every station further along the line look further from
    # its neighbour than it is.
    payload = {
        "timetable": {
            "routes": [
                {
                    "stationIntervals": [
                        {
                            "intervals": [
                                {"stopId": "B", "timeToArrival": 2.0},
                                {"stopId": "C", "timeToArrival": 4.0},
                                {"stopId": "D", "timeToArrival": 7.0},
                            ]
                        }
                    ]
                }
            ]
        }
    }

    durations = durations_from_timetable(payload, origin_naptan="A")

    assert durations[("A", "B")] == 120
    assert durations[("B", "C")] == 120
    assert durations[("C", "D")] == 180


def test_durations_from_the_real_victoria_timetable() -> None:
    """Durations are derived correctly from the real Victoria timetable."""
    durations = durations_from_timetable(
        fixture("timetable_victoria_wwl.json"), origin_naptan="940GZZLUWWL"
    )

    # Walthamstow Central -> Blackhorse Road, which the live API reports as
    # two minutes.
    assert durations[("940GZZLUWWL", "940GZZLUBLR")] == 120
    assert all(seconds >= 0 for seconds in durations.values())


def test_a_payload_with_no_timetable_yields_nothing_rather_than_failing() -> None:
    """A payload with no timetable yields nothing rather than failing."""
    # TfL returns this for some branch and direction combinations. The seed falls back
    # to a default rather than dying.
    assert durations_from_timetable({}, "A") == {}
    assert durations_from_timetable({"timetable": {"routes": []}}, "A") == {}


# --- segments ----------------------------------------------------------------


def test_consecutive_stops_become_directional_segments() -> None:
    """Consecutive stops become directional segments."""
    payload = {
        "stopPointSequences": [{"stopPoint": [{"id": "A"}, {"id": "B"}, {"id": "C"}]}]
    }

    rows, adjusted = segments_from_sequences(
        "victoria", [payload], {("A", "B"): 120, ("B", "C"): 180}
    )

    assert [(r.origin_naptan, r.destination_naptan, r.seconds) for r in rows] == [
        ("A", "B", 120),
        ("B", "C", 180),
    ]
    assert adjusted == 0


def test_segments_are_never_joined_across_branches() -> None:
    """Segments are never joined across branches."""
    payload = {
        "stopPointSequences": [
            {"branchId": 0, "stopPoint": [{"id": "A"}, {"id": "B"}]},
            {"branchId": 1, "stopPoint": [{"id": "X"}, {"id": "Y"}]},
        ]
    }

    rows, _ = segments_from_sequences("central", [payload], {})
    pairs = {(r.origin_naptan, r.destination_naptan) for r in rows}

    assert pairs == {("A", "B"), ("X", "Y")}
    assert ("B", "X") not in pairs


def test_a_zero_length_gap_is_floored_and_counted() -> None:
    """A zero-length gap is floored and counted."""
    payload = {"stopPointSequences": [{"stopPoint": [{"id": "A"}, {"id": "B"}]}]}

    rows, adjusted = segments_from_sequences("victoria", [payload], {("A", "B"): 0})

    assert rows[0].seconds == MIN_SEGMENT_SECONDS
    assert adjusted == 1


def test_a_segment_with_no_timetable_gets_the_default_and_is_counted() -> None:
    """A segment with no timetable gets the default and is counted."""
    payload = {"stopPointSequences": [{"stopPoint": [{"id": "A"}, {"id": "B"}]}]}

    rows, adjusted = segments_from_sequences("victoria", [payload], {})

    assert rows[0].seconds == DEFAULT_SEGMENT_SECONDS
    assert adjusted == 1


def test_a_repeated_stop_does_not_become_a_self_loop() -> None:
    """A repeated stop does not become a self-loop."""
    # TfL repeats a stop at some branch joins. The schema rejects a self-loop and it
    # would mean nothing anyway.
    payload = {
        "stopPointSequences": [{"stopPoint": [{"id": "A"}, {"id": "A"}, {"id": "B"}]}]
    }

    rows, _ = segments_from_sequences("victoria", [payload], {})

    assert all(r.origin_naptan != r.destination_naptan for r in rows)


def test_real_central_line_branches_produce_disjoint_segment_runs() -> None:
    """Real Central line branches produce disjoint segment runs."""
    payload = fixture("route_sequence_central_inbound.json")
    assert len(payload["stopPointSequences"]) > 1, "fixture should have branches"

    rows, _ = segments_from_sequences("central", [payload], {})

    # Every segment must come from within a single sequence.
    within = set()
    for sequence in payload["stopPointSequences"]:
        stops = [s["id"] for s in sequence["stopPoint"]]
        within |= set(zip(stops, stops[1:], strict=False))
    assert {(r.origin_naptan, r.destination_naptan) for r in rows} <= within


# --- interchanges ------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform_id", "expected"),
    [
        ("940GZZLUGPK-Plat03-NB-victoria", ("940GZZLUGPK", ["victoria"])),
        # The line code itself contains a hyphen.
        (
            "940GZZLUXXX-Plat01-EB-hammersmith-city",
            ("940GZZLUXXX", ["hammersmith-city"]),
        ),
        # One platform serving several lines.
        (
            "910GANERLEY-Plat01-NB-london-overground|national-rail",
            ("910GANERLEY", ["london-overground", "national-rail"]),
        ),
        ("nonsense", None),
        ("", None),
    ],
)
def test_platform_identifiers_are_parsed_into_station_and_lines(
    platform_id: str, expected: tuple[str, list[str]] | None
) -> None:
    """Platform identifiers are parsed into station and lines."""
    assert parse_platform_id(platform_id) == expected


def test_measured_distances_become_walk_times() -> None:
    """Measured distances become walk times."""
    rows = [
        {
            "FromPlatformUniqueId": "S-Plat01-NB-victoria",
            "ToPlatformUniqueId": "S-Plat02-SB-central",
            "DistanceInMetres": "240",
        }
    ]

    distances = interchange_distances(rows)

    assert distances[("S", "victoria", "central")] == 240


def test_a_distance_between_two_different_stations_is_not_an_interchange() -> None:
    """A distance between two different stations is not an interchange."""
    # That is what a station complex represents, not an interchange row.
    rows = [
        {
            "FromPlatformUniqueId": "A-Plat01-NB-victoria",
            "ToPlatformUniqueId": "B-Plat02-SB-central",
            "DistanceInMetres": "300",
        }
    ]

    assert interchange_distances(rows) == {}


def test_every_line_pair_at_a_station_gets_an_interchange_both_ways() -> None:
    """Every line pair at a station gets an interchange both ways."""
    station_lines = [
        StationLineRow("S", "victoria", True),
        StationLineRow("S", "central", False),
        StationLineRow("T", "victoria", True),
    ]

    rows = interchanges_from_station_lines(station_lines, {})

    pairs = {(r.naptan_id, r.from_line_code, r.to_line_code) for r in rows}
    # Both directions: the walk one way is not necessarily the walk back.
    assert pairs == {("S", "victoria", "central"), ("S", "central", "victoria")}
    # A station served by one line has nothing to change between.
    assert not any(r.naptan_id == "T" for r in rows)


def test_an_unmeasured_interchange_gets_the_stated_default() -> None:
    """An unmeasured interchange gets the stated default."""
    station_lines = [
        StationLineRow("S", "victoria", True),
        StationLineRow("S", "central", True),
    ]

    rows = interchanges_from_station_lines(station_lines, {})

    assert all(r.seconds == DEFAULT_INTERCHANGE_SECONDS for r in rows)


def test_an_unmeasured_change_between_accessible_platforms_is_step_free() -> None:
    """An unmeasured change between accessible platforms is step-free."""
    # Inferred, not measured: both platforms are step-free, so the change can normally
    # be made via the lifts.
    station_lines = [
        StationLineRow("S", "victoria", True),
        StationLineRow("S", "central", True),
    ]

    rows = interchanges_from_station_lines(station_lines, {})

    assert all(r.step_free is True for r in rows)


def test_a_change_touching_an_inaccessible_platform_is_not_step_free() -> None:
    """A change touching an inaccessible platform is not step-free."""
    # The counterweight, and the direction that matters. An inference that said yes
    # regardless would be worse than the rule it replaced: claiming a change is
    # accessible when it is not is the failure that strands someone mid-journey.
    station_lines = [
        StationLineRow("S", "victoria", True),
        StationLineRow("S", "central", False),
    ]

    rows = interchanges_from_station_lines(station_lines, {})

    assert all(r.step_free is False for r in rows)


def test_a_measured_interchange_uses_the_distance_and_is_step_free() -> None:
    """A measured interchange uses the distance and is step-free."""
    station_lines = [
        StationLineRow("S", "victoria", True),
        StationLineRow("S", "central", True),
    ]
    distances = {("S", "victoria", "central"): 240}

    rows = interchanges_from_station_lines(station_lines, distances)
    measured = next(r for r in rows if r.from_line_code == "victoria")
    unmeasured = next(r for r in rows if r.from_line_code == "central")

    assert measured.seconds == 200  # 240m at 1.2 m/s
    assert measured.step_free is True
    # The reverse direction has no measurement of its own.
    assert unmeasured.seconds == DEFAULT_INTERCHANGE_SECONDS


# TfL measures the same corridor whole and in halves: jubilee to victoria is 380 m, and
# jubilee to piccadilly to victoria is 220 + 160 - the same 380 m. Rounding each to
# whole seconds independently gives 317 direct against 183 + 133 = 316 decomposed, so
# the router could save a second by walking through a platform it never boards.
def test_a_chained_walk_never_undercuts_the_direct_one() -> None:
    """The real Green Park numbers, and the bug they caused."""
    station_lines = [
        StationLineRow("940GZZLUGPK", "jubilee", True),
        StationLineRow("940GZZLUGPK", "piccadilly", True),
        StationLineRow("940GZZLUGPK", "victoria", True),
    ]
    distances = {
        ("940GZZLUGPK", "jubilee", "victoria"): 380,
        ("940GZZLUGPK", "victoria", "jubilee"): 380,
        ("940GZZLUGPK", "jubilee", "piccadilly"): 220,
        ("940GZZLUGPK", "piccadilly", "jubilee"): 220,
        ("940GZZLUGPK", "piccadilly", "victoria"): 160,
        ("940GZZLUGPK", "victoria", "piccadilly"): 160,
    }

    rows = interchanges_from_station_lines(station_lines, distances)
    seconds = {(r.from_line_code, r.to_line_code): r.seconds for r in rows}

    # 317 direct would be beatable by 183 + 133. Closed to the shorter one.
    assert seconds[("jubilee", "victoria")] == 316
    assert seconds[("victoria", "jubilee")] == 316
    # The halves are untouched - nothing shorter runs through them.
    assert seconds[("jubilee", "piccadilly")] == 183
    assert seconds[("piccadilly", "victoria")] == 133

    # The property, stated directly: no two-step walk beats a one-step walk.
    for a, b in seconds:
        for via in {"jubilee", "piccadilly", "victoria"} - {a, b}:
            assert seconds[(a, b)] <= seconds[(a, via)] + seconds[(via, b)]


def test_closure_improves_a_default_that_has_a_measured_path_through() -> None:
    """Closure improves a default that has a measured path through."""
    # A pair with no measurement of its own would take the flat 180-second default, even
    # when two measured walks connect it in 120. The default is a stated guess and real
    # measurements should beat it.
    station_lines = [
        StationLineRow("S", "a", True),
        StationLineRow("S", "b", True),
        StationLineRow("S", "c", True),
    ]
    distances = {
        ("S", "a", "b"): 72,  # 60s
        ("S", "b", "c"): 72,  # 60s
    }

    rows = interchanges_from_station_lines(station_lines, distances)
    seconds = {(r.from_line_code, r.to_line_code): r.seconds for r in rows}

    assert seconds[("a", "c")] == 120
    # The reverse has no measured path at all, so it keeps the default.
    assert seconds[("c", "a")] == DEFAULT_INTERCHANGE_SECONDS


def test_no_interchange_is_instant() -> None:
    """No interchange is instant."""
    station_lines = [
        StationLineRow("S", "victoria", True),
        StationLineRow("S", "central", True),
    ]

    rows = interchanges_from_station_lines(
        station_lines, {("S", "victoria", "central"): 1}
    )

    # CHECK (seconds > 0) would reject zero, and a one-second interchange would make the
    # router treat changing as free.
    assert all(r.seconds >= 60 for r in rows)


# --- station lines -----------------------------------------------------------


def test_station_line_membership_comes_from_the_sequences() -> None:
    """Station line membership comes from the sequences."""
    sequences = {
        "victoria": [
            {"stopPointSequences": [{"stopPoint": [{"id": "A"}, {"id": "B"}]}]}
        ],
        "central": [
            {"stopPointSequences": [{"stopPoint": [{"id": "B"}, {"id": "C"}]}]}
        ],
    }

    rows = station_lines_from_sequences(sequences, {("B", "central"): True})

    pairs = {(r.naptan_id, r.line_code) for r in rows}
    assert pairs == {
        ("A", "victoria"),
        ("B", "victoria"),
        ("B", "central"),
        ("C", "central"),
    }
    b_central = next(r for r in rows if r.naptan_id == "B" and r.line_code == "central")
    b_victoria = next(
        r for r in rows if r.naptan_id == "B" and r.line_code == "victoria"
    )
    assert b_central.step_free_to_platform is True
    assert b_victoria.step_free_to_platform is False
