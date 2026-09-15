"""
The TfL Unified API client. The only file in this project that talks to TfL.

WHY THIS EXISTS
    Keeping every outbound HTTP call in one place means everything downstream
    of it is a pure function over a payload - which is what lets the whole of
    services/seed.py be tested against saved fixtures with no network at all.
    It also means the timeout, the retry policy and the app key are decided
    once rather than at each call site.

NO 2021 EQUIVALENT
    The old project called TfL too, but with the key written into the source
    at line 14 and repeated at six further call sites, no timeout, no retry,
    and the request built inline wherever a result was wanted. A change to
    the URL or the key meant finding every copy.

WHAT'S NEW
    Three things worth stating.

    A timeout on every request. Without one, httpx waits forever, and a seed
    that hangs on a single unresponsive endpoint looks identical to one doing
    slow work.

    Retries on 5xx, on transport failures, and on 429 - but on no other 4xx.
    A 404 means the line id is wrong and retrying it three times is being
    wrong three times more slowly. 429 is the opposite: it means "you were
    right, just slower", and it is the one status that is guaranteed to
    change if you wait.

    A minimum interval between requests, because TfL allows 50 a minute
    without a key and a seed of the tube network makes about ninety. Without
    throttling the run gets a third of the way through and then 429s - which
    is exactly how this was discovered.

    The client takes an httpx transport, so tests inject a MockTransport and
    exercise the retry and error paths without waiting on a real network or
    depending on TfL being up. CI does not go red because someone else's
    server is having a bad afternoon.
"""

import asyncio
import csv
import io
import zipfile
from dataclasses import dataclass
from typing import Any, Literal

import httpx

Direction = Literal["inbound", "outbound"]

# Files inside the station data zip that the seed reads. The archive holds
# eleven; these two are the ones with information nothing else publishes.
PLATFORM_SERVICES = "PlatformServices.csv"
STEP_FREE_INTERCHANGE = "StepFreeIntechangeInfo.csv"  # TfL's spelling, not ours

TOO_MANY_REQUESTS = 429

# How long to wait after a 429 when TfL does not send a Retry-After header.
# Their window is a minute, so anything shorter tends to be rate limited
# again immediately.
RATE_LIMIT_PAUSE = 30.0

# TfL allows 50 requests a minute without a key. 1.3 seconds between requests
# keeps a seed run - about ninety requests - comfortably inside that, at the
# cost of roughly two minutes wall clock. With a key the limit is far higher
# and this can be lowered.
UNAUTHENTICATED_REQUEST_INTERVAL = 1.3


def _retry_after(response: httpx.Response, *, default: float) -> float:
    """Read the Retry-After header, falling back to a default.

    Only the delay-seconds form is handled. The HTTP-date form is legal but
    TfL does not use it, and guessing at clock skew to parse one would add
    risk for no benefit.
    """
    raw = response.headers.get("Retry-After", "").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


class TfLError(RuntimeError):
    """TfL could not be reached, or answered with something unusable."""


@dataclass(frozen=True)
class StationData:
    """The two CSVs the seed needs out of the station data archive.

    Attributes:
        platform_services: One row per platform per line. Carries
            DesignatedLevelAccessPoint, which is step-free access per
            (station, line) - the only place TfL publishes it at that grain.
        step_free_interchanges: Platform-to-platform distances in metres.
            Sparse: about 114 rows for the whole network.
    """

    platform_services: list[dict[str, str]]
    step_free_interchanges: list[dict[str, str]]


