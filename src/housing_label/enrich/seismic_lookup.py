#!/usr/bin/env python3
"""National seismic hazard lookup — 2%/50yr & 10%/50yr PGA for any US lat/lon.

Primary source: the USGS design-maps (ASCE7) web service (keyless) returns the
mapped MCEG peak ground acceleration (``pga``), i.e. the 2%-in-50-year value at
the site-class B reference. This is correct nationwide (high in the West, low in
the stable interior), unlike the old New-Madrid-only model.

Fallback: a bundled coarse national PGA grid (``seismic_pga_grid.csv``),
inverse-distance interpolated, for offline / API-outage use. If neither source
is available, ``get_pga`` returns None and the caller leaves seismic unscored.

The 10%/50yr value is derived from the 2%/50yr value via a national ratio (the
downstream EAL model only needs two points on the hazard curve).
"""

from __future__ import annotations

import csv
import math
import pathlib
import time
from functools import lru_cache

import requests

from housing_label.config import TIMEOUT, RETRIES, BACKOFF, HEADERS, EARTH_RADIUS_MI

USGS_URL = "https://earthquake.usgs.gov/ws/designmaps/asce7-16.json"

# 10%/50yr PGA ≈ this fraction of the 2%/50yr PGA (national approximation; the
# CEUS ratio is ~0.4, the WUS ratio ~0.45). The two-point hazard integration in
# the EAL model is itself an approximation, so a constant ratio is adequate.
PGA_10_2_RATIO = 0.43

_GRID_CSV = pathlib.Path(__file__).resolve().parents[1] / "data" / "seismic_pga_grid.csv"


# ── Live USGS lookup ────────────────────────────────────────────────────────────
@lru_cache(maxsize=2048)
def _usgs_pga(lat: float, lon: float) -> float | None:
    """2%/50yr PGA (g, site class B) from USGS design maps. None on failure."""
    params = {"latitude": lat, "longitude": lon,
              "riskCategory": "II", "siteClass": "B", "title": "hnl"}
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(USGS_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            data = (r.json().get("response") or {}).get("data") or {}
            pga = data.get("pga")
            return float(pga) if pga is not None else None
        except Exception:  # noqa: BLE001
            if attempt == RETRIES:
                return None
            time.sleep(BACKOFF ** attempt)
    return None


# ── Bundled fallback grid ───────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _grid() -> list[tuple[float, float, float]]:
    """Load the bundled coarse PGA grid as [(lat, lon, pga2), …]; [] if absent."""
    if not _GRID_CSV.exists():
        return []
    out = []
    with _GRID_CSV.open() as f:
        for row in csv.DictReader(f):
            try:
                out.append((float(row["lat"]), float(row["lon"]), float(row["pga_2pct"])))
            except (KeyError, ValueError):
                continue
    return out


def _grid_pga(lat: float, lon: float, k: int = 4) -> float | None:
    """Inverse-distance interpolation of the k nearest grid points. None if no grid."""
    pts = _grid()
    if not pts:
        return None
    scored = []
    for glat, glon, pga in pts:
        d = _haversine(lat, lon, glat, glon)
        if d < 1e-6:
            return pga
        scored.append((d, pga))
    scored.sort(key=lambda t: t[0])
    near = scored[:k]
    wsum = sum(1.0 / d for d, _ in near)
    return sum((1.0 / d) * pga for d, pga in near) / wsum if wsum else None


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(a))


# ── Public API ──────────────────────────────────────────────────────────────────
def get_pga(lat: float, lon: float, allow_network: bool = True) -> tuple | None:
    """Return (pga_2pct, pga_10pct, source) for a lat/lon, or None if unavailable.

    Tries the live USGS service first, then the bundled grid.
    """
    pga2 = _usgs_pga(round(float(lat), 3), round(float(lon), 3)) if allow_network else None
    source = "USGS ASCE7 (2%/50yr)"
    if pga2 is None:
        pga2 = _grid_pga(lat, lon)
        source = "bundled PGA grid" if pga2 is not None else None
    if pga2 is None:
        return None
    return round(pga2, 3), round(pga2 * PGA_10_2_RATIO, 3), source
