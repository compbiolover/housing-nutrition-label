"""utils.py — shared helpers for the Housing Nutrition Label pipeline.

Canonical home for small utilities reused across pipeline stages:

* ``http_get`` / ``http_post`` — resilient JSON requests against the ArcGIS /
  FEMA REST endpoints (retries, timeout, browser User-Agent, error checking).
* ``haversine_miles`` — great-circle distance between two lat/lon points.
* ``webmercator_to_wgs84`` — EPSG:3857 → WGS84 lon/lat conversion.

The enrich/simulate modules that need great-circle distance import
``haversine_miles`` from here rather than re-implementing it. (The HTTP
helpers remain available for callers that want the shared retry/error
handling; some pipeline scripts still keep their own inline copies.)
"""

from __future__ import annotations

import contextlib
import logging
import math
import threading
import time
import urllib.parse

try:  # requests is only needed for the HTTP helpers
    import requests
except ImportError:  # pragma: no cover - geometry helpers still work without it
    requests = None  # type: ignore[assignment]

from . import config

log = logging.getLogger(__name__)


# ── Which upstream was slow ──────────────────────────────────────────────────────
# A label is a dozen live fetches against federal services, and when one of them
# starts answering in minutes the only visible symptom is a spinner: the request
# is slow, and nothing anywhere says which of the twelve is to blame. Guessing
# from the outside is not possible — the upstreams are reachable from everywhere
# except, apparently, the box that matters.
#
# So each call records what it cost, on a thread-local because the API serves
# requests on a threadpool and two visitors' timings must not braid together.
# ``drain()`` hands the list to whoever finishes the request (see the API's
# scoring endpoints), which logs one line naming the worst offender. Nothing here
# fails a request: a timing that cannot be recorded is not worth an exception.
# Recording is OPT-IN, per request, and that is not a detail. The seam below is
# installed process-wide, so it sees the geocoder calls behind /suggest as well
# as the dataset calls behind a label — and nothing drains a /suggest. Recording
# unconditionally would grow a list on every reused worker thread for as long as
# the process lived, which on this deployment is the slow RSS climb into an OOM
# that render.yaml already has a paragraph about. A thread records only between
# begin() and drain(); the rest of the time the seam costs a getattr.
_timings = threading.local()

# Belt to those braces: a scoring request makes twenty-odd calls, so a list past
# this is a bug somewhere else, and must not be allowed to become a leak here.
_MAX_RECORDED = 200


@contextlib.contextmanager
def timed(name: str):
    """Record how long one upstream call took, under ``name`` (its service).

    Outside a ``begin()``/``drain()`` window this only times: nobody is
    listening, so nothing is kept.
    """
    start = time.monotonic()
    try:
        yield
    finally:
        calls = getattr(_timings, "calls", None)
        if calls is not None and len(calls) < _MAX_RECORDED:
            calls.append((name, time.monotonic() - start))


def begin() -> None:
    """Start recording on this thread, discarding anything a request that raised
    before it could report may have left behind."""
    _timings.calls = []


def install_timing() -> None:
    """Time every outbound HTTP call, once, at one seam.

    The alternative was a ``with timed(...)`` around fourteen ``requests.get``
    calls in eleven modules — every one of which would have to be found again by
    the next person who adds a dataset, and silently missed if they didn't. All
    fourteen already funnel through ``Session.send``, so that is where the clock
    goes: complete by construction, and future call sites are covered the day
    they are written.

    Wrapping a library seam is what an APM agent does to a process, and it is
    only defensible when it is loud about it — hence a named wrapper, an
    idempotence flag, and an installer the *application* calls rather than an
    import side effect. The library, the CLI, and batch jobs are untouched unless
    they ask for this.
    """
    if requests is None or getattr(requests.sessions.Session.send, "_hnl_timed", False):
        return
    original = requests.sessions.Session.send

    def send_timed(self, request, **kwargs):
        # Nobody recording: one getattr and out. Every non-scoring request in the
        # process comes through here — /suggest, /place, the geocoder proxies —
        # and none of them has anyone to report to, so none of them should pay
        # for a URL parse and a context manager. (The claim above that the seam
        # "costs a getattr" is only true because of this line.)
        if getattr(_timings, "calls", None) is None:
            return original(self, request, **kwargs)
        with timed(host_of(getattr(request, "url", "") or "")):
            return original(self, request, **kwargs)

    send_timed._hnl_timed = True
    requests.sessions.Session.send = send_timed


