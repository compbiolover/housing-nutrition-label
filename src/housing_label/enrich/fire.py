#!/usr/bin/env python3
"""FEMA National Risk Index wildfire-hazard model library.

Resolves a parcel's census tract to a wildfire expected-annual-loss (EAL) rate
for the resilience model. Importable functions only; no batch runner.

Data source
-----------
  FEMA National Risk Index (NRI) — wildfire expected annual loss, bundled offline
  by ``scripts/build_nri_wildfire.py`` and read through ``data/wildfire.py``.

  Each parcel's 11-digit ``census_tract`` GEOID (added upstream by the health
  enrichment) is resolved tract → county → national average, yielding a wildfire
  **EAL rate** (fraction of building value lost to wildfire per year). This is the
  location-based "fire" hazard that ``score/resilience.py`` folds into the EAL
  model alongside flood, tornado, and seismic — replacing the old flat
  national-average fire constant.

  Memphis / Shelby County is uniformly low wildfire hazard, so values here are
  small; the same enrichment gives a fire-prone Western county a materially
  higher rate. Parcels without a resolved tract fall back to the county
  (Shelby = 47157), then the national average.

Columns added
-------------
  wildfire_eal_rate       NRI wildfire EAL rate (fraction/yr), tract→county→US
  wildfire_risk_rating    FEMA qualitative wildfire risk rating (e.g. "Very Low")
  wildfire_geo_level      geography that answered: tract / county / us
"""

from __future__ import annotations

import pandas as pd

from housing_label.data.wildfire import wildfire_for_county, wildfire_for_tract

# All Shelby County parcels share this county FIPS — the fallback when a parcel
# has no resolvable census tract.
SHELBY_COUNTY_FIPS = "47157"

FIRE_COLS = ["wildfire_eal_rate", "wildfire_risk_rating", "wildfire_geo_level"]


def _norm_tract(census_tract) -> str | None:
    """Normalise a raw census_tract value to an 11-digit GEOID string, or None.

    Mirrors ``enrich/health._clean_tract`` so the join key matches the crosswalk
    everywhere: a tract column with any missing value makes pandas store the GEOID
    as a float (e.g. ``47157006300.0``), and tracts outside TN have leading zeros
    (e.g. ``06037...``). Strip any decimal suffix and zero-pad back to 11 digits
    so the value matches rather than silently falling back to the county/US rate.
    """
    if census_tract is None or pd.isna(census_tract):
        return None
    s = str(census_tract).strip()
    if s.lower() in ("nan", "none", ""):
        return None
    if "." in s:                       # stringified/numpy float, e.g. "47157006300.0"
        s = s.split(".")[0]
    return s.zfill(11)


def _lookup(census_tract, county_fips: str = SHELBY_COUNTY_FIPS) -> dict:
    """Resolve one parcel's wildfire hazard from its census tract (county fallback)."""
    tract = _norm_tract(census_tract)
    if tract:
        return wildfire_for_tract(tract)
    return wildfire_for_county(county_fips)
