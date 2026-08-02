#!/usr/bin/env python3
"""Build the bundled per-county school-millage crosswalk.

Writes ``src/housing_label/data/school_millage_county.csv`` — for every county where a
state publishes school tax rates *and* gives owner-occupied homes school-specific relief,
the school operating and debt rates plus the owner exemption that applies to them.

Why this exists
---------------
``enrich/region_context.py`` builds the revenue side of Infrastructure Burden as

    municipal_rate = effective_tax_rate * (1 - school_tax_share)

and the two factors are measured over **different populations**: ``effective_tax_rate`` is
ACS B25103 / B25077, owner-occupied homes only, while ``school_tax_share`` comes from the
Census of Governments and covers all property. Where a state gives owner-occupied homes
school-*specific* relief, the ACS rate has already lost most of its school component and
netting the county-wide share removes it a second time — understating non-school revenue,
and so the score, for every parcel in the state.

This crosswalk replaces the estimate with a measurement. Given per-county school rates and
the statutory owner exemption, the owner's school rate can be computed at the county median
home value and *subtracted* rather than netted by share, so both terms are measured over the
same population. Counties absent from this file keep the multiplicative path unchanged.

Coverage
--------
**Texas only.** It is the largest affected state (9.2% of the US population) and the
Comptroller publishes rates per district *with a county column*, so districts resolve to
counties with no crosswalk. Michigan, Arizona, South Carolina, South Dakota and Vermont have
the same defect and are documented in ``research/infrastructure-burden-research.md``; each
needs a different state source, and MI/SC need an operating-versus-debt millage split rather
than a value exemption.

The Texas exemption applies to BOTH levies
------------------------------------------
Tex. Tax Code § 11.13(b) exempts $100,000 of a residence homestead's appraised value from
school district taxes. Whether that reaches the debt-service (I&S) levy as well as
maintenance-and-operations (M&O) is worth 10–13 percentage points of the correction, and
secondary sources say confidently that it does not.

**The source file says otherwise, and it is decisive.** It carries separate
``TAXABLE VALUE M&O`` and ``TAXABLE VALUE I&S`` columns:

  - the I&S base is **never smaller** than the M&O base (0 of 1,549 rows);
  - the two are **equal on 1,340 rows** (87%);
  - the I&S base is larger on 209 rows — 2.24% of statewide taxable value.

If the exemption applied only to M&O, the I&S base would exceed the M&O base in essentially
every district, since every district has homesteads. Instead they match in seven rows out of
eight. The 209 exceptions are the districts that may still tax exempted homestead value for
debt service — the hold-harmless for debt authorised before the exemption increases, which
TEA describes as the prior rule that SB 1453 (eff. 2026) narrows.

So the exemption reaches both levies, and the carve-out is measured rather than assumed:
``is_exempt_weight`` below is the share of a county's I&S levy sitting in districts whose two
bases match, and the consumer applies the exemption to that share of the I&S rate only.

Source (keyless, free, public)
------------------------------
Texas Comptroller, *ISD Rates and Levies* (annual, from the School District Property Value
Study). One XLSX, no API key, county already present.

Run:  python scripts/build_school_millage.py
      python scripts/build_school_millage.py --check    # verify the bundled file is current
"""

from __future__ import annotations

import argparse
import csv
import pathlib
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

import requests

_DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"
HEADERS = {"User-Agent": "housing-nutrition-label/0.1 (school-millage crosswalk build)"}

TX_YEAR = 2024
TX_URL = ("https://comptroller.texas.gov/taxes/property-tax/docs/"
          f"{TX_YEAR}-school-district-rates-levies.xlsx")
TX_COUNTY_COUNT = 254           # every Texas county must resolve, or the join is wrong

# Tex. Tax Code § 11.13(b). Rates in the source are dollars per $100 of value.
TX_HOMESTEAD_EXEMPTION = 100_000.0
RATE_PER_100 = 100.0

