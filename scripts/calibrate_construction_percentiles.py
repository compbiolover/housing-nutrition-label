#!/usr/bin/env python3
"""Calibrate NATIONAL percentile curves for the construction-driven dimensions
(energy, durability, environmental, resilience).

Why
---
The location-driven dimensions already carry national percentiles (Tier 1:
health / socioeconomic / walkability), and infrastructure + climate breakpoints
already track national quantiles. The four construction-driven dimensions, though,
are absolute 0-100 scores whose *value* isn't a percentile — so "how does this
home's durability compare to US homes?" had no answer.

This builds that answer the same way ``scripts/calibrate_infra_breakpoints.py``
builds the infrastructure distribution: run the REAL scorers over a household-
weighted national panel of ``{US county} x {building archetype}`` and record the
weighted distribution of each dimension's score, then emit percentile-anchor
curves (score at p1, p5, … p99). A dimension score maps to a national percentile
by interpolating on that curve.

The panel is a *modeled* reference (documented archetypes, not a census of real
homes), so a surfaced percentile is an honest estimate, versioned by this build.

Method (reproducible, keyless)
------------------------------
  • counties + centroids: Census 2023 Gazetteer (INTPTLAT/INTPTLONG), keyless.
  • household weights: bundled socio_county.csv (ACS occupied-housing-unit counts).
  • building archetypes: a documented year x construction grid with national
    household shares (ACS B25034 vintage split; ~80/20 frame/masonry), condition
    tied to vintage, median size, value auto-filled to the county ACS median.
  • per (county, archetype): score OFFLINE via build_label_parts (bundled seismic/
    wildfire + fallbacks give resilience without network), weighted by
    county_households x archetype_share.

Output
------
  src/housing_label/data/construction_percentiles.csv — one row per dimension with
  the score at each percentile anchor. Loaded by data/national_percentile.py.

Run:  python scripts/calibrate_construction_percentiles.py
      python scripts/calibrate_construction_percentiles.py --limit-counties 200  # quick
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import pathlib
import sys
import time
import zipfile

import numpy as np
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger("calib_construction")

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DATA = _ROOT / "src" / "housing_label" / "data"
GAZ_URL = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer"
           "/2023_Gaz_counties_national.zip")
HEADERS = {"User-Agent": "housing-nutrition-label/0.1 (construction-percentile build)"}

DIMENSIONS = ["energy", "durability", "environmental", "resilience"]
PCTS = [1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 99]

# Building archetypes: (year_built, construction, condition, national_share).
# Vintage split ≈ ACS B25034 occupied-unit shares; ~80% frame / ~20% masonry;
# condition tied to vintage (older stock skews toward average, newest toward good).
# Size is held at the US median (~1,800 sqft); value auto-fills to the county median.
_VINTAGES = [  # (year, condition, vintage_share)
    (1935, "average", 0.12),
    (1955, "average", 0.22),
    (1980, "average", 0.24),
    (2000, "good",    0.28),
    (2016, "good",    0.14),
]
_CONSTRUCTIONS = [("frame", 0.80), ("brick", 0.20)]
ARCHETYPES = [
    {"year_built": yr, "condition": cond, "construction": con,
     "foundation": "slab", "sqft": 1800, "units": 1, "lot_acres": 0.25,
     "share": vshare * cshare}
    for yr, cond, vshare in _VINTAGES
    for con, cshare in _CONSTRUCTIONS
]


def _download_centroids(cache: pathlib.Path) -> dict[str, tuple[float, float]]:
    """county FIPS -> (lat, lon) from the Census Gazetteer (cached)."""
    if not (cache.exists() and cache.stat().st_size > 1000):
        cache.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(GAZ_URL, headers=HEADERS, timeout=120)
        r.raise_for_status()
        cache.write_bytes(r.content)
    z = zipfile.ZipFile(io.BytesIO(cache.read_bytes()))
    text = z.read(z.namelist()[0]).decode("latin-1")
    out: dict[str, tuple[float, float]] = {}
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        row = {k.strip(): v for k, v in row.items()}
        try:
            out[row["GEOID"].zfill(5)] = (float(row["INTPTLAT"]), float(row["INTPTLONG"]))
        except (KeyError, ValueError):
            continue
    return out


def _households() -> dict[str, float]:
    """county FIPS -> household count (ACS occupied units) from socio_county.csv."""
    path = _DATA / "socio_county.csv"
    out: dict[str, float] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            g = str(row.get("geoid", "")).strip().zfill(5)
            try:
                hh = float(row.get("households") or 0)
            except ValueError:
                hh = 0.0
            if g and g != "00000" and hh > 0:
                out[g] = hh
    return out


def _weighted_percentile(vals: np.ndarray, wts: np.ndarray, pct: float) -> float:
    order = np.argsort(vals)
    v, w = vals[order], wts[order]
    cum = np.cumsum(w) - 0.5 * w
    return float(np.interp(pct / 100.0 * w.sum(), cum, v))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit-counties", type=int, default=None,
                    help="(quick) score only the N most-populous counties.")
    args = ap.parse_args()

    from housing_label.simulate.house import build_label_parts
    from housing_label.simulate.location import Location
    from housing_label.data import (climate as czone, egrid, wildfire,
                                    climate_projections as clim)

    def county_location(fips: str, lat: float, lon: float) -> Location:
        """A Location carrying this county's bundled climate zone, grid factor,
        wildfire, and climate projection — so offline scoring reflects the county's
        real geography (energy by climate zone, environmental by grid, resilience by
        wildfire) instead of the default fallbacks a bare lat/lon would use offline."""
        return Location(
            lat=lat, lon=lon, county_fips=fips,
            climate_zone=czone.climate_zone_for_county(fips),
            egrid_factor=egrid.egrid_for_county(fips)[1],
            wildfire=wildfire.wildfire_for_county(fips),
            climate_projection=clim.climate_projection_for_county(fips))

    centroids = _download_centroids(_ROOT / ".gaz_cache" / "counties.zip")
    households = _households()
    counties = sorted((c for c in households if c in centroids),
                      key=lambda c: households[c], reverse=True)
    if args.limit_counties:
        counties = counties[: args.limit_counties]
    log.info("Panel: %d counties x %d archetypes = %d scorings.",
             len(counties), len(ARCHETYPES), len(counties) * len(ARCHETYPES))

    samples = {d: {"v": [], "w": []} for d in DIMENSIONS}
    t0 = time.time()
    for i, fips in enumerate(counties, 1):
        lat, lon = centroids[fips]
        loc = county_location(fips, lat, lon)
        for a in ARCHETYPES:
            try:
                _cfg, _r, label = build_label_parts(
                    location=loc, preset=None, allow_network=False,
                    year_built=a["year_built"], construction=a["construction"],
                    foundation=a["foundation"], condition=a["condition"],
                    sqft=a["sqft"], units=a["units"], lot_acres=a["lot_acres"])
            except Exception:  # noqa: BLE001 — skip a county that can't score
                continue
            scores = {d["key"]: d.get("score") for d in label["dimensions"]}
            w = households[fips] * a["share"]
            for d in DIMENSIONS:
                s = scores.get(d)
                if s is not None:
                    samples[d]["v"].append(float(s))
                    samples[d]["w"].append(w)
        if i % 250 == 0:
            log.info("  %d/%d counties (%.0fs)", i, len(counties), time.time() - t0)

    out_path = _DATA / "construction_percentiles.csv"
    with out_path.open("w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["dimension"] + [f"p{p}" for p in PCTS])
        for d in DIMENSIONS:
            v = np.array(samples[d]["v"]); w = np.array(samples[d]["w"])
            if len(v) == 0:
                log.warning("no samples for %s", d); continue
            row = [round(_weighted_percentile(v, w, p), 2) for p in PCTS]
            wr.writerow([d] + row)
            log.info("%-14s p10=%.1f p50=%.1f p90=%.1f (n=%d)", d, row[2], row[6], row[10], len(v))
    log.info("Wrote %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
