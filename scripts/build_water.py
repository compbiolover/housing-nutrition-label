#!/usr/bin/env python3
"""Build the bundled county drinking-water-quality table for the Water dimension.

Writes one artifact so the runtime (``data/water.py``) can look up a location's
community-drinking-water compliance with no network call:

  • ``src/housing_label/data/water_county.csv`` — one row per county:
        county_fips, pct_pop_hb_violation, cws_pop, n_cws

``pct_pop_hb_violation`` is the share of the county's **community-water-system-
served population** (the sum of ``POPULATION_SERVED_COUNT`` over the active CWSs
attributed to the county — not all county residents) that is on a CWS with a
**health-based** drinking-water violation whose non-compliance period began within
the trailing 5-year window (anchored to the newest violation year in the dataset,
so the build is reproducible regardless of when it is run). Higher = worse water.

Method
------
A community water system (``PWS_TYPE_CODE == "CWS"``, ``PWS_ACTIVITY_CODE == "A"``)
serves year-round residents, so it is the right unit for "is the tap water at this
home safe". For each county we sum the population served by all CWSs mapped to it,
and separately the population served by CWSs with a recent health-based violation;
the ratio is the exposure share. A CWS serving several counties is attributed in
full to each (both numerator and denominator use the same attribution, so the
per-county ratio stays honest).

Source
------
EPA **Safe Drinking Water Information System (SDWIS)** federal reporting, via the
ECHO bulk download ``SDWA_latest_downloads.zip``. Three member tables are read
(streamed straight from the zip — the 4 GB violations table is never extracted):

  • ``SDWA_PUB_WATER_SYSTEMS.csv``     — PWSID → population served, type, activity
  • ``SDWA_GEOGRAPHIC_AREAS.csv``      — PWSID → county (ANSI code) served
  • ``SDWA_VIOLATIONS_ENFORCEMENT.csv``— PWSID → health-based violation + dates

  Download: https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip
  About SDWIS: https://www.epa.gov/ground-water-and-drinking-water/safe-drinking-water-information-system-sdwis-federal-reporting

The ~420 MB zip is fetched at build time (dev-time only; the shipped artifact is
the small county CSV), or read from a local copy with ``--local-zip``.

Run:  python scripts/build_water.py --local-zip /path/to/SDWA_latest_downloads.zip
"""
from __future__ import annotations

import argparse
import csv
import io
import pathlib
import sys
import zipfile

import requests

_DATA = pathlib.Path(__file__).resolve().parent.parent / "src" / "housing_label" / "data"
_COUNTY_OUT = _DATA / "water_county.csv"

SDWA_URL = "https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip"
_HEADERS = {"User-Agent": "housing-nutrition-label/water-build"}
_TIMEOUT = 900

_PWS_MEMBER = "SDWA_PUB_WATER_SYSTEMS.csv"
_GEO_MEMBER = "SDWA_GEOGRAPHIC_AREAS.csv"
_VIOL_MEMBER = "SDWA_VIOLATIONS_ENFORCEMENT.csv"

_RECENT_YEARS = 5   # trailing window (inclusive) anchored to the newest data year

# State USPS abbreviation (PWSID prefix) → 2-digit state FIPS.
_STATE_ABBR_TO_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56", "PR": "72",
}


def _open_member(z: zipfile.ZipFile, name: str):
    """csv.DictReader over a zip member, streamed (member never extracted to disk)."""
    return csv.DictReader(io.TextIOWrapper(z.open(name), encoding="latin-1", newline=""))


def _year(mmddyyyy: str) -> int | None:
    """Year from an ``MM/DD/YYYY`` SDWIS date string, or None."""
    s = (mmddyyyy or "").strip()
    if len(s) >= 4 and s[-4:].isdigit():
        return int(s[-4:])
    return None


def _county_fips(pwsid: str, ansi: str) -> str | None:
    """5-digit county FIPS from a PWSID prefix (state) + county ANSI code."""
    st = _STATE_ABBR_TO_FIPS.get((pwsid or "")[:2].upper())
    a = (ansi or "").strip()
    if not st or not a.isdigit():
        return None
    return st + a.zfill(3)


def _load_systems(z: zipfile.ZipFile) -> dict[str, int]:
    """{PWSID → population served} for active community water systems only."""
    out: dict[str, int] = {}
    for row in _open_member(z, _PWS_MEMBER):
        if row.get("PWS_TYPE_CODE") != "CWS" or row.get("PWS_ACTIVITY_CODE") != "A":
            continue
        pwsid = (row.get("PWSID") or "").strip()
        try:
            pop = int(float(row.get("POPULATION_SERVED_COUNT") or 0))
        except ValueError:
            pop = 0
        if pwsid and pop > 0:
            out[pwsid] = pop
    return out


