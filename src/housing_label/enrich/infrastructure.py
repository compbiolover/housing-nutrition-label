#!/usr/bin/env python3
"""Enrich shelby_parcels_energy.csv with modeled infrastructure cost burden.

Usage
-----
  python enrich_infrastructure.py              # all parcels
  python enrich_infrastructure.py --limit 10  # test with 10 rows first
  python enrich_infrastructure.py --dry-run    # validate + plan, no write

Methodology: Density-Adjusted Cost Allocation
----------------------------------------------
Urban planning literature consistently shows that low-density sprawl costs
municipalities 2–3x more per household than compact development, driven by
longer road/pipe networks, greater fire/police patrol area, and reduced
transit efficiency.

Primary calibration sources
  - Halifax Regional Municipality, "The Cost of Sprawl" (2004, 2020 update):
      Published per-household cost curves for roads, water/sewer, fire, police
      across density quintiles. Values are the most-cited North American
      benchmark for density-cost relationships.
  - Strong Towns, "The Real Math of Sprawl" (2020): calibration overlay
      applied to Halifax curves for Sun Belt / car-dependent city context,
      roughly matching Memphis's development pattern.
  - City of Memphis FY2026 Adopted Budget ($883M, ~253,000 households):
      Implies ~$3,490/household blended baseline for all general-fund services.
      Source: Memphis City Council, FY2026 Budget Book (April 2025).
  - Memphis FY2026 Budget detail:
      Police  : 42% of $350M personnel = ~$147M → ~$581/household
      Fire    : 34% of $350M personnel = ~$119M → ~$470/household
      Roads   : $73.5M / 4yr = ~$18.4M/yr → ~$73/household capital allocation
                (operating roads budget estimated ~$40M/yr additional)
      Solid Waste: $42/month fee × 12 = $504/household (Memphis-specific flat fee)
      Water/Sewer: MLGW separate utility; $2.3B budget, ~140,000 sewer connections
                  → ~$1,640/connection/yr gross; density adjustment applied.
  - Victoria Transport Policy Institute, "Land Use Impacts on Transport" (2019):
      Fire response cost distance multipliers.

Memphis-specific calibration notes
  Memphis is ~300 sq mi with ~620,000 residents ≈ 2,067 persons/sq mi overall.
  This is roughly 1.0–1.5 DU/acre at the city average — classic Sun Belt sprawl.
  The cost curves below are calibrated to this context; they are NOT generic
  national averages. Comments flag where national benchmarks are used as-is.

IMPORTANT: This is a modeled estimate, not an accounting audit. All cost
components are approximations intended for relative comparison across parcels.
Absolute dollar values carry ±30% uncertainty. Fiscal balance figures assume
a single dwelling unit per parcel (DWELDAT-type records); multi-unit parcels
are not adjusted in this pilot.

Columns added
-------------
  lot_density_du_acre       DU/acre (1 DU assumed per parcel)
  distance_to_core_mi       Haversine miles from parcel to Memphis city center
  infra_cost_roads          Road maintenance & capital cost ($/yr)
  infra_cost_water_sewer    Water/sewer pipe & treatment cost ($/yr)
  infra_cost_fire           Fire/EMS service cost ($/yr)
  infra_cost_police         Police patrol cost ($/yr)
  infra_cost_sanitation     Solid waste collection cost ($/yr)
  infra_cost_parks          Parks & other general services cost ($/yr)
  est_annual_infra_cost     Sum of all cost components ($/yr)
  est_property_tax          Estimated annual property tax revenue ($/yr)
  fiscal_balance            est_property_tax − est_annual_infra_cost ($/yr)
  fiscal_ratio              est_property_tax / est_annual_infra_cost
  infra_burden_rating       Categorical rating (net contributor / break-even /
                            minor burden / major burden)
"""

from __future__ import annotations

import argparse
import logging
import math
import pathlib
import sys

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── File paths ─────────────────────────────────────────────────────────────────
# Script lives in the git worktree; data files live in the main project directory.
# Walk up until we find shelby_parcels_sample.csv (handles both worktree and normal checkout).
def _find_project_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve().parent
    # Walk up to 5 levels to find the directory containing shelby_parcels_sample.csv.
    # Handles both normal checkout and git worktree (nested under .claude/worktrees/).
    candidate = here
    for _ in range(5):
        if (candidate / "shelby_parcels_sample.csv").exists():
            return candidate
        candidate = candidate.parent
    return here   # fallback — will produce a clear FileNotFoundError

