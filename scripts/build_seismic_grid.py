#!/usr/bin/env python3
"""Build the bundled coarse national PGA fallback grid.

Queries the USGS design-maps service across a coarse CONUS grid and writes
src/housing_label/data/seismic_pga_grid.csv (lat, lon, pga_2pct). This is a
one-time generator; the committed CSV is the offline fallback for
enrich/seismic_lookup.py when the live USGS service is unavailable.

Run:  python scripts/build_seismic_grid.py [--step 2.5]
"""

import argparse
import csv
import pathlib
import time

from housing_label.enrich.seismic_lookup import _usgs_pga

OUT = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data" / "seismic_pga_grid.csv"

# CONUS bounding box (a bit generous; ocean points just return low values).
LAT_MIN, LAT_MAX = 25.0, 49.0
LON_MIN, LON_MAX = -124.5, -67.0


def frange(lo, hi, step):
    v = lo
    while v <= hi + 1e-9:
        yield round(v, 3)
        v += step


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=float, default=2.5, help="Grid spacing in degrees.")
    ap.add_argument("--sleep", type=float, default=0.05, help="Delay between calls (s).")
    args = ap.parse_args()

    lats = list(frange(LAT_MIN, LAT_MAX, args.step))
    lons = list(frange(LON_MIN, LON_MAX, args.step))
    total = len(lats) * len(lons)
    print(f"Querying {total} grid points at {args.step}° spacing …")

    rows, done, hits = [], 0, 0
    for lat in lats:
        for lon in lons:
            pga = _usgs_pga(lat, lon)
            done += 1
            if pga is not None:
                rows.append((lat, lon, round(pga, 3)))
                hits += 1
            if done % 25 == 0:
                print(f"  {done}/{total}  ({hits} with data)")
            time.sleep(args.sleep)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["lat", "lon", "pga_2pct"])
        w.writerows(rows)
    print(f"Wrote {OUT} — {len(rows)} grid points with PGA data.")


if __name__ == "__main__":
    main()
