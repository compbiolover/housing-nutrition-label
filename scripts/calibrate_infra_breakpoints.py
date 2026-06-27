#!/usr/bin/env python3
"""Calibrate the Infrastructure Burden fiscal-ratio → score breakpoints to a
NATIONAL distribution (replacing the original Shelby-pilot-anchored thresholds).

Why
---
``src/housing_label/score/all_dimensions.py`` maps a parcel's fiscal ratio (property-tax revenue ÷
modeled cost-to-serve) to a 0–100 score via ``INFRA_XS`` breakpoints. Those were
anchored to the Shelby pilot's distribution, so once the cost and revenue sides
were localized per county (Census of Governments + ACS), the absolute grades were
no longer defensible nationally. This tool builds a national distribution of
fiscal ratios and prints percentile-anchored breakpoints so a given score means
roughly the same national percentile everywhere (e.g. a D ≈ bottom 20–40%).

Method (reproducible, from already-bundled crosswalks — no downloads)
--------------------------------------------------------------------
Build the national distribution over a grid of {US county} × {density archetype}:

  • county inputs (bundled): median home value + effective property-tax rate
    (``property_tax_county.csv``); per-function cost multipliers + population
    (``govfinance_county.csv``).
  • density archetypes: a documented spread of US residential densities, each with
    an approximate national household share (DENSITY_ARCHETYPES below).
  • each (county, archetype) fiscal ratio is computed with the SAME cost model the
    app uses (``housing_label.enrich.infrastructure.enrich_row``), and weighted by
    county population × archetype share — so the distribution reflects where US
    homes actually are, across the real density mix.

The printed percentiles are then baked into ``INFRA_XS`` (the repo's pattern:
breakpoints anchored to a printed national distribution, kept as a static const).

Run:  python scripts/calibrate_infra_breakpoints.py
"""

from __future__ import annotations

import csv
import pathlib

import pandas as pd

from housing_label.enrich.infrastructure import enrich_row

_DATA = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"

# Documented spread of US residential densities (DU/acre) with approximate national
# household shares. These are deliberately coarse but transparent — adjust the
# shares to reweight the reference mix. (Most US households are single-family on
# small-to-moderate lots, with a meaningful urban-multifamily tail.)
DENSITY_ARCHETYPES = [
    # (label, dwelling_units_per_acre, national_household_share, is_urban)
    ("rural / exurban (~2 ac)",      0.5, 0.12, False),
    ("large-lot suburb (~0.6 ac)",   1.5, 0.18, False),
    ("standard suburb (~0.2 ac)",    4.0, 0.35, True),
    ("compact suburb / townhome",    8.0, 0.20, True),
    ("urban multifamily",           20.0, 0.15, True),
]

# Map each score anchor to a percentile of the national fiscal-ratio distribution,
# so the resulting score tracks national percentile rank (score ≈ percentile).
SCORE_PERCENTILES = [(0, 5), (20, 20), (40, 40), (60, 60), (80, 80), (100, 95)]


def _load(path: pathlib.Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            g = str(row.get("geoid", "")).strip().zfill(5)
            if g:
                out[g] = row
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_distribution() -> list[tuple[float, float]]:
    """Return [(fiscal_ratio, weight)] over all (county × archetype) points."""
    tax = _load(_DATA / "property_tax_county.csv")
    gov = _load(_DATA / "govfinance_county.csv")
    components = ["roads", "water_sewer", "fire", "police", "sanitation", "parks"]

    points: list[tuple[float, float]] = []
    for fips, trow in tax.items():
        if fips == "00000":
            continue
        value = _num(trow.get("median_value"))
        rate = _num(trow.get("effective_tax_rate"))
        grow = gov.get(fips)
        if value is None or value <= 0 or rate is None or grow is None:
            continue
        pop = _num(grow.get("pop")) or 0.0
        if pop <= 0:
            continue
        mult = {c: (_num(grow.get(f"mult_{c}")) or 1.0) for c in components}
        # Net schools out of the revenue rate (like-for-like with the non-school
        # cost side), matching simulate/dimensions.py.
        school = _num(grow.get("school_tax_share"))
        school = school if school is not None and 0.0 <= school <= 1.0 else 0.41
        municipal_rate = rate * (1.0 - school)
        for _, du_acre, share, urban in DENSITY_ARCHETYPES:
            row = pd.Series({"CALC_ACRE": 1.0 / du_acre, "latitude": None,
                             "longitude": None, "RTOTAPR": value})
            out = enrich_row(row, assess_ratio=1.0, tax_rate=municipal_rate,
                             in_urban_area=urban, cost_multipliers=mult)
            fr = out.get("fiscal_ratio")
            if fr is not None and not pd.isna(fr):
                points.append((float(fr), pop * share))
    return points


def weighted_percentile(points: list[tuple[float, float]], pct: float) -> float:
    """Population-weighted percentile of the fiscal-ratio distribution."""
    if not points:
        raise ValueError("no fiscal-ratio points to take a percentile of")
    pts = sorted(points)
    total = sum(w for _, w in pts)
    if total <= 0:
        raise ValueError("total weight is zero — cannot compute a weighted percentile")
    target = total * pct / 100.0
    cum = 0.0
    for val, w in pts:
        cum += w
        if cum >= target:
            return val
    return pts[-1][0]


def main() -> int:
    points = build_distribution()
    if not points:
        raise SystemExit(
            "No fiscal-ratio points were produced — check that the bundled "
            "crosswalks (property_tax_county.csv, govfinance_county.csv) exist and "
            "have the expected columns.")
    print(f"National distribution: {len(points):,} (county × archetype) points, "
          f"weight = population × household share.\n")

    print("Fiscal-ratio percentiles (weighted):")
    for p in (1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 99):
        print(f"  p{p:<3} = {weighted_percentile(points, p):.3f}")

    xs = [round(weighted_percentile(points, p), 3) for _, p in SCORE_PERCENTILES]
    ys = [s for s, _ in SCORE_PERCENTILES]
    # Enforce strictly increasing xs (log-linear interp requires it).
    for i in range(1, len(xs)):
        if xs[i] <= xs[i - 1]:
            xs[i] = round(xs[i - 1] + 0.001, 3)

    print("\nSuggested national breakpoints (paste into src/housing_label/score/all_dimensions.py):")
    print(f"  INFRA_XS = {xs}")
    print(f"  INFRA_YS = {[float(y) for y in ys]}")
    print("\n(score ≈ national percentile rank: A=top 20%, B=60–80th, C=40–60th, "
          "D=20–40th, F=bottom 20%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