PROJECT_DIR = _find_project_root()
IN_FILE  = "shelby_parcels_energy.csv"
OUT_FILE = "shelby_parcels_infrastructure.csv"

REQUIRED_COLUMNS = ["latitude", "longitude", "CALC_ACRE"]


def _resolve_path(path_str: str) -> pathlib.Path:
    """Resolve a path; bare (non-absolute, no dir) names are placed in PROJECT_DIR."""
    path = pathlib.Path(path_str)
    if path.is_absolute() or path.parent != pathlib.Path("."):
        return path
    return PROJECT_DIR / path

# ── Memphis city center (Main St & Beale St intersection, downtown core) ───────
# Used as proxy for proximity to high-density urban services & fire stations.
# Source: Google Maps, Memphis, TN 38103
MEMPHIS_CORE_LAT = 35.1495
MEMPHIS_CORE_LON = -90.0490

# ── Property tax parameters (Memphis / Shelby County, FY2026) ─────────────────
# Memphis city property tax rate: $3.19 per $100 of assessed value
# Source: City of Memphis FY2026 Budget Book, Revenue section
# Note: Shelby County levies an additional ~$2.71/$100 not included here;
#       this model estimates only the CITY portion of the tax.
CITY_TAX_RATE           = 0.0319    # per $1 of assessed value
RESIDENTIAL_ASSESS_RATIO = 0.25     # 25% of appraised value; TN state law (TCA 67-5-502)

# ── Road cost vs density (continuous, $/household/yr) ─────────────────────────
# Source: Halifax Regional Municipality "Cost of Sprawl" (2004, updated 2020);
#         Strong Towns Sun Belt calibration applied (1.15x multiplier for
#         lower-density suburban road network typical of Memphis metro).
# Covers: pavement maintenance, reconstruction capital, stormwater drainage,
#         sidewalks/curb, traffic signals — all amortized to annual $/HH.
# These are calibrated to Memphis; NOT simple national averages.
#
# Anchor points are the published Halifax band costs placed at each band's
# geometric-mean density, then EXTENDED past 12 DU/acre (24, 48) by continuing
# the curve's slope (≈ density^-0.7). Cost is log-log interpolated between
# anchors and clamped flat outside the range (interp_cost). Linear road network
# is shared per-frontage, so per-household cost keeps falling with density rather
# than flooring at 12 DU/acre — small-multiplex infill (a quadplex ≈ 16 DU/acre)
# is squarely in the responsive range, not pinned at the old floor.
ROAD_COST_BY_DENSITY = [
    # (du_acre, $/HH/yr)
    (0.7,  2_400),   # rural/estate
    (1.73, 1_800),   # suburban sprawl
    (4.24, 1_200),   # suburban
    (8.49,   700),   # urban
    (12.0,   400),   # dense urban (published floor anchor)
    (24.0,   250),   # very dense infill (extended)
    (48.0,   150),   # mid-rise / compact urban (extended)
]

# ── Water/sewer cost vs density (continuous, $/household/yr) ───────────────────
# Source: Halifax "Cost of Sprawl" (2004/2020); MLGW sewer/stormwater capital
#         backlog (~$1B) amortized over 30 yr ÷ 140,000 connections adds ~$238/yr.
# Covers: water distribution pipe, sewer collection pipe, treatment plant
#         operations — all allocated per household by pipe-length-per-HH model.
# NOTE: MLGW is a separate utility from the City; these costs are included
#       because they represent public infrastructure burden even if not in the
#       general fund. Flag this if comparing to city-budget-only analyses.
# Same anchor/interpolation scheme as roads (band cost at geometric-mean density,
# extended past 12 DU/acre); the distribution/collection mains are shared linear
# infrastructure, so per-household cost keeps amortizing with density.
WATER_SEWER_COST_BY_DENSITY = [
    (0.7,  1_500),
    (1.73, 1_100),
    (4.24,   800),
    (8.49,   500),
    (12.0,   350),
    (24.0,   220),
    (48.0,   135),
]

