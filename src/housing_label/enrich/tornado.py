#!/usr/bin/env python3
"""Enrich shelby_parcels_climate.csv with SPC historical tornado data.

Usage
-----
  python enrich_tornado.py              # all 1 000 parcels
  python enrich_tornado.py --limit 10  # test with 10 rows first

Data source
-----------
  NOAA Storm Prediction Center (SPC) – Historical Tornado Data 1950-2023
  URL  : https://www.spc.noaa.gov/wcm/data/1950-2023_actual_tornadoes.csv
  Docs : https://www.spc.noaa.gov/wcm/#data
  Auth : None – free, public, keyless
  Size : ~7.8 MB (all US tornadoes 1950-2023)

  Key columns used from SPC CSV:
    slat / slon  – tornado start lat/lon
    elat / elon  – tornado end lat/lon (0 if unknown)
    mag          – EF/F-scale magnitude (0-5, -9 = unknown)
    yr           – year
    mo / dy      – month / day

  Strategy: download the full national CSV once, cache it locally, then for each
  parcel pre-filter to a box centered on that parcel before Haversine math — so
  the counts are correct for any US location, not just Shelby County.

Tornado columns added
---------------------
  tornado_count_25mi       Total tornadoes within 25 miles since 1950
  tornado_count_10mi       Total tornadoes within 10 miles since 1950
  max_ef_25mi              Highest EF/F rating within 25 miles (-1 = none)
  avg_tornadoes_per_yr_25mi  Annual average within 25 miles (tornado_count_25mi / years)
  tornado_risk             high / moderate / low (absolute national bands)
"""

import argparse, logging, math, pathlib, sys
import requests, pandas as pd, numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = pathlib.Path(__file__).resolve().parents[3]   # repo root; data lives here
SPC_URL     = "https://www.spc.noaa.gov/wcm/data/1950-2023_actual_tornadoes.csv"
CACHE_FILE  = SCRIPT_DIR / "spc_tornadoes_raw.csv"
IN_FILE     = SCRIPT_DIR / "shelby_parcels_climate.csv"
OUT_FILE    = SCRIPT_DIR / "shelby_parcels_tornado.csv"

RADIUS_25   = 25.0   # miles
RADIUS_10   = 10.0   # miles
DATA_YEARS  = 2023 - 1950 + 1  # 74 years

# Per-parcel pre-filter half-width. Each parcel's tornado count is taken over a
# box centered on THAT parcel (not a fixed Shelby box), so the stage works for any
# US location. ±0.50° latitude ≈ ~34 miles, comfortably covering the 25-mi radius;
# the longitude half-width is widened by 1/cos(lat) so it stays ≥34 mi away from
# the equator.
BBOX_DEG    = 0.50

