#!/usr/bin/env python3
"""Building-footprint geometry lookup — real area + perimeter at a lat/lon.

Resolves the actual building footprint at a point from **FEMA / Oak Ridge National
Lab USA Structures** — a keyless national inventory of ~125M building footprints
(>450 sq ft) covering all 50 states + DC + territories. This lets the embodied-carbon
model use a home's *real* footprint area and perimeter instead of estimating them
from floor area with a shape factor (P ≈ 4.1·√area).

Source: the national USA Structures view hosted in FEMA's ArcGIS Online org
(keyless, read-only ``Query`` service). We ask for the polygon whose footprint
intersects the geocoded point.

Two data gotchas, both handled here:
  * ``Shape__Area`` / ``Shape__Length`` come back in the service's native **Web
    Mercator** projection (inflated by ~1/cos²(lat) for area), so they are NOT real
    m²/m. We use the ORNL-precomputed ``SQMETERS`` for area, and compute the
    perimeter **geodesically** from the returned lon/lat rings.
  * A point may hit no building (rural / <450 sq ft) → empty features → ``None``.

Network/API failure or ``allow_network=False`` degrades gracefully to ``None`` (the
embodied model falls back to its shape-factor estimate), so this is a best-effort
enrichment, never a hard dependency. Attribution: FEMA / ORNL USA Structures
(CC BY 4.0).
"""

from __future__ import annotations

import math
import time
from functools import lru_cache

import requests

from housing_label.config import BACKOFF, HEADERS, RETRIES, TIMEOUT

# National USA Structures view (keyless, Query-only). Layer 0 = footprints.
_URL = ("https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
        "USA_Structures_View/FeatureServer/0/query")

_EARTH_R_M = 6_371_008.8   # mean Earth radius (m), for the geodesic perimeter


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_R_M * math.asin(math.sqrt(a))


def _ring_perimeter_m(ring: list) -> float:
    """Geodesic perimeter of a lon/lat ring (sum of haversine edge lengths).

    Closes the ring if the service returned it unclosed (last point != first), so the
    final edge back to the start is never dropped."""
    r = ring if ring and ring[0] == ring[-1] else list(ring) + [ring[0]]
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(r, r[1:]):
        total += _haversine_m(lon1, lat1, lon2, lat2)
    return total


def _ring_area_deg2(ring: list) -> float:
    """Planar shoelace area (deg²) of a ring — used only to rank rings, so the outer
    boundary (largest) is chosen over interior holes / multipart pieces."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _query(lat: float, lon: float) -> list[dict]:
    """Return USA Structures features intersecting the point (empty on failure)."""
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "SQMETERS,OCC_CLS",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json() or {}
            if "error" in data:
                # ArcGIS returns HTTP 200 with an error body for transient conditions
                # (rate-limit / overload) — treat it as a failure so the retry/backoff
                # loop gets a chance rather than giving up immediately.
                raise RuntimeError("arcgis error response")
            return data.get("features") or []
        except Exception:  # noqa: BLE001
            if attempt == RETRIES:
                return []
            time.sleep(BACKOFF ** attempt)
    return []


@lru_cache(maxsize=4096)
def _footprint_at(lat: float, lon: float, allow_network: bool) -> dict | None:
    if not allow_network:
        return None
    feats = _query(lat, lon)
    if not feats:
        return None
    # A point can intersect >1 footprint on a shared edge / overlap; take the largest
    # real footprint (SQMETERS), which is the building the address most likely names.
    best = max(feats, key=lambda f: (f.get("attributes") or {}).get("SQMETERS") or 0.0)
    attrs = best.get("attributes") or {}
    area = attrs.get("SQMETERS")
    if not area or area <= 0:
        return None
    # A polygon can have multiple rings (holes / multipart); the exterior wall
    # perimeter is the outer boundary — the largest-area ring.
    rings = [r for r in ((best.get("geometry") or {}).get("rings") or []) if len(r) >= 4]
    outer = max(rings, key=_ring_area_deg2) if rings else None
    perim = _ring_perimeter_m(outer) if outer else None
    if not perim or perim <= 0:
        return None
    return {
        "footprint_area_m2": round(float(area), 1),
        "footprint_perimeter_m": round(perim, 1),
        "occ_cls": (attrs.get("OCC_CLS") or "").strip() or None,
        "source": "FEMA/ORNL USA Structures",
    }


def footprint_for_point(lat, lon, allow_network: bool = True) -> dict | None:
    """Real building footprint at (lat, lon): ``{footprint_area_m2,
    footprint_perimeter_m, occ_cls, source}``, or ``None`` when no building is found,
    the service is unavailable, or ``allow_network`` is False.

    Area is ORNL's true 2-D ``SQMETERS``; perimeter is geodesic from the footprint
    rings (the service's ``Shape__Area``/``Shape__Length`` are Web-Mercator-distorted
    and deliberately not used)."""
    try:
        latf, lonf = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(latf) and math.isfinite(lonf)):
        return None
    return _footprint_at(round(latf, 6), round(lonf, 6), bool(allow_network))
