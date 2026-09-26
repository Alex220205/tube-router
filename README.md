# Tube Router

A London Underground journey planner that knows what is running.

Pick two stations and it finds the fastest route, the one with the fewest
changes, or a step-free one, across all 272 stations. It follows TfL's live
line status as it changes: a suspended line is routed around, and a line that
is only partly closed loses just the closed stretch. The route is drawn over
an interactive map of the network, with every leg and stop written out beside
it.

## Features

- **Three ways to plan a journey.** Fastest, fewest changes, or step-free,
  where every platform you board, change at and leave from has to be
  accessible.
- **Live disruption.** Line status is polled from TfL and pushed to the page
  over a WebSocket, coloured by severity. Closures and suspensions change the
  route; delays are reported but never silently reroute you.
- **The whole network on a map.** Lines that share track are drawn side by
  side, step-free stations are ringed, and a planned route is drawn over the
  dimmed network.
- **Search by place, not just by station** *(optional)*. Type "British Museum"
  and get the nearest stations to walk from.
- **What is near your destination** *(optional)*. Places to eat, drink and
  visit around the station you arrive at, with a Street View photograph of the
  exit.

## How it is built

| Folder | What it is |
|---|---|
| `engine/` | The routing engine. Dijkstra over (station, line) pairs, so changing line has a real cost. Pure Python, no dependencies, no I/O, and checked with `mypy --strict`. |
| `backend/` | The web service: FastAPI over PostgreSQL with PostGIS, and Redis. It seeds the network from TfL, polls live status and serves the API. |
| `frontend/` | React, Vite and MapLibre. |

`engine/` sits beside `backend/` rather than inside it because it does not
belong to the web service. It imports nothing web-related and nothing
database-related, a test enforces that, and
`backend/app/services/graph_loader.py` is the single file allowed to bridge
the two.

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
piece.

You only need it again after `docker compose down -v`, which deletes the volume
and therefore the data.

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Health | http://localhost:8000/health |

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

### Optional: Google Maps features

With a Google Maps key the app gains two things, and without one neither
appears and nothing else changes.

**Near your destination.** A collapsed section under the route listing places
around the destination station, with a photograph of the exit and a mark on
the ones with a wheelchair accessible entrance.

**Search by place, not station.** Type "British Museum" into From or To and,
when no station matches, it offers to look the place up and gives you the
nearest stations to walk from.

```bash
# in .env
GOOGLE_MAPS_KEY=...
```

Then `docker compose up -d api`. No rebuild: unlike the frontend's
`VITE_API_URL`, this is read at run time.

Get a key from the [Google Cloud console](https://console.cloud.google.com/)
and **restrict it to Places API (New), Street View Static API and Geocoding
API**. It must be a plain API key rather than one bound to a service account.
The key stays on the server, including for the photograph, which is proxied
rather than linked - a signed Google URL in the page would be a key in the
page.

Nothing is requested until the section is opened, and answers are cached, so
browsing routes costs nothing.

## Tests

```bash
cd engine   && uv run pytest      # no database or server needed
cd backend  && uv run pytest      # database tests run while the db container is up
cd frontend && npm test
```

CI runs all three on every push to `main`, along with linting, type checking,
the production build and a secret scan across the whole history.

## Data

Stations, lines, timetables, accessibility and live status: Powered by TfL Open
Data. Place details, geocoding and Street View imagery come from Google Maps
Platform when a key is configured.
