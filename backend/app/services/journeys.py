"""
Plans a journey against the network as it is running right now.

WHY THIS EXISTS
    Planning a journey is more than calling find_route. Lines with no trains
    come out, stretches TfL has closed come out, and what was taken out has
    to be reported back so the traveller knows why the answer looks the way
    it does. Those are rules about the live network, so they sit here, and
    routes/route.py only validates the request and shapes the answer.

WHAT THE 2021 VERSION DID
    Where:  database[works].py lines 780-791 and 846-851 for line status,
            lines 472-600 and 860-880 for the search
    How:    Line status was fetched from TfL and shown in a listbox. The
            search was a separate Traversal that never read it.
    Wrong:  The window could tell you a line was suspended and then plan
            your journey on it.

WHAT CHANGED AND WHY
    Disruption is read from the status poller and applied to the network
    before the search, so a suspended line is never offered and a closed
    stretch is never ridden.

WHAT'S NEW
    Partial closures. TfL says which stretch of a line is shut, and only that
    stretch leaves the network; the rest of the line keeps running.
"""

from app.services import status_poller
from tube_engine import Network, NoRoute, Objective, Route, RouteQuery, find_route


# Returns the result and the two lists of lines the journey was planned
# around. They are reported separately because they mean different things to
# a traveller: a wholly shut line is not available at all, while a partly
# closed one is still running and this route may use it - which is exactly
# what Heathrow Terminal 5 to Epping does on the Piccadilly while the middle
# of that line is shut.
async def plan(
    network: Network,
    origin: str,
    destination: str,
    objective: Objective,
    avoid_lines: frozenset[str],
) -> tuple[Route | NoRoute, list[str], list[str]]:
    """Find a route around whatever is shut right now."""
    # Lines with no trains on them, merged into whatever the caller asked to
    # avoid. Only closures and suspensions - a delay is reported on /status
    # and never silently rewrites a journey, because Severe Delays often
    # clears within the hour and rerouting someone around a line that is
    # still moving gives them a worse trip for nothing.
    disrupted = await status_poller.not_running_lines()

    # A line shut between two places is not a line that is shut. TfL says
    # which stretch in affectedStops, so those rides come out of the network
    # and the rest of the line keeps running - the District is closed west of
    # Earl's Court most weekends and its eastern half is untouched.
    sections = await status_poller.closed_sections()
    if sections:
        network = network.without_closed_sections(sections)

    result = find_route(
        network,
        RouteQuery(
            origin=origin,
            destination=destination,
            objective=objective,
            avoid_lines=avoid_lines | disrupted,
        ),
    )
    return result, sorted(disrupted), sorted(sections)
