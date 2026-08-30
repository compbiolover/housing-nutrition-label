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


def isna(v) -> bool:
    """True for a missing scalar: ``None`` or a NaN float.

    The scalar half of ``pandas.isna``, which the parcel-row models used to reach
    for. The rows they read are plain dicts of Python/numpy scalars built by
    ``simulate.dimensions.build_parcel_row`` (or supplied by a caller), so the
    container half was never needed — and importing pandas for it cost more than
    the whole rest of a scoring pass. ``pd.NaT`` / ``pd.NA`` are NOT handled: no
    datetime or masked-integer value reaches these paths.
    """
    return v is None or v != v


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


def begin(budget: float | None = None, per_host: float | None = None) -> None:
    """Start recording on this thread, discarding anything a request that raised
    before it could report may have left behind.

    ``budget`` (seconds from now) and ``per_host`` (seconds any one service may
    spend) turn the window into a spending limit as well as a record — see the
    section below. Both default to off, which is what the CLI and batch jobs
    want: there, a slow upstream is worth waiting out.
    """
    _timings.calls = []
    _timings.deadline = None if not budget else time.monotonic() + float(budget)
    _timings.host_budget = float(per_host) if per_host else None
    _timings.starved = []
    _timings.last = None
    _timings.depth = 0


# ── What one slow dataset is allowed to cost ────────────────────────────────────
# Recording which upstream was slow told the operator what happened. It did not
# help the reader, who still watched a spinner until the page's own deadline gave
# up and threw the whole label away — including the eight dimensions that had
# already answered — because one dataset was having a bad afternoon.
#
# So the window doubles as a spending limit. Two limits, because they answer
# different questions:
#
#   per_host  what ONE service may spend on this label. This is the one that does
#             the work: it is aimed squarely at the dataset that is slow, and it
#             leaves every other dataset its full speed. Once a host has spent it,
#             the next call to that host is refused where it stands, its module
#             raises its own "unavailable" the way it would for an outage, and its
#             dimension comes back N/A with a note instead of pinning the request.
#   budget    what the whole request may spend before it must have an answer. The
#             backstop for the case per_host cannot see: not one dataset in
#             trouble but six, each individually inside its share.
#
# A refusal is a ``requests`` timeout, because that is what it is — this dataset
# did not answer in the time it had — and because every fetcher in the tree
# already handles one. Nothing new has to be taught to degrade gracefully; the
# paths that turn an outage into a note were all written years before this.
_MIN_CALL = 1.0     # a call given less than this cannot succeed; refuse it instead

# Refusals are raised as a requests timeout so existing handlers catch them
# unchanged; TimeoutError only for a source tree without requests, where nothing
# can be refused anyway because nothing can be sent.
_TimeoutBase = requests.exceptions.Timeout if requests is not None else TimeoutError


class UpstreamTooSlow(_TimeoutBase):  # type: ignore[misc,valid-type]
    """This upstream has used the time this request could give it."""


def remaining(host: str) -> tuple[float | None, float | None]:
    """Seconds left in (the request's budget, this host's share). None = unlimited."""
    calls = getattr(_timings, "calls", None)
    if calls is None:
        return (None, None)
    deadline = getattr(_timings, "deadline", None)
    per_host = getattr(_timings, "host_budget", None)
    total_left = None if deadline is None else deadline - time.monotonic()
    host_left = None
    if per_host is not None:
        # The record is the meter: what this host has already cost this request.
        # It holds one entry per logical call — see the seam's redirect note, which
        # is what keeps a redirecting host from being billed twice for one answer.
        host_left = per_host - sum(t for n, t in calls if n == host)
    return (total_left, host_left)


def allowance(host: str) -> float | None:
    """How long the next call to ``host`` may take; None when unbudgeted.

    Zero or less means: do not make the call at all.
    """
    left = [x for x in remaining(host) if x is not None]
    return min(left) if left else None


def _capped(timeout, allow: float):
    """``timeout`` (a number, a (connect, read) pair, or None) held under ``allow``."""
    if timeout is None:
        return allow
    if isinstance(timeout, (tuple, list)):
        return tuple(allow if t is None else min(float(t), allow) for t in timeout)
    try:
        return min(float(timeout), allow)
    except (TypeError, ValueError):   # something exotic; the budget still applies
        return allow


def _note_starved(host: str) -> None:
    """Note that ``host`` was refused, for the caller that reports the label."""
    seen = getattr(_timings, "starved", None)
    if seen is not None and host not in seen and len(seen) < _MAX_RECORDED:
        seen.append(host)


def starved() -> list[str]:
    """Hosts this request refused to wait for, in the order they ran out.

    Read *inside* the window (``drain()`` closes it): the API asks after scoring,
    so the payload can say which dataset is missing and why, and so a label
    degraded by a slow upstream is not cached onto the coordinate.
    """
    return list(getattr(_timings, "starved", None) or ())


