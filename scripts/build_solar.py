#!/usr/bin/env python3
"""Build the bundled county solar-yield table for the Solar Potential dimension.

Writes ``src/housing_label/data/solar_yield_county.csv`` — one row per US county:

    county_fips, specific_yield_kwh_kwp, irradiation_kwh_m2

so the runtime (``data/solar.py``) can look up rooftop-solar productivity for any
county with no network call. Values come from the EU Joint Research Centre's
**PVGIS v5.2** PV-performance model, queried at each county's internal point using
the **PVGIS-NSRDB** satellite database (the same NREL NSRDB resource PVWatts uses,
covering the Americas). PVGIS is keyless and, unlike NREL's own API host, reachable
from this build environment — so the whole layer is self-served, no data handoff.

For each county we model a standard **1 kWp** rooftop array (so the annual energy
IS the specific yield, kWh per kW installed per year): building-mounted, 14% system
losses, at the **optimal tilt facing south** (a fair "well-oriented rooftop"
potential). ``specific_yield_kwh_kwp`` = PVGIS ``E_y``; ``irradiation_kwh_m2`` =
annual in-plane irradiation ``H(i)_y``.

County centroids come from the Census county **gazetteer** (``INTPTLAT`` /
``INTPTLONG``). PVGIS-NSRDB covers the contiguous US, Hawai'i, and Puerto Rico;
a county outside coverage (far-north Alaska) errors and is skipped → unscored.

The run makes ~3,100 keyless requests (bounded concurrency, polite retries) and
checkpoints to the CSV, so it can be stopped and resumed (existing county rows are
skipped on restart). Dev-time only; the shipped artifact is the CSV.

Sources
-------
  PVGIS v5.2 API (CC BY 4.0):  https://re.jrc.ec.europa.eu/api/v5_2/PVcalc
  Census county gazetteer:
    https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_counties_national.zip

Run:  python scripts/build_solar.py            # fetch + write the CSV
"""
from __future__ import annotations

import argparse
import csv
import io
import pathlib
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import requests

_OUT = (pathlib.Path(__file__).resolve().parent.parent
        / "src" / "housing_label" / "data" / "solar_yield_county.csv")

PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"
GAZ_URL = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
           "2023_Gazetteer/2023_Gaz_counties_national.zip")
_HEADERS = {"User-Agent": "housing-nutrition-label/solar-build"}


def _county_centroids(path: str | None) -> list[tuple[str, float, float]]:
    """[(5-digit county FIPS, lat, lon)] from the Census county gazetteer."""
    if path:
        text = pathlib.Path(path).read_text(encoding="latin-1")
    else:
        r = requests.get(GAZ_URL, headers=_HEADERS, timeout=120)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            name = next(n for n in z.namelist() if n.endswith(".txt"))
            text = z.read(name).decode("latin-1")
    out = []
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        row = {k.strip(): (v.strip() if v else v) for k, v in row.items()}
        try:
            out.append((row["GEOID"].zfill(5),
                        float(row["INTPTLAT"]), float(row["INTPTLONG"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _pvgis_yield(lat: float, lon: float, retries: int = 4) -> tuple[float, float] | None:
    """(specific yield kWh/kWp/yr, in-plane irradiation kWh/m²/yr) or None.

    None means PVGIS has no data at this point (outside NSRDB coverage) or the
    request failed after retries."""
    params = {
        "lat": f"{lat:.4f}", "lon": f"{lon:.4f}",
        "peakpower": "1", "loss": "14", "mountingplace": "building",
        "raddatabase": "PVGIS-NSRDB", "optimalinclination": "1", "aspect": "0",
        "outputformat": "json",
    }
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(PVGIS_URL, params=params, headers=_HEADERS, timeout=60)
            if r.status_code == 400:
                return None                      # location outside coverage
            r.raise_for_status()
            t = r.json()["outputs"]["totals"]["fixed"]
            return round(float(t["E_y"]), 1), round(float(t["H(i)_y"]), 1)
        except Exception:                        # noqa: BLE001 — retry transient errors
            if attempt == retries:
                return None
            time.sleep(1.5 * attempt)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gazetteer-path", help="local Census county gazetteer .txt (skip fetch)")
    ap.add_argument("--out", default=str(_OUT), help="output CSV path")
    ap.add_argument("--workers", type=int, default=10, help="concurrent PVGIS requests")
    args = ap.parse_args()

    out_path = pathlib.Path(args.out)
    counties = _county_centroids(args.gazetteer_path)
    print(f"{len(counties)} county centroids ← Census gazetteer")

    # Resume: keep county rows already written, only fetch the rest.
    done: dict[str, tuple[str, str]] = {}
    if out_path.exists():
        with out_path.open() as f:
            for row in csv.DictReader(f):
                if row.get("specific_yield_kwh_kwp"):
                    done[row["county_fips"]] = (row["specific_yield_kwh_kwp"],
                                                row.get("irradiation_kwh_m2", ""))
    todo = [c for c in counties if c[0] not in done]
    print(f"{len(done)} already done, fetching {len(todo)} …")

    results: dict[str, tuple[float, float] | None] = {}
    lock = threading.Lock()
    n = [0]

    def _merged() -> dict[str, tuple[str, str]]:
        rows = dict(done)                                  # resumed rows
        for fips, res in results.items():
            if res is not None:
                rows[fips] = (f"{res[0]:.1f}", f"{res[1]:.1f}")
        return rows

    def _flush():
        rows = _merged()
        with out_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["county_fips", "specific_yield_kwh_kwp", "irradiation_kwh_m2"])
            for fips in sorted(rows):
                y, ir = rows[fips]
                w.writerow([fips, y, ir])

    def work(c):
        fips, lat, lon = c
        res = _pvgis_yield(lat, lon)
        with lock:
            results[fips] = res
            n[0] += 1
            # Periodic checkpoint: the CSV on disk stays a valid, sorted, resumable
            # snapshot, so an interrupted run can pick up where it left off.
            if n[0] % 250 == 0:
                print(f"   {n[0]}/{len(todo)} …")
                _flush()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, todo))

    _flush()
    rows = _merged()
    misses = sum(1 for r in results.values() if r is None)
    print(f"\nWrote {len(rows)} county rows → {out_path}"
          + (f"  ({misses} outside PVGIS coverage, skipped)" if misses else ""))
    if rows:
        vals = sorted(float(y) for y, _ in rows.values())
        m = len(vals)
        q = lambda p: round(vals[min(m - 1, int(p * (m - 1)))], 0)  # noqa: E731
        print(f"Specific yield kWh/kWp national quantiles [10,25,50,75,90,95]: "
              f"[{q(.10)}, {q(.25)}, {q(.50)}, {q(.75)}, {q(.90)}, {q(.95)}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