# ── Fire/EMS base cost ($/household/yr) ───────────────────────────────────────
# Source: Memphis FY2026 budget; Fire/EMS = ~$119M total, ~253,000 HH → $470/HH.
# Rounded up to $800 to include capital (apparatus, stations) and mutual-aid costs
# sourced from: VFIS "Cost of Fire Protection" (2022), national avg $800–$1,200/HH.
# Memphis-calibrated base = $800 (between budget implied and national capital-inclusive).
FIRE_BASE_COST = 800   # $/HH/yr; Memphis-calibrated

# Distance multipliers for fire cost:
#   Parcels >10 mi from core are beyond many Memphis fire station service zones
#   → longer response times → higher effective cost per call served.
#   Parcels <3 mi from core are near multiple downtown stations → lower cost.
# Source: VTPI "Land Use Impacts on Transport" Table 5.4.2 (2019);
#         NFPA "Fire Protection Coverage" distance-cost relationship.
FIRE_DIST_MULTIPLIER_INNER = 0.85   # <3 mi from core
FIRE_DIST_MULTIPLIER_MID   = 1.00   # 3–10 mi from core
FIRE_DIST_MULTIPLIER_OUTER = 1.30   # >10 mi from core

FIRE_INNER_THRESHOLD_MI = 3.0
FIRE_OUTER_THRESHOLD_MI = 10.0

# ── Police cost by density ($/household/yr) ───────────────────────────────────
# Source: Memphis FY2026 budget; Police = ~$147M, ~253,000 HH → $581/HH.
# Rounded to $1,200 to include capital (vehicles, equipment, facilities).
# Low-density areas require more patrol-miles per call, increasing cost/HH.
# National benchmark: ICMA "Cost of Services" survey median $900–$1,400/HH.
# Memphis-calibrated base = $1,200 (higher than budget ratio; capital-inclusive).
POLICE_BASE_COST = 1_200   # $/HH/yr; Memphis-calibrated

POLICE_DENSITY_MULTIPLIERS = [
    # (max_du_acre, multiplier)
    (3.0,  1.20),   # <3 DU/acre: large patrol area per officer
    (8.0,  1.00),   # 3–8 DU/acre: moderate density
    (16.0, 0.80),   # 8–16 DU/acre: compact, efficient patrol
    (float("inf"), 0.70),  # 16+ DU/acre: dense infill, most efficient patrol
]

# ── Sanitation (solid waste) ──────────────────────────────────────────────────
# Source: City of Memphis Solid Waste fee = $42/month (FY2026, Memphis-specific).
# Applied as flat rate; does not vary by density in Memphis's flat-fee system.
SANITATION_COST = 504   # $/HH/yr = $42 × 12; MEMPHIS-SPECIFIC flat fee

# ── Parks & other general services ───────────────────────────────────────────
# Source: Memphis FY2026 budget; Parks + libraries + general govt = ~$75M
#         ÷ 253,000 HH ≈ $296/HH. Rounded to $300.
# Applied as flat rate (park access is not strongly density-dependent in
# Memphis's distributed park system; national benchmarks also show ~flat).
# National benchmark: Trust for Public Land "City Park Facts" (2023) avg $280–$350/HH.
PARKS_OTHER_COST = 300   # $/HH/yr; Memphis-calibrated (flat)

# ── Fiscal balance rating thresholds (fiscal_ratio) ──────────────────────────
# Interpretation: fiscal_ratio = property_tax_revenue / infra_cost
#   >1.0  = property generates more tax than it costs to serve (net contributor)
#   0.75–1.0  = roughly break-even (within ±25% of cost recovery)
#   0.40–0.75 = minor burden (city subsidizes 25–60% of cost)
#   <0.40     = major burden (city subsidizes 60%+ of cost)
# Thresholds calibrated by inspection of pilot distribution; intended for
# relative comparison, not absolute policy determination.
RATING_THRESHOLDS = [
    (1.00, "net contributor"),
    (0.75, "break-even"),
    (0.40, "minor burden"),
    (0.00, "major burden"),
]


