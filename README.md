# Tube Router

A London Underground journey planner. Rewrite of a 2021 A-level project, built
to fix what was wrong with it rather than to re-skin it.

> **Status: Phase 0 - scaffold.** The stack runs and reports its own health.
> Routing arrives in Phases 4-6.

## What this is

Three parts, and the separation between them is the point:

| Folder | What it is |
|---|---|
| `engine/` | The routing engine. Pure Python, zero dependencies, no I/O. Give it a graph and a query, it gives you a route. |
| `backend/` | The **web service** - FastAPI, Postgres, Redis. Not "all the Python"; it serves HTTP and owns the data. |
| `frontend/` | React + Vite + MapLibre. |

`engine/` sits beside `backend/` rather than inside it because it does not
belong to the web service - it is a package the web service happens to
consume. It imports nothing web-related and nothing database-related, and
`backend/app/services/graph_loader.py` is the single file allowed to bridge the
two.

## Running it

Requires Docker. Nothing else.

```bash
cp .env.example .env
docker compose up -d
docker compose exec api python seed.py
```

**The third command is not optional the first time.** `docker compose up` gives
you a running stack in front of an empty database, so until the seed has run
`/stations` returns `[]` and every route request is a 404 for a station that
does not exist yet.

It takes about two minutes. The seed reads TfL's public API - no key needed -
and deliberately waits 1.3 seconds between requests, because TfL allows 50 a
minute to unauthenticated callers and a full tube load is about ninety. It
finishes by printing seven checks, including whether the graph is one connected
piece; that one fails on the 2021 data and is the single most useful line of
output.

You only need it again after `docker compose down -v`, which deletes the volume
and therefore the data.

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Health | http://localhost:8000/health |

Pick two stations, choose fastest, fewest changes or step-free, and the route
is drawn over the network with its legs written out beside it. Live disruption
from TfL arrives over a WebSocket, and a line that is part closed has only its
closed stretch avoided rather than the whole line.

### Changing the code

The frontend container serves a **static build made when the image was
built**. Editing a file under `frontend/src` changes nothing you can see until
the image is rebuilt:

```bash
docker compose up -d --build frontend
```

For anything more than a one-off change, run the dev server directly instead
and get hot reload:

```bash
docker compose stop frontend          # it is holding port 5173
cd frontend && npm install && npm run dev
```

The page is on http://localhost:5173 either way, and the API base URL falls
back to `http://localhost:8000`, so no environment file is needed for this.
`docker compose start frontend` puts it back.

The backend container has no source mount and no `--reload` either, by the
same deliberate trade: `docker compose up -d --build api`.

### Optional: what is near your destination

With a Google Maps key, the route panel gains a collapsed **Near ...**
section listing places around the destination station, with a photograph of
the exit. Without one it simply does not appear, and nothing else changes.

```bash
# in .env
GOOGLE_MAPS_KEY=...
```

Then `docker compose up -d api`. No rebuild: unlike the frontend's
`VITE_API_URL`, this is read at run time.

Get a key from the [Google Cloud console](https://console.cloud.google.com/)
and **restrict it to Places API (New) and Street View Static API**. The key
stays on the server, including for the photograph, which is proxied rather
than linked - a signed Google URL in the page would be a key in the page.

Nothing is requested until the section is opened, and answers are cached, so
browsing routes costs nothing.

## Tests

```bash
cd engine   && uv run pytest      # no database or server needed
cd backend  && uv run pytest
cd frontend && npm test
```

## Documentation

The reasoning behind this rewrite - an audit of the 2021 database, a dated
decision log, the commenting standard the source holds itself to, and a
per-phase record - is kept as a working document rather than published here.

What is in the repository speaks for itself: every non-trivial file opens with
a header saying what it does, what the 2021 version did, and what was wrong
with it.

## The 2021 version

Link and comparison to follow in Phase 10.
