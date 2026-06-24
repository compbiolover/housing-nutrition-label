#!/usr/bin/env python3
"""Build the bundled county FIPS → eGRID subregion crosswalk.

Writes ``src/housing_label/data/egrid_subregions.csv`` (county_fips,
egrid_subregion) — the offline lookup that lets ``data/egrid.py`` return a real
regional grid CO2 factor for any US county instead of the national average.

Method (fully keyless, government-sourced)
------------------------------------------
EPA does not publish a county→subregion table; its authoritative mapping is
ZIP→utility→subregion (the Power Profiler tool). We aggregate that up to the
county level:

  1. EPA Power Profiler ``zip.csv`` → each ZIP's *predominant* utility subregion.
  2. Census 2020 ZCTA↔county relationship file → the land-area overlap between
     each ZCTA (≈ZIP) and each county it touches.
  3. For every county, sum the overlapping land area by subregion and assign the
     subregion with the largest share (area-weighted plurality).

Limitation: land-area weighting (population would be marginally better but the
keyless ZCTA population endpoint now requires an API key) can mis-assign the
small minority of counties that straddle two subregions toward the subregion
covering more *land* rather than more *people*. Straddling subregions are always
geographically adjacent, so their factors are similar; counties with no ZIP
coverage are simply omitted and fall back to the US-average factor. This is a
"national generalization" default, not a billing-grade determination.

Sources
-------
  • EPA Power Profiler ZIP crosswalk:
    https://github.com/USEPA/power-profiler  (app/data/zip.csv)
  • Census 2020 ZCTA↔County relationship file:
    https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt

Run:  python scripts/build_egrid_crosswalk.py
      python scripts/build_egrid_crosswalk.py --epa-zip local.csv --zcta-county local.txt
"""

from __future__ import annotations

import argparse
import csv
import io
import pathlib
import sys
from collections import defaultdict

import requests

OUT = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data" / "egrid_subregions.csv"

EPA_ZIP_URL = "https://raw.githubusercontent.com/USEPA/power-profiler/master/app/data/zip.csv"
ZCTA_COUNTY_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
    "tab20_zcta520_county20_natl.txt"
)
HEADERS = {"User-Agent": "housing-nutrition-label/0.1 (egrid crosswalk build)"}


def _load(url: str, local: str | None) -> str:
    if local:
        return pathlib.Path(local).read_text(encoding="utf-8-sig")
    print(f"  downloading {url}")
    r = requests.get(url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.content.decode("utf-8-sig")


def zip_to_subregion(epa_text: str) -> dict[str, str]:
    """ZIP (5-digit) → eGRID subregion, using each ZIP's predominant utility."""
    out: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(epa_text)):
        if str(row.get("Predominant Utility", "")).strip() != "1":
            continue
        z = str(row["zip"]).strip().zfill(5)
        sub = str(row["SUBRGN"]).strip()
        if z and sub:
            out[z] = sub
    return out


def county_subregions(zcta_text: str, zip_sub: dict[str, str]) -> dict[str, str]:
    """County FIPS → dominant subregion, area-weighted over its ZCTAs."""
    # county → subregion → summed overlapping land area
    weight: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in csv.DictReader(io.StringIO(zcta_text), delimiter="|"):
        zcta = str(row.get("GEOID_ZCTA5_20") or "").strip().zfill(5)
        county = str(row.get("GEOID_COUNTY_20") or "").strip().zfill(5)
        sub = zip_sub.get(zcta)
        if not sub or not county or county == "00000":
            continue
        try:
            area = float(row.get("AREALAND_PART") or 0.0)
        except ValueError:
            area = 0.0
        # Even zero-land overlaps (water-only) still signal coverage; nudge so a
        # county that only ever appears with 0 land area still gets assigned.
        weight[county][sub] += area + 1.0

    return {
        county: max(subs.items(), key=lambda kv: kv[1])[0]
        for county, subs in weight.items()
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--epa-zip", help="Local EPA Power Profiler zip.csv (else download).")
    ap.add_argument("--zcta-county", help="Local Census ZCTA↔county file (else download).")
    args = ap.parse_args()

    print("Loading EPA ZIP → subregion crosswalk …")
    zip_sub = zip_to_subregion(_load(EPA_ZIP_URL, args.epa_zip))
    print(f"  {len(zip_sub)} ZIPs across {len(set(zip_sub.values()))} subregions")

    print("Loading Census ZCTA ↔ county relationship file …")
    crosswalk = county_subregions(_load(ZCTA_COUNTY_URL, args.zcta_county), zip_sub)
    print(f"  resolved {len(crosswalk)} counties")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["county_fips", "egrid_subregion"])
        for fips in sorted(crosswalk):
            w.writerow([fips, crosswalk[fips]])
    print(f"Wrote {OUT} — {len(crosswalk)} counties.")

    if len(crosswalk) < 3000:
        print(f"WARNING: only {len(crosswalk)} counties resolved (expected ~3,200).",
              file=sys.stderr)


if __name__ == "__main__":
    main()
