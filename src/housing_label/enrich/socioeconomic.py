#!/usr/bin/env python3
"""Enrich shelby_parcels_sample.csv with Census ACS socioeconomic data.

Usage
-----
  python enrich_socioeconomic.py              # all 1 000 parcels
  python enrich_socioeconomic.py --limit 10  # test with 10 rows first
  python enrich_socioeconomic.py --year 2022 # pin a specific ACS 5-year vintage

Data source
-----------
  U.S. Census Bureau — American Community Survey 5-Year Estimates (ACS5)
  API  : https://api.census.gov/data/{year}/acs/acs5  (detailed tables)
  Auth : None required for light use.  An optional key (env CENSUS_API_KEY)
         is sent if present — get one free at https://api.census.gov/data/key_signup.html
  Level: Census tract (2020 vintage), Shelby County TN (state 47 / county 157)

Tract assignment
----------------
  U.S. Census Geocoder API (geocoding.geo.census.gov) converts each parcel's
  lat/lon to a 2020-vintage census tract GEOID (11-digit string) — the same
  approach used by enrich_health.py.
  Rate  : 0.2 s sleep between calls (~5 req/s — polite for a public service).
  Resume: existing output is reloaded on re-run; already-geocoded parcels are
          skipped, so interrupted runs can be safely restarted.
  Seed  : if shelby_parcels_health.csv exists (same tract geography), its
          census_tract column is reused to skip redundant geocoding.

ACS measures used
-----------------
  Poverty rate        B17001 — population below poverty / population for whom
                      poverty status is determined.
  Median HH income    B19013_001E — median household income (inflation-adjusted
                      dollars for the survey period).
  Housing cost burden B25106 — Tenure by Housing Costs as a Percentage of
                      Household Income.  "Cost-burdened" = paying 30 % or more
                      of household income on housing (owner + renter combined),
                      divided by households for whom the ratio is computed.

socioeconomic_index
-------------------
  Three headline metrics are each ranked 0–100 percentile relative to ALL
  Shelby County tracts in the ACS dataset (not just the parcel sample), then
  oriented so 100 = least economic stress:

    poverty_rate_pct        inverted  (lower poverty  → higher score)
    median_household_income direct    (higher income  → higher score)
    housing_cost_burden_pct inverted  (lower burden   → higher score)

  socioeconomic_index = mean of the three 0–100 scores.
  Range: 0–100   |   100 = least economically stressed vs. county peers.

  This answers: "How does this neighborhood rank for economic security
  compared to every other census tract in Shelby County?"

Columns added
-------------
  census_tract             GEOID of the 2020 census tract (11-digit string)
  poverty_rate_pct         % of population below the federal poverty line
  median_household_income  median household income (USD)
  housing_cost_burden_pct  % of households paying ≥ 30 % of income on housing
  cost_burden_owner_pct    same, owner-occupied households only
  cost_burden_renter_pct   same, renter-occupied households only
  socioeconomic_index      0–100 composite (100 = least stressed vs. peers)
"""

import argparse, logging, os, pathlib, sys, time
import requests, pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── File paths ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[3]   # repo root; data lives here
# Defaults; overridable via --input/--output so run_pipeline.py can chain stages.
# In the pipeline the input is shelby_parcels_health.csv, which already carries a
# census_tract column (same geography), so geocoding is skipped entirely.
DEFAULT_IN  = "shelby_parcels_health.csv"
DEFAULT_OUT = "shelby_parcels_socioeconomic.csv"
SEED_FILE   = SCRIPT_DIR / "shelby_parcels_health.csv"


def _resolve(path_str) -> pathlib.Path:
    """Resolve a bare path relative to SCRIPT_DIR; absolute paths pass through."""
    p = pathlib.Path(path_str)
    return p if p.is_absolute() else (SCRIPT_DIR / p)

# ── Geography ─────────────────────────────────────────────────────────────────
STATE_FIPS  = "47"     # Tennessee
COUNTY_FIPS = "157"    # Shelby County  (full county GEOID prefix = 47157)

