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
from collections import Counter
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


# ── Multi-unit auto-detection thresholds ──────────────────────────────────────
# NSI mislabels many garden-apartment complexes as clusters of single-family
# structures (verified: 3720 Spruce Ridge Way, Knoxville → 30 structures sharing
# one 1,332 sqft footprint, zero RES3). Validated against Knoxville/LA/Montpelier
# NSI samples: single-family addresses show ≤2 identical footprints and few/no
# RES3, while apartment/condo sites show 13–30 identical footprints or 15+ RES3.
# (See research/dense-housing-research.md.) Structure *density* is deliberately NOT
# used as a signal — a dense small-town single-family street matches an apartment
# complex on that axis (false positives).
_CLUSTER_MIN = 8         # ≥ this many residential structures sharing one footprint
_RES3_DISTRICT_MIN = 15  # ≥ this many RES3 (multi-family) structures in the box
_DEFAULT_MF_UNITS = 8    # representative unit-count estimate when NSI gives no count


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _nsi_query(lat: float, lon: float, half: float) -> list[dict]:
    """Query NSI for a box around the point; return the list of feature property
    dicts (empty on failure / no structures). NOT cached — the caller caches the
    small computed result instead of the large feature list."""
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
            return [f.get("properties") or {} for f in feats]
        except Exception:  # noqa: BLE001
            if attempt == RETRIES:
                return []
            time.sleep(BACKOFF ** attempt)
    return []


def _estimate_units(res3: list[dict]) -> int:
    """Best-effort unit-count estimate for a heuristically detected multi-family
    site: the median Hazus RES3 bin among any nearby RES3 structures, else a
    representative default. Always flagged ``units_confidence="estimated"``."""
    bins = sorted(b for b in (_units_for(p.get("occtype"), p.get("resunits"))
                              for p in res3) if b)
    return int(bins[len(bins) // 2]) if bins else _DEFAULT_MF_UNITS


def _result(props: dict, structure_type, num_units, *, units_confidence, detection,
            drop_shell: bool = False) -> dict:
    """Assemble the structure result dict from the addressed structure's props.

    ``drop_shell`` clears the material/stories for a heuristically detected site,
    where the nearest structure is a mislabeled house and its shell is unreliable."""
    stories = _num(props.get("num_story"))
    yr = _num(props.get("med_yr_blt"))
    material = _MATERIAL.get((props.get("bldgtype") or "").upper(), "other")
    return {
        "structure_type": structure_type,
        "num_units": num_units,
        "stories": None if drop_shell else (int(stories) if stories else None),
        "sqft": _num(props.get("sqft")),
        "bldg_material": None if drop_shell else material,
        "occtype": props.get("occtype"),
        "year_built": int(yr) if yr else None,
        "source": "NSI",
        "detection": detection,
        "units_confidence": units_confidence,
    }


@lru_cache(maxsize=4096)
def _structure_at(lat: float, lon: float, allow_network: bool) -> dict | None:
    """Resolve the building at a rounded coordinate. Caches the small result dict
    (not the feature list), so repeat coordinates are free without holding NSI
    feature collections in memory."""
    if not allow_network:
        return None
    # Try the narrow box, then widen once — including when the narrow query returned
    # features but none had usable centroids (else those incomplete features would
    # short-circuit the wider query that might have valid ones).
    return (_classify_site(_nsi_query(lat, lon, _BOX_DEG), lat, lon)
            or _classify_site(_nsi_query(lat, lon, _BOX_DEG_WIDE), lat, lon))


def _classify_site(props_list: list[dict], lat: float, lon: float) -> dict | None:
    """Classify the site from a box of NSI features, or None if none are usable."""
    if not props_list:
        return None

    def d2(p: dict) -> float:
        try:
            return (float(p["y"]) - lat) ** 2 + (float(p["x"]) - lon) ** 2
        except (KeyError, TypeError, ValueError):
            return float("inf")

    nearest = min(props_list, key=d2)
    if d2(nearest) == float("inf"):     # no usable coordinates → can't identify a structure
        return None
    nearest_type = _classify(nearest.get("occtype"))

    # A genuine RES3 at the address → reliable multi-family detection.
    if nearest_type == "multifamily":
        return _result(nearest, "multifamily",
                       _units_for(nearest.get("occtype"), nearest.get("resunits")),
                       units_confidence="detected", detection="nsi")

    # Otherwise inspect the whole site. NSI often models an apartment complex as a
    # cluster of identical single-family footprints, or the addressed building is a
    # RES3 that just isn't the nearest centroid — either pattern is a multi-unit
    # site the nearest-structure classification alone would miss.
    res = [p for p in props_list if str(p.get("occtype", "")).upper().startswith("RES")]
    res1 = [p for p in res if str(p.get("occtype", "")).upper().startswith("RES1")]
    res3 = [p for p in res if str(p.get("occtype", "")).upper().startswith("RES3")]
    # Count identical footprints among RES1 only — the mislabel signature is NSI
    # modeling an apartment complex as a cluster of single-family (RES1) structures.
    # RES3 density is handled as the separate district signal below, so it is not
    # folded into the footprint count (which would broaden it into false positives).
    footprints = Counter(round(v) for v in (_num(p.get("sqft")) for p in res1) if v)
    cluster = footprints.most_common(1)[0][1] if footprints else 0
    if cluster >= _CLUSTER_MIN or len(res3) >= _RES3_DISTRICT_MIN:
        return _result(nearest, "multifamily", _estimate_units(res3),
                       units_confidence="estimated", detection="nsi-cluster",
                       drop_shell=True)

    # Single-family / manufactured / other — classify from the addressed structure.
    return _result(nearest, nearest_type,
                   _units_for(nearest.get("occtype"), nearest.get("resunits")),
                   units_confidence="detected", detection="nsi")


def structure_for_point(lat: float, lon: float,
                        allow_network: bool = True) -> dict | None:
    """Return the building at (lat, lon) from NSI, or None if unavailable.

    Beyond the nearest structure's Hazus occupancy class, this recognizes a
    multi-unit *site* the nearest-structure classification alone would miss: an
    identical-footprint cluster (NSI's signature for a templated apartment complex
    it modeled as single-family structures) or a dense RES3 district. In those
    cases ``units_confidence`` is ``"estimated"`` and ``detection`` is
    ``"nsi-cluster"``, and the shell material/height are left unset (the nearest
    structure is a mislabeled house).

    Result keys: ``structure_type`` (single_family | manufactured | multifamily |
    other_residential | non_residential), ``num_units``, ``stories``, ``sqft``,
    ``bldg_material``, ``occtype`` (raw Hazus), ``year_built``, ``source``,
    ``detection`` (``nsi`` | ``nsi-cluster``), ``units_confidence`` (``detected`` |
    ``estimated``).
    """
    if not allow_network:
        return None
    return _structure_at(round(float(lat), 5), round(float(lon), 5), allow_network)
