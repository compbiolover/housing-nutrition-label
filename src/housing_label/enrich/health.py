#!/usr/bin/env python3
"""CDC PLACES neighborhood-health model library.

Fetches and scores CDC PLACES census-tract health data and geocodes parcels to
tracts for the health dimension. Importable functions only; no batch runner.

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
  Each tract's health_index is a NATIONAL percentile score (0–100, 100 = lowest
  chronic-disease burden), scored against the full national distribution of US
  census tracts — population-weighted — from the bundled crosswalk
  (data/health.py, built by scripts/build_health_ref.py). It is NOT a
  within-county rank, so a value means the same thing in Memphis and in Denver.
  The raw 7 measure columns are still the tract's own CDC PLACES prevalences.

  This answers: "How does this neighborhood's overall health burden compare to
  every census tract in the United States?"

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
  health_index            0–100 composite (100 = healthiest vs. all US tracts)
"""

from __future__ import annotations

import logging, time
import requests, pandas as pd

# Module logger only — no logging.basicConfig() at import time (library code).
log = logging.getLogger(__name__)

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
def fetch_places_data(county_fips: str = COUNTY_FIPS) -> pd.DataFrame:
    """Download and pivot CDC PLACES census-tract health data for a county.

    Returns a DataFrame indexed by locationid (11-digit GEOID) with one column
    per measure (crude prevalence %) plus a health_index column. The health_index
    is a NATIONAL percentile score from the bundled crosswalk (data/health.py) —
    comparable across locations — not a within-county rank.

    `county_fips` is the 5-digit state+county GEOID (default: Shelby County).
    """
    log.info("Fetching CDC PLACES data for county FIPS %s …", county_fips)
    params = {
        "countyfips":      county_fips,
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

    return compute_health_index(records, county_fips)


def compute_health_index(records: list, county_fips: str | None = None) -> pd.DataFrame:
    """Pivot raw PLACES records to a tract × measure frame with a health_index.

    Split out from ``fetch_places_data`` (the network half) so the composite —
    the part with the actual scoring logic — is unit-testable offline. ``records``
    is the CDC PLACES JSON list (dicts with locationid/measureid/data_value/year).
    ``county_fips`` (optional) is used only to make the empty-input error message
    accurate for whichever county was queried. Returns a DataFrame indexed by
    locationid (11-digit GEOID) with one crude-prevalence column per measure plus
    the NATIONAL-percentile ``health_index`` (from the bundled crosswalk, not a
    within-county rank).
    """
    where = f" for county FIPS {county_fips}" if county_fips else ""
    df = pd.DataFrame(records)
    # An empty (or malformed) response yields a column-less frame; guard before
    # indexing so it raises a clear RuntimeError instead of a bare KeyError.
    required = {"data_value", "year", "measureid", "locationid"}
    if df.empty or not required.issubset(df.columns):
        raise RuntimeError(
            f"No CDC PLACES records returned{where}. "
            "Check that the dataset ID (cwsq-ngmh) is still current."
        )
    df["data_value"] = pd.to_numeric(df["data_value"], errors="coerce")
    df["year"]       = pd.to_numeric(df["year"],        errors="coerce")

    # Keep only the measures we care about
    df = df[df["measureid"].isin(MEASURE_MAP)].copy()
    if df.empty:
        raise RuntimeError(
            f"No matching CDC PLACES measures found{where}. "
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

    # ── National health index (bundled, offline) ──────────────────────────────
    # Each tract's health_index is scored against the FULL NATIONAL distribution
    # of US census tracts (population-weighted), NOT ranked within this county —
    # so a value is comparable across locations (the old within-county rank made a
    # median tract score ~50 in every county). The national score comes from the
    # bundled crosswalk (data/health.py, built by scripts/build_health_ref.py);
    # tracts absent from it fall back tract -> county, and a national-only fallback
    # (no local data) is left unscored (NaN) rather than filled with a placeholder.
    from housing_label.data import health as health_ref

    def _national_idx(geoid: str) -> float:
        r = health_ref.health_for_tract(geoid)
        return r["health_index"] if r["resolved"] and r["health_index"] is not None \
            else float("nan")

    wide["health_index"] = pd.Series(
        {g: _national_idx(g) for g in wide.index}, dtype="float64"
    ).round(1)

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
