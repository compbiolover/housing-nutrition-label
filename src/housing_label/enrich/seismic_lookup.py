#!/usr/bin/env python3
"""National seismic hazard lookup — 2%/50yr & 10%/50yr PGA for any US lat/lon.

Primary source: the **USGS 2023 National Seismic Hazard Model (NSHM)** hazard-curve
web service (keyless). It returns the full PGA hazard curve — ground motion (g) vs.
annual frequency of exceedance — at a point, so we read the **true** ground motion at
BOTH return periods by interpolating the curve at their annual rates:
  * 2% in 50 yr  (~2475-yr return period) → λ = -ln(1-0.02)/50 ≈ 4.04e-4 /yr
  * 10% in 50 yr (~475-yr return period)  → λ = -ln(1-0.10)/50 ≈ 2.11e-3 /yr
This replaces the old constant 0.43 ratio between the two — which was materially off
(the real 10%/2% ratio is ~0.4 in the stable interior but ~0.5 in the West).

Fallbacks (each degrades gracefully, and the 0.43 ratio survives only here):
  1. The USGS ASCE7 design-maps service (2%/50yr MCEG) × the national ratio — for
     Alaska/Hawaii/territories (outside the CONUS NSHM) or an NSHM outage.
  2. A bundled coarse national PGA grid (``seismic_pga_grid.csv``) × the ratio, for
     offline use.
If none is available, ``get_pga`` returns None and the caller decides (the CLI
simulator falls back to the legacy New Madrid model).
"""

from __future__ import annotations

import csv
import math
import pathlib
import time
from functools import lru_cache

import requests

from housing_label.config import TIMEOUT, RETRIES, BACKOFF, HEADERS
from housing_label.utils import haversine_miles

# USGS 2023 NSHM hazard-curve service (keyless; path form, longitude first). vs30=760
# m/s is the BC-boundary reference site condition used by the national hazard maps.
NSHM_MODEL = "conus-2023"
NSHM_VS30 = 760
NSHM_URL = "https://earthquake.usgs.gov/ws/nshmp/{model}/dynamic/hazard/{lon}/{lat}/{vs30}"
# CONUS NSHM bounds [minLon, minLat, maxLon, maxLat]; outside these the service does
# not cleanly error, so we gate on the bounds ourselves and fall back.
_CONUS_BOUNDS = (-125.0, 24.4, -65.0, 50.0)

# Annual frequency of exceedance for the two return periods (per year).
LAMBDA_2PCT_50 = -math.log(1 - 0.02) / 50.0    # ~4.0405e-4
LAMBDA_10PCT_50 = -math.log(1 - 0.10) / 50.0   # ~2.1072e-3

USGS_URL = "https://earthquake.usgs.gov/ws/designmaps/asce7-16.json"

# 10%/50yr PGA ≈ this fraction of the 2%/50yr PGA — a national approximation used
# ONLY in the design-maps / grid fallbacks now (the primary NSHM path reads the true
# 10%/50yr straight off the hazard curve).
PGA_10_2_RATIO = 0.43

_GRID_CSV = pathlib.Path(__file__).resolve().parents[1] / "data" / "seismic_pga_grid.csv"


# ── Primary: USGS 2023 NSHM hazard curve (true 2%/50yr AND 10%/50yr) ────────────
def _in_conus(lat: float, lon: float) -> bool:
    lo_min, la_min, lo_max, la_max = _CONUS_BOUNDS
    return lo_min <= lon <= lo_max and la_min <= lat <= la_max


def _gm_at_rate(xs: list, ys: list, lam: float) -> float | None:
    """Interpolate the ground motion (g) at annual exceedance rate ``lam`` from a
    hazard curve — ``xs`` ground motion ascending, ``ys`` annual rate descending —
    in log-log space. Clamps to the curve ends if ``lam`` falls outside its range."""
    pts = [(float(x), float(y)) for x, y in zip(xs, ys) if y and float(y) > 0]
    if len(pts) < 2:
        return None
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if y0 >= lam >= y1:
            f = (math.log(lam) - math.log(y0)) / (math.log(y1) - math.log(y0))
            return math.exp(math.log(x0) + f * (math.log(x1) - math.log(x0)))
    return pts[0][0] if lam > pts[0][1] else pts[-1][0]


@lru_cache(maxsize=2048)
def _nshm_hazard_pga(lat: float, lon: float) -> tuple[float, float] | None:
    """True (pga_2pct, pga_10pct) in g from the USGS 2023 NSHM PGA hazard curve, or
    None outside CONUS / on failure."""
    if not _in_conus(lat, lon):
        return None
    url = NSHM_URL.format(model=NSHM_MODEL, lon=lon, lat=lat, vs30=NSHM_VS30)
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)  # follows redirects
            r.raise_for_status()
            payload = r.json() or {}
            if payload.get("status") == "error":
                return None
            resp = payload.get("response") or payload
            curves = resp.get("hazardCurves") or []
            pga = next((c for c in curves if (c.get("imt") or {}).get("value") == "PGA"), None)
            total = next((d for d in ((pga or {}).get("data") or [])
                          if d.get("component") == "Total"), None)
            vals = (total or {}).get("values") or {}
            xs, ys = vals.get("xs"), vals.get("ys")
            if not xs or not ys:
                return None
            p2 = _gm_at_rate(xs, ys, LAMBDA_2PCT_50)
            p10 = _gm_at_rate(xs, ys, LAMBDA_10PCT_50)
            if p2 is None or p10 is None:
                return None
            return round(p2, 3), round(p10, 3)
        except Exception:  # noqa: BLE001
            if attempt == RETRIES:
                return None
            time.sleep(BACKOFF ** attempt)
    return None


# ── Fallback: USGS ASCE7 design-maps 2%/50yr (× national ratio) ─────────────────
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
        d = haversine_miles(lat, lon, glat, glon)
        if d < 1e-6:
            return pga
        scored.append((d, pga))
    scored.sort(key=lambda t: t[0])
    near = scored[:k]
    wsum = sum(1.0 / d for d, _ in near)
    return sum((1.0 / d) * pga for d, pga in near) / wsum if wsum else None


# ── Public API ──────────────────────────────────────────────────────────────────
def get_pga(lat: float, lon: float,
            allow_network: bool = True) -> tuple[float, float, str] | None:
    """Return (pga_2pct, pga_10pct, source) for a lat/lon, or None if unavailable.

    Primary: the true 2%/50yr AND 10%/50yr PGA read off the USGS 2023 NSHM hazard
    curve. Fallbacks (which still derive 10%/50yr from the 0.43 ratio): the ASCE7
    design-maps service for non-CONUS points / NSHM outage, then the bundled grid.
    """
    lat, lon = round(float(lat), 3), round(float(lon), 3)
    if allow_network:
        hz = _nshm_hazard_pga(lat, lon)
        if hz is not None:
            return hz[0], hz[1], "USGS 2023 NSHM hazard curve (2%/50yr + 10%/50yr)"
        pga2 = _usgs_pga(lat, lon)
        if pga2 is not None:
            return round(pga2, 3), round(pga2 * PGA_10_2_RATIO, 3), "USGS ASCE7 (2%/50yr) × ratio"
    pga2 = _grid_pga(lat, lon)
    if pga2 is not None:
        return round(pga2, 3), round(pga2 * PGA_10_2_RATIO, 3), "bundled PGA grid × ratio"
    return None
