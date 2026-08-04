#!/usr/bin/env python3
"""Calibrate the Building grade against the homes US households actually live in.

Why
---
The Site & environment axis is ranked against the places US households live
(``calibrate_location_percentiles.py``). The Building axis was not — it kept the
raw mean of its members' percentiles and graded that on the absolute thresholds.

That left the two headline axes meaning different things, which is worse than it
sounds: a reader comparing "Building B / Site C" naturally assumes both letters
answer the same question, and only one of them was a rank against US homes.

The building axis happened to spread across the whole scale, which is why it was
not obviously broken. But "spreads well" is not the claim the label makes. This
makes it the same claim as the site axis: an 80 means *this home's construction
beats 80% of US homes*.

Method
------
Reuses the panel ``calibrate_construction_percentiles.py`` already built for the
per-dimension curves — the honest reference is the same one, one level up:

  • every US county, weighted by its ACS occupied-housing-unit count;
  • times a documented vintage x construction archetype grid whose shares come
    from the ACS B25034 year-built split and the ~80/20 frame/masonry mix;
  • scored OFFLINE through the real models, so energy picks up the county's
    climate zone, environmental its grid region, and resilience its wildfire and
    seismic hazard.

Each (county, archetype) is one simulated home carrying the household weight of
that combination. The distribution of ``construction_score`` over that panel is
what the grade is then ranked against.

What it is not
--------------
A census of real houses. The archetype grid is a documented model of the stock,
not a sample of deeds — so a surfaced percentile is an honest estimate versioned
by this build, exactly as ``construction_percentiles.csv`` already is. What it
does capture is the two things that actually move these scores: the national
vintage/material mix, and the geography those homes sit in.

Run:  python scripts/calibrate_building_percentiles.py
      python scripts/calibrate_building_percentiles.py --counties 600
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# One definition of the panel, imported rather than restated — the building axis
# and the per-dimension curves underneath it must be calibrated on the same stock,
# or the axis would rank against a population its own members never saw.
from scripts.calibrate_construction_percentiles import (  # noqa: E402
    ARCHETYPES, _download_centroids, _households)

PERCENTILES = [1, 5, 10, 25, 50, 75, 90, 95, 99]


def weighted_quantile(pairs: list[tuple[float, float]], pct: float) -> float:
    """`pairs` sorted by value; pct in 0-100. Lower-weighted-CDF convention."""
    total = sum(w for _, w in pairs)
    target, acc = total * pct / 100.0, 0.0
    for v, w in pairs:
        acc += w
        if acc >= target:
            return v
    return pairs[-1][0]


def build_panel(n_counties: int | None = None, progress=None):
    """[(construction_raw_mean, household weight)] over (county x archetype)."""
    from housing_label.simulate.house import build_label_parts, label_payload
    from housing_label.simulate.location import Location
    from housing_label.data import (climate as czone, egrid, wildfire,
                                    climate_projections as clim)

    centroids = _download_centroids(_ROOT / ".gaz_cache" / "counties.zip")
    households = _households()
    counties = sorted((c for c in households if c in centroids),
                      key=lambda c: households[c], reverse=True)
    if n_counties:
        counties = counties[:n_counties]

    pairs = []
    for i, fips in enumerate(counties, 1):
        lat, lon = centroids[fips]
        loc = Location(lat=lat, lon=lon, county_fips=fips,
                       climate_zone=czone.climate_zone_for_county(fips),
                       egrid_factor=egrid.egrid_for_county(fips)[1],
                       wildfire=wildfire.wildfire_for_county(fips),
                       climate_projection=clim.climate_projection_for_county(fips))
        for a in ARCHETYPES:
            try:
                cfg, r, label = build_label_parts(
                    location=loc, preset=None, allow_network=False,
                    year_built=a["year_built"], construction=a["construction"],
                    foundation=a["foundation"], condition=a["condition"],
                    sqft=a["sqft"], units=a["units"], lot_acres=a["lot_acres"])
                v = label_payload(cfg, r, label)["construction_raw_mean"]
            except Exception:                            # noqa: BLE001
                continue
            if v is not None:
                pairs.append((float(v), households[fips] * a["share"]))
        if progress and i % 100 == 0:
            progress(i, len(counties), len(pairs))
    pairs.sort()
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--counties", type=int, default=600,
                    help="score the N most-populous counties (default 600).")
    args = ap.parse_args()

    t0 = time.time()
    pairs = build_panel(args.counties, progress=lambda i, n, k: print(
        f"  {i}/{n} counties, {k:,} homes ({time.time() - t0:.0f}s)", file=sys.stderr))

    print(f"\nsimulated homes: {len(pairs):,}   "
          f"households represented: {sum(w for _, w in pairs):,.0f}")

    xs = [round(weighted_quantile(pairs, p), 1) for p in PERCENTILES]
    print(f"\n{'pct':>5} {'raw building sub-score':>24}")
    for p, x in zip(PERCENTILES, xs):
        print(f"{p:>4}% {x:>24}")

    print("\n# paste into data/national_percentile.py")
    print("BUILDING_XS = [" + ", ".join(f"{v:g}" for v in xs) + "]")
    print("BUILDING_YS = [" + ", ".join(str(p) for p in PERCENTILES) + "]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