def retry_wait(attempt: int, backoff: float | None = None) -> None:
    """Sleep before retrying an upstream — never past what this request has left.

    The fetchers all back off exponentially between attempts, which is right when
    the upstream is merely flaky and wrong when its budget is already spent: the
    retry will be refused the moment it is made, so the sleep buys nothing and
    spends seconds the *other* datasets still need. Outside a budgeted window
    (the CLI, batch jobs) this is exactly the sleep it replaced.
    """
    wait = float(config.BACKOFF if backoff is None else backoff) ** attempt
    allow = allowance(getattr(_timings, "last", None) or "")
    if allow is not None:
        if allow <= _MIN_CALL:
            return          # the next attempt is already doomed; don't pay to reach it
        wait = min(wait, max(0.0, allow - _MIN_CALL))
    if wait > 0:
        time.sleep(wait)


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
        # A redirect is resolved by calling Session.send again from inside the send
        # we are already timing. That hop is not a second call — it is the rest of
        # one question asked of one service — so it is neither timed again (a
        # single 10.8s USGS request used to read as "earthquake.usgs.gov 10.8s,
        # earthquake.usgs.gov 10.1s" in the log, two slow calls where there was
        # one) nor charged again, which would have a redirecting host spend its
        # share at twice the speed of the clock for no reason but redirecting. The
        # hop is still bounded: requests passes the outer call's timeout down, and
        # that one has already been capped to what the budget allows.
        if getattr(_timings, "depth", 0):
            return original(self, request, **kwargs)
        host = host_of(getattr(request, "url", "") or "")
        _timings.last = host        # which host retry_wait is about to wait for
        allow = allowance(host)
        if allow is not None:
            if allow < _MIN_CALL:
                # Refused, not attempted: the caller sees a timeout it already
                # knows how to survive, and pays nothing for it.
                _note_starved(host)
                total_left, host_left = remaining(host)
                if host_left is not None and (total_left is None or host_left <= total_left):
                    raise UpstreamTooSlow(
                        f"{host} is too slow to fit in this label: it has used the "
                        f"{getattr(_timings, 'host_budget', 0):.0f}s one dataset gets")
                raise UpstreamTooSlow(
                    f"no time left for {host}: this label's upstream budget is spent")
            # One call can't outlive the budget either — a 12s read timeout with
            # 4s left in the window would blow through it on its own.
            kwargs["timeout"] = _capped(kwargs.get("timeout"), allow)
        _timings.depth = 1
        try:
            with timed(host):
                return original(self, request, **kwargs)
        finally:
            _timings.depth = 0

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


# The public datasets behind a label, by the host that serves each one. A host is
# the right key because each of these services is one dataset here: we ask
# nsi.sec.usace.army.mil exactly one question, and asking chronicdata.cdc.gov a
# second one would be a second dataset with its own row. The names are what a
# reader is told when one of them is missing from their label, so they are the
# publisher's name for the data, not ours — "CDC PLACES", not "health".
DATASET_NAMES = {
    "nsi.sec.usace.army.mil": "the USACE National Structure Inventory",
    "hazards.fema.gov": "the FEMA National Flood Hazard Layer",
    "services2.arcgis.com": "the USA Structures building footprints",
    "services.arcgis.com": "the EPA water-system service areas",
    "earthquake.usgs.gov": "the USGS seismic hazard service",
    "chronicdata.cdc.gov": "CDC PLACES",
    "geocoding.geo.census.gov": "the Census geocoder",
    "tigerweb.geo.census.gov": "the Census TIGERweb road network",
    "api.census.gov": "the Census ACS API",
    "re.jrc.ec.europa.eu": "the PVGIS solar-yield service",
}


def dataset_name(host: str) -> str:
    """The publisher's name for the dataset ``host`` serves, else the host.

    Falling back to the host is deliberate: a new upstream that nobody added here
    still gets named in the label rather than described as "a dataset", and the
    bare hostname is a good enough name to search for.
    """
    return DATASET_NAMES.get(host, host)


def drain() -> list[tuple[str, float]]:
    """Take this thread's recorded timings, slowest first, and stop recording.

    Closing the window also lifts the spending limits, so the next thing this
    (reused) thread does is not charged against a request that has already
    finished — and cannot be refused by a deadline that has already passed.
    """
    calls = getattr(_timings, "calls", None) or []
    _timings.calls = None
    _timings.deadline = None
    _timings.host_budget = None
    _timings.starved = None
    _timings.last = None
    _timings.depth = 0
    return sorted(calls, key=lambda c: -c[1])


def log_upstreams(context: str, total: float, slow_after: float = 5.0) -> None:
    """Log this request's upstream timings, loudly when something dragged.

    ``slow_after`` is per call, not for the total: a label that takes 20 seconds
    because twelve datasets each took under two is healthy, and the line worth
    waking up to is the one where a single service ate the budget.
    """
    refused = starved()      # before drain(), which closes the window
    calls = drain()
    if not calls and not refused:
        return
    dropped = f" [dropped: {', '.join(refused)}]" if refused else ""
    detail = ", ".join(f"{n} {t:.1f}s" for n, t in calls[:8])
    worst, worst_secs = calls[0] if calls else ("", 0.0)
    if refused or worst_secs >= slow_after:
        log.warning("slow upstream: %s took %.1fs of %.1fs scoring %s (%s)%s",
                    worst or "nothing", worst_secs, total, context, detail, dropped)
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
            retry_wait(attempt)
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
            retry_wait(attempt)
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
