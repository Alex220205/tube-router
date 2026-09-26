"""Application settings, read from the environment once and cached."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from pydantic_settings import BaseSettings, SettingsConfigDict

# Count the hops, and recount them if this file ever moves: a wrong index points
# _REPO_ROOT at backend/, and the root .env silently stops being read.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Settings for the web service, read from the environment."""

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        # Compose injects frontend and Postgres variables into the same environment.
        # Ignoring unknown names keeps one shared .env workable.
        extra="ignore",
    )

    # Required. No default, because a wrong default here means connecting to something
    # unintended, which is worse than not starting.
    database_url: str

    redis_url: str = "redis://redis:6379/0"

    # --- TfL --------------------------------------------------------------
    tfl_base_url: str = "https://api.tfl.gov.uk"

    # Optional. Every endpoint the seed uses answers without a key; a key raises the
    # rate limit. Blank by default because it is a credential and the project has to
    # work for someone who has not got one.
    tfl_app_key: str = ""

    # Generous, because the station data zip is a few hundred KB.
    tfl_timeout_seconds: float = 30.0

    # Total attempts, not retries after the first. TfL returns occasional 5xx under load
    # and a single retry recovers almost all of them.
    tfl_max_attempts: int = 3

    # Smallest gap between requests. TfL allows 50 a minute without a key and a full
    # seed makes about ninety, so without this the run gets a third of the way through
    # and then starts getting 429s - which is how the value came to be here. With a key
    # the limit is far higher and this can drop.
    tfl_min_request_interval_seconds: float = 1.3

    # How often the background poller asks TfL what is running. TfL refreshes this
    # roughly every thirty seconds, so polling faster only spends someone else's rate
    # limit to learn nothing.
    tfl_status_poll_seconds: float = 60.0

    google_places_base_url: str = "https://places.googleapis.com"
    google_street_view_base_url: str = "https://maps.googleapis.com"
    # Same host as Street View today. Named separately because Google has already moved
    # one of these once, and a shared setting would mean moving both to follow either.
    google_geocoding_base_url: str = "https://maps.googleapis.com"

    # Blank disables the feature completely: no request is made, the endpoint answers
    # `available: false`, and the page renders nothing. The project has to work for
    # someone who has not got a key, the way it already does without a TfL one.
    google_maps_key: str = ""

    # Shorter than TfL's 30s. Nothing here blocks an answer the user asked for - a route
    # is already on screen before this is ever called - so a slow Google should give up
    # quickly rather than hold a connection.
    google_maps_timeout_seconds: float = 5.0

    # Total attempts including the first, as with TfL.
    google_maps_max_attempts: int = 3

    # How far around the station to look.
    #
    # 1500m, not the 500m this started at. 500m is a six minute walk and is the right
    # answer in zone 1; outside it, it is the difference between a list and an empty
    # box. Epping within 500m has two places to eat and nothing at all to look at, and
    # within 1500m has eight of each.
    google_places_radius_metres: float = 1500.0

    # Google allows 1 to 20. Eight is a list you read rather than scroll.
    google_places_max_results: int = 8

    # A day for places, because opening hours and ratings drift; a month for Street
    # View, because a station entrance does not move. Both are billing decisions before
    # they are latency ones.
    google_places_cache_ttl_seconds: int = 86_400
    google_street_view_cache_ttl_seconds: int = 2_592_000

    # Comma-separated in the environment because env vars are strings. Parsed by
    # cors_origin_list below.
    cors_origins: str = "http://localhost:5173"

    version: str = "0.1.0"

    @property
    def cors_origin_list(self) -> list[str]:
        """The allowed CORS origins, split and stripped."""
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Return the application settings, reading the environment on first call."""
    return Settings()  # populated from the environment


# Companion to SessionDep in database.py, so a route that needs settings declares it the
# same way a route that needs a session does.
SettingsDep = Annotated[Settings, Depends(get_settings)]
