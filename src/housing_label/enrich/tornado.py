#!/usr/bin/env python3
"""FEMA National Risk Index tornado hazard model library.

Importable lookup functions that resolve a parcel's FEMA NRI tornado hazard
(EAL rate + risk rating) from its census tract. No batch/CLI runner.

Data source
-----------
  FEMA National Risk Index (NRI) — tornado expected annual loss, bundled offline
  by ``scripts/build_nri_tornado.py`` and read through ``data/tornado.py``.

  Each parcel resolves tract → county → national average, yielding a tornado
  **EAL rate** (fraction of building value lost to tornadoes per year). This is the
  location-based tornado hazard that ``score/resilience.py`` folds into the EAL
  model alongside flood, seismic, and fire.

  This replaces the old NOAA SPC touchdown-count model, which counted historical
  tornadoes within 25 miles and applied a single **TN/Mid-South EF-magnitude
  distribution (Ashley 2007) nationally** — so a Great Plains home was scored with
  Mid-South intensities. NRI's EAL rate reflects the **local** frequency *and* the
  **local** historic building-loss ratio, so "tornado alley" carries a much higher
  EAL than a low-risk area (~30× in the raw data) where the old model could not
  tell them apart.

  A parcel's 11-digit ``census_tract`` GEOID (added by the health enrichment)
  resolves at tract precision; without it the lookup falls back to the county
  (Shelby = 47157) — uniform across Shelby, which is a single county — then the
  national average.

Columns added
-------------
  tornado_nri_eal_rate    NRI tornado EAL rate (fraction/yr), tract→county→US
  tornado_risk_rating     FEMA qualitative tornado risk rating (e.g. "Very High")
  tornado_geo_level       geography that answered: tract / county / us
"""

from __future__ import annotations

import pandas as pd

from housing_label.data.tornado import tornado_for_county, tornado_for_tract

# All Shelby County parcels share this county FIPS — the fallback when a parcel
# has no resolvable census tract.
SHELBY_COUNTY_FIPS = "47157"

TORNADO_COLS = ["tornado_nri_eal_rate", "tornado_risk_rating", "tornado_geo_level"]


def _norm_tract(census_tract) -> str | None:
    """Normalise a raw census_tract value to an 11-digit GEOID string, or None.

    Mirrors ``enrich/fire._norm_tract`` so the join key matches the crosswalk
    everywhere: a tract column with any missing value makes pandas store the GEOID
    as a float (e.g. ``47157006300.0``), and tracts outside TN have leading zeros
    (e.g. ``06037...``). Strip any decimal suffix and zero-pad back to 11 digits so
    the value matches rather than silently falling back to the county/US rate.
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
    """Resolve one parcel's tornado hazard from its census tract (county fallback)."""
    tract = _norm_tract(census_tract)
    if tract:
        return tornado_for_tract(tract)
    return tornado_for_county(county_fips)
