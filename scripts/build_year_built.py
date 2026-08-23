#!/usr/bin/env python3
"""Build the tract/county YEAR-BUILT DISTRIBUTION crosswalk (ACS B25034 + B25035).

Why
---
Every label's ``year_built`` came from the USACE NSI field ``med_yr_blt``, which its
own documentation defines as *"the median year built of structures within the Census
tract"* — a property of the tract, never of the building standing on the parcel. The
label already says so (``status="assumed"`` in ``simulate/house.py``), but a bare
point estimate cannot tell a reader *how wrong it might be*, and the answer turns out
to be: very. Across the 84k tracts that score here the **median interquartile spread
is 27 years**, and 72.8% of tracts spread 20 years or more. A tract median is a point
estimate with roughly ±14 years of slack at the quartiles, and that is enough to move
``code_era_factor`` by ~18% and to halve or double a modeled component age.

So this builds the thing NSI never had: the **distribution**, not just its centre.

Method (reproducible, KEYLESS — ACS 5-year table-based Summary File)
--------------------------------------------------------------------
Same bulk source and parsing shape as ``scripts/build_socio_ref.py`` — one
pipe-delimited file per table, no API key (the Census Data *API* now needs one;
these files do not). Each file carries every geography, so tract
(``1400000US``), county (``0500000US``) and national (``0100000US``) rows are all
read straight from the source rather than rolled up here. That matters for a
percentile: aggregating tract medians into a county would be a median-of-medians,
whereas the county's own bucket counts give the real county distribution.

  1. **B25034** "Year Structure Built" — ten decade buckets, verified against the
     Census variable metadata for this vintage:

         E002 2020 or later   E003 2010–2019   E004 2000–2009   E005 1990–1999
         E006 1980–1989       E007 1970–1979   E008 1960–1969   E009 1950–1959
         E010 1940–1949       E011 1939 or earlier

  2. Derive **p25 / p50 / p75** by linear interpolation within the bucket that
     contains each quantile, walking oldest → newest so the CDF runs forward in
     time. Buckets are treated as half-open continuous intervals ([1940, 1950) for
     "1940 to 1949"), which is the standard treatment of grouped data and the same
     one the Census applies to this table.

  3. **B25035** "Median Year Structure Built" is the Census's *own* published median
     for the same distribution. It is written as the shipped ``median`` — it is the
     authoritative, citable figure — and the median derived in step 2 is used to
     **validate** the interpolation: if our rule reproduces theirs across 80k
     tracts, the same rule applied to p25/p75 is trustworthy. The build logs the
     agreement and fails loudly if it degrades.

Two conventions, stated because they are choices
------------------------------------------------
The oldest bucket is open-ended ("1939 or earlier") and is treated as [1900, 1940);
the newest ("2020 or later") as [2020, 2025) for this 2020–2024 vintage. A quantile
landing inside either is interpolated within that nominal span, so the extremes are
bounded rather than infinite. Tracts below ``MIN_UNITS`` housing units are dropped
rather than written: their quartiles are noise, and dropping them lets the runtime
fall back to the county distribution, which is the honest answer there.

Margins of error — used, not carried
------------------------------------
Nothing in this repo has ever read an ACS margin of error: every builder pulls the
``_E`` estimate columns and leaves the ``_M`` margins on the floor. This one reads
B25034_M001 and **acts on it at build time**, dropping any geography whose
housing-unit count has a coefficient of variation above :data:`MAX_CV` — the
conventional ACS "unreliable" threshold. Nationally that is 157 tracts (0.19%), each
of which then falls back to its county, which is the honest answer for a place whose
own count is that uncertain.

Acting on the margin rather than shipping it is deliberate, and the reason is what a
margin is *for*: it qualifies an estimate, and the only place anything here is in a
position to act on that is the build. A request handed ``units_moe`` could not do
anything with it that this filter has not already done. Not shipping it also keeps a
column off a 512 MB instance where the bundled tract tables are the memory ceiling
(see ``data/_tractstore.py``) — measured at 0.6 MB, which is a real saving and a
minor one next to the ~10 MB floor every tract table pays for its geoid index.

Outputs (bundled, committed)
----------------------------
  src/housing_label/data/year_built_tracts.csv.gz  geoid(11) + p25/median/p75 + units
  src/housing_label/data/year_built_county.csv     geoid(5) + same (plus a national row, geoid 00000)

Run:  python scripts/build_year_built.py
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys
import time

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger("build_year_built")

_DATA = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"
HEADERS = {"User-Agent": "housing-nutrition-label/0.1 (year-built crosswalk build)"}

ACS_YEAR = 2024
_SF = (f"https://www2.census.gov/programs-surveys/acs/summary_file/{ACS_YEAR}"
       "/table-based-SF/data/5YRData")

TRACT_PREFIX = "1400000US"
COUNTY_PREFIX = "0500000US"
NATION_GEOID = "0100000US"
NATIONAL_OUT = "00000"

# Buckets OLDEST → NEWEST as half-open [lo, hi) year spans, paired with the B25034
# column that counts them. Order is load-bearing: the CDF is accumulated in this
# sequence, so reversing it would invert every percentile.
BUCKETS = [
    ("B25034_E011", 1900, 1940),          # 1939 or earlier (open-ended; see docstring)
    ("B25034_E010", 1940, 1950),
    ("B25034_E009", 1950, 1960),
    ("B25034_E008", 1960, 1970),
    ("B25034_E007", 1970, 1980),
    ("B25034_E006", 1980, 1990),
    ("B25034_E005", 1990, 2000),
    ("B25034_E004", 2000, 2010),
    ("B25034_E003", 2010, 2020),
    ("B25034_E002", 2020, ACS_YEAR + 1),  # 2020 or later
]
TOTAL_COL = "B25034_E001"
TOTAL_MOE_COL = "B25034_M001"
ACS_MEDIAN_COL = "B25035_E001"

NEEDED = {
    "b25034": [TOTAL_COL, TOTAL_MOE_COL] + [c for c, _, _ in BUCKETS],
    "b25035": [ACS_MEDIAN_COL],
}

# A tract with almost no housing units has no meaningful vintage distribution — its
# quartiles would be one or two homes wide apart. Dropping it sends the runtime to
# the county row instead, which is the honest fallback.
MIN_UNITS = 20

# Maximum coefficient of variation on the housing-unit count for a geography to be
# shipped: CV = (MOE / 1.645) / estimate, the standard ACS reliability measure, and
# 0.30 the conventional "do not use" line. A tract past it has a unit count too
# uncertain for its own quartiles to mean anything; dropping it defers to the county.
MAX_CV = 0.30

# Plausibility window for a published median. B25035 uses jam values for
# suppressed cells, and a year outside this range is one of them, not a date.
YEAR_MIN, YEAR_MAX = 1800, ACS_YEAR + 1

# Build-time gate on step 3's validation: our derived median must agree with the
# Census's published B25035 to within this many years for at least AGREE_SHARE of
# the tracts where both exist. These are not tuning knobs — they encode "the
# interpolation rule reproduces the Census's own", and a build that misses them has
# a broken rule, not an unlucky threshold.
AGREE_TOL_YEARS = 3.0
AGREE_SHARE = 0.95

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
    """geoid(GEO_ID) -> {col: float} for the wanted cols, tract/county/national only.

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


