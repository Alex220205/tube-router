# Tube Router

A London Underground journey planner. Rewrite of a 2021 A-level project, built
to fix what was wrong with it rather than to re-skin it.

> **Status: Phase 0 — scaffold.** The stack runs and reports its own health.
> Routing arrives in Phases 4-6.

## What this is

Three parts, and the separation between them is the point:

| Folder | What it is |
|---|---|
| `engine/` | The routing engine. Pure Python, zero dependencies, no I/O. Give it a graph and a query, it gives you a route. |
| `backend/` | The **web service** — FastAPI, Postgres, Redis. Not "all the Python"; it serves HTTP and owns the data. |
| `frontend/` | React + Vite + MapLibre. |

`engine/` sits beside `backend/` rather than inside it because it does not
belong to the web service — it is a package the web service happens to
consume. It imports nothing web-related and nothing database-related, and
`backend/app/graph_loader.py` is the single file allowed to bridge the two.

## Running it

Requires Docker. Nothing else.

```bash
cp .env.example .env
docker compose up
```

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Health | http://localhost:8000/health |

## Tests

```bash
cd engine   && uv run pytest      # no database or server needed
cd backend  && uv run pytest
cd frontend && npm test
```

## Documentation

- [`docs/COMMENTING.md`](docs/COMMENTING.md) — the commenting standard this repo holds itself to
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — one dated entry per decision, and why

## The 2021 version

Link and comparison to follow in Phase 9.
