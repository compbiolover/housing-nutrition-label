#!/usr/bin/env python3
"""Walk Score data model library for parcel enrichment.

Importable helpers that build parcel addresses and fetch walk/transit/bike
scores from the Walk Score API. No batch/CLI runner.

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

import logging, sys, time, urllib.parse
import requests, pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
API_URL    = "https://api.walkscore.com/score"
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
