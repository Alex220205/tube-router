"""
Tests for the live status transforms.

WHY THIS EXISTS
    One decision in this file decides whether a user gets routed down a closed
    line: which severities mean "not running". Getting it too narrow sends
    someone to a suspended platform; too wide silently rewrites journeys over
    a delay that clears in twenty minutes.

    Both failures look like a working service from the outside, which is why
    the rule is tested in both directions rather than only the obvious one.

NO 2021 EQUIVALENT
    The old project stored service_status as a column and printed it. Status
    and the router never met - a suspended line was something you read about
    after being routed down it - so there was nothing of this kind to test.

CONSTRAINT
    Pure functions. No network, no database, no Redis. The fixture was
    captured from the live endpoint so a TfL outage is never a red build.
"""

import json
from pathlib import Path

from app.services.status import (
    GOOD_SERVICE,
    LineStatus,
    not_running,
    statuses_from_payload,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tfl" / "line_status.json"


def real_payload() -> list[dict]:
    """The recorded TfL line status response."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def line(code: str, severity: int, description: str = "x", reason: str | None = None):
    """One line's worth of TfL's shape, for the cases the capture cannot show."""
    return {
        "id": code,
        "lineStatuses": [
            {
                "statusSeverity": severity,
                "statusSeverityDescription": description,
                "reason": reason,
            }
        ],
    }


def test_the_real_payload_reads_as_eleven_lines() -> None:
    """The real payload reads as eleven lines."""
    # Captured from api.tfl.gov.uk on 2026-09-15, with three lines genuinely
    # degraded at the time. Better evidence than anything hand-written.
    statuses = statuses_from_payload(real_payload())

    assert len(statuses) == 11
    by_code = {s.line_code: s for s in statuses}
    assert by_code["piccadilly"].description == "Severe Delays"
    assert by_code["bakerloo"].description == "Minor Delays"
    assert by_code["victoria"].severity == GOOD_SERVICE
    # The sentence a user reads survives the transform.
    assert "delays" in (by_code["bakerloo"].reason or "").lower()


# Severe Delays is the severity it is most tempting to avoid, and avoiding
# it means rerouting every Piccadilly journey in London over a condition
# that is often gone within the hour. The captured payload has two lines in
# exactly that state, and neither may be excluded.
def test_delays_are_reported_but_do_not_stop_a_line_running() -> None:
    """The counterweight, and the more important direction."""
    statuses = statuses_from_payload(real_payload())

    assert not_running(statuses) == frozenset()
    assert all(s.running for s in statuses)


def test_closures_and_suspensions_stop_a_line_running() -> None:
    """Closures and suspensions stop a line running."""
    # The positive case the real capture cannot show, because nothing was
    # suspended on the day it was taken.
    payload = [
        line("piccadilly", 2, "Suspended"),
        line("central", 1, "Closed"),
        line("district", 3, "Part Suspended"),
        line("victoria", GOOD_SERVICE, "Good Service"),
        line("bakerloo", 9, "Minor Delays"),
    ]

    assert not_running(statuses_from_payload(payload)) == frozenset(
        {"piccadilly", "central", "district"}
    )


def test_an_unknown_severity_is_treated_as_running() -> None:
    """An unknown severity is treated as running."""
    # TfL can add a code at any time. The optimistic reading being wrong shows
    # a user a delayed line; the pessimistic reading being wrong deletes a
    # working line from the network, which is the failure that strands someone.
    statuses = statuses_from_payload([line("victoria", 99, "Something New")])

    assert statuses[0].running is True
    assert not_running(statuses) == frozenset()


def test_the_worst_of_several_statuses_wins() -> None:
    """The worst of several statuses wins."""
    # A line can report part of itself suspended while the rest runs normally.
    # Taking the cheerful half would send someone to a closed platform.
    payload = [
        {
            "id": "district",
            "lineStatuses": [
                {"statusSeverity": 10, "statusSeverityDescription": "Good Service"},
                {"statusSeverity": 3, "statusSeverityDescription": "Part Suspended"},
            ],
        }
    ]

    statuses = statuses_from_payload(payload)

    assert statuses[0].description == "Part Suspended"
    assert statuses[0].running is False


def test_a_malformed_payload_yields_what_it_can_rather_than_raising() -> None:
    """A malformed payload yields what it can rather than raising."""
    # This runs in a background poller. One bad line must not cost the other
    # ten, and a shape TfL never sends must not take the task down - it would
    # stop status updating entirely, with no symptom on the page.
    payload = [
        "not a line",
        {"no_id": True},
        {"id": "", "lineStatuses": [{"statusSeverity": 2}]},
        {"id": "victoria", "lineStatuses": []},
        line("central", 10, "Good Service"),
    ]

    statuses = statuses_from_payload(payload)

    assert [s.line_code for s in statuses] == ["central"]
    assert statuses_from_payload({"unexpected": "object"}) == []
    assert statuses_from_payload(None) == []


def test_lines_come_back_in_a_stable_order() -> None:
    """Lines come back in a stable order."""
    # The poller publishes only when the picture changes, and "changed" is an
    # equality check against the last list. Unstable ordering would wake every
    # connected client sixty times an hour to say nothing happened.
    first = statuses_from_payload(real_payload())
    shuffled = list(reversed(real_payload()))

    assert statuses_from_payload(shuffled) == first


def test_the_status_carries_the_number_not_just_a_verdict() -> None:
    """The status carries the number, not just a verdict."""
    # A client may want to colour Minor Delays differently from Severe Delays.
    # Collapsing severity to a boolean here would throw that away for good.
    status = statuses_from_payload([line("central", 6, "Severe Delays")])[0]

    assert isinstance(status, LineStatus)
    assert status.severity == 6
    assert status.running is True