def quantile_year(counts: list[float], q: float) -> float | None:
    """The year at quantile ``q`` of a bucketed year-built distribution.

    ``counts`` is parallel to :data:`BUCKETS` — oldest first. Linear interpolation
    within the bucket that contains ``q``; returns None for an empty distribution.
    """
    total = float(sum(counts))
    if total <= 0:
        return None
    target = q * total
    cum = 0.0
    for (_, lo, hi), c in zip(BUCKETS, counts):
        c = float(c)
        if c <= 0:
            continue
        if cum + c >= target:
            return lo + (target - cum) / c * (hi - lo)
        cum += c
    # Ran off the newest end (only reachable at q=1.0 with float slack).
    return float(BUCKETS[-1][2])


def derive(b25034: dict, b25035: dict) -> pd.DataFrame:
    """One row per geography: quartiles, the ACS median, and the unit count."""
    # Sorted so the written CSV is deterministic, independent of dict iteration —
    # keeps rebuild diffs readable.
    rows: list[dict] = []
    dropped: list[str] = []
    for g in sorted(b25034):
        src = b25034[g]
        counts = [src.get(c) or 0.0 for c, _, _ in BUCKETS]
        total = src.get(TOTAL_COL)
        if total is None or total < MIN_UNITS:
            continue
        p25 = quantile_year(counts, 0.25)
        p50 = quantile_year(counts, 0.50)
        p75 = quantile_year(counts, 0.75)
        if p25 is None or p50 is None or p75 is None:
            continue

        # Reliability gate. A published MOE of None means the Census didn't give one,
        # which is not evidence of precision — but it is also not grounds to discard
        # a row, so an absent margin passes.
        moe = src.get(TOTAL_MOE_COL)
        if moe is not None and total > 0 and (moe / 1.645) / total > MAX_CV:
            dropped.append(_norm_geoid(g))
            continue

        acs_med = (b25035.get(g) or {}).get(ACS_MEDIAN_COL)
        if acs_med is not None and not (YEAR_MIN <= acs_med <= YEAR_MAX):
            acs_med = None      # a jam value, not a date

        rows.append({
            "geoid": _norm_geoid(g),
            "p25": p25,
            "derived_median": p50,
            "acs_median": acs_med,
            "p75": p75,
            "units": total,
        })
    log.info("Dropped %d geographies over the CV>%.2f reliability threshold.",
             len(dropped), MAX_CV)
    return pd.DataFrame(rows).set_index("geoid")


