#!/usr/bin/env python3
"""Enrich shelby_parcels_tornado.csv with USGS seismic hazard data.

Usage
-----
  python enrich_seismic.py              # all 1 000 parcels
  python enrich_seismic.py --limit 10  # test with 10 rows first

Data source
-----------
  USGS National Seismic Hazard Model (NSHM) 2023
  Reference: https://earthquake.usgs.gov/hazards/hazmaps/
  API docs:  https://earthquake.usgs.gov/nshmp/ws/hazard

  Memphis / Shelby County sits on the New Madrid Seismic Zone (NMSZ),
  the most seismically active region in the central-eastern United States.
  PGA values here are among the highest east of the Rockies.

  Reference values used (NSHM 2023, Site Class D, Memphis metro):
    PGA 2% in 50 yr  (~2475-yr return period): 0.35–0.60 g
    PGA 10% in 50 yr (~475-yr return period):  0.15–0.25 g

  Within-county variation is modeled using two proxies:
    1. Distance to NMSZ center – parcels closer to the fault have higher PGA.
    2. Longitude (east–west proxy for Mississippi alluvium) – western parcels
       on deep alluvial soils experience greater amplification.

  Upgrade path: replace reference-value interpolation with live USGS API calls:
    GET https://earthquake.usgs.gov/nshmp-haz-ws/hazard/E2014B/CEUS/{lon}/{lat}/PGA/760
  Each call returns a full hazard curve; log-log interpolation yields exact PGA
  at any annual frequency of exceedance. Throttle to ~1 req/sec to be polite.

Columns added
-------------
  pga_2pct_50yr          Peak ground acceleration (g), 2% prob. exceedance in 50 yr
  pga_10pct_50yr         Peak ground acceleration (g), 10% prob. exceedance in 50 yr
  seismic_design_category  ASCE 7 SDC (all of Shelby County = D, per USGS maps)
  nmsz_distance_mi       Great-circle distance (mi) to NMSZ reference point
  seismic_risk           Categorical risk: high / very high
  soil_amplification_note  Short note on site amplification class
"""

import argparse, logging, math, pathlib, sys
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[3]   # repo root; data lives here
REQUIRED_COLS = ["latitude", "longitude"]

# New Madrid Seismic Zone reference point (approximate center of the main rupture
# zone, near New Madrid, MO / Caruthersville, MO area).
NMSZ_LAT = 36.5
NMSZ_LON = -89.6

# NSHM 2023 reference PGA values for Memphis (Site Class D, Mississippi alluvium).
# Source: USGS Seismic Hazard Maps – Central US, NSHM 2023 update.
# These values are for a "median" Memphis site; we apply small per-parcel
# adjustments based on fault distance and soil position.
PGA_2PCT_BASE   = 0.48   # g  (2% in 50 yr, ~2475-yr return period)
PGA_10PCT_BASE  = 0.19   # g  (10% in 50 yr, ~475-yr return period)

# Approximate distance range of Shelby County parcels to NMSZ (miles).
# Measured empirically from actual parcel coordinates to NMSZ_LAT/LON above.
# Parcels closer (NE corner) → slightly higher PGA; farther (SW) → slightly lower.
DIST_NEAR = 76.0   # closest parcels (NE corner of county, ~76 mi from NMSZ center)
DIST_FAR  = 110.0  # farthest parcels (SW corner of county, ~108 mi from NMSZ center)

# Western Shelby County longitude threshold – parcels west of this are on
# thicker Mississippi alluvium and get a modest amplification bump.
ALLUVIUM_LON_THRESHOLD = -89.95   # approx. eastern edge of Mississippi floodplain

SEISMIC_COLS = [
    "pga_2pct_50yr",
    "pga_10pct_50yr",
    "seismic_design_category",
    "nmsz_distance_mi",
    "seismic_risk",
    "soil_amplification_note",
]


