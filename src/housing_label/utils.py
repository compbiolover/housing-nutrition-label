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

import math
import time

try:  # requests is only needed for the HTTP helpers
    import requests
except ImportError:  # pragma: no cover - geometry helpers still work without it
    requests = None  # type: ignore[assignment]

from . import config


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