# ── API endpoints ─────────────────────────────────────────────────────────────
ACS_URL_TMPL = "https://api.census.gov/data/{year}/acs/acs5"
GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"

# ── Request settings ──────────────────────────────────────────────────────────
SLEEP_SEC    = 0.2    # polite delay between geocoder calls (~5 req/s)
TIMEOUT      = 25     # seconds per HTTP call
MAX_RETRIES  = 3
BACKOFF      = 2      # exponential back-off multiplier
CHECKPOINT   = 50     # save every N geocoded rows
DEFAULT_YEAR = 2023   # newest ACS5 vintage known-good at time of writing
YEAR_FALLBACK = 3     # step back up to N years if a vintage isn't published yet

# ── ACS variables ─────────────────────────────────────────────────────────────
# Poverty (B17001) and median household income (B19013).
POVERTY_TOTAL = "B17001_001E"   # population for whom poverty status is determined
POVERTY_BELOW = "B17001_002E"   # income in the past 12 months below poverty level
MEDIAN_INCOME = "B19013_001E"   # median household income

# Housing cost burden (B25106 — Tenure by Housing Costs as % of Household Income).
# "30.0 percent or more" cells, per income bracket, for owners and renters.
B25106_TOTAL          = "B25106_001E"
B25106_OWNER_TOTAL    = "B25106_002E"
B25106_RENTER_TOTAL   = "B25106_024E"
B25106_OWNER_30PLUS   = ["B25106_006E", "B25106_010E", "B25106_014E",
                         "B25106_018E", "B25106_022E"]
B25106_RENTER_30PLUS  = ["B25106_028E", "B25106_032E", "B25106_036E",
                         "B25106_040E", "B25106_044E"]
# Households for whom the cost ratio is NOT computed (excluded from denominator).
B25106_OWNER_NOTCOMP  = "B25106_023E"   # owner, zero or negative income
B25106_RENTER_NOTCOMP = ["B25106_045E", "B25106_046E"]  # zero/neg income, no cash rent

ACS_VARS = (
    [POVERTY_TOTAL, POVERTY_BELOW, MEDIAN_INCOME,
     B25106_TOTAL, B25106_OWNER_TOTAL, B25106_RENTER_TOTAL,
     B25106_OWNER_NOTCOMP]
    + B25106_OWNER_30PLUS + B25106_RENTER_30PLUS + B25106_RENTER_NOTCOMP
)

SOCIO_COLS = [
    "census_tract",
    "poverty_rate_pct",
    "median_household_income",
    "housing_cost_burden_pct",
    "cost_burden_owner_pct",
    "cost_burden_renter_pct",
    "socioeconomic_index",
]

# ACS uses large negative sentinels (e.g. -666666666) for jam/suppressed values.
ACS_NULL_FLOOR = -100000000


# ── Helpers ────────────────────────────────────────────────────────────────────
def _clean_tract(val) -> str | None:
    """Normalise a raw census_tract value to an 11-char GEOID string or None."""
    if val is None:
        return None
    s = str(val).strip()
    if s.lower() in ("nan", "none", ""):
        return None
    # Strip any accidental decimal suffix (e.g. "47157000400.0" → "47157000400")
    if "." in s:
        s = s.split(".")[0]
    return s.zfill(11)


def _safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    """Element-wise num/den*100, returning NaN where the denominator is ≤ 0."""
    den = den.where(den > 0)
    return (num / den * 100.0).round(1)


