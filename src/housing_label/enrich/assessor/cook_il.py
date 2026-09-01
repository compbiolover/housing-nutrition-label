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

from housing_label.enrich.assessor._shared import (
    arcgis_parcels, cache_bucket, deadline_from, get_json, num, select_parcel,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

COUNTY_FIPS = frozenset({"17031"})          # Cook County, IL
NAME = "Cook County Assessor"
ATTRIBUTION = "Cook County Assessor's Office (Open Data, keyless)"
DATA_VINTAGE = "Cook County Assessor iasWorld improvement characteristics (refreshed bi-weekly)"

PARCEL_URL = ("https://gis.cookcountyil.gov/traditional/rest/services"
              "/CookViewer3Parcels/MapServer/0/query")
CAMA_URL = "https://datacatalog.cookcountyil.gov/resource/x54s-btds.json"

# County wording → the label's vocabulary. Anything absent here is dropped; see
# the module docstring for which values that is and why.
# "Masonry" is the county's single category for all solid masonry; the label
# distinguishes brick, block and stone. It is mapped to `brick` as the class that
# dominates Cook County residential masonry, which makes this the one genuinely
# LOSSY entry in this table rather than a transcription — block and stone houses
# are read as brick. It is kept, rather than dropped under the map-only-unambiguous
# rule, because the alternative is NSI's coarse 5-class guess for 45% of the
# county's stock, which is less accurate rather than more honest. The cost is paid
# instead in confidence: see TRANSLATED in base.py.
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
# "3 Story +" is deliberately absent. It is a bucket with an open top, and
# recording it as exactly 3 would report a precise observed height for every 4-
# and 6-storey building in it — inventing a fact rather than transcribing one, and
# understating the multi-family flood-floor adjustment while carrying the
# "observed" tag that tells a reader not to doubt it. Same reasoning as "1.5
# Story" and "Split Level": the label's field is a whole-number storey count and
# these three categories do not answer it.
_STORIES = {"1 Story": 1, "2 Story": 2}


def _parcels(lat: float, lon: float, distance_m: float = 0,
             *, deadline: float) -> list[dict]:
    """Parcel attributes at (or within ``distance_m`` of) a point."""
    return arcgis_parcels(PARCEL_URL, lat, lon, "PIN14,street_address",
                          distance_m, deadline=deadline)


def _clean_pin(attrs: dict) -> str | None:
    pin = attrs.get("PIN14")
    pin = str(pin).strip() if pin is not None else ""
    # The county's own guidance: PINs lose leading zeros in some exports, so
    # zero-pad before using one as a key.
    return pin.zfill(14) if pin and pin.lower() != "none" else None


def _pin_at(lat: float, lon: float, address: str | None = None,
            *, deadline: float | None = None) -> str | None:
    """Hop 1: the PIN of the parcel this point belongs to, or None.

    The selection policy — containment confirmed by address, then an
    address-anchored buffer — is shared; see ``_shared.select_parcel`` for why it
    is shaped that way. Cook's parcel layer keeps the city in its own column, so
    ``street_address`` is already free of a locality tail and no trim is needed.
    """
    deadline = deadline_from(deadline)
    chosen = select_parcel(
        lambda d: _parcels(lat, lon, d, deadline=deadline),
        address, lambda a: a.get("street_address"))
    return _clean_pin(chosen) if chosen else None


def _assessment_year(row: dict) -> str | None:
    """The assessment roll a characteristics row belongs to, as a plain year."""
    raw = str(row.get("year") or "").strip()
    year = raw.split(".")[0]
    return f"{year} roll" if year.isdigit() and len(year) == 4 else None


def _characteristics(pin: str, *, deadline: float | None = None) -> dict | None:
    """Hop 2: the newest assessment year's primary card for this PIN."""
    rows = get_json(CAMA_URL, {
        "pin": pin,
        "$select": ("pin,year,card,char_yrblt,char_bldg_sf,char_ext_wall,"
                    "char_bsmt,char_repair_cnd,char_type_resd"),
        "$order": "year DESC, card ASC",
        "$limit": "1",
    }, deadline_from(deadline))
    return rows[0] if rows else None


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    deadline = deadline_from(None)
    pin = _pin_at(lat, lon, address, deadline=deadline)
    if not pin:
        return None
    row = _characteristics(pin, deadline=deadline)
    if not row:
        return None

    year = num(row.get("char_yrblt"))
    sqft = num(row.get("char_bldg_sf"))
    # A year of 0 is the county's "not recorded", not the year zero; the same for
    # a zero floor area. Both would otherwise reach the scorer as facts.
    return AssessorRecord(
        source=ATTRIBUTION,
        # The row carries the assessment year it belongs to, and the query
        # deliberately picks the newest. Storing only the generic refresh note
        # would tell a reader the value is observed without letting them date it,
        # and the roll advances underneath the same wording — so the selected year
        # travels with it when the row has one.
        data_vintage=(f"{DATA_VINTAGE}, {_roll}" if (_roll := _assessment_year(row))
                      else DATA_VINTAGE),
        parcel_id=pin,
        year_built=int(year) if year and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100 else None,
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
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Cook County assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
