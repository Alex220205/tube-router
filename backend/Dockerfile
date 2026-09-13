# syntax=docker/dockerfile:1

# Production image for the API. Multi-stage, no source mount, non-root.
#
# A container that mounts your source and runs --reload is a development
# convenience, not an artefact you could ship. This is the shippable one, and
# it exists from Phase 0 rather than Phase 9 because retrofitting it costs a
# day and writing it now costs an hour.
#
# Build context is the repository root, not backend/, because the uv
# workspace spans both backend/ and engine/ and the lockfile lives at the top.
#   docker build -f backend/Dockerfile .

# --- Stage 1: build the virtual environment ----------------------------------
FROM python:3.12-slim AS builder

# Pinned. An unpinned tool in a build is a different build every time.
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Manifests first, then source. Dependencies change far less often than code,
# so this layer stays cached across most rebuilds.
COPY pyproject.toml uv.lock .python-version ./
COPY engine/pyproject.toml engine/pyproject.toml
COPY backend/pyproject.toml backend/pyproject.toml

# engine/ is a workspace member and has to be buildable for the sync to
# resolve, so its source comes in here rather than in the runtime stage only.
COPY engine/tube_engine/ engine/tube_engine/

# --frozen: fail if the lockfile disagrees with the manifests, rather than
# quietly resolving something new inside a build nobody is watching.
# --no-dev: pytest and mypy have no business in a production image.
RUN uv sync --frozen --no-dev --all-packages

# --- Stage 2: runtime --------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Non-root. Nothing in this service needs to write to the filesystem.
RUN useradd --create-home --uid 1000 app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app engine/ engine/
COPY --chown=app:app backend/ backend/

USER app

# Run from backend/ so the import path is app.main, matching how the tests
# and a local `uv run uvicorn app.main:app` see it.
WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