# ══════════════════════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════════════════════

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in miles between two lat/lon points."""
    R_MILES = 3_958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R_MILES * math.asin(math.sqrt(a))


def interp_cost(density: float, anchors: list[tuple]) -> float:
    """Log-log linear interpolation of per-household cost vs density.

    ``anchors`` is an ascending list of (du_acre, cost) points. Between anchors,
    both axes are interpolated in log space (cost falls smoothly as a power of
    density); outside the anchor range the cost is clamped flat to the nearest
    endpoint. A continuous curve (vs the old step tiers) means every added unit
    moves the cost, and extending the anchors past 12 DU/acre keeps crediting
    denser infill instead of flooring at a triplex.
    """
    if density <= anchors[0][0]:
        return float(anchors[0][1])
    if density >= anchors[-1][0]:
        return float(anchors[-1][1])
    for (d_lo, c_lo), (d_hi, c_hi) in zip(anchors, anchors[1:]):
        if d_lo <= density <= d_hi:
            t = (math.log(density) - math.log(d_lo)) / (math.log(d_hi) - math.log(d_lo))
            return float(math.exp(math.log(c_lo) + t * (math.log(c_hi) - math.log(c_lo))))
    return float(anchors[-1][1])


def police_cost(base: float, density: float) -> float:
    """Apply density multiplier to base police cost."""
    for max_du, mult in POLICE_DENSITY_MULTIPLIERS:
        if density < max_du:
            return base * mult
    return base * POLICE_DENSITY_MULTIPLIERS[-1][1]


def fiscal_rating(ratio: float) -> str:
    """Map fiscal_ratio to human-readable burden rating."""
    for threshold, label in RATING_THRESHOLDS:
        if ratio >= threshold:
            return label
    return "major burden"


def _fire_dist_multiplier(dist_mi: float) -> float:
    """Return the correct fire multiplier for a given distance."""
    if dist_mi < FIRE_INNER_THRESHOLD_MI:
        return FIRE_DIST_MULTIPLIER_INNER
    if dist_mi < FIRE_OUTER_THRESHOLD_MI:
        return FIRE_DIST_MULTIPLIER_MID
    return FIRE_DIST_MULTIPLIER_OUTER


# ══════════════════════════════════════════════════════════════════════════════
# Row-level enrichment
# ══════════════════════════════════════════════════════════════════════════════

def enrich_row(row: pd.Series, *,
               core_lat: float = MEMPHIS_CORE_LAT,
               core_lon: float = MEMPHIS_CORE_LON,
               assess_ratio: float = RESIDENTIAL_ASSESS_RATIO,
               tax_rate: float = CITY_TAX_RATE,
               in_urban_area: bool | None = None,
               cost_multipliers: dict | None = None) -> pd.Series:
    """Compute all infrastructure cost fields for a single parcel row.

    Memphis defaults reproduce the Shelby pilot. For other locations the simulator
    passes a national-average parameterization: a national effective property-tax
    rate (``assess_ratio`` × ``tax_rate``) and, when ``in_urban_area`` is given,
    an urban/rural fire multiplier in place of distance-to-the-Memphis-core.

    ``cost_multipliers`` optionally recalibrates the per-household cost *levels* to
    a specific county's local-government spending (from the Census of Governments
    crosswalk, ``data/govfinance.py``): a dict with any of the keys ``roads``,
    ``water_sewer``, ``fire``, ``police``, ``sanitation``, ``parks``, each scaling
    that component. The Memphis-calibrated curves give the density *shape*; these
    multipliers give the local *level* (1.0 = Shelby pilot, the default).
    """
    mult = cost_multipliers or {}

    # ── Density metric ─────────────────────────────────────────────────────────
    acres = row["CALC_ACRE"]
    # Guard against zero/negative acres (data error); treat as very small lot
    if pd.isna(acres) or acres <= 0:
        acres = 0.01
    # Assuming 1 dwelling unit per parcel (single-family / DWELDAT record)
    lot_density = 1.0 / acres   # DU/acre

    # ── Fire service multiplier: urban-area flag (national) or core distance ────
    dist_mi = float("nan")
    if in_urban_area is not None:
        fire_mult = FIRE_DIST_MULTIPLIER_MID if in_urban_area else FIRE_DIST_MULTIPLIER_OUTER
    else:
        lat, lon = row["latitude"], row["longitude"]
        dist_mi = (5.0 if pd.isna(lat) or pd.isna(lon)
                   else haversine_miles(lat, lon, core_lat, core_lon))
        fire_mult = _fire_dist_multiplier(dist_mi)

    # ── Cost components ────────────────────────────────────────────────────────
    # Each density/urban-shape cost is scaled by the county's local-spending
    # multiplier (default 1.0 = Shelby pilot calibration).
    cost_roads       = interp_cost(lot_density, ROAD_COST_BY_DENSITY) * mult.get("roads", 1.0)
    cost_water_sewer = interp_cost(lot_density, WATER_SEWER_COST_BY_DENSITY) * mult.get("water_sewer", 1.0)
    cost_fire        = FIRE_BASE_COST * fire_mult * mult.get("fire", 1.0)
    cost_police      = police_cost(POLICE_BASE_COST, lot_density) * mult.get("police", 1.0)
    cost_sanitation  = float(SANITATION_COST) * mult.get("sanitation", 1.0)
    cost_parks       = float(PARKS_OTHER_COST) * mult.get("parks", 1.0)

    total_infra = (
        cost_roads + cost_water_sewer + cost_fire
        + cost_police + cost_sanitation + cost_parks
    )

    # ── Property tax revenue estimate ──────────────────────────────────────────
    appraised = row["RTOTAPR"]
    if pd.isna(appraised) or appraised <= 0:
        appraised = 0.0
    est_tax = appraised * assess_ratio * tax_rate

    # ── Fiscal balance ─────────────────────────────────────────────────────────
    fiscal_bal = est_tax - total_infra
    if total_infra > 0:
        ratio = est_tax / total_infra
    else:
        ratio = float("nan")

    rating = fiscal_rating(ratio) if not math.isnan(ratio) else "unknown"

    return pd.Series({
        "lot_density_du_acre":   round(lot_density, 4),
        "distance_to_core_mi":   round(dist_mi, 3),
        "infra_cost_roads":      round(cost_roads, 2),
        "infra_cost_water_sewer": round(cost_water_sewer, 2),
        "infra_cost_fire":       round(cost_fire, 2),
        "infra_cost_police":     round(cost_police, 2),
        "infra_cost_sanitation": round(cost_sanitation, 2),
        "infra_cost_parks":      round(cost_parks, 2),
        "est_annual_infra_cost": round(total_infra, 2),
        "est_property_tax":      round(est_tax, 2),
        "fiscal_balance":        round(fiscal_bal, 2),
        "fiscal_ratio":          round(ratio, 4),
        "infra_burden_rating":   rating,
    })


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

ADDED_COLUMNS = [
    "lot_density_du_acre", "distance_to_core_mi",
    "infra_cost_roads", "infra_cost_water_sewer",
    "infra_cost_fire", "infra_cost_police",
    "infra_cost_sanitation", "infra_cost_parks",
    "est_annual_infra_cost", "est_property_tax",
    "fiscal_balance", "fiscal_ratio", "infra_burden_rating",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich parcels with infrastructure cost burden"
    )
    parser.add_argument("--input", default=IN_FILE,
                        help="Input CSV (default: %(default)s)")
    parser.add_argument("--output", default=OUT_FILE,
                        help="Output CSV (default: %(default)s)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only N rows (testing)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate and report plan without writing output")
    args = parser.parse_args()

    in_path = _resolve_path(args.input)
    out_path = _resolve_path(args.output)

    # ── Input validation ───────────────────────────────────────────────────────
    if not in_path.exists():
        log.error("Input file does not exist: %s", in_path)
        sys.exit(1)

    log.info("Reading %s", in_path)
    df = pd.read_csv(in_path)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        log.error("Input missing required columns: %s", missing)
        sys.exit(1)

    input_rows = len(df)
    if args.limit:
        df = df.head(args.limit)
        log.info("Limiting to %d rows", args.limit)
    log.info("Loaded %d parcels", len(df))

    # ── Dry-run: report plan and exit without writing ───────────────────────────
    if args.dry_run:
        log.info("DRY RUN — no output will be written")
        log.info("  Input:   %s", in_path)
        log.info("  Output:  %s", out_path)
        log.info("  Rows to enrich: %d", len(df))
        log.info("  Columns that would be added: %s", ADDED_COLUMNS)
        return

    log.info("Computing infrastructure cost fields …")
    enriched = df.apply(enrich_row, axis=1)
    df = pd.concat([df, enriched], axis=1)

    log.info("Writing %s", out_path)
    df.to_csv(out_path, index=False)
    log.info("wrote %d rows × %d cols", len(df), df.shape[1])
    if args.limit is None and len(df) != input_rows:
        log.warning("Output rows (%d) != input rows (%d)", len(df), input_rows)

    # ── Summary report ─────────────────────────────────────────────────────────
    print("\n" + "═" * 65)
    print("INFRASTRUCTURE BURDEN SUMMARY — Shelby County Pilot (n={:,})".format(len(df)))
    print("═" * 65)

    print("\n── Infrastructure cost distribution ($/household/yr) ──")
    cost_cols = [
        "infra_cost_roads", "infra_cost_water_sewer",
        "infra_cost_fire", "infra_cost_police",
        "infra_cost_sanitation", "infra_cost_parks",
        "est_annual_infra_cost",
    ]
    stats = df[cost_cols].describe(percentiles=[0.25, 0.50, 0.75]).T[
        ["mean", "25%", "50%", "75%", "min", "max"]
    ].round(0)
    print(stats.to_string())

    print("\n── Property tax vs infrastructure cost ──")
    print(f"  Mean est. property tax:   ${df['est_property_tax'].mean():,.0f}/yr")
    print(f"  Mean est. infra cost:     ${df['est_annual_infra_cost'].mean():,.0f}/yr")
    print(f"  Mean fiscal balance:      ${df['fiscal_balance'].mean():,.0f}/yr")
    print(f"  Median fiscal ratio:       {df['fiscal_ratio'].median():.2f}")

    print("\n── Fiscal burden rating distribution ──")
    rating_counts = df["infra_burden_rating"].value_counts()
    for label, count in rating_counts.items():
        pct = 100 * count / len(df)
        print(f"  {label:<20s}: {count:4d}  ({pct:.1f}%)")

    net_contrib = (df["infra_burden_rating"] == "net contributor").sum()
    print(f"\n  Net contributors: {net_contrib:,} of {len(df):,} parcels "
          f"({100*net_contrib/len(df):.1f}%)")

    print("\n── Density distribution ──")
    density_bins = [0, 1, 3, 6, 12, float("inf")]
    density_labels = ["<1 DU/ac (rural)", "1–3 (sprawl)", "3–6 (suburban)",
                      "6–12 (urban)", "12+ (dense)"]
    df["_density_bin"] = pd.cut(
        df["lot_density_du_acre"], bins=density_bins, labels=density_labels, right=False
    )
    for label, count in df["_density_bin"].value_counts().sort_index().items():
        pct = 100 * count / len(df)
        print(f"  {label:<22s}: {count:4d}  ({pct:.1f}%)")
    df.drop(columns=["_density_bin"], inplace=True)

    print("\n── 5 illustrative parcels (spanning density range) ──")
    sample_cols = [
        "PARCELID", "CALC_ACRE", "lot_density_du_acre", "distance_to_core_mi",
        "est_annual_infra_cost", "est_property_tax", "fiscal_ratio",
        "infra_burden_rating",
    ]
    # pick one from each broad density tier
    examples = []
    for lo, hi in [(0, 1), (1, 3), (3, 6), (6, 12), (12, 9999)]:
        subset = df[
            (df["lot_density_du_acre"] >= lo) & (df["lot_density_du_acre"] < hi)
        ]
        if not subset.empty:
            examples.append(subset.iloc[len(subset) // 2])  # median-ish row

    example_df = pd.DataFrame(examples)[sample_cols].reset_index(drop=True)
    example_df["CALC_ACRE"] = example_df["CALC_ACRE"].round(3)
    example_df["lot_density_du_acre"] = example_df["lot_density_du_acre"].round(2)
    example_df["distance_to_core_mi"] = example_df["distance_to_core_mi"].round(1)
    example_df["est_annual_infra_cost"] = example_df["est_annual_infra_cost"].apply(
        lambda x: f"${x:,.0f}"
    )
    example_df["est_property_tax"] = example_df["est_property_tax"].apply(
        lambda x: f"${x:,.0f}"
    )
    example_df["fiscal_ratio"] = example_df["fiscal_ratio"].round(2)
    print(example_df.to_string(index=False))
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
        sys.exit(0)
    except Exception:
        log.error("Unhandled error", exc_info=True)
        sys.exit(1)