def validate_median(df: pd.DataFrame) -> float:
    """Check the interpolation rule against the Census's own published median.

    Returns the share agreeing within :data:`AGREE_TOL_YEARS`. Raises when the rule
    fails to reproduce B25035 — that means step 2 is wrong, and the p25/p75 it also
    produces cannot be trusted either.
    """
    both = df[df["acs_median"].notna()]
    if both.empty:
        raise SystemExit("no geography carries B25035 — cannot validate the interpolation")
    diff = (both["derived_median"] - both["acs_median"]).abs()
    share = float((diff <= AGREE_TOL_YEARS).mean())
    log.info("Interpolation vs. published B25035 over %d geographies: "
             "median |Δ| = %.2f yr, p95 |Δ| = %.2f yr, within %.0f yr = %.2f%%",
             len(both), diff.median(), diff.quantile(.95), AGREE_TOL_YEARS, 100 * share)
    if share < AGREE_SHARE:
        raise SystemExit(
            f"derived median reproduces B25035 for only {share:.1%} of geographies "
            f"(need {AGREE_SHARE:.0%}) — the bucket interpolation is wrong, so the "
            f"p25/p75 it also produces cannot be shipped")
    return share


def finalize(df: pd.DataFrame) -> pd.DataFrame:
    """Pick the shipped median and enforce p25 <= median <= p75.

    The Census's published median wins where it exists; ours fills in where B25035
    is suppressed. Clamping matters because the two are computed from the same
    distribution by *almost* the same rule, so on a handful of geographies the
    published median can land a hair outside our quartiles — and a range that
    doesn't contain its own centre would render as nonsense.
    """
    median = df["acs_median"].where(df["acs_median"].notna(), df["derived_median"])
    out = pd.DataFrame(index=df.index)
    out["p25"] = df["p25"].round().astype("Int64")
    out["median"] = median.round().astype("Int64")
    out["p75"] = df["p75"].round().astype("Int64")
    out["median"] = out["median"].clip(lower=out["p25"], upper=out["p75"])
    out["units"] = df["units"].round().astype("Int64")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache-dir", default=None, help="download cache directory")
    ap.add_argument("--limit-states", type=int, default=None,
                    help="(smoke test) keep only the first N state FIPS.")
    args = ap.parse_args()

    cache = pathlib.Path(args.cache_dir
                         or (pathlib.Path(__file__).resolve().parents[1] / ".yearbuilt_cache"))
    log.info("ACS year-built build (%d 5-yr). Cache: %s", ACS_YEAR, cache)

    parsed = {}
    for table, cols in NEEDED.items():
        path = _download(f"{_SF}/acsdt5y{ACS_YEAR}-{table}.dat",
                         cache / f"acsdt5y{ACS_YEAR}-{table}.dat")
        parsed[table] = _parse_table(path, cols)
        log.info("Parsed %s: %d geographies.", table, len(parsed[table]))

    df = derive(parsed["b25034"], parsed["b25035"])
    log.info("Derived quantiles for %d geographies (>= %d units).", len(df), MIN_UNITS)

    validate_median(df)
    final = finalize(df)

    tracts = final[final.index.str.len() == 11]
    counties = final[final.index.str.len() != 11]
    if args.limit_states:
        keep = sorted({i[:2] for i in tracts.index})[: args.limit_states]
        tracts = tracts[tracts.index.str[:2].isin(keep)]
        log.info("Smoke build: kept %d tracts in states %s", len(tracts), keep)

    tract_out = _DATA / "year_built_tracts.csv.gz"
    county_out = _DATA / "year_built_county.csv"
    tracts.reset_index().to_csv(tract_out, index=False, compression="gzip")
    counties.reset_index().to_csv(county_out, index=False)
    log.info("Wrote %s (%d tracts) and %s (%d county/national rows).",
             tract_out.name, len(tracts), county_out.name, len(counties))

    spread = (tracts["p75"] - tracts["p25"]).astype(float)
    log.info("Tract interquartile spread: median=%.0f yr  mean=%.1f yr  p90=%.0f yr  "
             ">=20 yr: %.1f%% of tracts",
             spread.median(), spread.mean(), spread.quantile(.90),
             100.0 * float((spread >= 20).mean()))
    med = tracts["median"].astype(float)
    log.info("Tract median year built: p10=%.0f p50=%.0f p90=%.0f",
             med.quantile(.10), med.median(), med.quantile(.90))
    if NATIONAL_OUT in counties.index:
        nat = counties.loc[NATIONAL_OUT]
        log.info("National row: p25=%s median=%s p75=%s", nat["p25"], nat["median"], nat["p75"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
