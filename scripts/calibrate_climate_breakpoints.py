#!/usr/bin/env python3
"""Recalibrate the Climate Projections breakpoints onto US HOUSEHOLDS, at tracts.

Why this exists
---------------
``data/national_percentile.py`` maps a score to a national percentile **"vs US
homes"**, and treats climate as needing no remapping because its breakpoints are
anchored to national quantiles. Those anchors had two problems at once, and this
script fixes both:

1. **Unweighted.** ``build_climate_projections.py`` printed them with
   ``statistics.quantiles`` over one value per county, so Loving County TX (64
   people) counted as much as Los Angeles County (10 million) — the same defect
   Solar shed in #257.

2. **Wrong geography.** The dimension RESOLVES at the tract
   (``climate_projection_for_tract``, sampled from the ~6 km LOCA2 grid), but the
   reference it was ranked against was a distribution of COUNTIES. A tract was
   being told its percentile among a population it was not a member of. Counties
   average away exactly the sub-county variation the tract file exists to capture,
   so this compressed the tails: an extreme tract inside an unremarkable county had
   nowhere to rank.

Both are fixed by taking household-weighted quantiles of the TRACT distribution —
the values that actually get scored, weighted by the homes that experience them.

Weights
-------
Households per tract, from the bundled ``socio_tracts.csv.gz`` (ACS) — no new data
source and no network. It is the right table for this because it shares the climate
file's tract vintage: 85,382 of the climate file's 85,396 tracts join, carrying
100% of its 130.5M households. The 14 that do not are Suffolk County NY (36103)
tract splits.

Two other bundled tract tables were rejected as weights, and the reasons are worth
recording so nobody re-tries them:

  * ``walkability_tracts.csv.gz`` also has a ``households`` column, but it is an
    older tract vintage (73,767 rows against climate's 85,396) — a quarter of all
    households fail to join.
  * ``health_tracts.csv.gz`` has ``totalpop18plus``, but CDC PLACES bundles no
    tracts at all for **Pennsylvania, Kentucky or Puerto Rico**, which would drop
    ~17M people and two whole climate regions out of the reference.

Tracts with zero households (1,103 of them — parks, water, industrial) correctly
contribute zero weight: nobody is exposed there.

Run:  python scripts/calibrate_climate_breakpoints.py
"""

from __future__ import annotations

import csv
import gzip
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_DATA = _ROOT / "src" / "housing_label" / "data"
_CLIMATE = _DATA / "climate_projections_tracts.csv.gz"
_SOCIO = _DATA / "socio_tracts.csv.gz"

# The score anchors, and the percentiles they sit at. Higher hazard → lower score,
# so the xs increase while the ys fall.
PERCENTILES = [5, 25, 50, 75, 90, 95]
SCORES = [100, 80, 60, 40, 20, 0]

# The metrics in data/climate_projections.py's _BREAKPOINTS, in that order. All are
# anchored on the LOW (SSP2-4.5) band; fire is a single RCP8.5 pathway whose low and
# high columns are identical, which `verify` below asserts rather than assumes.
METRICS = ["heat_days95", "heat_days100", "precip_days1in", "precip_max5day",
           "drought_consecdd", "fire_fwi"]
BAND = "low"


def _rows(path: pathlib.Path) -> list[dict]:
    with gzip.open(path, "rt", newline="") as f:
        return list(csv.DictReader(f))


def load() -> tuple[list[dict], dict[str, float]]:
    climate = _rows(_CLIMATE)
    weights = {r["geoid"].zfill(11): float(r["households"] or 0)
               for r in _rows(_SOCIO)}
    return climate, weights


def weighted_quantile(pairs: list[tuple[float, float]], pct: float) -> float:
    """`pairs` sorted by value; pct in 0-100. Lower-weighted-CDF convention."""
    total = sum(w for _, w in pairs)
    if total <= 0:
        raise ValueError("total weight is zero")
    target, acc = total * pct / 100.0, 0.0
    for v, w in pairs:
        acc += w
        if acc >= target:
            return v
    return pairs[-1][0]


def anchors(climate: list[dict], weights: dict[str, float],
            metric: str, band: str = BAND) -> list[float]:
    col = f"{metric}_{band}"
    pairs = sorted((float(r[col]), weights.get(r["geoid"].zfill(11), 0.0))
                   for r in climate if (r.get(col) or "").strip() != "")
    return [round(weighted_quantile(pairs, p), 1) for p in PERCENTILES]


def main() -> int:
    climate, weights = load()

    matched = sum(1 for r in climate if r["geoid"].zfill(11) in weights)
    covered = sum(weights.get(r["geoid"].zfill(11), 0.0) for r in climate)
    print(f"climate tracts: {len(climate):,}   weighted: {matched:,}   "
          f"households: {covered:,.0f}")

    # The fire leg is a single pathway; the module documents low == high. Check it
    # rather than trust it, since the anchors below are taken from the low column.
    bad = [r["geoid"] for r in climate
           if (r.get("fire_fwi_low") or "") != (r.get("fire_fwi_high") or "")]
    print(f"fire_fwi low == high on every tract: {not bad}"
          + (f"  ({len(bad)} mismatches!)" if bad else ""))

    print("\n_BREAKPOINTS (household-weighted tract quantiles):")
    for m in METRICS:
        xs = anchors(climate, weights, m)
        print(f'    "{m}":'.ljust(26) + f"({xs}, {SCORES}),")
    return 0


if __name__ == "__main__":
    sys.exit(main())
