#!/usr/bin/env python3
"""Build the bundled per-county local-government finance calibration crosswalk.

Writes ``data/govfinance_county.csv`` — for every U.S. county, a set of
per-function **cost multipliers** that let ``enrich/infrastructure.py`` scale its
density-based cost-to-serve curves to local spending levels instead of reusing the
Memphis (Shelby County) calibration everywhere. A county that spends 2x the
Memphis per-capita rate on roads gets ``mult_roads = 2.0``, and so on.

Method (per-capita average costing — the FIA technique that generalizes across
thousands of jurisdictions; see research/infrastructure-burden-research.md)
-----------------------------------------------------------------------------
1. Sum **direct general expenditure** (current operations E + construction F +
   other capital G) by function for every LOCAL government unit, aggregated to
   the county the unit sits in:
       roads        = highways (44)
       water_sewer  = sewerage (80) + water utilities (91)
       fire         = fire protection (24)
       police       = police protection (62)
       sanitation   = solid waste management (81)
       parks        = parks & recreation (61)
   Local units only (county/municipal/township/special-district types 1-4);
   state (0) and school-district (5) governments are excluded.
2. Divide by county population → per-capita spend per function.
3. Normalize each county to **Shelby County, TN (47157)** — the pilot the cost
   curves are calibrated to — so ``mult = county_per_capita / shelby_per_capita``.
   Shelby itself is therefore 1.0 on every function (the pilot is unchanged), and
   every other county scales by its real spending ratio. Multipliers are clamped
   to [0.25, 4.0]; a county with zero recorded local spend on a function (e.g.
   water served by a utility counted elsewhere) falls back to the national-average
   multiplier for that function rather than zeroing the cost.
4. A national-average row (geoid ``00000``) is the fallback for unmapped counties.

Sources (both keyless, free, public — bulk files, no API key)
-------------------------------------------------------------
- U.S. Census Bureau, **2022 Census of Governments — Individual Unit File** (the
  most recent complete finance census, every ~90k local units; the Census of
  Governments is a full count only in years ending in 2 and 7 — annual surveys in
  other years are samples). Record ID encodes FIPS state (pos 1-2), government
  type (pos 3), and FIPS county (pos 4-6); item code (pos 13-15) is
  object+function; amount (pos 16-27) is in thousands of dollars.
- U.S. Census Bureau, **Population Estimates (PEP)** county totals
  (POPESTIMATE2022) for the per-capita denominator.

Run:  python scripts/build_govfinance.py            # full national crosswalk
      python scripts/build_govfinance.py --cache-dir .govfin_cache
"""

from __future__ import annotations

import argparse
import csv
import io
import pathlib
import sys
import time
import zipfile
from collections import defaultdict

import requests

_DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"
HEADERS = {"User-Agent": "housing-nutrition-label/0.1 (gov-finance crosswalk build)"}

COG_YEAR = 2022
COG_ZIP = ("https://www2.census.gov/programs-surveys/gov-finances/tables/"
           "2022/2022_Individual_Unit_File.zip")
# The finance-estimates member carries a revision date in its name and (2022+)
# sits inside a subdirectory, so locate it by pattern rather than hardcoding.
COG_FIN_PATTERN = "FinEstDAT"
PEP_CSV = ("https://www2.census.gov/programs-surveys/popest/datasets/"
           "2020-2024/counties/totals/co-est2024-alldata.csv")
POP_COL = "POPESTIMATE2022"   # match the finance vintage

# Census finance function codes → our cost components. Direct general expenditure
# for a function = the E (current ops) + F (construction) + G (other capital)
# objects of that 2-digit function code.
FUNC_TO_COMPONENT = {
    "44": "roads",        # Regular highways
    "80": "water_sewer",  # Sewerage
    "91": "water_sewer",  # Water utilities
    "24": "fire",         # Fire protection
    "62": "police",       # Police protection
    "81": "sanitation",   # Solid waste management
    "61": "parks",        # Parks & recreation
}
COMPONENTS = ["roads", "water_sewer", "fire", "police", "sanitation", "parks"]
EXPENDITURE_OBJECTS = set("EFG")
LOCAL_GOV_TYPES = set("1234")   # county, municipal, township, special district
SHELBY_FIPS = "47157"           # the pilot county the cost curves are calibrated to

MULT_FLOOR, MULT_CEIL = 0.25, 4.0
OUT_COLUMNS = (["geoid", "county_name", "state", "pop"]
               + [f"mult_{c}" for c in COMPONENTS] + ["resolved"])


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


def parse_county_spend(fin_text: io.TextIOBase) -> dict[str, dict[str, float]]:
    """Aggregate direct general expenditure by county FIPS × component ($)."""
    spend: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for line in fin_text:
        line = line.rstrip("\n")
        if len(line) < 31:
            continue
        gid = line[0:12]
        if gid[2] not in LOCAL_GOV_TYPES:        # local governments only
            continue
        item = line[12:15]
        component = FUNC_TO_COMPONENT.get(item[1:3])
        if component is None or item[0] not in EXPENDITURE_OBJECTS:
            continue
        try:
            amount = float(line[15:27])           # thousands of dollars
        except ValueError:
            continue
        county_fips = gid[0:2] + gid[3:6]         # FIPS state + FIPS county
        spend[county_fips][component] += amount * 1000.0
    return spend


