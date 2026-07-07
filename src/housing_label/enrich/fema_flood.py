#!/usr/bin/env python3
"""Enrich shelby_parcels_clean.csv with FEMA flood zone data.

Usage
-----
  python enrich_fema_flood.py              # all 1 000 parcels
  python enrich_fema_flood.py --limit 10  # test with 10 rows first

API notes
---------
  Service   : FEMA National Flood Hazard Layer (NFHL) – ArcGIS REST
  Endpoint  : https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query
  Layer 28  : Flood Hazard Zones (polygon layer, ~5.5 M features nationwide)
  Auth      : None – free, public, keyless
  Rate limit: None officially published; 0.25 s sleep used to be polite
  inSR      : 4326 (WGS84 lat/lon input)
  Key fields: FLD_ZONE  – zone code (A, AE, AO, AH, AR, A99, V, VE, X, D, …)
              ZONE_SUBTY – subtype detail (e.g. "0.2 PCT ANNUAL CHANCE FLOOD HAZARD")

Flood risk classification
--------------------------
  high     : A, AE, AO, AH, AR, AR/A*, AR/AE, AR/AH, AR/AO, AR/X,
             V, VE, A99  (Special Flood Hazard Areas – 1 % annual chance)
  moderate : X  with ZONE_SUBTY containing "0.2 PCT"  (shaded X, 500-yr zone)
  minimal  : X  (unshaded – outside 0.2 % annual chance flood zone)
  unknown  : D  (area of undetermined flood hazard) or no polygon found
"""

from __future__ import annotations

import argparse, json, logging, sys, time, pathlib
import requests, pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = pathlib.Path(__file__).resolve().parents[3]   # repo root; data lives here
FEMA_URL    = ("https://hazards.fema.gov/arcgis/rest/services"
               "/public/NFHL/MapServer/28/query")
SLEEP_SEC   = 0.25    # polite delay between requests (~4 req/s)
TIMEOUT     = 20      # seconds per HTTP call
MAX_RETRIES = 3
BACKOFF     = 2       # exponential back-off multiplier
CHECKPOINT  = 50      # save every N rows

FLOOD_COLS  = ["flood_zone", "flood_risk"]

