#!/usr/bin/env python3
"""Build the bundled per-county effective property-tax-rate crosswalk.

Writes ``src/housing_label/data/property_tax_county.csv`` — for every U.S. county, the effective
property-tax rate (annual property tax as a fraction of home value). This is the
**revenue side** of Infrastructure Burden's fiscal ratio: it replaces the single
national effective rate previously applied to every non-Shelby location, so a
high-tax county (e.g. parts of the Northeast/Midwest) and a low-tax county (e.g.
Hawaii) get materially different revenue estimates — effective rates vary ~10x
nationally (Honolulu ~0.3% to Detroit ~3%).

Method
------
Effective rate = **median real estate taxes paid / median home value**, per
county — the standard ACS top-down proxy. Both come from the U.S. Census Bureau
**American Community Survey 5-year** estimates:

  - B25103_001  Median real estate taxes paid (owner-occupied units), dollars
  - B25077_001  Median home value, dollars

Rates are clamped to [0.1%, 5.0%] to guard against ACS noise in small counties; a
county missing either median falls back to the national-average row.

Source (keyless, free, public — bulk files, no API key)
-------------------------------------------------------
The modern ACS **table-based Summary File** publishes one pipe-delimited file per
table, keyless, so we fetch just the two tables we need (the Census Data API
requires a key; these bulk files do not). The first column is ``GEO_ID``; county
records use summary level 050 with GEO_ID ``0500000US<5-digit FIPS>``, and the
national row is ``0100000US``.

Caveats (documented in data/propertytax.py too)
-----------------------------------------------
ACS effective-rate proxies are county-level and noisy (a median-of-medians ratio,
within the ACS margin of error only ~half-to-two-thirds of the time) and reflect
ALL property taxes including the school-district share — whereas the cost side
(govfinance) excludes school spending — so the fiscal ratio is for relative
comparison, not an absolute accounting. Sub-county / per-jurisdiction millage
(state DOR tables) is a future refinement.

Run:  python scripts/build_property_tax.py
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
HEADERS = {"User-Agent": "housing-nutrition-label/0.1 (property-tax crosswalk build)"}

ACS_YEAR = 2024
_SF = (f"https://www2.census.gov/programs-surveys/acs/summary_file/{ACS_YEAR}"
       "/table-based-SF/data/5YRData")
TAXES_URL = f"{_SF}/acsdt5y{ACS_YEAR}-b25103.dat"   # median real estate taxes paid
VALUE_URL = f"{_SF}/acsdt5y{ACS_YEAR}-b25077.dat"   # median home value

COUNTY_PREFIX = "0500000US"   # ACS GEO_ID prefix for summary level 050 (county)
NATION_GEOID = "0100000US"

RATE_FLOOR, RATE_CEIL = 0.001, 0.05   # 0.1%–5.0% sanity clamp
OUT_COLUMNS = ["geoid", "median_taxes", "median_value", "effective_tax_rate", "resolved"]


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


def build_rows(taxes: dict[str, float], value: dict[str, float]) -> list[dict]:
    """Per-county effective rate = median taxes / median value, clamped."""
    def rate(t: float, v: float) -> float | None:
        if v <= 0 or t <= 0:
            return None
        return max(RATE_FLOOR, min(RATE_CEIL, t / v))

    # National fallback from the US-level medians (else the legacy 1.1% constant).
    nat_rate = rate(taxes.get(NATION_GEOID, 0.0), value.get(NATION_GEOID, 0.0)) or 0.011
    rows = [{
        "geoid": "00000", "median_taxes": round(taxes.get(NATION_GEOID, 0)),
        "median_value": round(value.get(NATION_GEOID, 0)),
        "effective_tax_rate": round(nat_rate, 5), "resolved": "national",
    }]

    for geoid in sorted(taxes):
        if not geoid.startswith(COUNTY_PREFIX):
            continue
        fips = geoid[len(COUNTY_PREFIX):]
        if len(fips) != 5:
            continue
        t = taxes.get(geoid)
        v = value.get(geoid)
        r = rate(t, v) if (t is not None and v is not None) else None
        rows.append({
            "geoid": fips,
            "median_taxes": round(t) if t is not None else "",
            "median_value": round(v) if v is not None else "",
            "effective_tax_rate": round(r, 5) if r is not None else round(nat_rate, 5),
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
                         or (pathlib.Path(__file__).resolve().parents[1] / ".proptax_cache"))
    print(f"ACS property-tax build ({ACS_YEAR} 5-yr). Cache: {cache}", file=sys.stderr)

    taxes_path = _download(TAXES_URL, cache / f"acsdt5y{ACS_YEAR}-b25103.dat", min_size=1 << 20)
    value_path = _download(VALUE_URL, cache / f"acsdt5y{ACS_YEAR}-b25077.dat", min_size=1 << 20)

    print("Parsing ACS tables …", file=sys.stderr)
    taxes = _parse_table(taxes_path)
    value = _parse_table(value_path)
    rows = build_rows(taxes, value)

    out = pathlib.Path(args.out) if args.out else _DATA_DIR / "property_tax_county.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    counties = [r for r in rows if r["resolved"] == "county"]
    rates = sorted(r["effective_tax_rate"] for r in counties)
    q = statistics.quantiles(rates, n=100)
    print(f"\nWrote {len(counties)} counties + 1 national row → {out}", file=sys.stderr)
    print(f"National fallback rate: {rows[0]['effective_tax_rate']:.4f}", file=sys.stderr)
    print(f"County effective rate: p10={q[9]:.4f} p50={q[49]:.4f} p90={q[89]:.4f} "
          f"min={rates[0]:.4f} max={rates[-1]:.4f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