def host_of(url: str) -> str:
    """The host out of a URL, for naming a timing. Never raises on an odd URL.

    ``urlsplit().hostname`` rather than splitting on slashes, because the
    authority may carry userinfo — a ``name:secret@`` prefix — and this string is
    written to a log. None of our URLs do today; a log that would print a
    credential if one ever did is not a thing to leave lying around. (Spelled out
    in prose rather than as a URL literal: the literal form trips credential
    scanners, and gets masked in code review, which hides the very point.)
    """
    try:
        return urllib.parse.urlsplit(url).hostname or url or "unknown"
    except Exception:  # noqa: BLE001
        return url or "unknown"


def drain() -> list[tuple[str, float]]:
    """Take this thread's recorded timings, slowest first, and stop recording."""
    calls = getattr(_timings, "calls", None) or []
    _timings.calls = None
    return sorted(calls, key=lambda c: -c[1])


def log_upstreams(context: str, total: float, slow_after: float = 5.0) -> None:
    """Log this request's upstream timings, loudly when something dragged.

    ``slow_after`` is per call, not for the total: a label that takes 20 seconds
    because twelve datasets each took under two is healthy, and the line worth
    waking up to is the one where a single service ate the budget.
    """
    calls = drain()
    if not calls:
        return
    worst, worst_secs = calls[0]
    detail = ", ".join(f"{n} {t:.1f}s" for n, t in calls[:8])
    if worst_secs >= slow_after:
        log.warning("slow upstream: %s took %.1fs of %.1fs scoring %s (%s)",
                    worst, worst_secs, total, context, detail)
    else:
        log.info("scored %s in %.1fs (%s)", context, total, detail)


# ── HTTP ─────────────────────────────────────────────────────────────────────────
def http_get(url: str, params: dict | None = None) -> dict:
    """GET ``url`` as JSON with retries, timeout, and ArcGIS error checking."""
    if requests is None:  # pragma: no cover
        raise RuntimeError("The 'requests' package is required for http_get().")
    last_exc: Exception | None = None
    for attempt in range(1, config.RETRIES + 1):
        try:
            r = requests.get(
                url,
                params={**(params or {}), "f": "json"},
                timeout=config.TIMEOUT,
                headers=config.HEADERS,
            )
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(f"ArcGIS error: {data['error']}")
            return data
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == config.RETRIES:
                raise
            time.sleep(config.BACKOFF ** attempt)
    raise last_exc  # type: ignore[misc]


def http_post(url: str, data: dict | None = None) -> dict:
    """POST (form-encoded) ``url`` as JSON with retries and error checking.

    Used for queries with long WHERE clauses that exceed GET URL length limits.
    """
    if requests is None:  # pragma: no cover
        raise RuntimeError("The 'requests' package is required for http_post().")
    last_exc: Exception | None = None
    for attempt in range(1, config.RETRIES + 1):
        try:
            r = requests.post(
                url,
                data={**(data or {}), "f": "json"},
                timeout=config.TIMEOUT,
                headers=config.HEADERS,
            )
            r.raise_for_status()
            result = r.json()
            if "error" in result:
                raise RuntimeError(f"ArcGIS error: {result['error']}")
            return result
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == config.RETRIES:
                raise
            time.sleep(config.BACKOFF ** attempt)
    raise last_exc  # type: ignore[misc]


# Convenience aliases matching the inline helpers used in the scripts.
_get = http_get
_post = http_post


# ── Geometry ───────────────────────────────────────────────────────────────────
def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in miles between two lat/lon points."""
    lat1, lon1, lat2, lon2 = (math.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * config.EARTH_RADIUS_MI * math.asin(math.sqrt(a))


# Alias for the shorter name referenced in the package layout docs.
haversine = haversine_miles


def webmercator_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """Convert Web Mercator (EPSG:3857) x,y to WGS84 (lon, lat) degrees."""
    R = 20037508.342789244
    lon = x * 180.0 / R
    lat = math.degrees(math.atan(math.exp(y * math.pi / R))) * 2.0 - 90.0
    return lon, lat
