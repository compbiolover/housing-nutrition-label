#!/usr/bin/env python3
"""Build the NATIONAL health reference crosswalks for the Health Impact dimension.

Why
---
Until now ``enrich/health.py`` computed a tract's ``health_index`` as a percentile
rank **within its own county** (``rank(pct=True)`` over the county's tracts), and
the live label ranked within the address's own county too. That silently
re-baselines per county — a median-health tract scores ~50 in *every* county — so
the score is **not comparable across locations**. This is the "can't do percentile
grades without national data" problem, baked into the score itself.

This script fixes it the way the rest of the repo already anchors scores
nationally (cf. ``scripts/calibrate_infra_breakpoints.py`` and the national
quantiles in ``data/climate_projections.py``): it computes each tract's health
score against the **full national distribution of US census tracts**, weighted by
adult population (the EJScreen population-weighting convention — the percentile
answers "what share of the US adult population lives in a tract with a lower
disease burden"). The result is a genuine national percentile, so a "70" means the
same thing in Memphis and in Denver.

Method (reproducible, keyless — CDC PLACES public API only)
----------------------------------------------------------
  1. Download CDC PLACES census-tract crude-prevalence for the 7 modelled measures
     for **every US tract** (keyless Socrata API, paginated).
  2. For each measure, compute every tract's **population-weighted national
     percentile** (weight = ``totalpop18plus``). All 7 measures are "higher =
     worse", so the per-measure score is ``(1 - percentile) * 100`` (100 = lowest
     disease burden nationally).
  3. ``health_index`` = mean of the available per-measure scores (needs >= MIN_MEASURES).
  4. Roll tracts up to a population-weighted county mean, plus a national row.

Outputs (bundled, committed — like nri_wildfire_tracts.csv.gz)
-------------------------------------------------------------
  src/housing_label/data/health_tracts.csv.gz   geoid(11) + 7 measure %s + health_index + pop
  src/housing_label/data/health_county.csv       geoid(5)  + 7 measure %s + health_index + pop
                                                 (plus a national row, geoid 00000)

Run:  python scripts/build_health_ref.py
      python scripts/build_health_ref.py --limit-states 2   # quick smoke build
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import time

import numpy as np
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger("build_health_ref")

_DATA = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"
PLACES_URL = "https://chronicdata.cdc.gov/resource/cwsq-ngmh.json"

# Same measure -> column mapping the enrichment uses, so the crosswalk columns
# line up with what the pipeline/label already expect.
MEASURE_MAP = {
    "LPA":      "physical_inactivity_pct",
    "OBESITY":  "obesity_pct",
    "DIABETES": "diabetes_pct",
    "MHLTH":    "mental_distress_pct",
    "CASTHMA":  "asthma_pct",
    "BPHIGH":   "high_bp_pct",
    "CHD":      "chd_pct",
}
MEASURE_COLS = list(MEASURE_MAP.values())
MIN_MEASURES = 4          # a tract needs >= this many measures to get an index

PAGE = 40000              # Socrata page size (offset paging)
TIMEOUT = 60
MAX_RETRIES = 4
BACKOFF = 2
NATIONAL_GEOID = "00000"


def _get(params: dict) -> list:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(PLACES_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("PLACES attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
            if attempt == MAX_RETRIES:
                raise
            time.sleep(BACKOFF ** attempt)
    return []


def download_places() -> pd.DataFrame:
    """Return a national tract x measure frame (index = 11-digit GEOID) plus pop.

    Pages the CDC PLACES tract dataset for the 7 measures (crude prevalence),
    keeping the most recent year per tract+measure, and pivots to one row per
    tract with a ``totalpop18plus`` column for population weighting.
    """
    measures = "','".join(MEASURE_MAP)
    where = f"datavaluetypeid='CrdPrv' AND measureid IN('{measures}')"
    rows: list[dict] = []
    offset = 0
    while True:
        page = _get({
            "$select": "locationid,measureid,data_value,totalpop18plus,year",
            "$where": where,
            "$order": ":id",          # stable pagination
            "$limit": PAGE,
            "$offset": offset,
        })
        if not page:
            break
        rows.extend(page)
        log.info("  fetched %d rows (offset %d)", len(rows), offset)
        if len(page) < PAGE:
            break
        offset += PAGE

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("CDC PLACES returned no rows — check the dataset id (cwsq-ngmh).")

    df["data_value"] = pd.to_numeric(df["data_value"], errors="coerce")
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["totalpop18plus"] = pd.to_numeric(df["totalpop18plus"], errors="coerce")
    df["locationid"] = df["locationid"].astype(str).str.zfill(11)

    # Most-recent year per tract+measure.
    df = (df.sort_values("year", ascending=False)
            .drop_duplicates(subset=["locationid", "measureid"], keep="first"))

    pop = df.groupby("locationid")["totalpop18plus"].max()   # same across measures
    wide = (df.pivot_table(index="locationid", columns="measureid",
                           values="data_value", aggfunc="first")
              .rename(columns=MEASURE_MAP))
    wide = wide.reindex(columns=MEASURE_COLS)
    wide["totalpop18plus"] = pop
    log.info("Pivoted to %d tracts x %d measures.", len(wide), len(MEASURE_COLS))
    return wide


def weighted_percentile_score(values: pd.Series, weights: pd.Series) -> pd.Series:
    """Population-weighted national percentile, inverted to a 0-100 score.

    ``score = (1 - pct) * 100`` where ``pct`` is the population-weighted fraction
    of tracts with a *lower* value. Tied values (common with rounded prevalences)
    share a single **group** mid-rank percentile — ``(weight below the group +
    half the group's weight) / total`` — so the result does not depend on the
    arbitrary order of ties. Higher value (worse disease burden) -> lower score.
    NaN inputs stay NaN.
    """
    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce").fillna(0.0).clip(lower=0.0)
    mask = v.notna() & (w > 0)
    out = pd.Series(np.nan, index=values.index)
    if not mask.any():
        return out
    vv, ww = v[mask], w[mask]
    total = float(ww.sum())
    gw = ww.groupby(vv).sum().sort_index()   # summed weight per distinct value
    below = gw.cumsum() - gw                  # weight strictly below each group
    mid = (below + 0.5 * gw) / total          # one mid-rank percentile per group
    out.loc[mask] = (1.0 - vv.map(mid)) * 100.0
    return out.round(1)


def build_tract_scores(wide: pd.DataFrame) -> pd.DataFrame:
    """Score every tract nationally and add the composite ``health_index``."""
    scores = pd.DataFrame(index=wide.index)
    for col in MEASURE_COLS:
        scores[col] = weighted_percentile_score(wide[col], wide["totalpop18plus"])
    n_avail = scores.notna().sum(axis=1)
    health_index = scores.mean(axis=1, skipna=True).round(1)
    health_index[n_avail < MIN_MEASURES] = np.nan

    out = wide[MEASURE_COLS].copy()
    out["health_index"] = health_index
    out["totalpop18plus"] = wide["totalpop18plus"].round(0)
    return out


def roll_up_county(tracts: pd.DataFrame) -> pd.DataFrame:
    """Population-weighted county means (measures + health_index) + a national row."""
    df = tracts.reset_index()
    df = df.rename(columns={df.columns[0]: "geoid"})
    df["geoid"] = df["geoid"].astype(str).str.zfill(11)
    df["county"] = df["geoid"].str[:5]

    def _wmean(frame: pd.DataFrame, cols: list[str]) -> dict:
        ww = frame["totalpop18plus"].fillna(0.0).clip(lower=0.0)
        res = {}
        for c in cols:
            v = frame[c]
            m = v.notna() & (ww > 0)
            res[c] = round(float((v[m] * ww[m]).sum() / ww[m].sum()), 1) if m.any() else ""
        res["totalpop18plus"] = round(float(ww.sum()), 0)
        return res

    cols = MEASURE_COLS + ["health_index"]
    county_rows = []
    for fips, g in df.groupby("county"):
        row = {"geoid": fips}
        row.update(_wmean(g, cols))
        county_rows.append(row)
    national = {"geoid": NATIONAL_GEOID}
    national.update(_wmean(df, cols))
    county_rows.append(national)
    return pd.DataFrame(county_rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit-states", type=int, default=None,
                    help="(smoke test) keep only the first N state FIPS after download.")
    args = ap.parse_args()

    wide = download_places()
    if args.limit_states:
        keep = sorted({i[:2] for i in wide.index})[: args.limit_states]
        wide = wide[wide.index.str[:2].isin(keep)]
        log.info("Smoke build: kept %d tracts in states %s", len(wide), keep)

    tracts = build_tract_scores(wide)
    scored = int(tracts["health_index"].notna().sum())
    log.info("Scored %d/%d tracts nationally (health_index).", scored, len(tracts))

    county = roll_up_county(tracts)

    tract_out = _DATA / "health_tracts.csv.gz"
    county_out = _DATA / "health_county.csv"
    out_tracts = tracts.reset_index()
    out_tracts = out_tracts.rename(columns={out_tracts.columns[0]: "geoid"})
    out_tracts.to_csv(tract_out, index=False, compression="gzip")
    county.to_csv(county_out, index=False)

    hi = tracts["health_index"].dropna()
    log.info("Wrote %s (%d tracts) and %s (%d counties).",
             tract_out.name, len(tracts), county_out.name, len(county) - 1)
    log.info("health_index national spread: min=%.1f p25=%.1f median=%.1f p75=%.1f max=%.1f",
             hi.min(), hi.quantile(.25), hi.median(), hi.quantile(.75), hi.max())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