class TfLClient:
    """Reads the TfL Unified API. Knows nothing about this project's schema."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.tfl.gov.uk",
        app_key: str = "",
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        min_request_interval_seconds: float = 0.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Build a client.

        Args:
            base_url: Root of the API.
            app_key: Optional. Raises the rate limit; every endpoint used here
                answers without one.
            timeout_seconds: Applied to each attempt, not to the total.
            max_attempts: Total attempts including the first.
            min_request_interval_seconds: Smallest gap between the start of
                one request and the next. TfL allows 50 a minute without a
                key, so the seed sets this; tests leave it at zero.
            transport: Injected by tests. None means a real network transport.
        """
        self._base_url = base_url.rstrip("/")
        self._app_key = app_key
        self._max_attempts = max_attempts
        self._min_interval = min_request_interval_seconds
        self._last_request_at = 0.0
        # Serialises the throttle. Requests are made sequentially by the seed
        # anyway, but without the lock a future concurrent caller would slip
        # past the interval and reintroduce the 429s.
        self._throttle = asyncio.Lock()
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )

    async def _wait_for_slot(self) -> None:
        """Hold until enough time has passed since the previous request."""
        if self._min_interval <= 0:
            return
        async with self._throttle:
            elapsed = asyncio.get_running_loop().time() - self._last_request_at
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request_at = asyncio.get_running_loop().time()

    async def __aenter__(self) -> "TfLClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying connection pool."""
        await self._client.aclose()

    # --- the request itself --------------------------------------------------

    async def _get(self, path: str) -> httpx.Response:
        """GET a path, retrying transport failures and 5xx.

        Args:
            path: Path beginning with a slash.

        Returns:
            The successful response.

        Raises:
            TfLError: On a 4xx, or once the attempts are exhausted.
        """
        # The key goes in the query string because that is what TfL accepts;
        # they have no header form. Omitted entirely when blank, rather than
        # sent empty, which TfL rejects as a malformed key.
        params = {"app_key": self._app_key} if self._app_key else None
        last: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            await self._wait_for_slot()
            pause = 0.5 * attempt

            try:
                response = await self._client.get(
                    f"{self._base_url}{path}", params=params
                )
            except httpx.HTTPError as exc:
                # Timeouts and connection failures. Worth retrying: the
                # request may never have reached them.
                last = exc
            else:
                if response.status_code < 400:
                    return response

                if response.status_code == TOO_MANY_REQUESTS:
                    # The one 4xx worth retrying. It does not mean the
                    # request was wrong, it means it was too soon - so
                    # waiting is the entire fix.
                    last = TfLError(f"GET {path} was rate limited")
                    pause = max(pause, _retry_after(response, default=RATE_LIMIT_PAUSE))
                elif response.status_code < 500:
                    # 404 means the line id is wrong. Retrying is being wrong
                    # three times more slowly.
                    raise TfLError(
                        f"GET {path} returned {response.status_code}, which will not "
                        f"change on a retry"
                    )
                else:
                    last = TfLError(f"GET {path} returned {response.status_code}")

            if attempt < self._max_attempts:
                # Linear rather than exponential, except for rate limiting
                # where TfL's own Retry-After wins. The failures worth
                # retrying here are brief, and the seed makes about ninety
                # requests - exponential backoff would turn a bad minute into
                # a bad hour.
                await asyncio.sleep(pause)

        raise TfLError(
            f"GET {path} failed after {self._max_attempts} attempts"
        ) from last

    async def _get_json(self, path: str) -> Any:
        response = await self._get(path)
        try:
            return response.json()
        except ValueError as exc:
            raise TfLError(f"GET {path} returned a body that is not JSON") from exc

    # --- endpoints -----------------------------------------------------------

    async def tube_lines(self) -> list[dict[str, Any]]:
        """Every line running on the tube network.

        Returns:
            Eleven line objects, each with at least id, name and modeName.
            Includes Waterloo & City, which the 2021 database did not have.
        """
        return list(await self._get_json("/Line/Mode/tube"))

    async def line_status(self) -> list[dict[str, Any]]:
        """Live status for every tube line.

        The only endpoint here that is polled rather than read once, so it is
        also the only one whose failures are routine: TfL goes down, and the
        service carries on serving the last status it knew. The throttle, the
        429 handling and the retry are the ones every other call already uses.

        Returns:
            Eleven line objects, each carrying lineStatuses with a
            statusSeverity, its description, and a reason where there is one.
        """
        return list(await self._get_json("/Line/Mode/tube/Status"))

    async def route_sequence(
        self, line_id: str, direction: Direction
    ) -> dict[str, Any]:
        """The ordered stations along a line, including its branches.

        Args:
            line_id: TfL line id, e.g. "victoria".
            direction: "inbound" or "outbound". Both are needed, because a
                segment is directional and the two directions are not always
                mirror images.

        Returns:
            A payload whose stopPointSequences each carry an ordered
            stopPoint list plus branchId, prevBranchIds and nextBranchIds.
        """
        return dict(await self._get_json(f"/Line/{line_id}/Route/Sequence/{direction}"))

    async def stop_points(self, line_id: str) -> list[dict[str, Any]]:
        """Every station on a line, with coordinates and hub membership.

        Args:
            line_id: TfL line id.

        Returns:
            Stop point objects carrying naptanId, commonName, lat, lon and
            hubNaptanCode.
        """
        return list(await self._get_json(f"/Line/{line_id}/StopPoints"))

    async def timetable(self, line_id: str, from_stop_id: str) -> dict[str, Any]:
        """The timetable from one station along a line.

        Args:
            line_id: TfL line id.
            from_stop_id: NaPTAN id to start from.

        Returns:
            A payload whose timetable.routes[].stationIntervals[].intervals[]
            carry stopId and timeToArrival. timeToArrival is cumulative
            minutes from the origin, so the gap between adjacent stations is
            the difference between consecutive values.
        """
        return dict(await self._get_json(f"/Line/{line_id}/Timetable/{from_stop_id}"))

    async def station_data(self) -> StationData:
        """Download and unpack the detailed station data archive.

        Returns:
            The two CSVs the seed reads, as lists of row dicts.

        Raises:
            TfLError: If the archive is unreadable or missing a file.
        """
        response = await self._get("/stationdata/tfl-stationdata-detailed.zip")
        try:
            archive = zipfile.ZipFile(io.BytesIO(response.content))
            return StationData(
                platform_services=_read_csv(archive, PLATFORM_SERVICES),
                step_free_interchanges=_read_csv(archive, STEP_FREE_INTERCHANGE),
            )
        except (zipfile.BadZipFile, KeyError) as exc:
            raise TfLError(f"station data archive is unreadable: {exc}") from exc


def _read_csv(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    """Read one CSV out of the archive.

    utf-8-sig because TfL writes a byte order mark, and without it the first
    column name comes back as "﻿StationUniqueId" and every lookup of it
    fails in a way that looks like missing data.
    """
    with archive.open(name) as handle:
        return list(csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig")))
