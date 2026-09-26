"""Tests for settings resolution."""

from app.core.config import _REPO_ROOT


def test_repo_root_points_at_the_repository_root() -> None:
    """Repo root points at the repository root."""
    # .env.example is tracked, lives at the root, and is not going anywhere. If this
    # fails, the parents[] index in config.py is wrong again and the root .env is not
    # being read.
    assert (_REPO_ROOT / ".env.example").is_file(), (
        f"_REPO_ROOT resolved to {_REPO_ROOT}, which has no .env.example. "
        f"Recount the parents[] index in app/core/config.py."
    )