TORNADO_COLS = [
    "tornado_count_25mi",
    "tornado_count_10mi",
    "max_ef_25mi",
    "avg_tornadoes_per_yr_25mi",
    "tornado_risk",
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


def _haversine_np(lat: float, lon: float, slat, slon):
    """Great-circle miles from one point to arrays of lat/lon (same formula as
    haversine_miles, vectorized so a parcel's distance to every nearby tornado is
    one numpy op instead of a per-row Python apply)."""
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2, lon2 = np.radians(slat), np.radians(slon)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + math.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * _R * np.arcsin(np.sqrt(a))


# ── SPC data download & load ──────────────────────────────────────────────────
def load_spc_data(cache_file: pathlib.Path = CACHE_FILE) -> pd.DataFrame:
    """Download (or load cached) SPC tornado CSV and return a cleaned DataFrame."""
    if cache_file.exists():
        log.info("Using cached SPC data: %s", cache_file)
    else:
        log.info("Downloading SPC tornado data from %s …", SPC_URL)
        r = requests.get(SPC_URL, timeout=120, stream=True)
        r.raise_for_status()
        cache_file.write_bytes(r.content)
        log.info("  Saved → %s  (%d bytes)", cache_file, cache_file.stat().st_size)

    df = pd.read_csv(cache_file, low_memory=False)
    log.info("  Loaded %d tornado records, columns: %s", len(df), list(df.columns))

    # Normalise column names (strip whitespace)
    df.columns = df.columns.str.strip()

    # Keep only rows with valid start coordinates
    df = df[df["slat"].notna() & df["slon"].notna()]
    df = df[df["slat"] != 0]
    df["slat"] = df["slat"].astype(float)
    df["slon"] = df["slon"].astype(float)
    df["mag"]  = pd.to_numeric(df["mag"], errors="coerce").fillna(-9).astype(int)

    # Keep the full national table — the per-parcel pre-filter (enrich_parcel)
    # is centered on each parcel, so no fixed county box is applied here.
    nearby = df[["slat", "slon", "mag"]].copy()
    log.info("  Retained %d national tornado records (point-centered per parcel).", len(nearby))
    return nearby


# ── National tornado-risk classification ──────────────────────────────────────
def _national_risk(avg_yr: float, max_ef: int) -> str:
    """Absolute national tornado-risk label from the 25-mi annual rate + peak EF.

    Replaces the old within-Shelby relative thresholds: the plains 'tornado alley'
    lands 'high', most of the country 'low'. Display-only — the score reads
    ``avg_tornadoes_per_yr_25mi`` directly.
    """
    if avg_yr >= 0.75 or max_ef >= 4:
        return "high"
    if avg_yr >= 0.25 or max_ef >= 3:
        return "moderate"
    return "low"


# ── Per-parcel enrichment ─────────────────────────────────────────────────────
def enrich_parcel(lat: float, lon: float, tornadoes: pd.DataFrame) -> dict[str, object]:
    """Compute tornado metrics for a single parcel location.

    Pre-filters the national table to a box centered on this parcel (widening the
    longitude half-width by 1/cos(lat) so it stays ≥ the 25-mi radius away from the
    equator), then counts exact great-circle distances within 25 / 10 miles.
    """
    lat_lo, lat_hi = lat - BBOX_DEG, lat + BBOX_DEG
    lon_margin = BBOX_DEG / max(math.cos(math.radians(lat)), 0.1)
    lon_lo, lon_hi = lon - lon_margin, lon + lon_margin
    slat = tornadoes["slat"].to_numpy()
    slon = tornadoes["slon"].to_numpy()
    near = (slat >= lat_lo) & (slat <= lat_hi) & (slon >= lon_lo) & (slon <= lon_hi)
    slat, slon = slat[near], slon[near]
    mags = tornadoes["mag"].to_numpy()[near]

    dists = _haversine_np(lat, lon, slat, slon)
    w25 = dists <= RADIUS_25
    w10 = dists <= RADIUS_10

    count_25 = int(w25.sum())
    count_10 = int(w10.sum())
    valid_mags = mags[w25][mags[w25] >= 0]
    max_ef  = int(valid_mags.max()) if valid_mags.size else -1
    avg_yr  = round(count_25 / DATA_YEARS, 3)

    return {
        "tornado_count_25mi":       count_25,
        "tornado_count_10mi":       count_10,
        "max_ef_25mi":              max_ef,
        "avg_tornadoes_per_yr_25mi": avg_yr,
        "tornado_risk":             _national_risk(avg_yr, max_ef),
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich parcels with SPC historical tornado data."
    )
    parser.add_argument("--input", default="shelby_parcels_climate.csv",
                        help="Input parcels CSV (default: shelby_parcels_climate.csv).")
    parser.add_argument("--output", default="shelby_parcels_tornado.csv",
                        help="Output CSV (default: shelby_parcels_tornado.csv).")
    parser.add_argument("--cache", default="spc_tornadoes_raw.csv",
                        help="SPC raw tornado data CSV (default: spc_tornadoes_raw.csv).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N rows (for testing).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate inputs and log the plan without writing output.")
    args = parser.parse_args()

    # Resolve bare paths relative to the script directory.
    def _resolve(p: str) -> pathlib.Path:
        path = pathlib.Path(p)
        return path if path.is_absolute() else SCRIPT_DIR / path

    in_file    = _resolve(args.input)
    out_file   = _resolve(args.output)
    cache_file = _resolve(args.cache)

    # ── Input validation ──────────────────────────────────────────────────────
    if not in_file.exists():
        log.error("Input file does not exist: %s", in_file)
        sys.exit(1)
    if not cache_file.exists():
        log.error("Cache file (SPC raw data) does not exist: %s", cache_file)
        sys.exit(1)

    tornadoes = load_spc_data(cache_file)

    log.info("Reading %s", in_file)
    df = pd.read_csv(in_file)
    log.info("  %d rows × %d columns", *df.shape)

    required_cols = ["latitude", "longitude"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        log.error("Input is missing required column(s): %s", missing)
        sys.exit(1)

    input_rows = len(df)

    if args.limit:
        df = df.head(args.limit)
        log.info("--limit %d: working on first %d rows only.", args.limit, len(df))

    # ── Dry run: log the plan and stop before writing ─────────────────────────
    if args.dry_run:
        log.info("[dry-run] Plan:")
        log.info("[dry-run]   input  : %s", in_file)
        log.info("[dry-run]   output : %s", out_file)
        log.info("[dry-run]   cache  : %s", cache_file)
        log.info("[dry-run]   parcel rows to enrich : %d", len(df))
        log.info("[dry-run]   national tornado records: %d", len(tornadoes))
        log.info("[dry-run] No output written.")
        return

    log.info("Enriching %d parcels with tornado risk data …", len(df))
    results = []
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        lat, lon = row.get("latitude"), row.get("longitude")
        if pd.isna(lat) or pd.isna(lon):
            results.append({c: None for c in TORNADO_COLS})
        else:
            results.append(enrich_parcel(float(lat), float(lon), tornadoes))
        if i % 100 == 0 or i == len(df):
            log.info("  Progress: %d / %d", i, len(df))

    enriched = pd.DataFrame(results, index=df.index)
    for col in TORNADO_COLS:
        df[col] = enriched[col]

    df.to_csv(out_file, index=False)
    log.info("Saved → %s", out_file)

    # ── Output validation ─────────────────────────────────────────────────────
    out_rows, out_cols = df.shape
    log.info("wrote %d rows × %d cols", out_rows, out_cols)
    expected_rows = min(input_rows, args.limit) if args.limit else input_rows
    if out_rows != expected_rows:
        log.warning("Output rows (%d) != expected input rows (%d).",
                    out_rows, expected_rows)

    # ── Summary ───────────────────────────────────────────────────────────────
    total = len(df)
    risk_dist = df["tornado_risk"].value_counts().to_dict()
    w = 37
    print("\n╔══ SPC TORNADO ENRICHMENT SUMMARY ═══════════════════════════╗")
    print(f"║ Total rows enriched     : {total:<{w}}║")
    print(f"║ SPC data range          : {'1950-2023':<{w}}║")
    print(f"║ National tornado records: {len(tornadoes):<{w}}║")
    print(f"║ Search radii            : {'10 mi / 25 mi':<{w}}║")
    print("║ ── Tornado risk distribution ─────────────────────────────── ║")
    for label in ("high", "moderate", "low"):
        count = risk_dist.get(label, 0)
        pct   = count / total * 100 if total else 0
        print(f"║   {label:<10} : {count:>5}  ({pct:5.1f}%){'':>19}║")
    print(f"║ New columns added       : {len(TORNADO_COLS):<{w}}║")
    print(f"║ Output                  : {out_file.name:<{w}}║")
    print("╚══════════════════════════════════════════════════════════════╝\n")

    sample_cols = ["PARCELID", "latitude", "longitude",
                   "flood_risk"] + TORNADO_COLS
    avail = [c for c in sample_cols if c in df.columns]
    print("Sample rows (first 10):")
    print(df[avail].head(10).to_string(index=False))

    # EF distribution for 25mi parcels
    ef_counts = df["max_ef_25mi"].value_counts().sort_index()
    print("\nMax EF rating within 25 mi (distribution across parcels):")
    ef_labels = {-1: "none", 0: "EF0", 1: "EF1", 2: "EF2",
                  3: "EF3", 4: "EF4", 5: "EF5"}
    for ef, cnt in ef_counts.items():
        label = ef_labels.get(int(ef), f"EF{ef}")
        print(f"  {label:6s}: {cnt:4d} parcels")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted.")
        sys.exit(0)
    except Exception as exc:
        log.error("Fatal: %s", exc, exc_info=True)
        sys.exit(1)