# A county rate outside this band means the parse drifted onto the wrong column, not that
# Texas moved. M&O is compressed toward ~0.75 statewide and I&S rarely clears 0.5.
RATE_FLOOR, RATE_CEIL = 0.0, 0.03

OUT_COLUMNS = ["geoid", "state", "school_mo_rate", "school_is_rate",
               "is_exempt_weight", "owner_exempt_value", "resolved"]

_XL = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _download(url: str, dest: pathlib.Path, *, min_size: int = 1024) -> pathlib.Path:
    """Stream a URL to ``dest`` with retry/back-off; reuse a valid cached file."""
    if dest.exists() and dest.stat().st_size >= min_size:
        print(f"  cached {dest.name} ({dest.stat().st_size/1e6:.1f} MB)", file=sys.stderr)
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


def read_xlsx_rows(path: pathlib.Path, header_first_cell: str) -> list[dict]:
    """Rows of the first worksheet as dicts, keyed by the header row.

    Hand-rolled rather than via openpyxl: the project has no spreadsheet dependency and
    this file is a flat single-sheet table. Rows above the header (report titles) are
    skipped by waiting for the cell that starts the header.
    """
    with zipfile.ZipFile(path) as z:
        shared = [(t.text or "") for t in
                  ET.fromstring(z.read("xl/sharedStrings.xml")).iter(_XL + "t")]
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    header: list[str] | None = None
    rows: list[dict] = []
    for r in sheet.iter(_XL + "row"):
        cells = []
        for c in r.iter(_XL + "c"):
            v = c.find(_XL + "v")
            val = v.text if v is not None else None
            if c.get("t") == "s" and val is not None:
                val = shared[int(val)]
            cells.append(val)
        if not cells:
            continue
        if header is None:
            if cells[0] == header_first_cell:
                header = [(h or "").strip() for h in cells]
            continue
        if len(cells) >= len(header):
            rows.append(dict(zip(header, cells)))
    if header is None:
        raise SystemExit(f"No header row starting {header_first_cell!r} in {path.name}")
    return rows


def _norm(name: str) -> str:
    """County name → comparison key, tolerant of 'County', case, spaces and punctuation.

    Texas has De Witt/DeWitt and La Salle/LaSalle spelled inconsistently across sources,
    so match on letters only rather than trying to normalise the spacing.
    """
    return re.sub(r"[^a-z]", "", re.sub(r"\s+county$", "", name.strip(), flags=re.I).lower())


