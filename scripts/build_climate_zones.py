#!/usr/bin/env python3
"""Build the bundled county FIPS → IECC climate-zone crosswalk (2021 IECC).

Writes ``src/housing_label/data/climate_zones.csv`` (county_fips, iecc_zone) — the
offline lookup ``data/climate.py`` uses to scale the Energy dimension's EUI
benchmark by the property's climate zone.

Source
------
DOE / PNNL Building America "Guide to Determining Climate Zone by County"
(https://basc.pnnl.gov/guide-determining-climate-zone-county-data-files). The
distributed ``ClimateZoneDataFiles.zip`` carries one shapefile whose DBF holds
BOTH vintages per county: ``IECC15``/``Moisture15`` (the pre-2021 / 2015 IECC)
and ``IECC21``/``Moisture21`` (the current **2021 IECC**, per ASHRAE 169-2020).
The 2021 update moved ~370 counties (≈11%), almost all to a warmer zone; the
2024 IECC did not change the boundaries, so 2021 is the current authoritative map.
We read the **IECC21** columns.

Territories & retired FIPS
--------------------------
The PNNL table covers the 50 states + DC + Puerto Rico (3,220 counties). A handful
of counties in the prior crosswalk are outside it — the island territories
(American Samoa, Guam, N. Mariana Islands, US Virgin Islands, US minor outlying)
and one retired independent city (Bedford City VA, 51515, merged into Bedford
County in 2013). Their zones are stable (the territories are tropical 1A), so this
script carries them forward from the existing CSV rather than dropping coverage.

Run:  python scripts/build_climate_zones.py
      python scripts/build_climate_zones.py --zip local_ClimateZoneDataFiles.zip
"""

from __future__ import annotations

import argparse
import csv
import pathlib
import re
import struct
import sys
import time
import zipfile

import requests

_DATA = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"
OUT = _DATA / "climate_zones.csv"

ZIP_URL = "https://basc.pnnl.gov/sites/default/files/ClimateZoneDataFiles.zip"
# The PNNL host rejects the default python-requests UA (WAF), so present a browser UA.
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)", "Accept": "application/zip,*/*"}
DBF_MEMBER = "ClimateZones.dbf"
TIMEOUT = 120
MAX_RETRIES = 4


def _download(url: str, dest: pathlib.Path) -> pathlib.Path:
    if dest.exists() and dest.stat().st_size > (1 << 18):
        print(f"  cached {dest.name} ({dest.stat().st_size/1e6:.1f} MB)", file=sys.stderr)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            dest.write_bytes(r.content)
            print(f"  downloaded {dest.name} ({len(r.content)/1e6:.1f} MB)", file=sys.stderr)
            return dest
        except requests.RequestException as exc:
            print(f"  download attempt {attempt+1} failed: {exc}", file=sys.stderr)
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(2 ** attempt)
    return dest


def _parse_dbf(raw: bytes) -> list[dict]:
    """Minimal dBASE III reader — returns a list of {field: value} row dicts.

    (Avoids a GIS dependency: we only need the DBF attribute table, not geometry.)
    """
    num = struct.unpack("<I", raw[4:8])[0]
    hsize = struct.unpack("<H", raw[8:10])[0]
    rsize = struct.unpack("<H", raw[10:12])[0]
    fields, off = [], 32
    while raw[off] != 0x0D:
        name = raw[off:off + 11].split(b"\x00")[0].decode("latin-1")
        fields.append((name, raw[off + 16]))
        off += 32
    rows = []
    for i in range(num):
        rec = raw[hsize + i * rsize: hsize + (i + 1) * rsize]
        if rec[:1] == b"*":                       # deleted record
            continue
        o, vals = 1, {}
        for name, flen in fields:
            vals[name] = rec[o:o + flen].decode("latin-1").strip()
            o += flen
        rows.append(vals)
    return rows


def _zone(number: str, moisture: str) -> str | None:
    """Compose an IECC zone like "3A" / "5B" / "7" (zones 7 & 8 carry no letter)."""
    n, m = number.strip(), moisture.strip()
    return (n + m) if n else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", default=None, help="local ClimateZoneDataFiles.zip (skip download)")
    ap.add_argument("--cache-dir", default=None, help="download cache directory")
    args = ap.parse_args()

    if args.zip:
        zip_path = pathlib.Path(args.zip)
    else:
        cache = pathlib.Path(args.cache_dir
                             or (pathlib.Path(__file__).resolve().parents[1] / ".climate_zone_cache"))
        zip_path = _download(ZIP_URL, cache / "ClimateZoneDataFiles.zip")

    with zipfile.ZipFile(zip_path) as z:
        dbf = _parse_dbf(z.read(DBF_MEMBER))

    # Authoritative 2021 IECC zone per county (GEOID is "G"+FIPS in the shapefile).
    zones: dict[str, str] = {}
    for row in dbf:
        fips = re.sub(r"\D", "", row["GEOID"]).zfill(5)
        z = _zone(row["IECC21"], row["Moisture21"])
        if z:
            zones[fips] = z
    print(f"Parsed {len(zones)} counties from the 2021 IECC table.", file=sys.stderr)

    # Carry forward any prior-CSV counties the PNNL table doesn't cover (territories,
    # retired FIPS) so we never regress coverage.
    carried = 0
    if OUT.exists():
        with OUT.open() as f:
            for r in csv.DictReader(f):
                fips = str(r["county_fips"]).strip().zfill(5)
                if fips not in zones and r["iecc_zone"].strip():
                    zones[fips] = r["iecc_zone"].strip()
                    carried += 1
    if carried:
        print(f"Carried forward {carried} county rows outside the PNNL table "
              "(territories / retired FIPS).", file=sys.stderr)

    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["county_fips", "iecc_zone"])
        for fips in sorted(zones):
            w.writerow([fips, zones[fips]])
    print(f"Wrote {OUT.relative_to(_DATA.parents[2])} — {len(zones)} counties.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
