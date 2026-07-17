#!/usr/bin/env python3
"""FEMA flood-zone lookup library.

Queries the FEMA National Flood Hazard Layer for the flood zone at a
coordinate and classifies it into a simplified risk label. Import
``fetch_flood_zone`` to look up a single point.

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

import json, logging, time
import requests, pandas as pd

# Module logger only — no logging.basicConfig() at import time: this is library
# code imported by the API/simulator, and reconfiguring the root logger on import
# would clobber the host application's logging setup.
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
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
