"""Plans a journey against the network as it is running right now."""

from app.services import status_poller
from tube_engine import Network, NoRoute, Objective, Route, RouteQuery, find_route


# Returns the result and the two lists of lines the journey was planned around. They
# are separate because a wholly shut line is not available at all, while a partly
# closed one is still running and this route may use it.
async def plan(
    network: Network,
    origin: str,
    destination: str,
    objective: Objective,
    avoid_lines: frozenset[str],
) -> tuple[Route | NoRoute, list[str], list[str]]:
    """Find a route around whatever is shut right now."""
    # Lines with no trains on them, merged into whatever the caller asked to avoid. Only
    # closures and suspensions - a delay is reported on /status and never silently
    # rewrites a journey, because Severe Delays often clears within the hour and
    # rerouting someone around a line that is still moving gives them a worse trip for
    # nothing.
    disrupted = await status_poller.not_running_lines()

    # A line shut between two places is not a line that is shut. TfL says which stretch
    # in affectedStops, so those rides come out of the network and the rest of the line
    # keeps running - the District is closed west of Earl's Court most weekends and its
    # eastern half is untouched.
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
