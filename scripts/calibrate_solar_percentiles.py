#!/usr/bin/env python3
"""Recalibrate the Solar Potential breakpoints onto US HOUSEHOLDS.

Why this exists
---------------
``data/national_percentile.py`` says, in its first line, that it maps a score to a
national percentile **"vs US homes"**, and it lists solar among the dimensions that
need no remapping because *"their breakpoints are anchored to national quantiles,
so the score already tracks national percentile rank"*.

That argument quietly equates "percentile among 3,140 counties" with "percentile
among US homes". ``scripts/build_solar.py`` computed its quantiles over one value
per county, **unweighted**, so Loving County TX (64 people) counted exactly as much
as Los Angeles County (10 million). US households are concentrated in sunnier
places than US counties are, so the unweighted curve sat too low across its upper
half and over-credited a sunny-but-not-extreme parcel by up to ~7 points — right
where the A/B grade boundary lives.

Walkability and the four construction dimensions were already household-weighted
(see ``national_percentile.py``). Solar skipped it by riding the "already a
quantile" argument. This script closes that gap; it does not invent a new standard.

Weights
-------
Housing units per county, from the bundled ``county_lot_density.csv`` (2020 Census)
— no new data source, no network.

The two tables are built from different geography vintages, and that has to be
reconciled rather than ignored:

  * ``solar_yield_county.csv`` uses the 2023 gazetteer, in which **Connecticut** is
    nine PLANNING REGIONS (FIPS 09110-09190).
  * ``county_lot_density.csv`` uses 2020 Census geography, in which Connecticut is
    its eight legacy COUNTIES (09001-09015).

So none of Connecticut joins, and dropping it would silently remove 1.53M housing
units — 1.1% of the country, all sitting in one narrow band of the yield axis
(1265-1332 kWh/kWp), which would bias the lower-middle quantiles upward.

The rule below is general rather than a Connecticut special case: **within each
state, household mass is conserved.** Housing units belonging to counties absent
from the yield table are redistributed equally across that state's yield counties
that have no weight of their own. Connecticut is currently the only state where it
fires, and the script says so when it runs.

Mass belonging to counties PVGIS has no yield for *at all* (far-north Alaska
outside NSRDB coverage, and the territories) is correctly excluded instead: no home
there is scored on this dimension, so it does not belong in the reference
distribution either.

Run:  python scripts/calibrate_solar_percentiles.py
"""

from __future__ import annotations

import collections
import csv
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_DATA = _ROOT / "src" / "housing_label" / "data"
_YIELD_CSV = _DATA / "solar_yield_county.csv"
_DENSITY_CSV = _DATA / "county_lot_density.csv"

# The percentiles the breakpoint curve is anchored at. p0/p100 come from the
# observed min/max rather than from this list.
PERCENTILES = [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
NATIONAL_ROW = "00000"


def load_yields() -> dict[str, float]:
    return {r["county_fips"].zfill(5): float(r["specific_yield_kwh_kwp"])
            for r in csv.DictReader(_YIELD_CSV.open(newline=""))
            if (r.get("specific_yield_kwh_kwp") or "").strip()}


def load_housing_units() -> dict[str, float]:
    out = {}
    for r in csv.DictReader(_DENSITY_CSV.open(newline="")):
        geoid = str(r.get("geoid", "")).strip().zfill(5)
        if geoid == NATIONAL_ROW or not geoid.strip("0"):
            continue
        out[geoid] = float(r.get("housing_units") or 0)
    return out


def household_weights(yields: dict[str, float],
                      units: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    """county -> housing units, with per-state mass conservation. Plus a log."""
    weights = {k: units[k] for k in yields if k in units}
    unweighted = [k for k in yields if k not in units]

    # Mass in the density table with no counterpart in the yield table, by state.
    orphan = collections.Counter()
    for k, hu in units.items():
        if k not in yields:
            orphan[k[:2]] += hu

    log = []
    by_state = collections.defaultdict(list)
    for k in unweighted:
        by_state[k[:2]].append(k)
    for state, cousins in sorted(by_state.items()):
        share = orphan.get(state, 0.0) / len(cousins)
        for k in cousins:
            weights[k] = share
        log.append(f"state {state}: {orphan.get(state, 0.0):,.0f} housing units from "
                   f"a different geography vintage redistributed across "
                   f"{len(cousins)} yield counties ({share:,.0f} each)")

    dropped = sum(m for s, m in orphan.items() if s not in by_state)
    if dropped:
        log.append(f"excluded: {dropped:,.0f} housing units in counties PVGIS has no "
                   f"yield for (outside NSRDB coverage) — no home there is scored on "
                   f"this dimension")
    return weights, log


def weighted_quantile(pairs: list[tuple[float, float]], p: float) -> float:
    """`pairs` sorted by value; p in [0,1]. Lower-weighted-CDF convention."""
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= p * total:
            return v
    return pairs[-1][0]


def main() -> int:
    yields, units = load_yields(), load_housing_units()
    weights, log = household_weights(yields, units)
    for line in log:
        print(f"  note: {line}")

    pairs = sorted((v, weights.get(k, 0.0)) for k, v in yields.items())
    covered = sum(w for _, w in pairs)
    print(f"\ncounties: {len(pairs)}   households represented: {covered:,.0f}")

    xs = ([pairs[0][0]] + [weighted_quantile(pairs, p) for p in PERCENTILES]
          + [pairs[-1][0]])
    ys = [0.0] + [p * 100 for p in PERCENTILES] + [100.0]

    unw = sorted(yields.values())
    def uq(p):  # noqa: E306 — unweighted, for the comparison column only
        return unw[min(len(unw) - 1, int(p * (len(unw) - 1)))]

    print(f"\n{'pct':>5} {'unweighted':>12} {'household-wtd':>14} {'shift':>8}")
    for p in PERCENTILES:
        u, w = uq(p), weighted_quantile(pairs, p)
        print(f"{p*100:>4.0f}% {u:>12.1f} {w:>14.1f} {w-u:>+8.1f}")

    print("\n_YIELD_XS = [" + ", ".join(f"{v:g}" for v in xs) + "]")
    print("_YIELD_YS = [" + ", ".join(f"{v:g}" for v in ys) + "]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
