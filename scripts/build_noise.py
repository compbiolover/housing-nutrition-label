#!/usr/bin/env python3
"""Build the bundled census-tract transportation-noise table for the Noise dimension.

Writes two artifacts so the runtime (``data/noise.py``) can look up how noisy a
location is with no network call:

  • ``src/housing_label/data/noise_tracts.csv.gz`` — one row per census tract:
        geoid, pct_ge60db
  • ``src/housing_label/data/noise_county.csv`` — a county fallback (a simple,
        unweighted mean of the county's tract percentages — a coarse proxy, hit
        only when a tract can't be resolved):
        county_fips, pct_ge60db

``pct_ge60db`` is the share of a tract's residents exposed to transportation noise
of **LAeq ≥ 60 dB** — the population in the 60-70, 70-80, 80-90 and 90+ dB bands
divided by the tract's total population estimate. Higher = noisier.

Source
------
The **National Transportation Noise Exposure Map** (Seto & Huang 2023) — census-
tract population exposure to aviation + road + rail noise, derived from the US DOT
BTS National Transportation Noise Map. Distributed as per-state shapefiles; we read
only the ``.dbf`` attribute table (GEOID + per-dB-band population counts ``ns*n`` +
total population ``estimat``) with a small pure-Python dBASE reader — no geometry,
no GIS dependency. CONUS + Alaska/Hawai'i.

  Download page: https://deohs.washington.edu/national-transportation-noise-exposure-map-download
  Data DOI (BTS): https://doi.org/10.21949/3TFG-ZP62
  Underlying map: https://www.bts.gov/geospatial/national-transportation-noise-map

The two shapefile zips (~60 MB CONUS, plus AK/HI) are fetched at build time (dev-
time only; the shipped artifacts are the CSVs), or read from local copies with
``--conus-zip`` / ``--akhi-zip``.

Run:  python scripts/build_noise.py
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import pathlib
import struct
import sys
import zipfile

import requests

_DATA = pathlib.Path(__file__).resolve().parent.parent / "src" / "housing_label" / "data"
_TRACT_OUT = _DATA / "noise_tracts.csv.gz"
_COUNTY_OUT = _DATA / "noise_county.csv"

CONUS_URL = "https://www.edmundseto.com/NTNE_map/conus_shp.zip"
AKHI_URL = "https://www.edmundseto.com/NTNE_map/AK_HI_shp.zip"
_HEADERS = {"User-Agent": "housing-nutrition-label/noise-build"}
_TIMEOUT = 300

# Population-count fields for the ≥60 dB bands (60-70, 70-80, 80-90, 90+) and the
# total-population estimate, in the per-state ``.dbf`` attribute tables.
_GE60_FIELDS = ["ns6070n", "ns7080n", "ns8090n", "nois90n"]
_POP_FIELD = "estimat"
_GEOID_FIELD = "GEOID"


def _read_dbf(data: bytes) -> list[dict]:
    """Parse a dBASE III ``.dbf`` byte string into a list of {field: str} rows."""
    nrec = struct.unpack("<I", data[4:8])[0]
    hlen = struct.unpack("<H", data[8:10])[0]
    fields = []
    off = 32
    while data[off:off + 1] != b"\r":
        fd = data[off:off + 32]
        name = fd[:11].split(b"\x00")[0].decode("latin-1")
        fields.append((name, fd[16]))          # (name, length)
        off += 32
    reclen = sum(fl for _, fl in fields) + 1     # +1 deletion flag
    rows = []
    pos = hlen
    for _ in range(nrec):
        rec = data[pos:pos + reclen]
        pos += reclen
        if not rec or rec[0:1] == b"*":          # deleted record
            continue
        o = 1
        d = {}
        for name, fl in fields:
            d[name] = rec[o:o + fl].decode("latin-1").strip()
            o += fl
        rows.append(d)
    return rows


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _tract_noise_from_zip(raw: bytes) -> dict[str, float]:
    """{tract GEOID (11) → pct of residents exposed to ≥60 dB} from a shapefile zip.

    Reads every ``tractresult*.dbf`` member (one per state)."""
    out: dict[str, float] = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            if not name.lower().endswith(".dbf"):
                continue
            for row in _read_dbf(z.read(name)):
                geoid = (row.get(_GEOID_FIELD) or "").strip()[:11]
                if len(geoid) != 11 or not geoid.isdigit():
                    continue
                pop = _num(row.get(_POP_FIELD))
                if pop <= 0:
                    continue
                ge60 = sum(_num(row.get(f)) for f in _GE60_FIELDS)
                out[geoid] = round(100.0 * ge60 / pop, 2)
    return out


def _fetch(url: str, local: str | None) -> bytes:
    if local:
        return pathlib.Path(local).read_bytes()
    r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.content


def _quantiles(vals, qs=(0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)):
    s = sorted(vals)
    n = len(s)
    return [round(s[min(n - 1, int(round(q * (n - 1))))], 2) for q in qs]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--conus-zip", help="local CONUS shapefile zip (skip fetch)")
    ap.add_argument("--akhi-zip", help="local AK/HI shapefile zip (skip fetch)")
    ap.add_argument("--tracts-out", default=str(_TRACT_OUT))
    ap.add_argument("--county-out", default=str(_COUNTY_OUT))
    args = ap.parse_args()

    print("CONUS ← National Transportation Noise Exposure Map (per-state .dbf) …")
    tracts = _tract_noise_from_zip(_fetch(CONUS_URL, args.conus_zip))
    print(f"      {len(tracts)} CONUS tracts")
    print("AK/HI ← …")
    tracts.update(_tract_noise_from_zip(_fetch(AKHI_URL, args.akhi_zip)))
    print(f"      {len(tracts)} tracts total")

    with gzip.open(args.tracts_out, "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(["geoid", "pct_ge60db"])
        for g in sorted(tracts):
            w.writerow([g, f"{tracts[g]:.2f}"])
    print(f"Wrote {len(tracts)} tract rows → {args.tracts_out}")

    # County fallback: simple mean of the county's tract values (a coarse proxy —
    # noise is hyper-local — used only when a tract can't be resolved).
    by_county: dict[str, list[float]] = {}
    for g, v in tracts.items():
        by_county.setdefault(g[:5], []).append(v)
    with open(args.county_out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["county_fips", "pct_ge60db"])
        for fips in sorted(by_county):
            vals = by_county[fips]
            w.writerow([fips, f"{sum(vals) / len(vals):.2f}"])
    print(f"Wrote {len(by_county)} county rows → {args.county_out}")

    if tracts:
        print(f"pct≥60dB tract quantiles [10,25,50,75,90,95,99]: "
              f"{_quantiles(list(tracts.values()))}")
        zero = sum(1 for v in tracts.values() if v == 0.0)
        print(f"tracts with 0% exposure (quietest): {zero} ({100*zero/len(tracts):.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
