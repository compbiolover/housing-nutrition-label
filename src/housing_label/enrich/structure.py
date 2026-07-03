#!/usr/bin/env python3
"""Building structure lookup — what *kind* of building sits at a lat/lon.

The scoring engine was built on single-family detached parcels and otherwise has
no idea whether an address is a house, a townhome, a stacked condo, or a 200-unit
apartment building. This module resolves that from the **USACE National Structure
Inventory (NSI)** — a keyless national dataset (~123M structures) with, per
building, a FEMA Hazus occupancy class, residential unit count, stories, square
footage, construction material, and year built.

Source: the NSI web API (keyless), queried with a small polygon around the point;
the nearest structure to the geocoded location is returned. Network/API failure
degrades gracefully to ``None`` (the caller keeps its single-family default), so
this is a best-effort enrichment, never a hard dependency.

Occupancy classes (Hazus): RES1 = single-family, RES2 = manufactured home,
RES3A–RES3F = multi-family binned by unit count (2, 3–4, 5–9, 10–19, 20–49, 50+),
RES4–RES6 = lodging / institutional, COM*/IND*/… = non-residential.
"""

from __future__ import annotations

import time
from functools import lru_cache

import requests

from housing_label.config import TIMEOUT, RETRIES, BACKOFF, HEADERS

NSI_URL = "https://nsi.sec.usace.army.mil/nsiapi/structures"

# Half-width (degrees) of the query box around the point (~110 m); widened once
# if the first query finds nothing.
_BOX_DEG = 0.0010
_BOX_DEG_WIDE = 0.0028

# Hazus RES3 sub-class → representative residential unit count, used only when the
# NSI ``resunits`` field is missing.
_RES3_UNITS = {"RES3A": 2, "RES3B": 3, "RES3C": 7, "RES3D": 14, "RES3E": 30, "RES3F": 75}

# NSI ``bldgtype`` code → human material.
_MATERIAL = {"W": "wood", "M": "masonry", "C": "concrete", "S": "steel",
             "H": "manufactured", "MH": "manufactured"}


def _classify(occtype: str) -> str:
    """Hazus occupancy string → coarse structure_type category."""
    occ = (occtype or "").upper()
    if occ.startswith("RES1"):
        return "single_family"
    if occ.startswith("RES2"):
        return "manufactured"
    if occ.startswith("RES3"):
        return "multifamily"
    if occ.startswith(("RES4", "RES5", "RES6")):
        return "other_residential"
    return "non_residential"


def _units_for(occtype: str, resunits) -> int | None:
    """Best residential unit count: NSI ``resunits`` if present, else the RES3 bin."""
    try:
        n = int(round(float(resunits)))
        if n > 0:
            return n
    except (TypeError, ValueError):
        pass
    return _RES3_UNITS.get((occtype or "").upper()[:5])


@lru_cache(maxsize=2048)
def _nsi_nearest(lat: float, lon: float, half: float) -> dict | None:
    """Query NSI for structures in a box around the point; return the nearest
    feature's properties dict, or None on failure / no structures."""
    d = half
    # NSI's bbox is a closed polygon ring of lon,lat pairs (not a min/max box).
    ring = [(lon - d, lat - d), (lon - d, lat + d), (lon + d, lat + d),
            (lon + d, lat - d), (lon - d, lat - d)]
    bbox = ",".join(f"{x:.5f},{y:.5f}" for x, y in ring)
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(NSI_URL, params={"fmt": "fc", "bbox": bbox},
                             headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            feats = (r.json() or {}).get("features") or []
            if not feats:
                return None
            # Nearest structure centroid (planar distance is fine at this scale).
            def d2(f: dict) -> float:
                p = f.get("properties") or {}
                try:
                    return (float(p["y"]) - lat) ** 2 + (float(p["x"]) - lon) ** 2
                except (KeyError, TypeError, ValueError):
                    return float("inf")
            return (min(feats, key=d2).get("properties") or {})
        except Exception:  # noqa: BLE001
            if attempt == RETRIES:
                return None
            time.sleep(BACKOFF ** attempt)
    return None


def structure_for_point(lat: float, lon: float,
                        allow_network: bool = True) -> dict | None:
    """Return the building at (lat, lon) from NSI, or None if unavailable.

    The result dict carries:
      ``structure_type`` (single_family | manufactured | multifamily |
      other_residential | non_residential), ``num_units``, ``stories``, ``sqft``,
      ``bldg_material``, ``occtype`` (raw Hazus), ``year_built``, ``source``.
    """
    if not allow_network:
        return None
    la, lo = round(float(lat), 5), round(float(lon), 5)
    props = _nsi_nearest(la, lo, _BOX_DEG) or _nsi_nearest(la, lo, _BOX_DEG_WIDE)
    if not props:
        return None

    occ = props.get("occtype")

    def _num(key):
        v = props.get(key)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    stories = _num("num_story")
    yr = _num("med_yr_blt")
    return {
        "structure_type": _classify(occ),
        "num_units": _units_for(occ, props.get("resunits")),
        "stories": int(stories) if stories else None,
        "sqft": _num("sqft"),
        "bldg_material": _MATERIAL.get((props.get("bldgtype") or "").upper(), "other"),
        "occtype": occ,
        "year_built": int(yr) if yr else None,
        "source": "NSI",
    }
