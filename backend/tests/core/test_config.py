"""
Tests for settings resolution.

WHY THIS EXISTS
    One test, guarding one bug that has now happened twice.

    config.py builds an absolute path to the repository root by counting
    directory hops from __file__. When the file moved one level deeper during
    the Phase 1 restructure the count was not updated, so _REPO_ROOT silently
    became backend/ and the root .env stopped being read.

    Nothing failed for a week. Every test sets the environment directly and
    Compose injects it, so the .env path is only exercised by a human running
    a command by hand - and it surfaced as an unhelpful
    "database_url Field required" in the middle of an Alembic traceback.

NO 2021 EQUIVALENT
    The old project had no settings to resolve. Credentials were string
    literals at line 14 and six other places.
"""

from app.core.config import _REPO_ROOT


def test_repo_root_points_at_the_repository_root() -> None:
    """Repo root points at the repository root."""
    # .env.example is tracked, lives at the root, and is not going anywhere.
    # If this fails, the parents[] index in config.py is wrong again and the
    # root .env is not being read.
    assert (_REPO_ROOT / ".env.example").is_file(), (
        f"_REPO_ROOT resolved to {_REPO_ROOT}, which has no .env.example. "
        f"Recount the parents[] index in app/core/config.py."
    )
