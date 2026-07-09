#!/usr/bin/env python3
"""Build the NATIONAL walkability crosswalks from the EPA National Walkability Index.

Why
---
The Walkability dimension used the **Walk Score API**, which (a) is capped at
~5,000 calls/day and (b) whose Terms of Use PROHIBIT caching/storing returned
scores — a national, stored property-scoring product cannot use it. The EPA
**National Walkability Index** (NWI) is the open, public-domain alternative: it
covers every US census block group, is freely redistributable and storable, needs
no key or quota, and — because walkability is a property of *location, not
parcel* — joins to any point by geography with no per-parcel API calls.

Method (reproducible, keyless — EPA ArcGIS REST service)
-------------------------------------------------------
  1. Page the EPA NWI feature service for every block group: its 1-20 walkability
     index (``NatWalkInd``), its 2020 block-group GEOID (``GEOID20``), and its
     household count (``HH``) for weighting.
  2. Scale the 1-20 index to 0-100: ``(NatWalkInd - 1) / 19 * 100`` (1 -> 0, most
     walkable 20 -> 100). Higher = more walkable = better, as the label expects.
  3. Aggregate block groups to their **2020 census tract** (household-weighted
     mean), and roll tracts up to a household-weighted county mean + a national row.

The NWI itself is EPA's official national index (built from national percentile
ranks of intersection density, transit proximity, and land-use mix), so a scaled
value already expresses national walkability standing — no re-ranking needed.

Outputs (bundled, committed)
----------------------------
  src/housing_label/data/walkability_tracts.csv.gz  geoid(11) + walkability_score + nat_walk_ind + households
  src/housing_label/data/walkability_county.csv      geoid(5)  + walkability_score + nat_walk_ind + households
                                                     (plus a national row, geoid 00000)

Run:  python scripts/build_walkability.py
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys
import time

import numpy as np
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger("build_walkability")

_DATA = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"
NWI_URL = ("https://geodata.epa.gov/arcgis/rest/services/OA/WalkabilityIndex"
           "/MapServer/0/query")
HEADERS = {"User-Agent": "housing-nutrition-label/0.1 (walkability crosswalk build)"}

PAGE = 1000          # EPA NWI service caps a single query at 1000 records
TIMEOUT = 120
MAX_RETRIES = 4
NATIONAL_OUT = "00000"


def _page(offset: int) -> list[dict]:
    params = {
        "where": "NatWalkInd IS NOT NULL",
        "outFields": "GEOID20,NatWalkInd,HH",
        "orderByFields": "GEOID20",
        "returnGeometry": "false",
        "resultOffset": offset,
        "resultRecordCount": PAGE,
        "f": "json",
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(NWI_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            return [f["attributes"] for f in data.get("features", [])]
        except Exception as exc:  # noqa: BLE001
            log.warning("NWI page @%d attempt %d/%d failed: %s", offset, attempt, MAX_RETRIES, exc)
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2 ** attempt)
    return []


def download_nwi() -> pd.DataFrame:
    """All block groups: GEOID20, NatWalkInd (1-20), HH (household weight)."""
    rows: list[dict] = []
    offset = 0
    while True:
        page = _page(offset)
        if not page:
            break
        rows.extend(page)
        log.info("  fetched %d block groups (offset %d)", len(rows), offset)
        if len(page) < PAGE:
            break
        offset += PAGE
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("EPA NWI returned no rows — check the service URL.")
    df["GEOID20"] = df["GEOID20"].astype(str).str.zfill(12)
    df["NatWalkInd"] = pd.to_numeric(df["NatWalkInd"], errors="coerce")
    df["HH"] = pd.to_numeric(df["HH"], errors="coerce").fillna(0.0).clip(lower=0.0)
    df = df[df["NatWalkInd"].notna()]
    log.info("Downloaded %d block groups with a walkability index.", len(df))
    return df


def _scale(nwi: float) -> float:
    """EPA NWI 1-20 -> 0-100 (1 -> 0, 20 -> 100), clamped."""
    return float(np.clip((nwi - 1.0) / 19.0 * 100.0, 0.0, 100.0))


def _wmean(values: pd.Series, weights: pd.Series) -> float:
    """Household-weighted mean; falls back to a simple mean if all weights are 0."""
    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce").fillna(0.0).clip(lower=0.0)
    m = v.notna()
    if not m.any():
        return np.nan
    if (w[m] > 0).any():
        return float((v[m] * w[m]).sum() / w[m].sum())
    return float(v[m].mean())


def aggregate(bg: pd.DataFrame, level: int) -> pd.DataFrame:
    """Aggregate block groups to a geography (tract=11, county=5) — HH-weighted."""
    key = bg["GEOID20"].str[:level]
    out = []
    for geoid, g in bg.groupby(key):
        nwi = _wmean(g["NatWalkInd"], g["HH"])
        out.append({
            "geoid": geoid,
            "walkability_score": round(_scale(nwi), 1) if pd.notna(nwi) else "",
            "nat_walk_ind": round(nwi, 2) if pd.notna(nwi) else "",
            "households": round(float(g["HH"].sum()), 0),
        })
    return pd.DataFrame(out)


def national_row(bg: pd.DataFrame) -> dict:
    nwi = _wmean(bg["NatWalkInd"], bg["HH"])
    return {
        "geoid": NATIONAL_OUT,
        "walkability_score": round(_scale(nwi), 1),
        "nat_walk_ind": round(nwi, 2),
        "households": round(float(bg["HH"].sum()), 0),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit-states", type=int, default=None,
                    help="(smoke test) keep only the first N state FIPS after download.")
    args = ap.parse_args()

    bg = download_nwi()
    if args.limit_states:
        keep = sorted({g[:2] for g in bg["GEOID20"]})[: args.limit_states]
        bg = bg[bg["GEOID20"].str[:2].isin(keep)]
        log.info("Smoke build: kept %d block groups in states %s", len(bg), keep)

    tracts = aggregate(bg, 11)
    county = aggregate(bg, 5)
    county = pd.concat([county, pd.DataFrame([national_row(bg)])], ignore_index=True)

    tract_out = _DATA / "walkability_tracts.csv.gz"
    county_out = _DATA / "walkability_county.csv"
    tracts.to_csv(tract_out, index=False, compression="gzip")
    county.to_csv(county_out, index=False)

    ws = pd.to_numeric(tracts["walkability_score"], errors="coerce").dropna()
    log.info("Wrote %s (%d tracts) and %s (%d counties + national).",
             tract_out.name, len(tracts), county_out.name, len(county) - 1)
    log.info("walkability_score national spread: min=%.1f p25=%.1f median=%.1f p75=%.1f max=%.1f",
             ws.min(), ws.quantile(.25), ws.median(), ws.quantile(.75), ws.max())
    return 0


if __name__ == "__main__":
    sys.exit(main())
