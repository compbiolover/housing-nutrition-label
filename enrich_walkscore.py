#!/usr/bin/env python3
"""Enrich shelby_parcels_clean.csv with Walk Score data.

Usage
-----
  export WALKSCORE_API_KEY=your_key_here
  python enrich_walkscore.py              # all 1 000 parcels
  python enrich_walkscore.py --limit 10  # test with 10 rows first

Getting an API key
------------------
  1. Go to https://www.walkscore.com/professional/api.php
  2. Sign up for a Walk Score Professional API account.
  3. A free trial tier is available; production pricing is per-request.
  4. Set the key as WALKSCORE_API_KEY in your environment (never hardcode it).

API notes
---------
  Endpoint : GET https://api.walkscore.com/score
  Required  : wsapikey, lat, lon, address (URL-encoded string)
  Optional  : transit=1, bike=1  (request those sub-scores)
  Status 1  : success
  Status 2  : score being calculated – retry in a moment
  Status 40 : invalid API key
  Status 41 : daily quota exceeded
  Status 42 : IP not in allow-list
  Coverage  : US and Canada only
"""

import argparse, logging, os, sys, time, urllib.parse, pathlib
import requests, pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
API_URL    = "https://api.walkscore.com/score"
IN_FILE    = pathlib.Path(__file__).resolve().parent / "shelby_parcels_clean.csv"
OUT_FILE   = pathlib.Path(__file__).resolve().parent / "shelby_parcels_enriched.csv"
SLEEP_SEC  = 0.25   # 4 req/s – conservative; free tier limit undisclosed
RETRY_SEC  = 5.0    # wait before retrying a "score calculating" response
TIMEOUT    = 15     # seconds per HTTP call
MAX_RETRIES = 3

SCORE_COLS = ["walk_score", "transit_score", "bike_score"]


# ── Helpers ───────────────────────────────────────────────────────────────────
def build_address(row: pd.Series) -> str:
    """Assemble a URL-encoded address string from parcel fields."""
    parts = []
    if pd.notna(row.get("ADRNO"))  and str(row["ADRNO"]).strip():
        parts.append(str(int(float(row["ADRNO"]))).strip())
    if pd.notna(row.get("ADRSTR")) and str(row["ADRSTR"]).strip():
        parts.append(str(row["ADRSTR"]).strip())
    if pd.notna(row.get("ADRSUF")) and str(row["ADRSUF"]).strip():
        parts.append(str(row["ADRSUF"]).strip())
    city  = str(row.get("CITYNAME", "")).strip()
    state = str(row.get("STATECODE", "")).strip()
    zipcd = str(row.get("ZIP1", "")).strip()
    if city:   parts.append(city)
    if state:  parts.append(state)
    if zipcd:  parts.append(zipcd)
    return urllib.parse.quote(" ".join(parts))


def fetch_scores(api_key: str, lat: float, lon: float, address: str) -> dict:
    """Call Walk Score API; return dict with walk/transit/bike scores (or None)."""
    params = {
        "wsapikey": api_key,
        "lat":      lat,
        "lon":      lon,
        "address":  address,
        "transit":  1,
        "bike":     1,
        "format":   "json",
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(API_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            log.warning("HTTP error (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)
            if attempt == MAX_RETRIES:
                return {"walk_score": None, "transit_score": None, "bike_score": None}
            time.sleep(SLEEP_SEC * (2 ** attempt))
            continue

        status = data.get("status")
        if status == 1:
            return {
                "walk_score":    data.get("walkscore"),
                "transit_score": data.get("transit", {}).get("score"),
                "bike_score":    data.get("bike", {}).get("score"),
            }
        elif status == 2:
            # Score is still being calculated
            log.debug("Score calculating, retrying in %.1fs…", RETRY_SEC)
            time.sleep(RETRY_SEC)
            continue
        elif status == 40:
            log.error("Invalid API key – check WALKSCORE_API_KEY and try again.")
            sys.exit(1)
        elif status == 41:
            log.error("Daily API quota exceeded. Re-run tomorrow or upgrade your plan.")
            sys.exit(1)
        else:
            log.debug("Unexpected status %s for address %s", status, address)
            return {"walk_score": None, "transit_score": None, "bike_score": None}

    return {"walk_score": None, "transit_score": None, "bike_score": None}


def already_scored(row: pd.Series) -> bool:
    """True if all score columns are already populated."""
    return all(pd.notna(row.get(c)) for c in SCORE_COLS)


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Enrich parcels with Walk Score data.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N rows (for testing).")
    args = parser.parse_args()

    api_key = os.environ.get("WALKSCORE_API_KEY", "").strip()
    if not api_key:
        log.error("WALKSCORE_API_KEY environment variable is not set.")
        log.error("See https://www.walkscore.com/professional/api.php to obtain a key.")
        sys.exit(1)

    # Load source data
    log.info("Reading %s", IN_FILE)
    df = pd.read_csv(IN_FILE)
    log.info("  %d rows × %d columns", *df.shape)

    # Resume: merge any previously enriched rows
    if OUT_FILE.exists():
        log.info("Found existing output – loading to resume: %s", OUT_FILE)
        enriched = pd.read_csv(OUT_FILE)
        # Use the index (row position) as the join key
        for col in SCORE_COLS:
            if col in enriched.columns:
                df[col] = enriched[col]
        already = df.apply(already_scored, axis=1).sum()
        log.info("  %d rows already have scores; skipping those.", already)
    else:
        for col in SCORE_COLS:
            df[col] = None

    # Optionally cap the total rows to process
    if args.limit:
        df = df.head(args.limit)
        log.info("--limit %d: working on first %d rows only.", args.limit, len(df))

    todo = df[~df.apply(already_scored, axis=1)]
    log.info("%d rows to score.", len(todo))

    if todo.empty:
        log.info("Nothing to do – all rows already scored.")
    else:
        for i, (idx, row) in enumerate(todo.iterrows(), start=1):
            lat = row.get("latitude")
            lon = row.get("longitude")
            if pd.isna(lat) or pd.isna(lon):
                log.debug("Row %d: no coordinates, skipping.", idx)
                continue

            address = build_address(row)
            scores  = fetch_scores(api_key, lat, lon, address)
            for col, val in scores.items():
                df.at[idx, col] = val

            if i % 50 == 0 or i == len(todo):
                log.info("Progress: %d/%d rows scored.", i, len(todo))
                df.to_csv(OUT_FILE, index=False)   # checkpoint save

            time.sleep(SLEEP_SEC)

    # Final save
    df.to_csv(OUT_FILE, index=False)
    log.info("Saved → %s", OUT_FILE)

    # ── Summary ──────────────────────────────────────────────────────────
    scored   = df["walk_score"].notna().sum()
    unscored = df["walk_score"].isna().sum()
    print("\n╔══ WALK SCORE ENRICHMENT SUMMARY ════════════════════════╗")
    print(f"║ Total rows        : {len(df):<36}║")
    print(f"║ Rows scored       : {scored:<36}║")
    print(f"║ Rows without score: {unscored:<36}║")
    if scored:
        for col in SCORE_COLS:
            mean = df[col].mean()
            print(f"║ Avg {col:<17}: {mean:<32.1f}║")
    print(f"║ Output            : {OUT_FILE.name:<36}║")
    print("╚════════════════════════════════════════════════════════╝\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted – partial results saved to %s", OUT_FILE)
        sys.exit(0)
    except Exception as exc:
        log.error("Fatal: %s", exc, exc_info=True)
        sys.exit(1)
