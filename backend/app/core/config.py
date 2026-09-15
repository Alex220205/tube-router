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

    # Unused until Phase 6 (cached network) and Phase 7 (status pub/sub).
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
