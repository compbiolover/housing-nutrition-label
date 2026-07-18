"""Transportation noise by location — census-tract exposure (keyless + offline).

Backs the **Noise** dimension: how quiet a location is, scored 0-100 where higher
= quieter. One tract-level layer, looked up with no network call:

  • **pct_ge60db** — the share of a tract's residents exposed to transportation
    noise (aviation + road + rail) of **LAeq ≥ 60 dB**. 60 dB is roughly a busy
    restaurant; sustained transportation noise at/above it is the level at which
    it becomes a recognized nuisance and sleep/health concern.

Resolution
----------
Resolved at the **census tract** (falling back to the tract's county mean when a
tract is missing) — mirroring the other tract-level location dimensions.
``noise_for_tract`` resolves tract → county; ``noise_for_county`` resolves the
county directly. Every result carries a ``geo_level`` (``"tract"`` / ``"county"``).

Scoring
-------
The exposure share is mapped to a 0-100 score by piecewise-linear interpolation
over the **national tract quantiles** (more exposure → lower score), so the score
reads directly as a national percentile of quiet — an identity dimension in
``data/national_percentile.py``, comparable across locations.

Data
----
  noise_tracts.csv.gz (tract) + noise_county.csv (county fallback), built by
  scripts/build_noise.py from the National Transportation Noise Exposure Map
  (Seto & Huang 2023, from the US DOT BTS National Transportation Noise Map).

Scope: US census tracts in the noise map (CONUS + Alaska + Hawai'i). A tract/county
absent from the tables returns None, so the caller leaves Noise unscored.

Source (public, US DOT BTS): https://doi.org/10.21949/3TFG-ZP62
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

from housing_label.data._util import num as _num

NOISE_VINTAGE = "BTS National Transportation Noise Exposure Map (2023, tract-level)"

_DIR = pathlib.Path(__file__).resolve().parent
_CSV = _DIR / "noise_county.csv"                     # county fallback
_TRACT_CSV = _DIR / "noise_tracts.csv"               # plain CSV accepted if present
_TRACT_CSV_GZ = _DIR / "noise_tracts.csv.gz"         # bundled (gzipped) tract table

# ── Score breakpoints: (% residents exposed to ≥60 dB → score) — a piecewise
# approximation to the national CDF, INVERTED (more noise = lower score). Anchors
# are the tract quantiles [min, p10, p25, p50, p75, p90, p95, p99, max] from
# scripts/build_noise.py.
_PCT_XS = [0.0, 0.08, 0.5, 1.85, 4.75, 9.28, 13.47, 26.54, 100.0]
_PCT_YS = [100.0, 90.0, 75.0, 50.0, 25.0, 10.0, 5.0, 1.0, 0.0]


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    """Piecewise-linear interpolation, flat outside the anchor range."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]


@lru_cache(maxsize=1)
def _tract_table():
    """tract GEOID (11-digit) → row {pct_ge60db}, via the shared columnar
    TractStore (memory-frugal for the ~84k-tract table)."""
    path = _TRACT_CSV_GZ if _TRACT_CSV_GZ.exists() else _TRACT_CSV
    if not path.exists():
        return {}
    from housing_label.data._tractstore import load_tract_store
    return load_tract_store(path, 11)


@lru_cache(maxsize=1)
def _county_table() -> dict[str, float]:
    """county FIPS (5-digit) → pct_ge60db (county mean fallback)."""
    table: dict[str, float] = {}
    if not _CSV.exists():
        return table
    with _CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            raw = str(row.get("county_fips") or "").strip()
            pct = _num(row.get("pct_ge60db"))
            if raw and pct is not None:
                table[raw.zfill(5)] = pct
    return table


def _reading(pct: float, geo_level: str) -> dict:
    return {
        "score": round(_interp(pct, _PCT_XS, _PCT_YS), 1),
        "pct_ge60db": pct,
        "geo_level": geo_level,
        "label": NOISE_VINTAGE,
    }


def noise_for_county(county_fips: str | None) -> dict | None:
    """Noise reading + 0-100 score (higher = quieter) for a 5-digit county FIPS.

    Returns None for a missing/blank FIPS or a county absent from the table, so the
    caller leaves Noise unscored.
    """
    if not county_fips:
        return None
    pct = _county_table().get(str(county_fips).strip().zfill(5))
    return None if pct is None else _reading(pct, "county")


def noise_for_tract(tract_geoid: str | None) -> dict | None:
    """Noise reading + 0-100 score for an 11-digit tract GEOID (tract → county).

    Returns None when neither the tract nor its county is in the bundled tables.
    """
    geoid = str(tract_geoid).strip().zfill(11) if tract_geoid else None
    if not geoid:
        return None
    row = _tract_table().get(geoid)
    if row is not None:
        pct = _num(row.get("pct_ge60db"))
        if pct is not None:
            return _reading(pct, "tract")
    return noise_for_county(geoid[:5])