# ── Haversine ─────────────────────────────────────────────────────────────────
_R = 3958.8  # Earth radius in miles

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in miles between two lat/lon points."""
    lat1, lon1, lat2, lon2 = (math.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _R * math.asin(math.sqrt(a))


# ── National seismic classification (from mapped PGA) ─────────────────────────
def _national_risk(pga_2pct: float) -> str:
    """Coarse national seismic-risk label from the mapped 2%/50yr PGA (g).

    Absolute, nationwide bands (not the old within-Shelby relative split): the
    stable interior lands 'low'/'very low', the New Madrid & West-Coast zones
    'high'/'very high'. Display-only — the score reads the PGA columns directly.
    """
    if pga_2pct >= 0.60:
        return "very high"
    if pga_2pct >= 0.30:
        return "high"
    if pga_2pct >= 0.15:
        return "moderate"
    if pga_2pct >= 0.06:
        return "low"
    return "very low"


def _national_sdc(pga_2pct: float) -> str:
    """Approximate ASCE 7 Seismic Design Category from the mapped 2%/50yr PGA (g).

    A coarse national proxy (true SDC needs Sds + risk category + site class);
    kept for display continuity with the pilot's ``seismic_design_category``.
    """
    if pga_2pct >= 0.50:
        return "E"
    if pga_2pct >= 0.33:
        return "D"
    if pga_2pct >= 0.17:
        return "C"
    if pga_2pct >= 0.083:
        return "B"
    return "A"


# ── Per-parcel enrichment ─────────────────────────────────────────────────────
def enrich_parcel(lat: float, lon: float, allow_network: bool = True) -> dict:
    """Compute seismic hazard metrics for a single parcel location.

    National path (default): the mapped 2%/50yr & 10%/50yr PGA come from
    ``seismic_lookup.get_pga`` — the USGS ASCE7 design-maps service, correct
    anywhere in the US, with a bundled coarse grid as an offline fallback. Risk +
    design-category labels are derived from the mapped PGA on absolute national
    bands. When neither USGS nor the grid is available (offline, no bundled grid),
    it falls back to the legacy New-Madrid-only model below.
    """
    from housing_label.enrich.seismic_lookup import get_pga

    res = get_pga(lat, lon, allow_network=allow_network)
    if res is not None:
        pga_2pct, pga_10pct, source = res
        return {
            "pga_2pct_50yr":           pga_2pct,
            "pga_10pct_50yr":          pga_10pct,
            "seismic_design_category": _national_sdc(pga_2pct),
            "nmsz_distance_mi":        round(haversine_miles(lat, lon, NMSZ_LAT, NMSZ_LON), 1),
            "seismic_risk":            _national_risk(pga_2pct),
            "soil_amplification_note": f"{source}; site class B reference",
        }
    return _legacy_nmsz_parcel(lat, lon)


def _legacy_nmsz_parcel(lat: float, lon: float) -> dict:
    """Legacy New-Madrid-only interpolation (offline fallback for Shelby County).

    Methodology
    -----------
    1. Compute Haversine distance to NMSZ reference point.
    2. Apply a linear distance factor: parcels at DIST_NEAR get +10% PGA,
       parcels at DIST_FAR get -10% PGA, interpolated linearly between.
    3. Apply a +5% soil amplification bump for parcels on western alluvium
       (lon < ALLUVIUM_LON_THRESHOLD), reflecting deeper soft-soil column.
    4. Round PGA values to 3 decimal places.
    5. Seismic Design Category D applies county-wide per ASCE 7 (Ss > 0.5 g).
    6. All parcels are classified 'very high' or 'high' seismic risk – the
       NMSZ represents a genuine, nationally significant hazard.
    """
    dist_mi = haversine_miles(lat, lon, NMSZ_LAT, NMSZ_LON)

    # Distance factor: ±10% over the observed county distance range.
    # Clamp to [DIST_NEAR, DIST_FAR] before normalising.
    clamped = max(DIST_NEAR, min(dist_mi, DIST_FAR))
    dist_factor = 1.10 - 0.20 * (clamped - DIST_NEAR) / (DIST_FAR - DIST_NEAR)

    # Soil amplification: western alluvial parcels get +5%.
    on_alluvium = lon < ALLUVIUM_LON_THRESHOLD
    soil_factor = 1.05 if on_alluvium else 1.0

    pga_2pct   = round(PGA_2PCT_BASE  * dist_factor * soil_factor, 3)
    pga_10pct  = round(PGA_10PCT_BASE * dist_factor * soil_factor, 3)

    # Seismic risk label. All of Memphis is nationally high-risk; we use the
    # alluvium flag and distance to split into two tiers within the county.
    if on_alluvium or dist_mi < 45:
        risk = "very high"
    else:
        risk = "high"

    soil_note = (
        "Site Class D/E – Mississippi alluvial soils; significant amplification expected"
        if on_alluvium
        else "Site Class C/D – upland soils; moderate amplification expected"
    )

    return {
        "pga_2pct_50yr":           pga_2pct,
        "pga_10pct_50yr":          pga_10pct,
        "seismic_design_category": "D",
        "nmsz_distance_mi":        round(dist_mi, 1),
        "seismic_risk":            risk,
        "soil_amplification_note": soil_note,
    }


def _resolve_path(p: str) -> pathlib.Path:
    """Resolve a bare path relative to SCRIPT_DIR; leave absolute paths as-is."""
    path = pathlib.Path(p)
    return path if path.is_absolute() else SCRIPT_DIR / path


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich parcels with USGS seismic hazard data (NSHM 2023 reference values)."
    )
    parser.add_argument("--input", default="shelby_parcels_tornado.csv",
                        help="Input CSV path (relative paths resolve to script dir).")
    parser.add_argument("--output", default="shelby_parcels_seismic.csv",
                        help="Output CSV path (relative paths resolve to script dir).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N rows (for testing).")
    parser.add_argument("--offline", action="store_true",
                        help="Skip the live USGS lookup; use the bundled PGA grid, "
                             "else the legacy New Madrid model.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Load and validate input, log the plan, then exit without writing.")
    args = parser.parse_args()
    allow_network = not args.offline

    in_file = _resolve_path(args.input)
    out_file = _resolve_path(args.output)

    # ── Input validation ────────────────────────────────────────────────────
    if not in_file.exists():
        log.error("Input file does not exist: %s", in_file)
        sys.exit(1)

    log.info("Reading %s", in_file)
    df = pd.read_csv(in_file)
    log.info("  %d rows × %d columns", *df.shape)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        log.error("Input is missing required column(s): %s", ", ".join(missing))
        sys.exit(1)

    if args.limit:
        df = df.head(args.limit)
        log.info("--limit %d: working on first %d rows only.", args.limit, len(df))

    input_rows = len(df)

    # ── Dry run ─────────────────────────────────────────────────────────────
    if args.dry_run:
        log.info("Dry run – no output will be written.")
        log.info("  Input  : %s", in_file)
        log.info("  Output : %s", out_file)
        log.info("  Rows to enrich: %d", input_rows)
        return

    log.info("Enriching %d parcels with seismic hazard data …", len(df))
    results = []
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        lat, lon = row.get("latitude"), row.get("longitude")
        if pd.isna(lat) or pd.isna(lon):
            results.append({c: None for c in SEISMIC_COLS})
        else:
            results.append(enrich_parcel(float(lat), float(lon), allow_network=allow_network))
        if i % 200 == 0 or i == len(df):
            log.info("  Progress: %d / %d", i, len(df))

    enriched = pd.DataFrame(results, index=df.index)
    for col in SEISMIC_COLS:
        df[col] = enriched[col]

    df.to_csv(out_file, index=False)
    log.info("Saved → %s", out_file)
    log.info("wrote %d rows × %d cols", df.shape[0], df.shape[1])
    if len(df) != input_rows:
        log.warning("Output rows (%d) != input rows (%d).", len(df), input_rows)

    # ── Summary ───────────────────────────────────────────────────────────────
    total      = len(df)
    risk_dist  = df["seismic_risk"].value_counts().to_dict()
    pga2_min   = df["pga_2pct_50yr"].min()
    pga2_max   = df["pga_2pct_50yr"].max()
    pga2_mean  = df["pga_2pct_50yr"].mean()
    pga10_min  = df["pga_10pct_50yr"].min()
    pga10_max  = df["pga_10pct_50yr"].max()
    dist_min   = df["nmsz_distance_mi"].min()
    dist_max   = df["nmsz_distance_mi"].max()
    sdc_dist   = df["seismic_design_category"].value_counts().to_dict()
    w = 39

    print("\n╔══ USGS SEISMIC HAZARD ENRICHMENT SUMMARY ═══════════════════════╗")
    print(f"║ Total rows enriched        : {total:<{w}}║")
    print(f"║ Data source                : {'USGS ASCE7 design maps (national)':<{w}}║")
    print(f"║ Offline fallback           : {'bundled PGA grid → legacy NMSZ':<{w}}║")
    print("║ ── PGA 2% in 50 yr (2475-yr return period) ──────────────────── ║")
    print(f"║   min  : {pga2_min:.3f} g{'':<{w-12}}║")
    print(f"║   max  : {pga2_max:.3f} g{'':<{w-12}}║")
    print(f"║   mean : {pga2_mean:.3f} g{'':<{w-12}}║")
    print("║ ── PGA 10% in 50 yr (475-yr return period) ───────────────────── ║")
    print(f"║   min  : {pga10_min:.3f} g{'':<{w-12}}║")
    print(f"║   max  : {pga10_max:.3f} g{'':<{w-12}}║")
    print("║ ── Distance to NMSZ ──────────────────────────────────────────── ║")
    print(f"║   nearest parcel : {dist_min:.1f} mi{'':<{w-16}}║")
    print(f"║   farthest parcel: {dist_max:.1f} mi{'':<{w-16}}║")
    print("║ ── Seismic risk distribution ─────────────────────────────────── ║")
    for label in ("very high", "high", "moderate", "low", "very low"):
        count = risk_dist.get(label, 0)
        pct   = count / total * 100 if total else 0
        print(f"║   {label:<12}: {count:>5}  ({pct:5.1f}%){'':>19}║")
    print("║ ── Seismic Design Category (approx, from PGA) ────────────────── ║")
    for cat in ("E", "D", "C", "B", "A"):
        count = sdc_dist.get(cat, 0)
        if count:
            print(f"║   SDC {cat:<8}: {count:>5}  ({count/total*100:5.1f}%){'':>19}║")
    print(f"║ New columns added          : {len(SEISMIC_COLS):<{w}}║")
    print(f"║ Output                     : {out_file.name:<{w}}║")
    print("╚══════════════════════════════════════════════════════════════════╝\n")

    sample_cols = ["PARCELID", "latitude", "longitude"] + SEISMIC_COLS
    avail = [c for c in sample_cols if c in df.columns]
    print("Sample rows (first 10):")
    print(df[avail].head(10).to_string(index=False))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted.")
        sys.exit(0)
    except Exception as exc:
        log.error("Fatal: %s", exc, exc_info=True)
        sys.exit(1)
