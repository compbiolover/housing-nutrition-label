#!/usr/bin/env python3
"""Enrich shelby_parcels_infrastructure.csv with CDC PLACES neighborhood health data.

Usage
-----
  python enrich_health.py                       # all parcels
  python enrich_health.py --limit 10            # test with 10 rows first
  python enrich_health.py --limit 5 --dry-run   # validate + plan, no API calls
  python enrich_health.py --input X.csv --output Y.csv

Data source
-----------
  CDC PLACES: Local Data for Better Health, Census Tract Data (2023 release)
  API  : https://chronicdata.cdc.gov/resource/cwsq-ngmh.json  (Socrata SODA)
  Auth : None – free, public, keyless
  Level: Census tract (2020 vintage), Shelby County TN (FIPS 47157)
  Type : Crude prevalence (% adults 18+)

Tract assignment
----------------
  U.S. Census Geocoder API (geocoding.geo.census.gov) converts each parcel's
  lat/lon to a 2020-vintage census tract GEOID (11-digit string).
  Rate  : 0.2 s sleep between calls (~5 req/s — polite for a public service).
  Resume: existing output is reloaded on re-run; already-geocoded parcels are
          skipped, so interrupted runs can be safely restarted.

Health measures used
--------------------
  LPA     : No leisure-time physical activity (physical inactivity %)
  OBESITY : Obesity among adults (BMI ≥ 30)
  DIABETES: Diagnosed diabetes among adults
  MHLTH   : Frequent mental distress (≥ 14 bad mental-health days/month)
  CASTHMA : Current asthma among adults
  BPHIGH  : High blood pressure among adults
  CHD     : Coronary heart disease among adults

health_index
------------
  For each of the 7 measures, each tract is ranked 0–100 percentile relative
  to ALL Shelby County tracts in the PLACES dataset (not just the parcel
  sample).  Score is inverted so that 100 = lowest / healthiest prevalence.

    score_i = (1 − rank_pct_i) × 100

  health_index = mean of up to 7 individual scores.
  Range: 0–100   |   100 = healthiest relative to all Shelby County tracts.

  This answers: "How does this neighborhood rank for overall health burden
  compared to every other census tract in Shelby County?"

Columns added
-------------
  census_tract            GEOID of the 2020 census tract (11-digit string)
  physical_inactivity_pct % adults with no leisure-time physical activity
  obesity_pct             % adults obese (BMI ≥ 30)
  diabetes_pct            % adults with diagnosed diabetes
  mental_distress_pct     % adults with frequent mental distress
  asthma_pct              % adults with current asthma
  high_bp_pct             % adults with high blood pressure
  chd_pct                 % adults with coronary heart disease
  health_index            0–100 composite (100 = healthiest vs. county peers)
"""

import argparse, logging, pathlib, sys, time
import requests, pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── File paths ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
IN_FILE    = "shelby_parcels_infrastructure.csv"   # chained upstream input
OUT_FILE   = "shelby_parcels_health.csv"


def _resolve(p: str) -> pathlib.Path:
    """Resolve a path, treating bare/relative paths as relative to SCRIPT_DIR."""
    path = pathlib.Path(p)
    return path if path.is_absolute() else (SCRIPT_DIR / path)

# ── Geography ─────────────────────────────────────────────────────────────────
COUNTY_FIPS = "47157"   # Tennessee (47) + Shelby County (157)

# ── API endpoints ─────────────────────────────────────────────────────────────
PLACES_URL   = "https://chronicdata.cdc.gov/resource/cwsq-ngmh.json"
GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"

# ── Request settings ──────────────────────────────────────────────────────────
SLEEP_SEC   = 0.2    # polite delay between geocoder calls (~5 req/s)
TIMEOUT     = 25     # seconds per HTTP call
MAX_RETRIES = 3
BACKOFF     = 2      # exponential back-off multiplier
CHECKPOINT  = 50     # save every N geocoded rows

# ── CDC PLACES measures → output column names ─────────────────────────────────
MEASURE_MAP = {
    "LPA":      "physical_inactivity_pct",
    "OBESITY":  "obesity_pct",
    "DIABETES": "diabetes_pct",
    "MHLTH":    "mental_distress_pct",
    "CASTHMA":  "asthma_pct",
    "BPHIGH":   "high_bp_pct",
    "CHD":      "chd_pct",
}

HEALTH_COLS = [
    "census_tract",
    "physical_inactivity_pct",
    "obesity_pct",
    "diabetes_pct",
    "mental_distress_pct",
    "asthma_pct",
    "high_bp_pct",
    "chd_pct",
    "health_index",
]


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