# Zones that constitute Special Flood Hazard Areas (high risk)
SFHA_ZONES  = {
    "A", "AE", "AO", "AH", "AR", "A99",
    "V", "VE",
    "AR/A", "AR/AE", "AR/AH", "AR/AO", "AR/X",
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def classify_risk(zone: str | None, subtype: str | None) -> str:
    """Map a raw FLD_ZONE + ZONE_SUBTY to a simplified risk label."""
    if not zone or pd.isna(zone):
        return "unknown"
    zone = str(zone).strip().upper()
    subtype = str(subtype).strip().upper() if subtype and not pd.isna(subtype) else ""
    if zone in SFHA_ZONES:
        return "high"
    if zone == "X":
        return "moderate" if "0.2 PCT" in subtype else "minimal"
    if zone == "D":
        return "unknown"
    # Catch any AR/* variants not explicitly listed
    if zone.startswith("AR/") or zone.startswith("A/"):
        return "high"
    return "unknown"


def fetch_flood_zone(lat: float, lon: float) -> dict:
    """Query FEMA NFHL layer 28 for the flood zone at (lat, lon).

    Returns dict with keys 'flood_zone' and 'flood_risk'.
    """
    geometry_json = json.dumps({"x": lon, "y": lat})
    params = {
        "geometry":     geometry_json,
        "geometryType": "esriGeometryPoint",
        "inSR":         "4326",
        "spatialRel":   "esriSpatialRelIntersects",
        "outFields":    "FLD_ZONE,ZONE_SUBTY",
        "returnGeometry": "false",
        "f":            "json",
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(FEMA_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            log.warning("HTTP error (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)
            if attempt == MAX_RETRIES:
                return {"flood_zone": None, "flood_risk": "unknown"}
            time.sleep(BACKOFF ** attempt)
            continue

        if "error" in data:
            log.warning("FEMA API error: %s", data["error"])
            return {"flood_zone": None, "flood_risk": "unknown"}

        features = data.get("features", [])
        if not features:
            # No polygon at this point → outside mapped area or open water
            return {"flood_zone": None, "flood_risk": "unknown"}

        attrs    = features[0].get("attributes", {})
        zone     = attrs.get("FLD_ZONE")
        subtype  = attrs.get("ZONE_SUBTY")
        return {
            "flood_zone": zone,
            "flood_risk": classify_risk(zone, subtype),
        }

    return {"flood_zone": None, "flood_risk": "unknown"}


def already_enriched(row: pd.Series) -> bool:
    return all(pd.notna(row.get(c)) for c in FLOOD_COLS)


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich parcels with FEMA flood zone data.")
    parser.add_argument("--input", default="shelby_parcels_clean.csv",
                        help="Input CSV path (default: shelby_parcels_clean.csv).")
    parser.add_argument("--output", default="shelby_parcels_flood.csv",
                        help="Output CSV path (default: shelby_parcels_flood.csv).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N rows (for testing).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate inputs and report the plan without making API calls or writing output.")
    args = parser.parse_args()

    # Resolve bare paths relative to the script directory
    in_path = pathlib.Path(args.input)
    if not in_path.is_absolute():
        in_path = SCRIPT_DIR / in_path
    out_path = pathlib.Path(args.output)
    if not out_path.is_absolute():
        out_path = SCRIPT_DIR / out_path

    # Input validation
    if not in_path.exists():
        log.error("Input file not found: %s", in_path)
        sys.exit(1)

    log.info("Reading %s", in_path)
    df = pd.read_csv(in_path)
    log.info("  %d rows × %d columns", *df.shape)
    input_rows = len(df)

    required_cols = ["latitude", "longitude"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        log.error("Input is missing required columns: %s", missing)
        sys.exit(1)

    # Resume: merge any previously enriched rows
    if out_path.exists():
        log.info("Found existing output – loading to resume: %s", out_path)
        prev = pd.read_csv(out_path)
        for col in FLOOD_COLS:
            if col in prev.columns:
                df[col] = prev[col]
        already = df.apply(already_enriched, axis=1).sum()
        log.info("  %d rows already enriched; skipping those.", already)
    else:
        for col in FLOOD_COLS:
            df[col] = None

    if args.limit:
        df = df.head(args.limit)
        log.info("--limit %d: working on first %d rows only.", args.limit, len(df))

    todo = df[~df.apply(already_enriched, axis=1)]
    log.info("%d rows to enrich.", len(todo))

    if args.dry_run:
        log.info("DRY RUN – no API calls or writes will be made.")
        log.info("  Input : %s", in_path)
        log.info("  Output: %s", out_path)
        log.info("  Rows that would be enriched: %d", len(todo))
        return

    if todo.empty:
        log.info("Nothing to do – all rows already enriched.")
    else:
        for i, (idx, row) in enumerate(todo.iterrows(), start=1):
            lat = row.get("latitude")
            lon = row.get("longitude")
            if pd.isna(lat) or pd.isna(lon):
                log.debug("Row %d: no coordinates, skipping.", idx)
                df.at[idx, "flood_zone"] = None
                df.at[idx, "flood_risk"] = "unknown"
                continue

            result = fetch_flood_zone(float(lat), float(lon))
            df.at[idx, "flood_zone"] = result["flood_zone"]
            df.at[idx, "flood_risk"] = result["flood_risk"]

            log.debug("Row %d: zone=%s risk=%s", idx, result["flood_zone"], result["flood_risk"])

            if i % CHECKPOINT == 0 or i == len(todo):
                log.info("Progress: %d/%d  (checkpoint save)", i, len(todo))
                df.to_csv(out_path, index=False)

            time.sleep(SLEEP_SEC)

    df.to_csv(out_path, index=False)
    log.info("Saved → %s", out_path)

    # Output validation
    log.info("wrote %d rows × %d cols", df.shape[0], df.shape[1])
    if len(df) != input_rows:
        if args.limit is not None:
            log.warning("Output row count (%d) != input row count (%d) due to --limit %d.",
                        len(df), input_rows, args.limit)
        else:
            log.warning("Output row count (%d) != input row count (%d).", len(df), input_rows)

    # ── Summary ───────────────────────────────────────────────────────────
    total    = len(df)
    enriched = df["flood_zone"].notna().sum()
    dist     = df["flood_risk"].value_counts().to_dict()
    print("\n╔══ FEMA FLOOD ENRICHMENT SUMMARY ════════════════════════╗")
    print(f"║ Total rows         : {total:<35}║")
    print(f"║ Rows with zone data: {enriched:<35}║")
    for label in ("high", "moderate", "minimal", "unknown"):
        count = dist.get(label, 0)
        print(f"║   {label:<17}: {count:<35}║")
    print(f"║ Output             : {out_path.name:<35}║")
    print("╚════════════════════════════════════════════════════════╝\n")

    if not df.empty:
        sample = df[["latitude", "longitude", "flood_zone", "flood_risk"]].head(10)
        print("Sample results:")
        print(sample.to_string(index=False))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted – partial results saved to the last checkpoint.")
        sys.exit(0)
    except Exception as exc:
        log.error("Fatal: %s", exc, exc_info=True)
        sys.exit(1)
