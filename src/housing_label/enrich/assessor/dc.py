"""Washington, DC — observed parcel construction from the District's own CAMA table.

The second adapter, and the one that decides whether the registry is a seam or just
Cook County with extra steps. Everything dangerous — picking the right parcel from
an interpolated geocode, comparing two addresses, bounding the request budget — is
in ``_shared`` and is not reimplemented here. What is left is exactly what should
differ between jurisdictions: two endpoints, a join key, and a translation.

The chain, verified live and keyless:

1. ``Owner Polygons (Common Ownership Layer)`` — point in polygon → ``SSL``
   (square-suffix-lot, the District's parcel id) and ``PREMISEADD``.
2. ``RESIDENTIAL (CAMA)`` — ``SSL`` → ``AYB``, ``GBA``, ``STORIES``, ``EXTWALL_D``,
   ``CNDTN_D``, ``NUM_UNITS``.

Condominium units take a second chain, for the reason given under "Two kinds of
address" below:

3. ``RESIDENTIAL UNITS`` — ``PRIMARY_ADDRESS`` + ``UNIT_NUMBER`` → ``CONDO_SSL``.
4. ``CONDOMINIUM (CAMA)`` — that SSL → ``AYB`` and ``LIVING_GBA``.

Two things differ from Cook in ways worth knowing
-------------------------------------------------
**The parcel layer carries owner data.** Cook's CAMA split meant the characteristics
table held no owner name or mailing address at all. DC's parcel layer holds
``OWNERNAME``, ``ADDRESS1``, ``CAREOFNAME``, sale prices and tax balances beside the
geometry. None of that is an input to any dimension, so the field list is explicit
and narrow and this adapter never requests ``*``. The safeguard Cook got from its
source's schema, this one has to provide itself.

**The wall vocabulary is finer than the label's, not coarser.** Cook publishes one
"Masonry" category that had to be flattened onto ``brick``, losing block and stone.
DC distinguishes twenty-six exterior wall types, including the veneer-versus-
structural difference the label's ``brick-frame`` value exists for — so ``Brick
Veneer`` maps to a framed wall with a brick face rather than to solid masonry, which
is what it actually is.

**Two kinds of address, and only one of them is a place.** A house is somewhere a
coordinate can land. A condominium unit is not: its SSL never appears in the parcel
polygons — those hold the building — so no point-in-polygon can pick unit 305 out of
a stack of forty. That is a property of the District's schema, and it is why roughly
a third of DC's housing stock was unreachable here: 61,329 condominium records
against 109,273 residential.

The District publishes the missing edge keylessly in the same MapServer, so the
condo lookup runs off the address instead of the point, and the unit number the
reader typed is the only thing that can identify their home. Without one there is no
lookup — every unit in the building shares the street address, and answering with
one of them would be the same confident guess as taking the nearest parcel, which
``select_parcel`` exists to refuse. So the parcel path is asked first and its answer
is never second-guessed; the condominium path runs only where point-in-polygon found
no residential record, which is what a condo address looks like from the parcel
layer.

A condo record carries less and more than a house's. Less: the condominium table has
no exterior wall, no storey count and no condition, and those stay absent rather
than being borrowed from the building the unit sits in — a different structure's
record. More: ``LIVING_GBA`` is the unit's own floor area, where the residential
table's ``GBA`` is the whole building's and has to be dropped on a multi-unit parcel.

Not covered
-----------
There is no basement or foundation column in either table. That field is simply not
among the ones this county contributes; the autofill applies what an adapter returns
per field, so NSI's estimate stands for it.

The published accuracy figures do not cover the condominium path. The benchmark is
drawn from the residential table, so the measurement describes houses only — see
``scripts/jurisdictions.py``. Serving a path is not the same as having measured it.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

from housing_label.enrich.assessor._shared import (
    address_key, arcgis_parcels, cache_bucket, deadline_from, get_json, num,
    same_address, select_parcel,
)
from housing_label.enrich.assessor.base import AssessorRecord

log = logging.getLogger(__name__)

COUNTY_FIPS = frozenset({"11001"})          # District of Columbia
NAME = "DC Office of Tax and Revenue"
ATTRIBUTION = "DC Office of Tax and Revenue (Open Data DC, keyless)"
DATA_VINTAGE = "DC OTR Computer Assisted Mass Appraisal — residential"
CONDO_VINTAGE = "DC OTR Computer Assisted Mass Appraisal — condominium"

_BASE = ("https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA"
         "/Property_and_Land_WebMercator/MapServer")
PARCEL_URL = f"{_BASE}/40/query"
CAMA_URL = f"{_BASE}/25/query"

# Only what the label scores. The parcel layer also carries owner names, owner
# mailing addresses and tax balances; requesting them would put personal data in a
# cache for no benefit to any dimension.
_PARCEL_FIELDS = "SSL,PREMISEADD"
_CAMA_FIELDS = "SSL,AYB,GBA,STORIES,EXTWALL_D,CNDTN_D,NUM_UNITS"

# The parcel layer runs the whole mailing address into PREMISEADD with no comma —
# "3401 NEWARK ST NW WASHINGTON DC 20016" — so the comparison needs to know where
# the street stops. The quadrant (NW/NE/SW/SE) is kept: in a quadrant city it is
# part of the street's identity, not a decoration.
_LOCALITY = frozenset({"washington", "dc"})

# District wording → the label's vocabulary. Anything absent is dropped rather than
# approximated; see the module docstring for the rule.
#
# The veneer entries are the point of this table. A brick or stone VENEER is a
# framed wall wearing a masonry face: it has the thermal mass and the seismic
# behaviour of frame, not of solid masonry, and calling it `brick` would tell the
# durability and resilience models the opposite of the truth about the structure.
_EXT_WALL = {
    "Common Brick": "brick",
    "Face Brick": "brick",
    "Brick Veneer": "brick-frame",
    "Brick/Siding": "brick-frame",
    "Stone": "stone",
    # Both halves are solid masonry, and the label has no combined class. Read as
    # brick, which dominates DC masonry — the same knowingly LOSSY call the Cook
    # adapter makes for its single "Masonry" category, and paid for the same way,
    # in confidence rather than coverage (see TRANSLATED). It is the largest
    # unmapped group in the city at ~4% of stock; the alternative is NSI's coarse
    # guess for those, which is less accurate rather than more honest.
    "Brick/Stone": "brick",
    "Concrete Block": "block",
    "Stucco Block": "block",
    "Vinyl Siding": "vinyl",
    # Siding is cladding, and cladding of these kinds is hung on a framed wall.
    "Wood Siding": "frame",
    "Shingle": "frame",
    "Hardboard": "frame",
    "Plywood": "frame",
    "Aluminum": "frame",
    "Metal Siding": "frame",
}
# Deliberately unmapped, and each for a reason rather than by omission:
#
#   Stucco, SPlaster      stucco is applied over frame AND over masonry, so it says
#                         nothing about the structure — the same call Cook's adapter
#                         makes for its own Stucco category
#   Concrete              cast concrete is not concrete block, and `block` is the
#                         only concrete value the label has
#   Stone Veneer          a framed wall with a stone face; the label has brick-frame
#                         but no stone-frame, and `stone` would assert solid masonry
#   Brick/Stone,          genuinely mixed walls with no dominant system to name
#   Brick/Stucco,
#   Stone/Siding,
#   Stone/Stucco
#   Adobe, Rustic Log     no equivalent in the label's vocabulary
#   No Data, ""           the District's own "not recorded"

# DC grades condition on a six-step scale that lines up with the label's almost
# exactly — a translation with far less loss than Cook's three-value collapse.
# "Very Good" has no counterpart and is read DOWN to `good` rather than up to
# `excellent`: where the scales disagree, the reading that claims less wins.
_CONDITION = {
    "Excellent": "excellent",
    "Very Good": "good",
    "Good": "good",
    "Average": "average",
    "Fair": "fair",
    "Poor": "poor",
}


def _parcels(lat: float, lon: float, distance_m: float = 0,
             *, deadline: float) -> list[dict]:
    return arcgis_parcels(PARCEL_URL, lat, lon, _PARCEL_FIELDS,
                          distance_m, deadline=deadline)


def _ssl_at(lat: float, lon: float, address: str | None = None,
            *, deadline: float | None = None) -> str | None:
    """The SSL of the parcel this point belongs to, or None.

    The selection policy is shared; see ``_shared.select_parcel`` for why it refuses
    a nearest-parcel match. Measured here too: the Census geocoder puts 3401 Newark
    St NW twenty metres off its own parcel, in the roadway, with twenty-six parcels
    inside the search radius — so the address, not the distance, has to decide.
    """
    deadline = deadline_from(deadline)
    chosen = select_parcel(
        lambda d: _parcels(lat, lon, d, deadline=deadline),
        address, lambda a: a.get("PREMISEADD"), _LOCALITY)
    if not chosen:
        return None
    ssl = str(chosen.get("SSL") or "").strip()
    return ssl or None


def _characteristics(ssl: str, *, deadline: float | None = None) -> dict | None:
    """The residential CAMA row for this parcel, or None."""
    body = get_json(CAMA_URL, {
        # Quoting is safe because SSL comes from the parcel layer's own response,
        # not from user input; the apostrophe strip is belt and braces against a
        # malformed record breaking the predicate.
        "where": f"SSL='{ssl.replace(chr(39), '')}'",
        "outFields": _CAMA_FIELDS, "returnGeometry": "false", "f": "json",
    }, deadline_from(deadline))
    feats = (body or {}).get("features") or []
    return ((feats[0] or {}).get("attributes") or None) if feats else None


# --- condominium units ---------------------------------------------------------
#
# A condo unit is not reachable from a coordinate. Its SSL never appears in the
# parcel polygons — those hold the building — so no point-in-polygon can pick unit
# 305 out of a stack of forty. That is a property of the schema, not of this code,
# and it is why the residential path returns nothing for roughly a third of DC's
# housing stock.
#
# The District does publish the missing edge, keylessly, in the same MapServer:
# RESIDENTIAL UNITS carries FULL_ADDRESS, PRIMARY_ADDRESS, UNIT_NUMBER and the
# unit's own CONDO_SSL. So the lookup is address-driven rather than point-driven —
# the unit number the reader typed is the only thing that can identify their home,
# and it has to come from them.
UNITS_URL = f"{_BASE}/68/query"
CONDO_CAMA_URL = f"{_BASE}/24/query"
_UNITS_FIELDS = "PRIMARY_ADDRESS,UNIT_NUMBER,CONDO_SSL"
# LIVING_GBA is the unit's own area, unlike the residential table's GBA, which is
# the whole building's. So a condo reports floor area where a multi-unit
# non-condo parcel has to drop it.
_CONDO_FIELDS = "SSL,AYB,LIVING_GBA"

# "#305", "APT 305", "UNIT 305" — and a bare trailing token, which is how DC's own
# unit table writes it ("2123 CALIFORNIA STREET NW D7").
_UNIT_MARKER_RE = re.compile(
    r"[\s,]+(?:#|apt\.?|unit|ste\.?|suite)\s*([A-Za-z0-9\-]+)\s*$", re.I)
_BARE_UNIT_RE = re.compile(
    r"^(?P<base>.*\b(?:nw|ne|sw|se))\s+(?P<unit>[A-Za-z]?\d+[A-Za-z]?|[A-Za-z]\d*)\s*$",
    re.I)


def _split_unit(address: str | None) -> tuple[str, str | None]:
    """``(building address, unit)`` — the unit being None when none was given.

    A condo lookup without a unit is not a lookup: every unit in the building
    shares the street address, and picking one would be the same confident guess
    as taking the nearest parcel. So the absence is reported, not filled in.
    """
    text = " ".join(str(address or "").split())
    if not text:
        return "", None
    m = _UNIT_MARKER_RE.search(text)
    if m:
        return text[:m.start()].strip(" ,"), m.group(1)
    m = _BARE_UNIT_RE.match(text)
    if m:
        return m.group("base").strip(), m.group("unit")
    return text, None


def _same_unit(a: str | None, b: str | None) -> bool:
    """Whether two unit designators are the same one.

    Case and punctuation vary between what a reader types and what the District
    records ("#3-B", "3B"). Nothing else is normalised: leading zeros stay
    significant because unit 01 and unit 1 can both exist in one building.
    """
    def norm(v):
        return "".join(ch for ch in str(v or "").upper() if ch.isalnum())
    return bool(norm(a)) and norm(a) == norm(b)


def _condo_ssl(base: str, unit: str, *, deadline: float | None = None) -> str | None:
    """The SSL of this unit, or None — never a guess at which unit was meant.

    The query is narrowed by house number so the response stays small, and the
    decision is made here rather than in the predicate: the address is compared
    with the same matcher the parcel path uses, and the unit must match exactly
    one row. Two rows claiming the unit is an ambiguity, not a tie to break.
    """
    key = address_key(base, _LOCALITY)
    if not key:
        return None
    number = key[0].replace("'", "")
    body = get_json(UNITS_URL, {
        "where": (f"PRIMARY_ADDRESS LIKE '{number} %' "
                  f"AND UNIT_TYPE='CONDO' AND STATUS='ACTIVE'"),
        "outFields": _UNITS_FIELDS, "returnGeometry": "false", "f": "json",
    }, deadline_from(deadline))
    hits = []
    for feat in (body or {}).get("features") or []:
        a = (feat or {}).get("attributes") or {}
        if not same_address(base, a.get("PRIMARY_ADDRESS"), _LOCALITY):
            continue
        if _same_unit(unit, a.get("UNIT_NUMBER")) and (a.get("CONDO_SSL") or "").strip():
            hits.append(a["CONDO_SSL"].strip())
    return hits[0] if len(set(hits)) == 1 else None


def _condo_characteristics(ssl: str, *, deadline: float | None = None) -> dict | None:
    body = get_json(CONDO_CAMA_URL, {
        "where": f"SSL='{ssl.replace(chr(39), '')}'",
        "outFields": _CONDO_FIELDS, "returnGeometry": "false", "f": "json",
    }, deadline_from(deadline))
    feats = (body or {}).get("features") or []
    return ((feats[0] or {}).get("attributes") or None) if feats else None


def _condo_record(address: str | None, *, deadline: float | None = None):
    """The District's record of one condominium unit, or None.

    Reports year built and the unit's own floor area, and nothing else: the
    condominium table records no exterior wall, no storey count and no condition,
    so those stay absent rather than being borrowed from the building.
    """
    base, unit = _split_unit(address)
    if not (base and unit):
        return None
    ssl = _condo_ssl(base, unit, deadline=deadline)
    if not ssl:
        return None
    row = _condo_characteristics(ssl, deadline=deadline)
    if not row:
        return None
    year = num(row.get("AYB"))
    area = num(row.get("LIVING_GBA"))
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=CONDO_VINTAGE,
        parcel_id=ssl,
        year_built=int(year) if year and 1800 <= year <= 2100 else None,
        sqft=area if area and area > 0 else None,
    )


def _stories(raw) -> int | None:
    """A whole-number storey count, or None.

    DC records storeys as a float, and a 2.5-storey house is a real and common
    thing here. The label's field is a whole number, so a half storey is not
    rounded into one — the same call the Cook adapter makes for "1.5 Story".
    """
    v = num(raw)
    return int(v) if v is not None and v > 0 and float(v).is_integer() else None


def _residential_record(lat: float, lon: float, address: str | None,
                        *, deadline: float | None = None) -> AssessorRecord | None:
    """The District's record of the house standing on this parcel, or None."""
    ssl = _ssl_at(lat, lon, address, deadline=deadline)
    if not ssl:
        return None
    row = _characteristics(ssl, deadline=deadline)
    if not row:
        return None

    year = num(row.get("AYB"))
    gba = num(row.get("GBA"))
    units = num(row.get("NUM_UNITS"))
    # GBA is the WHOLE building's gross area and the label's sqft is per dwelling
    # unit. On a multi-unit parcel they are different quantities, so the field is
    # dropped rather than divided by a count that would still leave gross area
    # standing in for living area.
    if units is not None and units > 1:
        gba = None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=DATA_VINTAGE,
        parcel_id=ssl,
        # AYB, not EYB. EYB is the "effective" year built the District uses for
        # depreciation — it moves when a property is improved, so it is a statement
        # about condition, not about when the building went up. The label asks for
        # the second.
        year_built=int(year) if year and 1800 <= year <= 2100 else None,
        sqft=gba if gba and gba > 0 else None,
        stories=_stories(row.get("STORIES")),
        construction=_EXT_WALL.get((row.get("EXTWALL_D") or "").strip()),
        condition=_CONDITION.get((row.get("CNDTN_D") or "").strip()),
    )


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    """The parcel first, then the unit — never the unit instead of the parcel.

    The two paths answer for disjoint halves of the District's stock, and the
    parcel path is the one that can be reached from a coordinate alone. So it is
    asked first and its answer is never second-guessed: the condominium lookup
    runs only where point-in-polygon found no residential record, which is what a
    condo address looks like from the parcel layer. Nothing an existing caller
    already gets can change shape.
    """
    deadline = deadline_from(None)
    record = _residential_record(lat, lon, address, deadline=deadline)
    if record is not None:
        return record
    return _condo_record(address, deadline=deadline)


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What the District says is standing at this point, or None.

    Fails open on everything, like every adapter: a timeout, a 500, a reorganised
    layer, a parcel with no residential row. The caller then keeps whatever it had.
    """
    try:
        # Round before the cache so two clicks on the same rooftop share an entry.
        # 5 dp is ~1 m — finer than a parcel, coarse enough to be a useful key.
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("DC assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
