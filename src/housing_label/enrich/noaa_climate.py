#!/usr/bin/env python3
"""Enrich shelby_parcels_flood.csv with NOAA climate normals data.

Usage
-----
  python enrich_noaa_climate.py              # all 1 000 parcels
  python enrich_noaa_climate.py --limit 10  # test with 10 rows first

Data source
-----------
  NOAA 1991–2020 U.S. Climate Normals
  Station : Memphis International Airport  (USW00013893)
  Location: 35.0584° N, 89.9787° W  (Shelby County, TN)

  All 1,000 parcels are in the same IECC climate zone (4A, Mixed-Humid),
  so a single county-wide set of normals is applied to every parcel.
  These are published reference values and will not change between runs.

  Full CDO API: https://www.ncei.noaa.gov/cdo-web/api/v2/
  Free token  : https://www.ncdc.noaa.gov/cdo-web/token
  (API-based lookup is the upgrade path when this expands beyond Shelby County.)

Climate columns added
---------------------
  climate_zone            IECC energy-code zone (e.g. "4A")
  climate_zone_desc       Human-readable zone label
  hdd_annual              Heating Degree Days, base 65°F (annual normal)
  cdd_annual              Cooling Degree Days, base 65°F (annual normal)
  avg_jan_low_f           Average January daily low (°F)
  avg_jul_high_f          Average July daily high (°F)
  precip_annual_in        Normal annual precipitation (inches)
  extreme_heat_days       Days/yr with max temp > 95°F
  freeze_days             Days/yr with min temp < 32°F
  climate_station         NOAA station ID used as reference
  climate_normals_period  Normals period (e.g. "1991-2020")
"""

import argparse, logging, pathlib, sys
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── File paths ────────────────────────────────────────────────────────────────
SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[3]   # repo root; data lives here

# ── NOAA 1991-2020 Climate Normals: Memphis International Airport ─────────────
#    Source: NOAA Climate Normals for the U.S. (1991–2020), NCEI station USW00013893
MEMPHIS_CLIMATE = {
    "climate_zone":           "4A",
    "climate_zone_desc":      "Mixed-Humid",
    "hdd_annual":             3082,    # Heating Degree Days (base 65°F)
    "cdd_annual":             2191,    # Cooling Degree Days (base 65°F)
    "avg_jan_low_f":          31.1,    # Average January daily low (°F)
    "avg_jul_high_f":         92.5,    # Average July daily high (°F)
    "precip_annual_in":       53.7,    # Normal annual precipitation (in)
    "extreme_heat_days":      45,      # Days/yr with max temp > 95°F
    "freeze_days":            50,      # Days/yr with min temp < 32°F
    "climate_station":        "USW00013893",
    "climate_normals_period": "1991-2020",
}

CLIMATE_COLS = list(MEMPHIS_CLIMATE.keys())


# ── Main ──────────────────────────────────────────────────────────────────────
def resolve_path(raw: str) -> pathlib.Path:
    """Resolve a path; bare (non-absolute) paths are taken relative to SCRIPT_DIR."""
    p = pathlib.Path(raw)
    return p if p.is_absolute() else SCRIPT_DIR / p


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich parcels with NOAA climate normals (Memphis / Shelby County)."
    )
    parser.add_argument("--input", default="shelby_parcels_flood.csv",
                        help="Input CSV path (default: shelby_parcels_flood.csv).")
    parser.add_argument("--output", default="shelby_parcels_climate.csv",
                        help="Output CSV path (default: shelby_parcels_climate.csv).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N rows (for testing).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate and log the plan without writing output.")
    args = parser.parse_args()

    in_file = resolve_path(args.input)
    out_file = resolve_path(args.output)

    if not in_file.exists():
        log.error("Input file not found: %s", in_file)
        sys.exit(1)

    log.info("Reading %s", in_file)
    df = pd.read_csv(in_file)
    log.info("  %d rows × %d columns", *df.shape)

    if args.limit:
        df = df.head(args.limit)
        log.info("--limit %d: working on first %d rows only.", args.limit, len(df))

    in_rows = len(df)

    if args.dry_run:
        log.info("DRY RUN — no output will be written.")
        log.info("  Input  : %s", in_file)
        log.info("  Output : %s", out_file)
        log.info("  Rows   : %d", in_rows)
        log.info("  Columns that WOULD be added: %s", list(MEMPHIS_CLIMATE))
        return

    log.info("Applying Memphis / Shelby County climate normals  "
             "(station %s, %s normals) …",
             MEMPHIS_CLIMATE["climate_station"],
             MEMPHIS_CLIMATE["climate_normals_period"])

    for col, val in MEMPHIS_CLIMATE.items():
        df[col] = val

    df.to_csv(out_file, index=False)
    log.info("Saved → %s", out_file)
    log.info("wrote %d rows × %d cols", len(df), len(df.columns))
    if len(df) != in_rows:
        log.warning("Output row count (%d) != input row count (%d).", len(df), in_rows)

    # ── Summary ───────────────────────────────────────────────────────────────
    total = len(df)
    w = 33
    print("\n╔══ NOAA CLIMATE ENRICHMENT SUMMARY ══════════════════════╗")
    print(f"║ Total rows enriched  : {total:<{w}}║")
    print(f"║ Reference station    : {MEMPHIS_CLIMATE['climate_station']:<{w}}║")
    print(f"║ Normals period       : {MEMPHIS_CLIMATE['climate_normals_period']:<{w}}║")
    zone_label = f"{MEMPHIS_CLIMATE['climate_zone']} – {MEMPHIS_CLIMATE['climate_zone_desc']}"
    print(f"║ IECC climate zone    : {zone_label:<{w}}║")
    print(f"║ Heating degree days  : {MEMPHIS_CLIMATE['hdd_annual']:<{w}}║")
    print(f"║ Cooling degree days  : {MEMPHIS_CLIMATE['cdd_annual']:<{w}}║")
    print(f"║ Avg Jan low (°F)     : {MEMPHIS_CLIMATE['avg_jan_low_f']:<{w}}║")
    print(f"║ Avg Jul high (°F)    : {MEMPHIS_CLIMATE['avg_jul_high_f']:<{w}}║")
    print(f"║ Annual precip (in)   : {MEMPHIS_CLIMATE['precip_annual_in']:<{w}}║")
    print(f"║ Extreme heat days/yr : {MEMPHIS_CLIMATE['extreme_heat_days']:<{w}}║")
    print(f"║ Freeze days/yr       : {MEMPHIS_CLIMATE['freeze_days']:<{w}}║")
    print(f"║ New columns added    : {len(CLIMATE_COLS):<{w}}║")
    print(f"║ Total columns        : {len(df.columns):<{w}}║")
    print(f"║ Output               : {out_file.name:<{w}}║")
    print("╚══════════════════════════════════════════════════════════╝\n")

    sample_cols = ["PARCELID", "latitude", "longitude", "flood_risk"] + CLIMATE_COLS
    available = [c for c in sample_cols if c in df.columns]
    print("Sample rows (first 5):")
    print(df[available].head(5).to_string(index=False))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted.")
        sys.exit(0)
    except Exception as exc:
        log.error("Fatal: %s", exc, exc_info=True)
        sys.exit(1)
