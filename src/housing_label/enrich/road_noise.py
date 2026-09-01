#!/usr/bin/env python3
"""Transportation noise sources near a lat/lon — how far to the nearest one.

The Noise dimension scores the share of a CENSUS TRACT's residents exposed to
>=60 dB transportation noise. That is a population statistic, and a tract is a
poor unit for it: a rural tract containing one highway corridor reports a nonzero
exposure that belongs to the handful of homes beside the corridor, while every
other parcel in the tract — which may be miles away — inherits it.

True point-level noise is not obtainable. The BTS National Transportation Noise
Map exists as a 30 m raster, but its public ArcGIS service is ``TilesOnly`` (it
renders map images and cannot be queried at a point), the bundled upstream product
is already tract-aggregated, and the national raster is far too large to ship.

What IS obtainable at a point, keylessly, is the geometry of the noise SOURCES:
Census TIGERweb publishes primary roads, secondary roads and railroads as queryable
layers. Distance to the nearest one is a real parcel-level fact, and >=60 dB is a
loud bar that transportation noise only clears close to its source.

So this module answers a narrower question than "how loud is it here" — it answers
"is there anything near enough to be that loud". See ``simulate/dimensions.py`` for
how that is used, and for the limits it is used within.

Distances, and why they are not HUD's
-------------------------------------
HUD's screening distances (24 CFR 51B: 1,000 ft from a busy road, 3,000 ft from a
railroad) are deliberately over-inclusive — they decide when an assessment is
*required*, not where noise actually is. Using them here would be the wrong kind of
conservative: almost every rural parcel sits within 1,000 ft of some state highway,
so nothing would ever resolve.

These are attenuation distances instead, from line-source geometry (roughly
3-4.5 dB per doubling of distance over soft ground, FHWA TNM):

  * a freeway is ~75-80 dBA at 15 m, so >=60 dB reaches a few hundred metres
  * a busy arterial is ~65-70 dBA at 15 m, so >=60 dB reaches tens of metres
  * a local street rarely clears 60 dB L_eq beyond its own right-of-way, which is
    why local roads are not queried at all — including them would flag every
    parcel in the country, since every house is on a road.

Attribution: US Census Bureau TIGERweb (public domain).
"""

from __future__ import annotations

import math
from functools import lru_cache

from housing_label import utils
from housing_label.config import BACKOFF, HEADERS, RETRIES, TIMEOUT


class RoadDataUnavailable(RuntimeError):
    """TIGERweb could not be reached (every retry failed).

    Distinct from "no sources found nearby": an outage that read as "nothing
    around" would hand every address in the country a quiet-parcel refinement at
    once. Raised so the caller declines to refine rather than refining wrongly.
    """


_URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
        "Transportation/MapServer/{layer}/query")

# TIGERweb layer ids, with the distance at which each class can still plausibly
# deliver >=60 dB. Local roads (layer 8) are deliberately absent — see the module
# docstring.
_SOURCES = {
    "primary":   (2, 300.0),   # interstates + primary highways
    "secondary": (6, 100.0),   # US/state highways, major arterials (finest scale)
    "rail":      (9, 300.0),   # mainline railroads
}

# How far out to look. Wider than the largest threshold so "nothing within the
# threshold" is a measured absence rather than an artifact of the search box.
_SEARCH_M = 1200.0
_M_PER_DEG_LAT = 111320.0


def _haversine_ish_m(lat0: float, lon0: float, lat: float, lon: float) -> float:
    return math.hypot((lat - lat0) * _M_PER_DEG_LAT,
                      (lon - lon0) * _M_PER_DEG_LAT * math.cos(math.radians(lat0)))


