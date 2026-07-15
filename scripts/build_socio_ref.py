#!/usr/bin/env python3
"""Build the NATIONAL socioeconomic reference crosswalks for the Socioeconomic dim.

Why
---
Like Health, the old Socioeconomic score ranked each tract's poverty / income /
housing-cost-burden **within its own county** (``rank(pct=True)``), so a median
tract scored ~50 in every county and scores were not comparable across locations.
This builds a genuine **national** reference so a "70" means the same thing
everywhere, matching how Infrastructure and Climate are already anchored.

Method (reproducible, KEYLESS — ACS 5-year table-based Summary File)
-------------------------------------------------------------------
The modern ACS **table-based Summary File** publishes one pipe-delimited file per
table, keyless (the Census Data *API* now needs a key; these bulk files do not) —
the same source ``scripts/build_property_tax.py`` uses. Each file carries *every*
geography, so we filter the **tract** rows (GEO_ID ``1400000US<11-digit>``) plus
the county (``0500000US``) and national (``0100000US``) rows.

  1. Derive five headline metrics per tract. The first three use the same formulas
     as enrich/socioeconomic.py; the last two are standard ACS ratios added here:
     - poverty_rate_pct              = B17001_E002 / B17001_E001 * 100
     - median_household_income       = B19013_E001
     - housing_cost_burden_pct       = (owner 30%+ + renter 30%+) / occupied-with-ratio (B25106)
     - education_bachelors_plus_pct  = (B15003_E022..E025) / B15003_E001 * 100  (pop 25+)
     - unemployment_rate_pct         = B23025_E005 / B23025_E003 * 100          (civilian LF)
  2. Compute each tract's **household-weighted national percentile** (weight =
     occupied housing units, B25106_E001). Orient so 100 = least stress:
     poverty, burden & unemployment inverted; income & education direct.
  3. socioeconomic_index = mean of the available metric scores (needs >= MIN_METRICS).
  4. Roll tracts up to a household-weighted county mean, plus a national row.

Outputs (bundled, committed)
----------------------------
  src/housing_label/data/socio_tracts.csv.gz  geoid(11) + 5 metrics + socioeconomic_index + households
  src/housing_label/data/socio_county.csv      geoid(5)  + 5 metrics + socioeconomic_index + households
                                              (plus a national row, geoid 00000)

Run:  python scripts/build_socio_ref.py
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
log = logging.getLogger("build_socio_ref")

_DATA = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"
HEADERS = {"User-Agent": "housing-nutrition-label/0.1 (socio crosswalk build)"}

ACS_YEAR = 2023
_SF = (f"https://www2.census.gov/programs-surveys/acs/summary_file/{ACS_YEAR}"
       "/table-based-SF/data/5YRData")

TRACT_PREFIX = "1400000US"
COUNTY_PREFIX = "0500000US"
NATION_GEOID = "0100000US"
NATIONAL_OUT = "00000"

MIN_METRICS = 3           # a tract needs >= this many of the 5 metrics for an index
METRIC_COLS = ["poverty_rate_pct", "median_household_income", "housing_cost_burden_pct",
               "education_bachelors_plus_pct", "unemployment_rate_pct"]

# ACS variables we need, by table. Column names in the Summary File are TABLE_E### .
NEEDED = {
    "b17001": ["B17001_E001", "B17001_E002"],
    "b19013": ["B19013_E001"],
    "b25106": ["B25106_E001", "B25106_E023", "B25106_E045", "B25106_E046",
               "B25106_E006", "B25106_E010", "B25106_E014", "B25106_E018", "B25106_E022",
               "B25106_E028", "B25106_E032", "B25106_E036", "B25106_E040", "B25106_E044"],
    # Educational attainment (pop 25+): total + bachelor's / master's / professional / doctorate.
    "b15003": ["B15003_E001", "B15003_E022", "B15003_E023", "B15003_E024", "B15003_E025"],
    # Employment status (pop 16+): civilian labor force + civilian unemployed.
    "b23025": ["B23025_E003", "B23025_E005"],
}
OWNER_30 = ["B25106_E006", "B25106_E010", "B25106_E014", "B25106_E018", "B25106_E022"]
RENTER_30 = ["B25106_E028", "B25106_E032", "B25106_E036", "B25106_E040", "B25106_E044"]
BACHELORS_PLUS = ["B15003_E022", "B15003_E023", "B15003_E024", "B15003_E025"]

TIMEOUT = 240
MAX_RETRIES = 4


def _download(url: str, dest: pathlib.Path, min_size: int = 1 << 20) -> pathlib.Path:
    if dest.exists() and dest.stat().st_size >= min_size:
        log.info("  cached %s (%.0f MB)", dest.name, dest.stat().st_size / 1e6)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(MAX_RETRIES):
        try:
            with requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                tmp.replace(dest)
            log.info("  downloaded %s (%.0f MB)", dest.name, dest.stat().st_size / 1e6)
            return dest
        except requests.RequestException as exc:
            log.warning("  download attempt %d failed: %s", attempt + 1, exc)
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(2 ** attempt)
    return dest


def _parse_table(path: pathlib.Path, cols: list[str]) -> dict[str, dict]:
    """geoid(GEO_ID) -> {col: float} for the wanted cols, tract/county/national rows only.

    ACS suppression jam values (large negatives) become None.
    """
    keep_prefix = (TRACT_PREFIX, COUNTY_PREFIX)
    out: dict[str, dict] = {}
    with path.open(encoding="latin-1") as f:
        header = f.readline().rstrip("\n").split("|")
        idx = {c: header.index(c) for c in cols if c in header}
        missing = [c for c in cols if c not in idx]
        if missing:
            raise SystemExit(f"{path.name}: missing columns {missing}")
        for line in f:
            parts = line.rstrip("\n").split("|")
            geoid = parts[0]
            if not (geoid == NATION_GEOID or geoid.startswith(keep_prefix)):
                continue
            row = {}
            for c, i in idx.items():
                try:
                    v = float(parts[i])
                except (ValueError, IndexError):
                    v = None
                row[c] = v if (v is not None and v > -1e8) else None
            out[geoid] = row
    return out


def _norm_geoid(geo_id: str) -> str:
    if geo_id == NATION_GEOID:
        return NATIONAL_OUT
    if geo_id.startswith(TRACT_PREFIX):
        return geo_id[len(TRACT_PREFIX):]
    if geo_id.startswith(COUNTY_PREFIX):
        return geo_id[len(COUNTY_PREFIX):]
    return geo_id


def derive_metrics(b17001: dict, b19013: dict, b25106: dict,
                   b15003: dict, b23025: dict) -> pd.DataFrame:
    """One row per geography with the 5 headline metrics + household weight."""
    # Sort the union so the derived rows — and thus the written CSV — are in a
    # deterministic order, independent of dict/hash iteration; keeps rebuild diffs clean.
    geoids = sorted(set(b17001) | set(b19013) | set(b25106) | set(b15003) | set(b23025))
    rows = []
    for g in geoids:
        p = b17001.get(g, {})
        i = b19013.get(g, {})
        h = b25106.get(g, {})
        e = b15003.get(g, {})
        j = b23025.get(g, {})

        pov_total, pov_below = p.get("B17001_E001"), p.get("B17001_E002")
        poverty = (pov_below / pov_total * 100.0) if (pov_total and pov_total > 0
                                                      and pov_below is not None) else None

        income = i.get("B19013_E001")

        total = h.get("B25106_E001")
        owner_30 = sum(h.get(c) or 0.0 for c in OWNER_30)
        renter_30 = sum(h.get(c) or 0.0 for c in RENTER_30)
        notcomp = (h.get("B25106_E023") or 0.0) + (h.get("B25106_E045") or 0.0) \
            + (h.get("B25106_E046") or 0.0)
        den = (total - notcomp) if total is not None else None
        burden = ((owner_30 + renter_30) / den * 100.0) if (den and den > 0) else None

        # Educational attainment: share of the 25+ population with a bachelor's or higher.
        # Require every numerator cell to be present — treating a suppressed
        # bachelor's/master's/etc. cell as 0 would understate the share and bias the
        # percentile, so a missing cell leaves the metric unscored instead.
        edu_total = e.get("B15003_E001")
        bp_cells = [e.get(c) for c in BACHELORS_PLUS]
        education = ((sum(bp_cells) / edu_total * 100.0)
                     if (edu_total and edu_total > 0
                         and all(c is not None for c in bp_cells)) else None)

        # Unemployment: civilian unemployed / civilian labor force.
        labor_force, unemployed = j.get("B23025_E003"), j.get("B23025_E005")
        unemployment = ((unemployed / labor_force * 100.0)
                        if (labor_force and labor_force > 0 and unemployed is not None)
                        else None)

        rows.append({
            "geoid": _norm_geoid(g),
            "poverty_rate_pct": round(poverty, 1) if poverty is not None else np.nan,
            "median_household_income": round(income) if income is not None else np.nan,
            "housing_cost_burden_pct": round(burden, 1) if burden is not None else np.nan,
            "education_bachelors_plus_pct": round(education, 1) if education is not None else np.nan,
            "unemployment_rate_pct": round(unemployment, 1) if unemployment is not None else np.nan,
            "households": total if total is not None else np.nan,
        })
    df = pd.DataFrame(rows).set_index("geoid")
    return df


def _wpct(values: pd.Series, weights: pd.Series) -> pd.Series:
    """Household-weighted percentile in [0,1] (fraction below). NaN kept.

    Tied values share one **group** mid-rank percentile — ``(weight below the
    group + half the group's weight) / total`` — so the percentile does not
    depend on the arbitrary order of ties.
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
    out.loc[mask] = vv.map(mid)
    return out


def score_tracts(tracts: pd.DataFrame) -> pd.DataFrame:
    """National household-weighted score per tract (100 = least economic stress)."""
    w = tracts["households"]
    pct_pov = _wpct(tracts["poverty_rate_pct"], w)
    pct_inc = _wpct(tracts["median_household_income"], w)
    pct_bur = _wpct(tracts["housing_cost_burden_pct"], w)
    pct_edu = _wpct(tracts["education_bachelors_plus_pct"], w)
    pct_unemp = _wpct(tracts["unemployment_rate_pct"], w)

    score = pd.DataFrame(index=tracts.index)
    score["poverty"] = ((1.0 - pct_pov) * 100.0)      # lower poverty       -> higher
    score["income"] = (pct_inc * 100.0)               # higher income       -> higher
    score["burden"] = ((1.0 - pct_bur) * 100.0)       # lower burden        -> higher
    score["education"] = (pct_edu * 100.0)            # more bachelor's+    -> higher
    score["jobs"] = ((1.0 - pct_unemp) * 100.0)       # lower unemployment  -> higher

    n_avail = score.notna().sum(axis=1)
    idx = score.mean(axis=1, skipna=True).round(1)
    idx[n_avail < MIN_METRICS] = np.nan

    out = tracts[METRIC_COLS].copy()
    out["socioeconomic_index"] = idx
    out["households"] = tracts["households"].round(0)
    return out


def roll_up_county(tracts: pd.DataFrame) -> pd.DataFrame:
    df = tracts.reset_index()
    df["county"] = df["geoid"].astype(str).str.zfill(11).str[:5]
    cols = METRIC_COLS + ["socioeconomic_index"]

    def _wmean(frame: pd.DataFrame) -> dict:
        ww = frame["households"].fillna(0.0).clip(lower=0.0)
        res = {}
        for c in cols:
            v = frame[c]
            m = v.notna() & (ww > 0)
            res[c] = round(float((v[m] * ww[m]).sum() / ww[m].sum()), 1) if m.any() else ""
        res["households"] = round(float(ww.sum()), 0)
        return res

    rows = []
    for fips, g in df.groupby("county"):
        row = {"geoid": fips}
        row.update(_wmean(g))
        rows.append(row)
    nat = {"geoid": NATIONAL_OUT}
    nat.update(_wmean(df))
    rows.append(nat)
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache-dir", default=None, help="download cache directory")
    ap.add_argument("--limit-states", type=int, default=None,
                    help="(smoke test) keep only the first N state FIPS after scoring.")
    args = ap.parse_args()

    cache = pathlib.Path(args.cache_dir
                         or (pathlib.Path(__file__).resolve().parents[1] / ".socio_cache"))
    log.info("ACS socio build (%d 5-yr). Cache: %s", ACS_YEAR, cache)

    parsed = {}
    for table, cols in NEEDED.items():
        path = _download(f"{_SF}/acsdt5y{ACS_YEAR}-{table}.dat",
                         cache / f"acsdt5y{ACS_YEAR}-{table}.dat")
        parsed[table] = _parse_table(path, cols)
        log.info("Parsed %s: %d geographies.", table, len(parsed[table]))

    metrics = derive_metrics(parsed["b17001"], parsed["b19013"], parsed["b25106"],
                             parsed["b15003"], parsed["b23025"])
    tracts = metrics[metrics.index.str.len() == 11].copy()   # tract rows only for scoring
    log.info("Derived metrics for %d tracts.", len(tracts))

    scored = score_tracts(tracts)
    if args.limit_states:
        keep = sorted({i[:2] for i in scored.index})[: args.limit_states]
        scored = scored[scored.index.str[:2].isin(keep)]
        log.info("Smoke build: kept %d tracts in states %s", len(scored), keep)

    n = int(scored["socioeconomic_index"].notna().sum())
    log.info("Scored %d/%d tracts nationally (socioeconomic_index).", n, len(scored))

    county = roll_up_county(scored)

    tract_out = _DATA / "socio_tracts.csv.gz"
    county_out = _DATA / "socio_county.csv"
    scored.reset_index().to_csv(tract_out, index=False, compression="gzip")
    county.to_csv(county_out, index=False)

    si = scored["socioeconomic_index"].dropna()
    log.info("Wrote %s (%d tracts) and %s (%d counties).",
             tract_out.name, len(scored), county_out.name, len(county) - 1)
    log.info("socioeconomic_index national spread: min=%.1f p25=%.1f median=%.1f p75=%.1f max=%.1f",
             si.min(), si.quantile(.25), si.median(), si.quantile(.75), si.max())
    return 0


if __name__ == "__main__":
    sys.exit(main())