def _load_counties(z: zipfile.ZipFile, systems: set[str]) -> dict[str, set[str]]:
    """{PWSID → set of county FIPS served}, restricted to the systems of interest."""
    out: dict[str, set[str]] = {}
    for row in _open_member(z, _GEO_MEMBER):
        if row.get("AREA_TYPE_CODE") != "CN":
            continue
        pwsid = (row.get("PWSID") or "").strip()
        if pwsid not in systems:
            continue
        fips = _county_fips(pwsid, row.get("ANSI_ENTITY_CODE"))
        if fips:
            out.setdefault(pwsid, set()).add(fips)
    return out


def _load_violating_systems(z: zipfile.ZipFile, systems: set[str]) -> set[str]:
    """PWSIDs (from ``systems``) with a health-based violation whose non-compliance
    period began within the trailing ``_RECENT_YEARS`` window (anchored to the newest
    health-based violation year in the file). Streams the 4 GB violations table."""
    hb_year: dict[str, int] = {}   # PWSID → newest health-based non-compliance year
    max_year = 0
    for row in _open_member(z, _VIOL_MEMBER):
        if row.get("IS_HEALTH_BASED_IND") != "Y":
            continue
        pwsid = (row.get("PWSID") or "").strip()
        if pwsid not in systems:
            continue
        yr = _year(row.get("NON_COMPL_PER_BEGIN_DATE"))
        if yr is None:
            continue
        if yr > max_year:
            max_year = yr
        if yr > hb_year.get(pwsid, 0):
            hb_year[pwsid] = yr
    if not max_year:
        return set()
    cutoff = max_year - (_RECENT_YEARS - 1)
    print(f"      newest health-based violation year {max_year}; "
          f"recent window {cutoff}–{max_year}")
    return {p for p, y in hb_year.items() if y >= cutoff}


def _fetch_zip(local: str | None) -> bytes:
    if local:
        return pathlib.Path(local).read_bytes()
    print("Fetching SDWA_latest_downloads.zip (~420 MB) …")
    r = requests.get(SDWA_URL, headers=_HEADERS, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.content


def _weighted_quantiles(rows, qs=(0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)):
    """Population-weighted quantiles of pct_pop_hb_violation (weight = cws_pop)."""
    pairs = sorted((pct, w) for pct, w in rows if w > 0)
    total = sum(w for _, w in pairs)
    if not total:
        return []
    out = []
    for q in qs:
        target = total * q
        cum = 0.0
        val = pairs[-1][0]
        for pct, w in pairs:
            cum += w
            if cum >= target:
                val = pct
                break
        out.append(round(val, 2))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local-zip", help="local SDWA_latest_downloads.zip (skip fetch)")
    ap.add_argument("--county-out", default=str(_COUNTY_OUT))
    args = ap.parse_args()

    with zipfile.ZipFile(io.BytesIO(_fetch_zip(args.local_zip))) as z:
        print("Reading active community water systems …")
        systems = _load_systems(z)
        print(f"      {len(systems)} active CWSs")
        sysset = set(systems)
        print("Mapping systems → counties …")
        pws_counties = _load_counties(z, sysset)
        print(f"      {len(pws_counties)} systems mapped to a county")
        print("Scanning violations (streaming ~4 GB) …")
        violating = _load_violating_systems(z, sysset)
        print(f"      {len(violating)} CWSs with a recent health-based violation")

    # Aggregate to counties: total CWS pop and violating-CWS pop.
    total_pop: dict[str, int] = {}
    viol_pop: dict[str, int] = {}
    n_cws: dict[str, int] = {}
    for pwsid, counties in pws_counties.items():
        pop = systems[pwsid]
        bad = pwsid in violating
        for fips in counties:
            total_pop[fips] = total_pop.get(fips, 0) + pop
            n_cws[fips] = n_cws.get(fips, 0) + 1
            if bad:
                viol_pop[fips] = viol_pop.get(fips, 0) + pop

    rows = []
    for fips in sorted(total_pop):
        tp = total_pop[fips]
        pct = 100.0 * viol_pop.get(fips, 0) / tp if tp else 0.0
        rows.append((fips, round(pct, 2), tp, n_cws[fips]))

    with open(args.county_out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["county_fips", "pct_pop_hb_violation", "cws_pop", "n_cws"])
        for fips, pct, tp, n in rows:
            w.writerow([fips, f"{pct:.2f}", tp, n])
    print(f"Wrote {len(rows)} county rows → {args.county_out}")

    q = _weighted_quantiles([(pct, tp) for _, pct, tp, _ in rows])
    print(f"pop-weighted pct_pop_hb_violation quantiles "
          f"[10,25,50,75,90,95,99]: {q}")
    zero_pop = sum(tp for _, pct, tp, _ in rows if pct == 0.0)
    all_pop = sum(tp for _, _, tp, _ in rows)
    print(f"population in counties with 0% health-based exposure: "
          f"{100 * zero_pop / all_pop:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