def texas_fips_by_name() -> dict[str, str]:
    """Normalised Texas county name → 5-digit FIPS, from the bundled crosswalk."""
    out: dict[str, str] = {}
    with (_DATA_DIR / "govfinance_county.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("state") or "").strip() == "Texas":
                out[_norm(row.get("county_name") or "")] = (row.get("geoid") or "").zfill(5)
    return out


def build_texas_rows(records: list[dict]) -> list[dict]:
    """Levy-weighted M&O and I&S rates per Texas county.

    Weighted by each district-county row's own taxable value on the matching levy, so a
    district straddling two counties contributes to each in proportion to the value it
    actually taxes there. ``is_exempt_weight`` is the I&S-value-weighted share of the
    county sitting in districts whose M&O and I&S bases match — see the module docstring.
    """
    agg: dict[str, dict[str, float]] = {}
    for rec in records:
        try:
            v_mo = float(rec["TAXABLE VALUE M&O"])
            v_is = float(rec["TAXABLE VALUE I&S"])
            r_mo = float(rec["M&O RATE"])
            r_is = float(rec["I&S RATE"])
        except (KeyError, TypeError, ValueError):
            continue
        key = _norm(rec.get("COUNTY NAME") or "")
        if not key:
            continue
        a = agg.setdefault(key, {"mo": 0.0, "v_mo": 0.0, "is": 0.0, "v_is": 0.0, "ex": 0.0})
        a["mo"] += r_mo * v_mo
        a["v_mo"] += v_mo
        a["is"] += r_is * v_is
        a["v_is"] += v_is
        if abs(v_is - v_mo) <= 1.0:        # bases match → the exemption reached I&S too
            a["ex"] += v_is

    fips_by_name = texas_fips_by_name()
    rows: list[dict] = []
    unmatched: list[str] = []
    for key, a in sorted(agg.items()):
        fips = fips_by_name.get(key)
        if fips is None:
            unmatched.append(key)
            continue
        mo = (a["mo"] / a["v_mo"] / RATE_PER_100) if a["v_mo"] else 0.0
        isr = (a["is"] / a["v_is"] / RATE_PER_100) if a["v_is"] else 0.0
        for label, rate in (("M&O", mo), ("I&S", isr)):
            if not RATE_FLOOR <= rate <= RATE_CEIL:
                raise SystemExit(f"{key}: {label} rate {rate:.5f} outside "
                                 f"[{RATE_FLOOR}, {RATE_CEIL}] — check the column mapping")
        rows.append({
            "geoid": fips,
            "state": "TX",
            "school_mo_rate": round(mo, 6),
            "school_is_rate": round(isr, 6),
            "is_exempt_weight": round(a["ex"] / a["v_is"], 4) if a["v_is"] else 0.0,
            "owner_exempt_value": round(TX_HOMESTEAD_EXEMPTION),
            "resolved": "county",
        })
    if unmatched:
        raise SystemExit(f"{len(unmatched)} county names did not join: {sorted(unmatched)[:8]}")
    if len(rows) != TX_COUNTY_COUNT:
        raise SystemExit(f"Expected {TX_COUNTY_COUNT} Texas counties, built {len(rows)} — "
                         "the source file changed shape")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache-dir", default=None, help="download cache directory")
    ap.add_argument("--out", default=None, help="output crosswalk path override")
    ap.add_argument("--check", action="store_true",
                    help="rebuild and compare against the bundled file; do not write")
    args = ap.parse_args()

    cache = pathlib.Path(args.cache_dir
                         or (pathlib.Path(__file__).resolve().parents[1] / ".schoolmill_cache"))
    print(f"School-millage build (TX {TX_YEAR}). Cache: {cache}", file=sys.stderr)

    path = _download(TX_URL, cache / f"tx-isd-rates-levies-{TX_YEAR}.xlsx", min_size=1 << 16)
    records = read_xlsx_rows(path, "CAD ID")
    print(f"  {len(records)} district-county rows", file=sys.stderr)
    rows = build_texas_rows(records)

    out = pathlib.Path(args.out) if args.out else _DATA_DIR / "school_millage_county.csv"
    if args.check:
        if not out.exists():
            print(f"MISSING: {out}", file=sys.stderr)
            return 1
        with out.open(newline="") as f:
            existing = list(csv.DictReader(f))
        rebuilt = [{k: str(v) for k, v in r.items()} for r in rows]
        if existing != rebuilt:
            print(f"STALE: {out} differs from a fresh build "
                  f"({len(existing)} bundled vs {len(rebuilt)} rebuilt rows)", file=sys.stderr)
            return 1
        print(f"{out.name} is current ({len(existing)} counties).", file=sys.stderr)
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    mo = sorted(r["school_mo_rate"] for r in rows)
    isr = sorted(r["school_is_rate"] for r in rows)
    exw = sorted(r["is_exempt_weight"] for r in rows)
    mid = len(rows) // 2
    print(f"\nWrote {len(rows)} counties → {out}", file=sys.stderr)
    print(f"M&O rate: min={mo[0]:.4f} median={mo[mid]:.4f} max={mo[-1]:.4f}", file=sys.stderr)
    print(f"I&S rate: min={isr[0]:.4f} median={isr[mid]:.4f} max={isr[-1]:.4f}", file=sys.stderr)
    print(f"I&S exemption weight: min={exw[0]:.3f} median={exw[mid]:.3f} max={exw[-1]:.3f} "
          "(1.0 = the homestead exemption reaches the whole debt levy)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
