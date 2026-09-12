"""
Application settings, read from the environment once and cached.

WHY THIS EXISTS
    Every value the service needs that differs between a laptop, CI and a
    host somewhere — database URL, allowed CORS origins, API keys — arrives
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
            — there were literals.

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

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for the web service, read from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
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

    # Comma-separated in the environment because env vars are strings.
    # Parsed by cors_origin_list below.
    cors_origins: str = "http://localhost:5173"

    log_level: str = "info"
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