# ── CDC PLACES data fetch ──────────────────────────────────────────────────────
def fetch_places_data() -> pd.DataFrame:
    """Download and pivot CDC PLACES census-tract health data for Shelby County.

    Returns a DataFrame indexed by locationid (11-digit GEOID) with one column
    per measure (crude prevalence %) plus a pre-computed health_index column.
    The health_index is based on all Shelby County tracts so percentile ranks
    reflect the full county distribution, not just the parcel sample.
    """
    log.info("Fetching CDC PLACES data for Shelby County (FIPS %s) …", COUNTY_FIPS)
    params = {
        "countyfips":      COUNTY_FIPS,
        "datavaluetypeid": "CrdPrv",   # crude prevalence only (consistent type)
        "$select":         "locationid,measureid,data_value,year",
        "$limit":          50000,       # well above the ~200 tracts × 7 measures
    }

    records = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(PLACES_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            records = r.json()
            break
        except Exception as exc:
            log.warning("PLACES API attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"CDC PLACES API unavailable after {MAX_RETRIES} attempts"
                ) from exc
            time.sleep(BACKOFF ** attempt)

    log.info("  %d raw records received from PLACES API", len(records))

    df = pd.DataFrame(records)
    df["data_value"] = pd.to_numeric(df["data_value"], errors="coerce")
    df["year"]       = pd.to_numeric(df["year"],        errors="coerce")

    # Keep only the measures we care about
    df = df[df["measureid"].isin(MEASURE_MAP)].copy()
    if df.empty:
        raise RuntimeError(
            "No matching CDC PLACES measures found for Shelby County. "
            "Check that the dataset ID (cwsq-ngmh) is still current."
        )

    # When multiple data years are present, keep the most recent per tract+measure
    df = df.sort_values("year", ascending=False)
    df = df.drop_duplicates(subset=["locationid", "measureid"], keep="first")

    # Pivot: rows = tract GEOID, columns = measure ID
    wide = df.pivot_table(
        index="locationid",
        columns="measureid",
        values="data_value",
        aggfunc="first",
    )
    wide.columns.name = None
    wide = wide.rename(columns=MEASURE_MAP)

    # Retain only the columns that came through (guard against suppressed measures)
    avail_cols = [c for c in MEASURE_MAP.values() if c in wide.columns]
    wide = wide[avail_cols].copy()

    log.info(
        "  Pivoted to %d tracts × %d measures  (measures: %s)",
        len(wide), len(avail_cols), ", ".join(avail_cols),
    )

    # ── Percentile scores (computed across all county tracts) ─────────────────
    # rank(pct=True) → 0–1 where 1.0 = highest prevalence (= worst health).
    # score = (1 − rank_pct) × 100  so that 100 = lowest/healthiest prevalence.
    score_cols = []
    for col in avail_cols:
        rank_pct = wide[col].rank(pct=True, na_option="keep")
        wide[f"_score_{col}"] = ((1.0 - rank_pct) * 100.0).round(1)
        score_cols.append(f"_score_{col}")

    wide["health_index"] = wide[score_cols].mean(axis=1).round(1)
    wide = wide.drop(columns=score_cols)

    return wide


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
        except Exception as exc:
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


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich Shelby County parcels with CDC PLACES health data."
    )
    parser.add_argument(
        "--input", default=IN_FILE,
        help=f"Input parcels CSV (default: {IN_FILE}).",
    )
    parser.add_argument(
        "--output", default=OUT_FILE,
        help=f"Output CSV (default: {OUT_FILE}).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N rows (for testing).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Load + validate only; make no API calls and write nothing.",
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
    input_rows = len(df)

    if "latitude" not in df.columns or "longitude" not in df.columns:
        log.error("Input must have 'latitude' and 'longitude' columns.")
        sys.exit(1)

    # ── Resume: reload any previously geocoded rows ───────────────────────────
    if out_path.exists():
        log.info("Found existing output — loading for resume: %s", out_path)
        prev = pd.read_csv(out_path)
        if "census_tract" in prev.columns:
            df["census_tract"] = prev["census_tract"].apply(_clean_tract)
        else:
            df["census_tract"] = None
        already = df["census_tract"].notna().sum()
        log.info("  %d rows already have a census tract assigned.", already)
    else:
        df["census_tract"] = None

    if args.limit:
        df = df.head(args.limit)
        log.info("--limit %d applied.", args.limit)
        input_rows = len(df)

    # ── Dry run: report the plan, then exit before any network I/O ────────────
    if args.dry_run:
        need_geocode = int(
            (
                df["census_tract"].isna()
                & df["latitude"].notna()
                & df["longitude"].notna()
            ).sum()
        )
        log.info("DRY RUN — no API calls, no checkpoints, no output written.")
        log.info("  Input            : %s", in_path)
        log.info("  Output (planned) : %s", out_path)
        log.info("  Rows to process  : %d", len(df))
        log.info("  Need geocoding   : %d parcels", need_geocode)
        return

    # ── Step 1: Download CDC PLACES tract-level data ──────────────────────────
    tract_health = fetch_places_data()

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

    # ── Step 3: Join PLACES health data to parcels ────────────────────────────
    log.info("Joining health data from %d tracts …", len(tract_health))

    # Normalise census_tract to clean 11-digit strings for a reliable merge key
    df["census_tract"] = df["census_tract"].apply(_clean_tract)

    # Drop any stale health columns from a previous run before re-joining
    stale = [c for c in HEALTH_COLS[1:] if c in df.columns]
    if stale:
        df = df.drop(columns=stale)

    tract_df = (
        tract_health
        .reset_index()
        .rename(columns={"locationid": "census_tract"})
    )
    tract_df["census_tract"] = tract_df["census_tract"].apply(_clean_tract)

    df = df.merge(tract_df, on="census_tract", how="left")

    # ── Save ──────────────────────────────────────────────────────────────────
    df.to_csv(out_path, index=False)
    log.info("Saved → %s", out_path)
    log.info("wrote %d rows × %d cols", df.shape[0], df.shape[1])
    if len(df) != input_rows:
        log.warning(
            "Output rows (%d) != input rows (%d) — row count changed during enrichment.",
            len(df), input_rows,
        )

    # ── Summary ───────────────────────────────────────────────────────────────
    total          = len(df)
    tract_assigned = df["census_tract"].notna().sum()
    health_data    = df["health_index"].notna().sum()
    n_tracts       = df["census_tract"].nunique()
    measure_cols   = [c for c in MEASURE_MAP.values() if c in df.columns]
    hi             = df["health_index"].dropna()
    w = 46

    # Identify out-of-county tracts (shouldn't start with COUNTY_FIPS)
    out_county = (
        df["census_tract"]
        .dropna()
        .loc[~df["census_tract"].dropna().str.startswith(COUNTY_FIPS)]
        .count()
    )

    print("\n╔══ HEALTH ENRICHMENT SUMMARY ══════════════════════════════════════╗")
    print(f"║ Total parcels                : {total:<{w}}║")
    print(f"║ Census tracts assigned       : {tract_assigned:<{w}}║")
    print(f"║ Unique tracts found          : {n_tracts:<{w}}║")
    if out_county > 0:
        print(f"║ Parcels outside Shelby Co.   : {out_county:<{w}}║")
    print(f"║ Parcels with health data     : {health_data:<{w}}║")
    print(f"║ Source                       : {'CDC PLACES 2023 (crude prevalence, adults 18+)':<{w}}║")
    print(f"║ Geography                    : {'Census tract · Shelby County TN (FIPS 47157)':<{w}}║")

    if not hi.empty:
        spread = hi.max() - hi.min()
        print("║ ── health_index (0–100, higher = healthier vs. county) ──────────── ║")
        print(f"║   min    : {hi.min():<{w-2}.1f}║")
        print(f"║   p25    : {hi.quantile(0.25):<{w-2}.1f}║")
        print(f"║   median : {hi.median():<{w-2}.1f}║")
        print(f"║   p75    : {hi.quantile(0.75):<{w-2}.1f}║")
        print(f"║   max    : {hi.max():<{w-2}.1f}║")
        print(f"║   spread : {spread:<{w-2}.1f}  (max − min; > 30 = clear gradient)║")

    print("║ ── Measure medians across all matched parcels ───────────────────── ║")
    for col in measure_cols:
        med   = df[col].median()
        label = col.replace("_pct", "").replace("_", " ")
        print(f"║   {label:<24}: {med:>5.1f}%{'':>17}║")

    # Tract-level extremes (deduplicated)
    if not hi.empty:
        tract_summary = (
            df[["census_tract", "health_index"] + measure_cols]
            .dropna(subset=["health_index"])
            .drop_duplicates("census_tract")
            .sort_values("health_index", ascending=False)
        )

        print("║ ── Top 5 healthiest tracts ──────────────────────────────────────── ║")
        for _, r in tract_summary.head(5).iterrows():
            obesity = r.get("obesity_pct", float("nan"))
            diab    = r.get("diabetes_pct", float("nan"))
            fmt     = f"tract {r['census_tract']}  idx={r['health_index']:.0f}  ob={obesity:.0f}%  diab={diab:.0f}%"
            print(f"║   {fmt:<{w+1}}║")

        print("║ ── Bottom 5 least-healthy tracts ────────────────────────────────── ║")
        for _, r in tract_summary.tail(5).iterrows():
            obesity = r.get("obesity_pct", float("nan"))
            diab    = r.get("diabetes_pct", float("nan"))
            fmt     = f"tract {r['census_tract']}  idx={r['health_index']:.0f}  ob={obesity:.0f}%  diab={diab:.0f}%"
            print(f"║   {fmt:<{w+1}}║")

    print(f"║ New columns added            : {len(HEALTH_COLS):<{w}}║")
    print(f"║ Output                       : {out_path.name:<{w}}║")
    print("╚═══════════════════════════════════════════════════════════════════╝\n")

    # ── Sample rows ───────────────────────────────────────────────────────────
    sample_cols = (
        ["PARCELID", "latitude", "longitude", "census_tract"]
        + measure_cols
        + ["health_index"]
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
        log.info("Interrupted – any partial results were saved at the last checkpoint.")
        sys.exit(0)
    except Exception as exc:
        log.error("Fatal: %s", exc, exc_info=True)
        sys.exit(1)