# ── Census ACS data fetch ──────────────────────────────────────────────────────
def fetch_acs_data(year: int, state_fips: str = STATE_FIPS,
                   county_fips: str = COUNTY_FIPS) -> tuple[pd.DataFrame, int]:
    """Download ACS5 tract-level socioeconomic data for a county.

    Tries the requested `year` and steps back up to YEAR_FALLBACK vintages if
    that release is not yet published.  Returns a DataFrame indexed by 11-digit
    tract GEOID with the headline metrics plus a pre-computed socioeconomic_index
    (percentile-ranked across all county tracts), and the vintage actually used.

    `state_fips` (2-digit) and `county_fips` (3-digit) default to Shelby County.
    """
    api_key = os.environ.get("CENSUS_API_KEY")
    if api_key:
        log.info("Using CENSUS_API_KEY from environment.")

    last_exc: Exception | None = None
    for yr in range(year, year - YEAR_FALLBACK - 1, -1):
        url = ACS_URL_TMPL.format(year=yr)
        params = {
            "get": "NAME," + ",".join(ACS_VARS),
            "for": "tract:*",
            "in":  f"state:{state_fips} county:{county_fips}",
        }
        if api_key:
            params["key"] = api_key

        log.info("Fetching ACS5 %d data for FIPS %s%s …",
                 yr, state_fips, county_fips)
        try:
            records = _acs_get(url, params)
        except Exception as exc:                       # noqa: BLE001
            last_exc = exc
            log.warning("ACS5 %d unavailable (%s) — trying previous vintage.", yr, exc)
            continue

        df = _acs_to_frame(records)
        if df.empty:
            last_exc = RuntimeError(f"ACS5 {yr} returned no tracts for Shelby County")
            log.warning("ACS5 %d returned no rows — trying previous vintage.", yr)
            continue

        log.info("  %d tracts received from ACS5 %d.", len(df), yr)
        return _compute_socio(df), yr

    raise RuntimeError(
        f"Census ACS API unavailable for vintages {year}..{year - YEAR_FALLBACK}"
    ) from last_exc