def load_population(pep_text: io.TextIOBase) -> dict[str, dict]:
    """county FIPS → {pop, county_name, state} from the PEP county totals CSV."""
    out: dict[str, dict] = {}
    for row in csv.DictReader(pep_text):
        if row.get("SUMLEV") != "050":            # 050 = county; 040 = state
            continue
        fips = f"{row['STATE']}{row['COUNTY']}"
        try:
            pop = int(row[POP_COL])
        except (KeyError, ValueError):
            continue
        out[fips] = {"pop": pop, "county_name": row.get("CTYNAME", ""),
                     "state": row.get("STNAME", "")}
    return out


def build_rows(spend: dict[str, dict[str, float]],
               pop: dict[str, dict]) -> list[dict]:
    """Compute per-capita spend, normalize to Shelby, return crosswalk rows."""
    # Per-capita spend per county per component (only counties with population).
    pc: dict[str, dict[str, float]] = {}
    for fips, comps in spend.items():
        p = pop.get(fips, {}).get("pop", 0)
        if p > 0:
            pc[fips] = {c: comps.get(c, 0.0) / p for c in COMPONENTS}

    if SHELBY_FIPS not in pc:
        raise SystemExit(f"Shelby County {SHELBY_FIPS} missing from finance data — "
                         "cannot normalize.")
    shelby_pc = pc[SHELBY_FIPS]

    # National-average per-capita (population-weighted) → fallback multipliers.
    nat_spend = {c: sum(spend[f].get(c, 0.0) for f in pc) for c in COMPONENTS}
    nat_pop = sum(pop[f]["pop"] for f in pc)
    nat_pc = {c: nat_spend[c] / nat_pop for c in COMPONENTS}
    nat_mult = {c: _clamp(nat_pc[c] / shelby_pc[c]) if shelby_pc[c] > 0 else 1.0
                for c in COMPONENTS}

    def mults_for(fips: str) -> dict[str, float]:
        out = {}
        for c in COMPONENTS:
            denom = shelby_pc[c]
            val = pc[fips].get(c, 0.0)
            # Zero local spend on a function → use the national multiplier rather
            # than zeroing the modeled cost-to-serve.
            out[c] = nat_mult[c] if val <= 0 or denom <= 0 else _clamp(val / denom)
        return out

    rows = [{
        "geoid": "00000", "county_name": "US national average", "state": "",
        "pop": nat_pop, **{f"mult_{c}": round(nat_mult[c], 4) for c in COMPONENTS},
        "resolved": "national",
    }]
    for fips in sorted(pc):
        meta = pop.get(fips, {})
        m = mults_for(fips)
        rows.append({
            "geoid": fips, "county_name": meta.get("county_name", ""),
            "state": meta.get("state", ""), "pop": meta.get("pop", ""),
            **{f"mult_{c}": round(m[c], 4) for c in COMPONENTS},
            "resolved": "county",
        })
    return rows


def _clamp(x: float) -> float:
    return max(MULT_FLOOR, min(MULT_CEIL, x))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache-dir", default=None, help="download cache directory")
    ap.add_argument("--out", default=None, help="output crosswalk path override")
    args = ap.parse_args()

    cache = pathlib.Path(args.cache_dir
                         or (pathlib.Path(__file__).resolve().parents[1] / ".govfin_cache"))
    print(f"Gov-finance build. Cache: {cache}", file=sys.stderr)

    zip_path = _download(COG_ZIP, cache / f"{COG_YEAR}_Individual_Unit_File.zip", min_size=1 << 20)
    pep_path = _download(PEP_CSV, cache / "co-est-alldata.csv", min_size=1 << 20)

    print("Parsing finance records …", file=sys.stderr)
    with zipfile.ZipFile(zip_path) as zf:
        member = next((n for n in zf.namelist()
                       if COG_FIN_PATTERN in n and n.endswith("_pu.txt")), None)
        if member is None:
            raise SystemExit(f"No {COG_FIN_PATTERN} member found in {zip_path.name}")
        with zf.open(member) as raw:
            spend = parse_county_spend(io.TextIOWrapper(raw, encoding="latin-1"))
    print(f"  {len(spend)} counties with local-government spend", file=sys.stderr)

    with pep_path.open(encoding="latin-1") as f:
        pop = load_population(f)
    print(f"  {len(pop)} counties with population", file=sys.stderr)

    rows = build_rows(spend, pop)
    out = pathlib.Path(args.out) if args.out else _DATA_DIR / "govfinance_county.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    # Quick sanity report.
    nat = rows[0]
    print(f"\nWrote {len(rows)-1} counties + 1 national row → {out}", file=sys.stderr)
    print(f"National-vs-Shelby multipliers: "
          + "  ".join(f"{c}={nat['mult_'+c]}" for c in COMPONENTS), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
