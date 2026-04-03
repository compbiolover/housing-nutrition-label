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

  Strategy: download the full CSV once, cache it locally, then pre-filter to
  a coarse bounding box around Shelby County before per-parcel Haversine math.

Tornado columns added
---------------------
  tornado_count_25mi       Total tornadoes within 25 miles since 1950
  tornado_count_10mi       Total tornadoes within 10 miles since 1950
  max_ef_25mi              Highest EF/F rating within 25 miles (-1 = none)
  avg_tornadoes_per_yr_25mi  Annual average within 25 miles (tornado_count_25mi / years)
  tornado_risk             high / moderate / low classification
"""

import argparse, logging, math, pathlib, sys
import requests, pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
SPC_URL     = "https://www.spc.noaa.gov/wcm/data/1950-2023_actual_tornadoes.csv"
CACHE_FILE  = pathlib.Path(__file__).resolve().parent / "spc_tornadoes_raw.csv"
IN_FILE     = pathlib.Path(__file__).resolve().parent / "shelby_parcels_climate.csv"
OUT_FILE    = pathlib.Path(__file__).resolve().parent / "shelby_parcels_tornado.csv"

RADIUS_25   = 25.0   # miles
RADIUS_10   = 10.0   # miles
DATA_YEARS  = 2023 - 1950 + 1  # 74 years

# Coarse bounding box for pre-filtering (degrees of lat/lon for 30 mi buffer)
# Shelby County center ≈ 35.15°N, 89.98°W; 30 mi ≈ 0.44°
SHELBY_LAT  = 35.15
SHELBY_LON  = -89.98
BBOX_DEG    = 0.50    # ±0.50° ≈ ~34 miles – generous pre-filter

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


# ── SPC data download & load ──────────────────────────────────────────────────
def load_spc_data() -> pd.DataFrame:
    """Download (or load cached) SPC tornado CSV and return a cleaned DataFrame."""
    if CACHE_FILE.exists():
        log.info("Using cached SPC data: %s", CACHE_FILE)
    else:
        log.info("Downloading SPC tornado data from %s …", SPC_URL)
        r = requests.get(SPC_URL, timeout=120, stream=True)
        r.raise_for_status()
        CACHE_FILE.write_bytes(r.content)
        log.info("  Saved → %s  (%d bytes)", CACHE_FILE, CACHE_FILE.stat().st_size)

    df = pd.read_csv(CACHE_FILE, low_memory=False)
    log.info("  Loaded %d tornado records, columns: %s", len(df), list(df.columns))

    # Normalise column names (strip whitespace)
    df.columns = df.columns.str.strip()

    # Keep only rows with valid start coordinates
    df = df[df["slat"].notna() & df["slon"].notna()]
    df = df[df["slat"] != 0]
    df["slat"] = df["slat"].astype(float)
    df["slon"] = df["slon"].astype(float)
    df["mag"]  = pd.to_numeric(df["mag"], errors="coerce").fillna(-9).astype(int)

    # Pre-filter to coarse bounding box around Shelby County
    lat_lo, lat_hi = SHELBY_LAT - BBOX_DEG, SHELBY_LAT + BBOX_DEG
    lon_lo, lon_hi = SHELBY_LON - BBOX_DEG, SHELBY_LON + BBOX_DEG
    nearby = df[
        (df["slat"] >= lat_lo) & (df["slat"] <= lat_hi) &
        (df["slon"] >= lon_lo) & (df["slon"] <= lon_hi)
    ].copy()
    log.info("  Pre-filtered to %d tornadoes within bounding box of Shelby County.", len(nearby))
    return nearby


# ── Per-parcel enrichment ─────────────────────────────────────────────────────
def enrich_parcel(lat: float, lon: float, tornadoes: pd.DataFrame) -> dict:
    """Compute tornado metrics for a single parcel location."""
    dists = tornadoes.apply(
        lambda r: haversine_miles(lat, lon, r["slat"], r["slon"]), axis=1
    )
    w25 = dists <= RADIUS_25
    w10 = dists <= RADIUS_10

    count_25 = int(w25.sum())
    count_10 = int(w10.sum())
    mags_25  = tornadoes.loc[w25, "mag"]
    valid_mags = mags_25[mags_25 >= 0]
    max_ef  = int(valid_mags.max()) if not valid_mags.empty else -1
    avg_yr  = round(count_25 / DATA_YEARS, 3)

    # Risk classification – relative within Shelby County.
    # The entire county is historically high-risk nationally; these thresholds
    # capture within-county variation using the 10-mile count as the primary
    # discriminator (range observed: ~12-27 tornadoes within 10 mi since 1950).
    if count_10 >= 20 or max_ef >= 4:
        risk = "high"
    elif count_10 >= 14 or max_ef >= 3:
        risk = "moderate"
    else:
        risk = "low"

    return {
        "tornado_count_25mi":       count_25,
        "tornado_count_10mi":       count_10,
        "max_ef_25mi":              max_ef,
        "avg_tornadoes_per_yr_25mi": avg_yr,
        "tornado_risk":             risk,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Enrich parcels with SPC historical tornado data."
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N rows (for testing).")
    args = parser.parse_args()

    tornadoes = load_spc_data()

    log.info("Reading %s", IN_FILE)
    df = pd.read_csv(IN_FILE)
    log.info("  %d rows × %d columns", *df.shape)

    if args.limit:
        df = df.head(args.limit)
        log.info("--limit %d: working on first %d rows only.", args.limit, len(df))

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

    df.to_csv(OUT_FILE, index=False)
    log.info("Saved → %s", OUT_FILE)

    # ── Summary ───────────────────────────────────────────────────────────────
    total = len(df)
    risk_dist = df["tornado_risk"].value_counts().to_dict()
    w = 37
    print("\n╔══ SPC TORNADO ENRICHMENT SUMMARY ═══════════════════════════╗")
    print(f"║ Total rows enriched     : {total:<{w}}║")
    print(f"║ SPC data range          : {'1950-2023':<{w}}║")
    print(f"║ Nearby tornadoes (bbox) : {len(tornadoes):<{w}}║")
    print(f"║ Search radii            : {'10 mi / 25 mi':<{w}}║")
    print("║ ── Tornado risk distribution ─────────────────────────────── ║")
    for label in ("high", "moderate", "low"):
        count = risk_dist.get(label, 0)
        pct   = count / total * 100 if total else 0
        print(f"║   {label:<10} : {count:>5}  ({pct:5.1f}%){'':>19}║")
    print(f"║ New columns added       : {len(TORNADO_COLS):<{w}}║")
    print(f"║ Output                  : {OUT_FILE.name:<{w}}║")
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