def _acs_get(url: str, params: dict) -> list:
    """GET the ACS API with retry/back-off; returns the parsed JSON list."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            # A missing vintage returns 404 — surface it so the caller can fall back.
            if r.status_code == 404:
                raise RuntimeError("HTTP 404 (vintage not published)")
            r.raise_for_status()
            return r.json()
        except Exception as exc:                       # noqa: BLE001
            log.warning("ACS API attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
            if attempt == MAX_RETRIES:
                raise
            time.sleep(BACKOFF ** attempt)
    return []


def _acs_to_frame(records: list) -> pd.DataFrame:
    """Convert the ACS [header, *rows] response into a typed, GEOID-indexed frame."""
    header, *rows = records
    df = pd.DataFrame(rows, columns=header)

    # Numeric coercion; ACS jam-values (large negatives) → NaN.
    for col in ACS_VARS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df.loc[df[col] < ACS_NULL_FLOOR, col] = pd.NA
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Build the 11-digit tract GEOID from the geography component columns.
    df["census_tract"] = (
        df["state"].str.zfill(2) + df["county"].str.zfill(3) + df["tract"].str.zfill(6)
    )
    return df.set_index("census_tract")


def _compute_socio(df: pd.DataFrame) -> pd.DataFrame:
    """Derive headline metrics and the percentile-ranked socioeconomic_index."""
    out = pd.DataFrame(index=df.index)

    # Poverty rate.
    out["poverty_rate_pct"] = _safe_div(df[POVERTY_BELOW], df[POVERTY_TOTAL])

    # Median household income (already a dollar value).
    out["median_household_income"] = df[MEDIAN_INCOME].round(0)

    # Housing cost burden — owners, renters, and combined.
    owner_30   = df[B25106_OWNER_30PLUS].sum(axis=1)
    renter_30  = df[B25106_RENTER_30PLUS].sum(axis=1)
    owner_den  = df[B25106_OWNER_TOTAL]  - df[B25106_OWNER_NOTCOMP]
    renter_den = df[B25106_RENTER_TOTAL] - df[B25106_RENTER_NOTCOMP].sum(axis=1)
    total_den  = (df[B25106_TOTAL]
                  - df[B25106_OWNER_NOTCOMP]
                  - df[B25106_RENTER_NOTCOMP].sum(axis=1))

    out["cost_burden_owner_pct"]   = _safe_div(owner_30, owner_den)
    out["cost_burden_renter_pct"]  = _safe_div(renter_30, renter_den)
    out["housing_cost_burden_pct"] = _safe_div(owner_30 + renter_30, total_den)

    # ── Percentile scores (computed across all county tracts) ─────────────────
    # rank(pct=True) → 0–1.  Orient every component so 100 = least stressed.
    pov_rank    = out["poverty_rate_pct"].rank(pct=True, na_option="keep")
    burden_rank = out["housing_cost_burden_pct"].rank(pct=True, na_option="keep")
    inc_rank    = out["median_household_income"].rank(pct=True, na_option="keep")

    score_pov    = (1.0 - pov_rank)    * 100.0   # lower poverty → higher score
    score_burden = (1.0 - burden_rank) * 100.0   # lower burden  → higher score
    score_inc    = inc_rank            * 100.0   # higher income → higher score

    scores = pd.concat([score_pov, score_inc, score_burden], axis=1)
    out["socioeconomic_index"] = scores.mean(axis=1, skipna=True).round(1)

    # Reorder to the documented column layout (index holds census_tract).
    return out[[c for c in SOCIO_COLS if c != "census_tract"]]


# ── Census Geocoder ────────────────────────────────────────────────────────────
def get_census_tract(lat: float, lon: float) -> str | None:
    """Return the 2020 census tract GEOID (11-digit string) for a lat/lon point.

    Uses the U.S. Census Bureau's public geocoder.  Returns None on any
    failure or when the point falls outside a mapped tract.
    """
    params = {
        "x":         lon,
        "y":         lat,
        "benchmark": "Public_AR_Current",
        "vintage":   "Current_Current",
        "format":    "json",
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(GEOCODER_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:                       # noqa: BLE001
            log.warning("Geocoder attempt %d/%d: %s", attempt, MAX_RETRIES, exc)
            if attempt == MAX_RETRIES:
                return None
            time.sleep(BACKOFF ** attempt)
            continue

        try:
            tracts = data["result"]["geographies"]["Census Tracts"]
            if not tracts:
                return None
            return str(tracts[0]["GEOID"]).zfill(11)
        except (KeyError, IndexError, TypeError):
            return None

    return None


def _seed_tracts(df: pd.DataFrame) -> int:
    """Fill census_tract from a prior enrichment (same tract geography), if present.

    enrich_health.py geocodes the identical parcels to the same 2020 tracts, so
    reusing its output avoids thousands of redundant geocoder calls.  Returns the
    number of rows seeded.
    """
    if not SEED_FILE.exists():
        return 0
    try:
        seed = pd.read_csv(SEED_FILE)
    except Exception as exc:                           # noqa: BLE001
        log.warning("Could not read seed file %s: %s", SEED_FILE.name, exc)
        return 0
    if "census_tract" not in seed.columns or len(seed) != len(df):
        log.info("Seed file present but not row-aligned — skipping seed.")
        return 0

    seeded = seed["census_tract"].apply(_clean_tract)
    fill = df["census_tract"].isna() & seeded.notna()
    df.loc[fill, "census_tract"] = seeded[fill].values
    n = int(fill.sum())
    if n:
        log.info("Seeded %d census tracts from %s (skips geocoding).", n, SEED_FILE.name)
    return n


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Enrich Shelby County parcels with Census ACS socioeconomic data."
    )
    parser.add_argument(
        "--input", default=DEFAULT_IN,
        help=f"Input parcels CSV (default: {DEFAULT_IN}).",
    )
    parser.add_argument(
        "--output", default=DEFAULT_OUT,
        help=f"Output CSV (default: {DEFAULT_OUT}).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N rows (for testing).",
    )
    parser.add_argument(
        "--year", type=int, default=DEFAULT_YEAR,
        help=f"ACS 5-year vintage to request (default {DEFAULT_YEAR}; "
             f"falls back up to {YEAR_FALLBACK} years if unpublished).",
    )
    args = parser.parse_args()

    in_path  = _resolve(args.input)
    out_path = _resolve(args.output)

    # ── Load parcels ──────────────────────────────────────────────────────────
    log.info("Reading %s", in_path)
    if not in_path.exists():
        log.error("Input file not found: %s", in_path)
        sys.exit(1)
    df = pd.read_csv(in_path)
    log.info("  %d rows × %d columns", *df.shape)

    if "latitude" not in df.columns or "longitude" not in df.columns:
        log.error("Input must have 'latitude' and 'longitude' columns.")
        sys.exit(1)

    # ── Census tract: prefer a value already on the input (the pipeline feeds
    #    shelby_parcels_health.csv, which carries census_tract), then resume from
    #    any prior output, then the health seed file. ───────────────────────────
    if "census_tract" in df.columns:
        df["census_tract"] = df["census_tract"].apply(_clean_tract)
    else:
        df["census_tract"] = None

    if out_path.exists():
        log.info("Found existing output — loading for resume: %s", out_path)
        prev = pd.read_csv(out_path)
        if "census_tract" in prev.columns and len(prev) == len(df):
            prev_tracts = prev["census_tract"].apply(_clean_tract)
            fill = df["census_tract"].isna() & prev_tracts.notna()
            df.loc[fill, "census_tract"] = prev_tracts[fill].values
        already = df["census_tract"].notna().sum()
        log.info("  %d rows already have a census tract assigned.", already)

    # Reuse tracts from the health enrichment (same geography) where still missing.
    _seed_tracts(df)

    if args.limit:
        df = df.head(args.limit)
        log.info("--limit %d applied.", args.limit)

    # ── Step 1: Download ACS tract-level data ─────────────────────────────────
    tract_socio, vintage = fetch_acs_data(args.year)

    # ── Step 2: Geocode parcels → census tract ────────────────────────────────
    todo = df[
        df["census_tract"].isna()
        & df["latitude"].notna()
        & df["longitude"].notna()
    ]
    log.info("%d parcels need census tract geocoding.", len(todo))

    if not todo.empty:
        for i, (idx, row) in enumerate(todo.iterrows(), start=1):
            tract = get_census_tract(float(row["latitude"]), float(row["longitude"]))
            df.at[idx, "census_tract"] = tract
            log.debug("Row %d (idx=%d): tract=%s", i, idx, tract)

            if i % CHECKPOINT == 0 or i == len(todo):
                log.info("Geocoder progress: %d/%d  (checkpoint save)", i, len(todo))
                df.to_csv(out_path, index=False)

            time.sleep(SLEEP_SEC)

    # ── Step 3: Join ACS data to parcels ──────────────────────────────────────
    log.info("Joining socioeconomic data from %d tracts …", len(tract_socio))

    # Normalise census_tract to clean 11-digit strings for a reliable merge key
    df["census_tract"] = df["census_tract"].apply(_clean_tract)

    # Drop any stale socioeconomic columns from a previous run before re-joining
    stale = [c for c in SOCIO_COLS[1:] if c in df.columns]
    if stale:
        df = df.drop(columns=stale)

    tract_df = (
        tract_socio
        .reset_index()
        .rename(columns={"index": "census_tract"})
    )
    tract_df["census_tract"] = tract_df["census_tract"].apply(_clean_tract)

    df = df.merge(tract_df, on="census_tract", how="left")

    # ── Save ──────────────────────────────────────────────────────────────────
    df.to_csv(out_path, index=False)
    log.info("Saved → %s", out_path)

    _print_summary(df, vintage, out_path)


# ── Summary ────────────────────────────────────────────────────────────────────
def _print_summary(df: pd.DataFrame, vintage: int, out_path: pathlib.Path):
    total          = len(df)
    tract_assigned = df["census_tract"].notna().sum()
    socio_data     = df["socioeconomic_index"].notna().sum()
    n_tracts       = df["census_tract"].nunique()
    si             = df["socioeconomic_index"].dropna()
    w = 46

    out_county = (
        df["census_tract"]
        .dropna()
        .loc[~df["census_tract"].dropna().str.startswith(STATE_FIPS + COUNTY_FIPS)]
        .count()
    )

    print("\n╔══ SOCIOECONOMIC ENRICHMENT SUMMARY ═══════════════════════════════╗")
    print(f"║ Total parcels                : {total:<{w}}║")
    print(f"║ Census tracts assigned       : {tract_assigned:<{w}}║")
    print(f"║ Unique tracts found          : {n_tracts:<{w}}║")
    if out_county > 0:
        print(f"║ Parcels outside Shelby Co.   : {out_county:<{w}}║")
    print(f"║ Parcels with ACS data        : {socio_data:<{w}}║")
    print(f"║ Source                       : {f'Census ACS 5-Year {vintage} (tract estimates)':<{w}}║")
    print(f"║ Geography                    : {'Census tract · Shelby County TN (FIPS 47157)':<{w}}║")

    if not si.empty:
        spread = si.max() - si.min()
        print("║ ── socioeconomic_index (0–100, higher = less stressed) ──────────── ║")
        print(f"║   min    : {si.min():<{w-2}.1f}║")
        print(f"║   p25    : {si.quantile(0.25):<{w-2}.1f}║")
        print(f"║   median : {si.median():<{w-2}.1f}║")
        print(f"║   p75    : {si.quantile(0.75):<{w-2}.1f}║")
        print(f"║   max    : {si.max():<{w-2}.1f}║")
        print(f"║   spread : {spread:<{w-2}.1f}  (max − min; > 30 = clear gradient)║")

    # Headline-metric medians across all matched parcels.
    print("║ ── Headline metric medians across matched parcels ───────────────── ║")
    pov = df["poverty_rate_pct"].median()
    inc = df["median_household_income"].median()
    bur = df["housing_cost_burden_pct"].median()
    print(f"║   poverty rate           : {pov:>6.1f}%{'':>17}║")
    print(f"║   median HH income       : ${inc:>10,.0f}{'':>14}║")
    print(f"║   housing cost burden    : {bur:>6.1f}%{'':>17}║")

    # Tract-level extremes (deduplicated).
    if not si.empty:
        tract_summary = (
            df[["census_tract", "socioeconomic_index",
                "poverty_rate_pct", "median_household_income", "housing_cost_burden_pct"]]
            .dropna(subset=["socioeconomic_index"])
            .drop_duplicates("census_tract")
            .sort_values("socioeconomic_index", ascending=False)
        )

        print("║ ── Top 5 least-stressed tracts ──────────────────────────────────── ║")
        for _, r in tract_summary.head(5).iterrows():
            fmt = (f"tract {r['census_tract']}  idx={r['socioeconomic_index']:.0f}  "
                   f"pov={r['poverty_rate_pct']:.0f}%  burden={r['housing_cost_burden_pct']:.0f}%")
            print(f"║   {fmt:<{w+1}}║")

        print("║ ── Bottom 5 most-stressed tracts ────────────────────────────────── ║")
        for _, r in tract_summary.tail(5).iterrows():
            fmt = (f"tract {r['census_tract']}  idx={r['socioeconomic_index']:.0f}  "
                   f"pov={r['poverty_rate_pct']:.0f}%  burden={r['housing_cost_burden_pct']:.0f}%")
            print(f"║   {fmt:<{w+1}}║")

    print(f"║ New columns added            : {len(SOCIO_COLS):<{w}}║")
    print(f"║ Output                       : {out_path.name:<{w}}║")
    print("╚═══════════════════════════════════════════════════════════════════╝\n")

    # ── Sample rows ───────────────────────────────────────────────────────────
    sample_cols = (
        ["PARCELID", "latitude", "longitude", "census_tract"]
        + SOCIO_COLS[1:]
    )
    avail = [c for c in sample_cols if c in df.columns]
    sample = df[avail].dropna(subset=["census_tract"]).head(10)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)
    pd.set_option("display.float_format", "{:.1f}".format)
    print("Sample results (first 10 rows with tract data):")
    print(sample.to_string(index=False))
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted – partial results saved to %s", DEFAULT_OUT)
        sys.exit(0)
    except Exception as exc:                           # noqa: BLE001
        log.error("Fatal: %s", exc, exc_info=True)
        sys.exit(1)
