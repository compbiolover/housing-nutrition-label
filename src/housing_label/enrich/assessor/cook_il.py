#!/usr/bin/env python3
"""Cook County, Illinois — assessor characteristics at a point (keyless, two hops).

Cook County is the first adapter because it publishes more of the label than any
other free source in the country: not just a year built and a floor area, but the
exterior wall, the basement type and an assessed condition — three fields
``research/parcel-level-data-research.md`` records as unobtainable at national
scale *at any price*. ~1.9M parcels, refreshed bi-weekly, no API key.

The chain, verified live
------------------------
The characteristics table is keyed on the 14-digit PIN, not on a coordinate, so
resolving a point takes two hops:

  1. **Point → PIN.** ``CookViewer3Parcels/MapServer/0``, an ArcGIS parcel
     polygon layer, point-in-polygon at 4326. Returns ``PIN14``.
  2. **PIN → characteristics.** Socrata dataset ``x54s-btds``
     ("Assessor - Single and Multi-Family Improvement Characteristics"),
     filtered to that PIN.

Both are keyless and public.

Two things about the source that are easy to get wrong
------------------------------------------------------
**``year`` is the assessment year, not the build year.** The table runs 1999 to
present and carries a row per PIN *per assessment year* — 30M+ rows for 1.9M
parcels. Reading an arbitrary row gives a characteristics snapshot that may be
two decades stale, so the query sorts descending and takes the newest. The build
year is ``char_yrblt``, which is a different column entirely.

**A PIN can have several cards.** ``pin_is_multicard`` marks a parcel with more
than one improvement (a house plus a coach house, say). The label scores one
dwelling, so the first card of the newest year is used and the rest ignored;
``card`` is ordered so this is the primary improvement rather than an arbitrary
one.

Fields deliberately left unmapped
---------------------------------
Per the rule in ``base.py`` — leaving a field None costs nothing, guessing wrong
scores the wrong house:

* ``char_ext_wall = "Stucco"`` (~1.6% of rows). Stucco is a cladding, not a
  structure; it sits over frame in most of this stock and over masonry in some,
  and the label's ``construction`` is asking which. Unmapped.
* ``char_type_resd`` values ``"1.5 Story"`` and ``"Split Level"``. The label's
  ``stories`` is a whole number feeding a geometry model, and neither of these
  is one. Unmapped — the other characteristics on those parcels still come
  through.

``char_heat`` and ``char_air`` are read by nothing in the label today, so they
are not requested; when an HVAC input appears they are already here.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import requests

from housing_label.enrich.assessor.base import AssessorRecord

log = logging.getLogger(__name__)

COUNTY_FIPS = frozenset({"17031"})          # Cook County, IL
NAME = "Cook County Assessor"
ATTRIBUTION = "Cook County Assessor's Office (Open Data, keyless)"
DATA_VINTAGE = "Cook County Assessor iasWorld improvement characteristics (refreshed bi-weekly)"

PARCEL_URL = ("https://gis.cookcountyil.gov/traditional/rest/services"
              "/CookViewer3Parcels/MapServer/0/query")
CAMA_URL = "https://datacatalog.cookcountyil.gov/resource/x54s-btds.json"

# Two hops share one budget. The hosted API allows ~12 s for a whole upstream and
# this is a nicety on the critical path, so it gets a fraction of that and no
# retries — a slow county portal must cost a visitor a moment, not a page.
TIMEOUT = 4.0

# How far from an interpolated geocode to look for the parcel whose street address
# matches. Sized from the observed error: the Barrington case misses by 38 m, and
# a 20 m buffer there does not reach the right parcel. It is safe to be generous
# because distance does not decide anything — the house number does.
SEARCH_RADIUS_M = 80

HEADERS = {"User-Agent": "housing-nutrition-label (assessor adapter)"}

# County wording → the label's vocabulary. Anything absent here is dropped; see
# the module docstring for which values that is and why.
_EXT_WALL = {
    "Frame": "frame",
    "Masonry": "brick",
    "Frame + Masonry": "brick-frame",
}
_BASEMENT = {
    "Full": "full-basement",
    "Partial": "partial-basement",
    "Crawl": "crawl",
    "Slab": "slab",
}
# The county records three grades against its own valuation baseline. They are
# mapped to the middle of the label's six-point scale rather than its extremes:
# "Below Average" is an assessor's relative note, not a claim that a house is
# derelict, and "poor"/"unsound" carry damage multipliers this source does not
# support.
_CONDITION = {
    "Above Average": "good",
    "Average": "average",
    "Below Average": "fair",
}
_STORIES = {"1 Story": 1, "2 Story": 2, "3 Story +": 3}


# Street-type suffixes dropped before comparing two addresses. Directionals are
# NOT dropped: "213 W Main" and "213 E Main" are different houses, and a match
# that ignored the W would be exactly the confident-but-wrong answer this whole
# confirmation step exists to prevent.
_SUFFIXES = frozenset({
    "st", "street", "ave", "avenue", "rd", "road", "dr", "drive", "ln", "lane",
    "ct", "court", "blvd", "boulevard", "pl", "place", "way", "ter", "terrace",
    "pkwy", "parkway", "cir", "circle", "hwy", "highway", "trl", "trail",
})
# Everything from a unit marker onwards is dropped: the parcel layer writes
# "234 W STATION ST B12" for one condo, and a unit number must not decide whether
# two records describe the same building.
_UNIT_MARKERS = frozenset({"apt", "unit", "ste", "suite", "#", "fl", "floor", "rm"})


def _addr_key(raw: str | None) -> tuple[str, frozenset] | None:
    """(house number, street-name tokens) for comparison, or None if unusable.

    Deliberately strict on the number and lenient on everything else: the number
    is what separates 213 W Main from the 205 and 209 that can sit closer to an
    interpolated geocode, so it must match exactly, while the suffix and any unit
    are noise that differs between two records of the same house.
    """
    if not raw:
        return None
    head = str(raw).split(",")[0].strip().lower()
    tokens = [t.strip(".") for t in head.replace("#", " # ").split() if t.strip(".")]
    if not tokens or not tokens[0].isdigit():
        return None                       # no house number → nothing to anchor on
    number, rest = tokens[0], tokens[1:]
    out = []
    for t in rest:
        if t in _UNIT_MARKERS:
            break
        if t in _SUFFIXES:
            continue
        out.append(t)
    return (number, frozenset(out)) if out else None


def _same_address(a: str | None, b: str | None) -> bool:
    ka, kb = _addr_key(a), _addr_key(b)
    if ka is None or kb is None:
        return False
    # Number identical, and one street-name token set contains the other — which
    # tolerates "MAIN" vs "MAIN ST N" style extra words without letting a
    # different street through.
    return ka[0] == kb[0] and (ka[1] <= kb[1] or kb[1] <= ka[1])


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parcels(lat: float, lon: float, distance_m: float = 0) -> list[dict]:
    """Parcel attributes at (or within ``distance_m`` of) a point."""
    params = {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "outFields": "PIN14,street_address", "returnGeometry": "false", "f": "json",
    }
    if distance_m:
        params["distance"] = str(distance_m)
        params["units"] = "esriSRUnit_Meter"
    r = requests.get(PARCEL_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return [(f or {}).get("attributes") or {} for f in ((r.json() or {}).get("features") or [])]


def _clean_pin(attrs: dict) -> str | None:
    pin = attrs.get("PIN14")
    pin = str(pin).strip() if pin is not None else ""
    # The county's own guidance: PINs lose leading zeros in some exports, so
    # zero-pad before using one as a key.
    return pin.zfill(14) if pin and pin.lower() != "none" else None


def _pin_at(lat: float, lon: float, address: str | None = None) -> str | None:
    """Hop 1: the PIN of the parcel this point belongs to, or None.

    Point-in-polygon first. That is the only unambiguous answer and it is the one
    used wherever it exists.

    It frequently does not exist. The Census geocoder interpolates a large share of
    addresses along the street centerline, which lands the point in the roadway
    between parcels — measured at 213 W Main St, Barrington: the geocode falls 38 m
    from the parcel and hits no polygon at all. Widening to the nearest parcel is
    the obvious repair and it is wrong: at a 10 m buffer the two nearest parcels
    there are 205 and 209, and a nearest-match would have reported a neighbour's
    1881 house as this address's, tagged "observed" with high confidence. That is a
    worse answer than the tract typical it would replace.

    So the buffer is only used with the geocoder's own matched address in hand, and
    a parcel is accepted only when its street address agrees on the house number.
    No address, or no agreement, or more than one agreeing parcel → None.
    """
    exact = _parcels(lat, lon)
    if len(exact) == 1:
        return _clean_pin(exact[0])
    if len(exact) > 1 or not address:
        # Overlapping parcels are ambiguous, and without an address there is
        # nothing to disambiguate a buffer with.
        return None
    hits = [a for a in _parcels(lat, lon, SEARCH_RADIUS_M)
            if _same_address(address, a.get("street_address"))]
    return _clean_pin(hits[0]) if len(hits) == 1 else None


def _characteristics(pin: str) -> dict | None:
    """Hop 2: the newest assessment year's primary card for this PIN."""
    r = requests.get(CAMA_URL, params={
        "pin": pin,
        "$select": ("pin,year,card,char_yrblt,char_bldg_sf,char_ext_wall,"
                    "char_bsmt,char_repair_cnd,char_type_resd"),
        "$order": "year DESC, card ASC",
        "$limit": "1",
    }, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    rows = r.json() or []
    return rows[0] if rows else None


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None) -> AssessorRecord | None:
    pin = _pin_at(lat, lon, address)
    if not pin:
        return None
    row = _characteristics(pin)
    if not row:
        return None

    year = _num(row.get("char_yrblt"))
    sqft = _num(row.get("char_bldg_sf"))
    # A year of 0 is the county's "not recorded", not the year zero; the same for
    # a zero floor area. Both would otherwise reach the scorer as facts.
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=DATA_VINTAGE,
        parcel_id=pin,
        year_built=int(year) if year and 1800 <= year <= 2100 else None,
        sqft=sqft if sqft and sqft > 0 else None,
        stories=_STORIES.get((row.get("char_type_resd") or "").strip()),
        construction=_EXT_WALL.get((row.get("char_ext_wall") or "").strip()),
        foundation=_BASEMENT.get((row.get("char_bsmt") or "").strip()),
        condition=_CONDITION.get((row.get("char_repair_cnd") or "").strip()),
    )


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What Cook County says is standing at this point, or None.

    ``address`` is the geocoder's matched address, used only to confirm a parcel
    when the point itself lands off-parcel; see :func:`_pin_at`. Without it the
    lookup still works wherever the geocode falls inside a polygon.

    Fails open on everything: a timeout, a 500, a reorganised layer, a PIN with
    no characteristics row. The caller then keeps whatever it had, which is the
    behaviour that existed before this adapter.
    """
    try:
        # Round before the cache so two clicks on the same rooftop share an entry.
        # 5 dp is ~1 m — finer than a parcel, coarse enough to be a useful key.
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address)
    except Exception as exc:  # noqa: BLE001
        log.debug("Cook County assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