def _query(lat: float, lon: float, layer: int) -> list[dict]:
    """Features of one layer within the search box. Raises on total failure."""
    dlat = _SEARCH_M / _M_PER_DEG_LAT
    dlon = dlat / max(math.cos(math.radians(lat)), 0.1)
    params = {
        "geometry": f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326", "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "NAME,MTFCC",
        "returnGeometry": "true",
        "f": "json",
    }
    for attempt in range(1, RETRIES + 1):
        try:
            r = utils.http_session().get(_URL.format(layer=layer), params=params,
                                         headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json() or {}
            if "error" in data:
                raise RuntimeError("tigerweb error response")
            return data.get("features") or []
        except Exception as exc:  # noqa: BLE001
            if attempt == RETRIES:
                raise RoadDataUnavailable(
                    f"TIGERweb layer {layer} failed after {RETRIES} attempts: {exc}"
                ) from exc
            utils.retry_wait(attempt, BACKOFF)
    return []   # unreachable


def _point_segment_m(lat: float, lon: float,
                     lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Metres from a point to a line SEGMENT (not to its endpoints).

    Worked in a local planar frame — metres east/north of the query point — which
    is exact enough at the hundreds-of-metres scale these thresholds live at.
    """
    k = _M_PER_DEG_LAT * math.cos(math.radians(lat))
    px, py = 0.0, 0.0                                    # the query point, at origin
    ax, ay = (lon1 - lon) * k, (lat1 - lat) * _M_PER_DEG_LAT
    bx, by = (lon2 - lon) * k, (lat2 - lat) * _M_PER_DEG_LAT
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 <= 0.0:                                      # degenerate segment
        return math.hypot(ax - px, ay - py)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    return math.hypot(ax + t * dx - px, ay + t * dy - py)


def _nearest_m(lat: float, lon: float, features: list[dict]) -> float | None:
    """Distance to the nearest point on any returned line, or None if none.

    True point-to-SEGMENT distance, not point-to-vertex. The difference matters and
    it matters in the dangerous direction: a vertex is never closer than the line
    it belongs to, so vertex distance can only ever OVERstate how near a road is —
    and overstating is exactly what grants the quiet-parcel credit. TIGER puts few
    vertices on a long straight run, so a house beside the midpoint of a straight
    interstate could have looked hundreds of metres clear of it.
    """
    best = None
    for f in features:
        for path in (f.get("geometry") or {}).get("paths") or []:
            for (lon1, lat1), (lon2, lat2) in zip(path, path[1:]):
                d = _point_segment_m(lat, lon, lat1, lon1, lat2, lon2)
                if best is None or d < best:
                    best = d
            if len(path) == 1 and len(path[0]) >= 2:     # single-vertex path
                d = _haversine_ish_m(lat, lon, path[0][1], path[0][0])
                if best is None or d < best:
                    best = d
    return best


@lru_cache(maxsize=4096)
def _sources_at(lat: float, lon: float, allow_network: bool) -> dict | None:
    if not allow_network:
        return None
    out: dict = {"distances_m": {}, "within_threshold": [], "thresholds_m": {}}
    for name, (layer, threshold) in _SOURCES.items():
        d = _nearest_m(lat, lon, _query(lat, lon, layer))
        out["distances_m"][name] = None if d is None else round(d, 1)
        out["thresholds_m"][name] = threshold
        if d is not None and d <= threshold:
            out["within_threshold"].append(name)
    out["any_within_threshold"] = bool(out["within_threshold"])
    out["source"] = "US Census TIGERweb (primary/secondary roads, railroads)"
    return out


def noise_sources_near(lat: float, lon: float,
                       allow_network: bool = True) -> dict | None:
    """Nearest primary road, secondary road and railroad to a point.

    Keys: ``distances_m`` (per class, None when none within ~1.2 km),
    ``thresholds_m``, ``within_threshold`` (class names inside their distance),
    ``any_within_threshold``, ``source``.

    Returns None off-network. Raises ``RoadDataUnavailable`` when TIGERweb itself
    is unreachable, so an outage cannot be mistaken for "nothing nearby".
    """
    return _sources_at(round(float(lat), 6), round(float(lon), 6), allow_network)
