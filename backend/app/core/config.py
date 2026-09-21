"""
Application settings, read from the environment once and cached.

WHY THIS EXISTS
    Every value the service needs that differs between a laptop, CI and a
    host somewhere - database URL, allowed CORS origins, API keys - arrives
    through this file and nowhere else. One place to look, one place to
    change, and a single point where a missing setting fails loudly at
    startup rather than quietly at the call site.

WHAT THE 2021 VERSION DID
    Where:  database[works].py line 14 (TfL key), lines 239 and 276 (Google
            Maps key), plus six further uses of the TfL key
    How:    Credentials were written into the source as string literals and
            referenced directly wherever they were needed.
    Wrong:  Three things. The keys were in version control, so they were
            exposed to anyone with repository access and remain in history
            forever. Changing one meant editing several call sites and
            hoping none were missed. And there was no way to run the same
            code against different settings, because there were no settings
            - there were literals.

WHAT CHANGED AND WHY
    Settings is a pydantic-settings model populated from environment
    variables. Nothing is hardcoded, .env is gitignored, and .env.example
    documents the names without the values. A missing required setting raises
    at import rather than producing a confusing failure later.

    get_settings() is cached, so the environment is read once per process
    rather than on every access.

WHAT'S NEW
    CORS origins as configuration. The 2021 project was a desktop Tkinter
    application with no browser and therefore no same-origin policy to
    satisfy. A wildcard would work and would never be noticed in
    development, which is exactly why it is not the default here.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from pydantic_settings import BaseSettings, SettingsConfigDict

# This file      -> core -> app -> backend -> repository root
#                    [0]     [1]    [2]        [3]
#
# Count the hops, and recount them if this file ever moves. It moved once
# already - from backend/app/config.py to backend/app/core/config.py - and the
# index was not updated, so _REPO_ROOT silently became backend/ and the root
# .env stopped being read. Nothing failed for a week, because the test suite
# sets the variables directly and Compose injects them, so the .env path is
# only exercised by a human running a command by hand.
#
# An absolute path rather than a bare ".env", because env_file is otherwise
# resolved against the working directory and the API runs from backend/.
#
# Inside the image this resolves to /app/.env, which is not there - .env is
# gitignored and never copied in. A missing env_file is not an error, and the
# values arrive from the environment instead.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Settings for the web service, read from the environment."""

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        # Compose injects frontend and Postgres variables into the same
        # environment. Ignoring unknown names keeps one shared .env workable.
        extra="ignore",
    )

    # Required. No default, because a wrong default here means connecting to
    # something unintended, which is worse than not starting.
    database_url: str

    # The cached network rows and the generation key (Phase 6), and live
    # line status with its pub/sub channel (Phase 7).
    redis_url: str = "redis://redis:6379/0"

    # --- TfL --------------------------------------------------------------
    tfl_base_url: str = "https://api.tfl.gov.uk"

    # Optional. Every endpoint the seed uses answers without a key; a key
    # raises the rate limit. Blank by default because it is a credential and
    # the project has to work for someone who has not got one.
    tfl_app_key: str = ""

    # Generous, because the station data zip is a few hundred KB.
    tfl_timeout_seconds: float = 30.0

    # Total attempts, not retries after the first. TfL returns occasional 5xx
    # under load and a single retry recovers almost all of them.
    tfl_max_attempts: int = 3

    # Smallest gap between requests. TfL allows 50 a minute without a key and
    # a full seed makes about ninety, so without this the run gets a third of
    # the way through and then starts getting 429s - which is how the value
    # came to be here. With a key the limit is far higher and this can drop.
    tfl_min_request_interval_seconds: float = 1.3

    # How often the background poller asks TfL what is running. TfL refreshes
    # this roughly every thirty seconds, so polling faster only spends someone
    # else's rate limit to learn nothing.
    #
    # Sixty seconds is also one request a minute against an unauthenticated
    # allowance of fifty, which leaves the seed's ninety-request run unaffected
    # if the two ever overlap.
    tfl_status_poll_seconds: float = 60.0

    # --- Google Maps (Phase 9) ---------------------------------------------
    # Two hosts, because Google splits them. Places API (New) lives on
    # places.googleapis.com; Street View Static is still on the older
    # maps.googleapis.com.
    google_places_base_url: str = "https://places.googleapis.com"
    google_street_view_base_url: str = "https://maps.googleapis.com"

    # Blank disables the feature completely: no request is made, the endpoint
    # answers `available: false`, and the page renders nothing. The project
    # has to work for someone who has not got a key, the way it already does
    # without a TfL one.
    #
    # NOT the 2021 key. That one is written into database[works].py in plain
    # text and is revoked in Phase 10.
    google_maps_key: str = ""

    # Shorter than TfL's 30s. Nothing here blocks an answer the user asked
    # for - a route is already on screen before this is ever called - so a
    # slow Google should give up quickly rather than hold a connection.
    google_maps_timeout_seconds: float = 5.0

    # Total attempts including the first, as with TfL.
    google_maps_max_attempts: int = 3

    # How far around the station to look.
    #
    # 1500m, not the 500m this started at. 500m is a six minute walk and is
    # the right answer in zone 1; outside it, it is the difference between a
    # list and an empty box. Epping within 500m has two places to eat and
    # nothing at all to look at, and within 1500m has eight of each.
    #
    # Widening it costs nothing in relevance because results are ranked by
    # distance and capped at eight, so a dense station returns the same eight
    # it always did. It does mean a result can be a fifteen minute walk away,
    # which is why every row now shows how far it is.
    google_places_radius_metres: float = 1500.0

    # Google allows 1 to 20. Eight is a list you read rather than scroll.
    google_places_max_results: int = 8

    # A day for places, because opening hours and ratings drift; a month for
    # Street View, because a station entrance does not move. Both are billing
    # decisions before they are latency ones.
    google_places_cache_ttl_seconds: int = 86_400
    google_street_view_cache_ttl_seconds: int = 2_592_000

    # Comma-separated in the environment because env vars are strings.
    # Parsed by cors_origin_list below.
    cors_origins: str = "http://localhost:5173"

    # No log_level here. It existed in .env.example, in docker-compose.yml and
    # on this model, and nothing read it - uvicorn's level is not set from it.
    # A setting that looks configurable and is not is worse than an absent
    # one, because it sends you looking for the bug somewhere else. It comes
    # back when something actually configures logging.
    version: str = "0.1.0"

    @property
    def cors_origin_list(self) -> list[str]:
        """The allowed CORS origins, split and stripped.

        Returns:
            One entry per origin. Empty entries from stray commas are dropped.
        """
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Return the application settings, reading the environment on first call.

    Returns:
        The cached Settings instance for this process.
    """
    return Settings()  # type: ignore[call-arg]  # populated from the environment


# Companion to SessionDep in database.py, so a route that needs settings
# declares it the same way a route that needs a session does.
SettingsDep = Annotated[Settings, Depends(get_settings)]
