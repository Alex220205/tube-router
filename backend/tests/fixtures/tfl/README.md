# TfL fixtures

Real responses from the TfL Unified API, captured 2026-09-13. Tests read these
and never call TfL, so a TfL outage is not a red build and the suite runs
offline.

## What each one is

| File | Endpoint | Why this one |
|---|---|---|
| `lines_tube.json` | `GET /Line/Mode/tube` | All 11 tube lines, including Waterloo & City |
| `route_sequence_victoria_inbound.json` | `GET /Line/victoria/Route/Sequence/inbound` | The simple case: one branch, 16 stations, easy to reason about |
| `route_sequence_central_inbound.json` | `GET /Line/central/Route/Sequence/inbound` | The hard case: **7 sequences**, so branch handling is tested against real branch structure |
| `stop_points_victoria.json` | `GET /Line/victoria/StopPoints` | Coordinates and `hubNaptanCode`. 11 of 16 stations belong to a hub |
| `timetable_victoria_wwl.json` | `GET /Line/victoria/Timetable/940GZZLUWWL` | Cumulative `timeToArrival`, from which segment durations are derived |
| `PlatformServices.csv` | station data archive | Step-free per (station, line). Tube rows only — 851 of 1,878 |
| `StepFreeIntechangeInfo.csv` | station data archive | Platform-to-platform distances. All 114 rows |

## They are trimmed, and here is exactly how

Captured whole, then reduced — the full set was 950 KB, most of it fields the
seed never reads. **No value was altered.** Only whole fields were removed:

| File | Removed | Why |
|---|---|---|
| `lines_tube.json` | `lineStatuses`, `disruptions`, `routeSections`, `crowding`, `created`, `modified` | Live status that changes hourly. A fixture that differs on every capture is not a fixture |
| `timetable_*.json` | `routes[].schedules`, `routes[].serviceType` | Every departure of every day. 85% of the file; the seed reads `stationIntervals` |
| `stop_points_*.json` | `additionalProperties`, `children`, `lineGroup`, `lineModeGroups`, `lines` | 15 facility entries per stop. Step-free comes from `PlatformServices.csv`, not from here |
| `route_sequence_*.json` | `lineStrings`, `stopPoint[].lines` | Encoded polyline geometry. Phase 8 will want it; Phase 2 does not |
| `PlatformServices.csv` | Non-tube rows | Phase 2 is tube only. National Rail, DLR, Elizabeth, tram and cable car dropped |

The trade is deliberate: a fixture small enough to read in a diff, against one
that proves the parser tolerates every field TfL sends. The parsers here select
the fields they want by name and ignore the rest, so the removed fields
exercise nothing the kept ones do not.

## Recapturing

The capture and trim scripts are not committed — they ran once. To refresh,
fetch the endpoints in the table above and apply the same removals. Expect
coordinates and timetable values to differ slightly; TfL revises them.
