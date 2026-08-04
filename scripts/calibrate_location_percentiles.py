#!/usr/bin/env python3
"""Calibrate the Site & environment grade against the places US households live.

Why
---
The Location sub-score is the mean of up to eight dimension percentiles. Averaging
percentiles pulls hard toward the middle — the standard deviation of a mean of *k*
of them is roughly 29/sqrt(k), about 10 at k=8 — so the raw mean clusters near 50
and the absolute grade thresholds (A >= 80 ... F < 20) stop discriminating. Measured
before this script existed: over 40 random tracts the raw sub-score ran 35.5-73.1
and landed **29 of 40 in C, with no A and no F**. An A was over three sigma out, so
the letter was close to decorative at the top of the range.

That is the same defect Solar (#257) and Climate (#258) had, and it takes the same
fix: rank the value against the distribution US HOUSEHOLDS actually experience,
rather than against a fixed 0-100 ruler nothing occupies the ends of.

Method
------
1. Sample census tracts and score each one with a FIXED reference building, so the
   only thing varying is the place.
   Hybrid members (resilience) are excluded from the aggregate by
   AGGREGATED_LOCATION, so the sample and the curve share one basis.
2. Take household-weighted quantiles of the resulting Location sub-scores, using
   the same ``socio_tracts.csv.gz`` household counts that #258 used for Climate.
3. Emit anchors mapping raw sub-score -> national percentile. The label then reads
   "this site beats N% of US homes' locations", which is the claim
   ``national_percentile.py`` makes for every other dimension.

The reference building, and why one is needed
---------------------------------------------
Two of the eight members are not pure properties of a place:

  * **resilience** is site hazard TIMES construction factors — the same tract
    scores differently for a 1975 frame house and a 2025 ICF one;
  * **infrastructure** divides the county's cost-to-serve by the revenue THIS
    parcel generates, so lot size, value and unit count all move it.

So "the distribution of locations" is only well defined once a building is fixed.
This uses the ``baseline`` preset — the closest thing the repo has to a typical US
home — and the resulting percentile is therefore *"how this site ranks for a
typical house"*. A mansion on the same parcel would shift its own resilience and
infrastructure scores; it does not shift the yardstick, which is the point of
having one.

Sampling
--------
Scoring all ~85k tracts takes ~1 hour at ~41 ms each, so this samples. Tracts are
drawn uniformly and then weighted by households, rather than drawn with probability
proportional to households: households per tract are deliberately uniform by
construction (the Census targets ~4,000 residents), so the two are near-equivalent
and the uniform draw keeps the estimator simple and unbiased.

Run:  python scripts/calibrate_location_percentiles.py
      python scripts/calibrate_location_percentiles.py --sample 8000 --seed 11
"""

from __future__ import annotations

import argparse
import csv
import gzip
import pathlib
import random
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_DATA = _ROOT / "src" / "housing_label" / "data"
_SOCIO = _DATA / "socio_tracts.csv.gz"

# The percentiles the curve is anchored at. Dense in the middle where most places
# sit, so the curve tracks the steep part of the CDF rather than chording across it.
PERCENTILES = [1, 5, 10, 25, 50, 75, 90, 95, 99]

REFERENCE_PRESET = "baseline"


def load_tract_households() -> dict[str, float]:
    with gzip.open(_SOCIO, "rt", newline="") as f:
        return {r["geoid"].zfill(11): float(r["households"] or 0)
                for r in csv.DictReader(f)}


def score_tract(tract: str):
    """RAW Location sub-score for one tract with the reference building, or None.

    ``location_raw_mean``, not ``location_score``. The latter is already the
    percentile this script produces the curve for, so sampling it would rank the
    ranking — the quantiles come back as an almost perfect 1, 5, 10 ... 99 straight
    line, which is what a circular calibration looks like from the outside.
    """
    from housing_label.simulate.location import resolve_location
    from housing_label.simulate.house import build_label_parts, label_payload
    geo = {"county_fips": tract[:5], "county_name": None, "state_fips": tract[:2],
           "tract": tract, "place_label": None, "place_geoid": None,
           # Unknown rather than False: the cost model reads None as "keep the full
           # service bundle", which is the neutral assumption for a yardstick.
           "incorporated": None, "in_urban_area": False}
    try:
        loc = resolve_location(lat=35.0, lon=-90.0, allow_network=False,
                               geography=geo)
        cfg, r, lbl = build_label_parts(preset=REFERENCE_PRESET, location=loc,
                                        allow_network=False)
        return label_payload(cfg, r, lbl)["location_raw_mean"]
    except Exception:                                    # noqa: BLE001
        return None


def weighted_quantile(pairs: list[tuple[float, float]], pct: float) -> float:
    """`pairs` sorted by value; pct in 0-100. Lower-weighted-CDF convention."""
    total = sum(w for _, w in pairs)
    target, acc = total * pct / 100.0, 0.0
    for v, w in pairs:
        acc += w
        if acc >= target:
            return v
    return pairs[-1][0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=20260804)
    args = ap.parse_args()

    households = load_tract_households()
    tracts = sorted(households)
    rng = random.Random(args.seed)
    picked = rng.sample(tracts, min(args.sample, len(tracts)))

    pairs, skipped = [], 0
    for i, t in enumerate(picked, 1):
        s = score_tract(t)
        if s is None:
            skipped += 1
            continue
        pairs.append((s, households.get(t, 0.0)))
        if i % 1000 == 0:
            print(f"  scored {i}/{len(picked)}", file=sys.stderr)
    pairs.sort()

    covered = sum(w for _, w in pairs)
    print(f"\nreference preset: {REFERENCE_PRESET}   seed: {args.seed}")
    print(f"tracts scored: {len(pairs):,}  (skipped {skipped})   "
          f"households represented: {covered:,.0f}")

    xs = [round(weighted_quantile(pairs, p), 1) for p in PERCENTILES]
    print(f"\n{'pct':>5} {'raw location sub-score':>24}")
    for p, x in zip(PERCENTILES, xs):
        print(f"{p:>4}% {x:>24}")

    print("\n# paste into data/national_percentile.py")
    print("LOCATION_XS = [" + ", ".join(f"{v:g}" for v in xs) + "]")
    print("LOCATION_YS = [" + ", ".join(str(p) for p in PERCENTILES) + "]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
