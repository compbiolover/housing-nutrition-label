#!/usr/bin/env python3
"""Build the bundled per-county median gross rent crosswalk.

Writes ``src/housing_label/data/rent_county.csv`` — for every U.S. county, the
median gross rent (monthly, dollars). This is the market-rent input to the
**dense-housing value-per-door** estimate (``data/multifamily_value.py``): a
detected multi-family building's per-unit value is derived from local rent via the
standard income / cap-rate method, instead of the single-family owner-occupied
median (ACS B25077) that is wrong for apartments and condos.

Method
------
Median gross rent per county comes from the U.S. Census Bureau **American
Community Survey 5-year** estimates:

  - B25064_001  Median gross rent (renter-occupied units paying cash rent), dollars/mo

Gross rent (contract rent + tenant-paid utilities) is the standard national
rent measure. It is rent paid by *current* tenants, so it slightly understates
market rent for new/market-rate construction — HUD Fair Market Rents (40th
percentile, market-rent-targeted) are the preferred input and can replace this
crosswalk later without changing the value formula (see data/multifamily_value.py).

Source (keyless, free, public — bulk files, no API key)
-------------------------------------------------------
The modern ACS **table-based Summary File** publishes one pipe-delimited file per
table, keyless (the Census Data API requires a key; these bulk files do not). The
first column is ``GEO_ID``; county records use summary level 050 with GEO_ID
``0500000US<5-digit FIPS>``, and the national row is ``0100000US``. This mirrors
``scripts/build_property_tax.py`` exactly (same source, vintage, and parser).

Run:  python scripts/build_rent.py
"""

from __future__ import annotations

import argparse
import csv
import pathlib
import statistics
import sys
import time

import requests

_DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"
HEADERS = {"User-Agent": "housing-nutrition-label/0.1 (rent crosswalk build)"}

ACS_YEAR = 2024
_SF = (f"https://www2.census.gov/programs-surveys/acs/summary_file/{ACS_YEAR}"
       "/table-based-SF/data/5YRData")
RENT_URL = f"{_SF}/acsdt5y{ACS_YEAR}-b25064.dat"   # median gross rent (monthly)

COUNTY_PREFIX = "0500000US"   # ACS GEO_ID prefix for summary level 050 (county)
NATION_GEOID = "0100000US"

RENT_FLOOR, RENT_CEIL = 200.0, 5000.0   # $/mo sanity clamp (guards ACS small-county noise)
OUT_COLUMNS = ["geoid", "median_gross_rent", "resolved"]


def _download(url: str, dest: pathlib.Path, *, min_size: int = 1024) -> pathlib.Path:
    """Stream a URL to ``dest`` with retry/back-off; reuse a valid cached file."""
    if dest.exists() and dest.stat().st_size >= min_size:
        print(f"  cached {dest.name} ({dest.stat().st_size/1e6:.0f} MB)", file=sys.stderr)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        try:
            with requests.get(url, headers=HEADERS, timeout=180, stream=True) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                tmp.replace(dest)
            return dest
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return dest


def _parse_table(path: pathlib.Path) -> dict[str, float]:
    """GEO_ID → first-column estimate (E001) for all geographies in a table file.

    Returns the national row under the key ``NATION_GEOID`` too. Non-numeric /
    suppressed estimates (negative ACS jam values) are skipped.
    """
    out: dict[str, float] = {}
    with path.open(encoding="latin-1") as f:
        header = f.readline().rstrip("\n").split("|")
        try:
            est_col = header.index([h for h in header if h.endswith("_E001")][0])
        except (ValueError, IndexError):
            raise SystemExit(f"No *_E001 estimate column in {path.name}")
        for line in f:
            parts = line.rstrip("\n").split("|")
            if len(parts) <= est_col:
                continue
            geoid = parts[0]
            try:
                val = float(parts[est_col])
            except ValueError:
                continue
            if val < 0:           # ACS uses large negatives as suppression jam values
                continue
            out[geoid] = val
    return out


def build_rows(rent: dict[str, float]) -> list[dict]:
    """Per-county median gross rent, clamped to the sanity band."""
    def clamp(v: float | None) -> float | None:
        if v is None or v <= 0:
            return None
        return max(RENT_FLOOR, min(RENT_CEIL, v))

    nat_rent = clamp(rent.get(NATION_GEOID)) or 1300.0   # ~US median gross rent fallback
    rows = [{
        "geoid": "00000",
        "median_gross_rent": round(nat_rent),
        "resolved": "national",
    }]

    for geoid in sorted(rent):
        if not geoid.startswith(COUNTY_PREFIX):
            continue
        fips = geoid[len(COUNTY_PREFIX):]
        if len(fips) != 5:
            continue
        r = clamp(rent.get(geoid))
        rows.append({
            "geoid": fips,
            "median_gross_rent": round(r) if r is not None else round(nat_rent),
            "resolved": "county" if r is not None else "national",
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache-dir", default=None, help="download cache directory")
    ap.add_argument("--out", default=None, help="output crosswalk path override")
    args = ap.parse_args()

    cache = pathlib.Path(args.cache_dir
                         or (pathlib.Path(__file__).resolve().parents[1] / ".rent_cache"))
    print(f"ACS gross-rent build ({ACS_YEAR} 5-yr). Cache: {cache}", file=sys.stderr)

    rent_path = _download(RENT_URL, cache / f"acsdt5y{ACS_YEAR}-b25064.dat", min_size=1 << 20)

    print("Parsing ACS table …", file=sys.stderr)
    rent = _parse_table(rent_path)
    rows = build_rows(rent)

    out = pathlib.Path(args.out) if args.out else _DATA_DIR / "rent_county.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    counties = [r for r in rows if r["resolved"] == "county"]
    rents = sorted(r["median_gross_rent"] for r in counties)
    q = statistics.quantiles(rents, n=100)
    print(f"\nWrote {len(counties)} counties + 1 national row → {out}", file=sys.stderr)
    print(f"National fallback rent: ${rows[0]['median_gross_rent']}/mo", file=sys.stderr)
    print(f"County median gross rent: p10=${q[9]} p50=${q[49]} p90=${q[89]} "
          f"min=${rents[0]} max=${rents[-1]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
