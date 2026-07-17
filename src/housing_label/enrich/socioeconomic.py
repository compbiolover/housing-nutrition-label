#!/usr/bin/env python3
"""Census ACS socioeconomic data model library for parcel enrichment.

Importable functions that fetch Census ACS5 tract data, geocode parcels to
census tracts, and derive the socioeconomic metrics/index. No batch/CLI runner.

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
  The socioeconomic_index is a NATIONAL percentile score (0–100, 100 = least
  economic stress), scored against the full national distribution of US census
  tracts — household-weighted — from the bundled crosswalk
  (data/socioeconomic.py, built by scripts/build_socio_ref.py). It blends three
  metrics (poverty & housing-cost-burden inverted, income direct) and is NOT a
  within-county rank, so a value means the same thing in Memphis and in Denver.
  The raw three metric columns are still the tract's own ACS values.

  This answers: "How does this neighborhood's economic security compare to every
  census tract in the United States?"

Columns added
-------------
  census_tract             GEOID of the 2020 census tract (11-digit string)
  poverty_rate_pct         % of population below the federal poverty line
  median_household_income  median household income (USD)
  housing_cost_burden_pct  % of households paying ≥ 30 % of income on housing
  cost_burden_owner_pct    same, owner-occupied households only
  cost_burden_renter_pct   same, renter-occupied households only
  socioeconomic_index      0–100 composite (100 = least stressed vs. all US tracts)
"""

from __future__ import annotations

import logging, os, time
import requests, pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

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
DEFAULT_YEAR = 2024   # newest ACS5 vintage known-good at time of writing
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
    tract GEOID with the headline metrics plus the socioeconomic_index (a NATIONAL
    percentile from the bundled crosswalk, not a within-county rank), and the
    vintage actually used.

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
        df.loc[df[col] < ACS_NULL_FLOOR, col] = pd.NA   # float64 col keeps NA as NaN

    # Build the 11-digit tract GEOID from the geography component columns.
    df["census_tract"] = (
        df["state"].str.zfill(2) + df["county"].str.zfill(3) + df["tract"].str.zfill(6)
    )
    return df.set_index("census_tract")


def _compute_socio(df: pd.DataFrame) -> pd.DataFrame:
    """Derive headline ACS metrics; socioeconomic_index is the NATIONAL percentile
    from the bundled crosswalk (data/socioeconomic.py), not a within-county rank."""
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

    # ── National socioeconomic index (bundled, offline) ───────────────────────
    # socioeconomic_index is scored against the FULL NATIONAL distribution of US
    # census tracts (household-weighted), NOT ranked within this county — so a
    # value is comparable across locations (the old within-county rank made a
    # median tract score ~50 in every county). From the bundled crosswalk
    # (data/socioeconomic.py, built by scripts/build_socio_ref.py); tracts absent
    # from it fall back tract -> county, and a national-only fallback (no local
    # data) is left unscored (NaN) rather than filled with a placeholder. The raw
    # metric columns above remain the tract's own ACS values.
    from housing_label.data import socioeconomic as socio_ref

    def _national_idx(geoid: str) -> float:
        r = socio_ref.socio_for_tract(geoid)
        return r["socioeconomic_index"] if r["resolved"] \
            and r["socioeconomic_index"] is not None else float("nan")

    out["socioeconomic_index"] = pd.Series(
        {g: _national_idx(g) for g in out.index}, dtype="float64"
    ).round(1)

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
