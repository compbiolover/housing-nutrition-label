#!/usr/bin/env python3
"""Utah — all 29 counties from UGRC's per-county LIR parcel layers.

DOCSTRING_PLACEHOLDER
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    address_key, cache_bucket, deadline_from, num, select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

_ORG = "https://services1.arcgis.com/99lidPhWCzftIe9K/arcgis/rest/services"

#: County FIPS → the UGRC service holding that county's LIR parcels. Read off the
#: organisation's services directory, where exactly these 29 ``Parcels_*_LIR``
#: services exist — one per Utah county, so no county is missing. Utah's county
#: codes are the odd numbers 49001–49057 in alphabetical order, which is also the
#: order of UGRC's own ``COUNTY_ID`` (Beaver = 1 … Weber = 29), so the table can be
#: checked against two independent orderings; a test does both.
COUNTY_SERVICES = {
    "49001": "Parcels_Beaver_LIR",
    "49003": "Parcels_BoxElder_LIR",
    "49005": "Parcels_Cache_LIR",
    "49007": "Parcels_Carbon_LIR",
    "49009": "Parcels_Daggett_LIR",
    "49011": "Parcels_Davis_LIR",
    "49013": "Parcels_Duchesne_LIR",
    "49015": "Parcels_Emery_LIR",
    "49017": "Parcels_Garfield_LIR",
    "49019": "Parcels_Grand_LIR",
    "49021": "Parcels_Iron_LIR",
    "49023": "Parcels_Juab_LIR",
    "49025": "Parcels_Kane_LIR",
    "49027": "Parcels_Millard_LIR",
    "49029": "Parcels_Morgan_LIR",
    "49031": "Parcels_Piute_LIR",
    "49033": "Parcels_Rich_LIR",
    "49035": "Parcels_SaltLake_LIR",
    "49037": "Parcels_SanJuan_LIR",
    "49039": "Parcels_Sanpete_LIR",
    "49041": "Parcels_Sevier_LIR",
    "49043": "Parcels_Summit_LIR",
    "49045": "Parcels_Tooele_LIR",
    "49047": "Parcels_Uintah_LIR",
    "49049": "Parcels_Utah_LIR",
    "49051": "Parcels_Wasatch_LIR",
    "49053": "Parcels_Washington_LIR",
    "49055": "Parcels_Wayne_LIR",
    "49057": "Parcels_Weber_LIR",
}
#: Counties whose layer exists but carries nothing this adapter could report.
#: Juab's 15,259 rows have no year built and no wall material at all, and its
#: floor areas come with no one-dwelling evidence — so a lookup there could only
#: spend a second of the label's budget to return nothing. Measured 2026-10-03;
#: drop it from this set the day Juab's rows start carrying BUILT_YR.
_NOTHING_TO_SAY = frozenset({"49023"})
COUNTY_FIPS = frozenset(COUNTY_SERVICES) - _NOTHING_TO_SAY

NAME = "Utah Geospatial Resource Center"
ATTRIBUTION = ("Utah county assessors via UGRC Land Information Records parcels "
               "(State of Utah, SGID; keyless)")
DATA_VINTAGE = "UGRC LIR parcels (county tax-roll attributes)"

#: A template, not a URL: ``{service}`` is the county's entry in COUNTY_SERVICES.
PARCEL_URL = _ORG + "/{service}/FeatureServer/0/query"
#: UGRC's county boundaries, used only when the caller did not say which county
#: the point is in. See ``_county_at``.
COUNTY_URL = _ORG + "/UtahCountyBoundaries/FeatureServer/0/query"

#: How long the service may go quiet before the silence is a stall, and the budget
#: for a whole Utah lookup. Both are the SHARED defaults, kept on purpose and named
#: here only so every request visibly passes them: measured over 153 random homes
#: (see "Timing" in the module docstring) the slowest of all 459 requests took
#: 0.58 s, and the slowest county + containment + buffer triple 1.4 s, so neither
#: Florida's nor Connecticut's longer clock is warranted. Raising them would only
#: let a genuinely hung portal hold the label longer.
READ_SLICE_S = _shared._READ_SLICE_S
LOOKUP_TIMEOUT = _shared.TIMEOUT

# Only what the label scores, plus what decides which building is the home and
# whether its area describes one dwelling. EFFBUILT_YR (effective year), HOUSE_CNT
# (a building count despite its name — see the module docstring), PRIMARY_RES
# (owner-occupancy) and every market value are deliberately absent.
_FIELDS = ("PARCEL_ID,PARCEL_ADD,PROP_CLASS,BUILT_YR,BLDG_SQFT,BLDG_SQFT_INFO,"
           "FLOORS_CNT,CONST_MATERIAL,CURRENT_ASOF")

# The columns that describe one BUILDING, as opposed to the parcel. Two rows of
# one parcel that agree on all of them are the same building repeated — once per
# polygon part of a multipart parcel — not two buildings.
_BUILDING_COLUMNS = ("BUILT_YR", "BLDG_SQFT", "BLDG_SQFT_INFO", "FLOORS_CNT",
                     "CONST_MATERIAL")


class _Truncated(Exception):
    """The service returned only part of what matched (``exceededTransferLimit``)."""


def _norm(value) -> str:
    """Case- and whitespace-insensitive form of a county's free-text category."""
    return " ".join(str(value or "").split()).lower()


# ── which building is the home ─────────────────────────────────────────────────

# The building vocabulary shared by the 20 counties on the common CAMA system
# (Beaver, Cache, Carbon, Daggett, Duchesne, Emery, Garfield, Grand, Iron, Kane,
# Millard, Morgan, Piute, Sanpete, Sevier, Tooele, Uintah, Utah, Wayne, Weber).
# A RESIDENTIAL building card carries an exterior-wall type written
# "<structure>: <cladding>" — "Frame:  Metal Vinyl Siding", "Masonry:  Common
# Brick", and for manufactured homes "2 X 4: Lap Siding". Every other building on a
# parcel carries a bare construction class instead.
#
# Measured in Utah County, the one county that also publishes each building's
# style (in BLDG_SQFT_INFO): every "one_story", "two_story", "split_level",
# "duplex", townhouse and cabin card carries the colon form; every "shed:_wood",
# "detached" (garage), barn, carport, office and warehouse carries a bare class.
_RESIDENTIAL_CARD_PREFIXES = ("frame:", "masonry:", "2 x 4:", "2 x 6:",
                              "wood stresskin panels:")
_NON_DWELLING_CLASSES = frozenset({
    "wood framed", "wood", "steel framed", "steel", "pole framed", "hoop",
    "structural steel", "aluminum", "concrete column-beam", "masonry",
    "wood framed, veneer", "wood slant wall",
})


def _is_residential_card(building: dict) -> bool:
    return _norm(building.get("CONST_MATERIAL")).startswith(_RESIDENTIAL_CARD_PREFIXES)


def _is_non_dwelling_class(building: dict) -> bool:
    return _norm(building.get("CONST_MATERIAL")) in _NON_DWELLING_CLASSES


def _the_dwelling(buildings: list[dict]) -> dict | None:
    """The one building on this parcel that is the home, or None.

    The layer has one row per BUILDING, not per parcel, so a house with a shed and
    a detached garage is three rows. Which of them is the home decides the year
    built, and getting it wrong reports the shed's year as observed fact.

    * Where the county writes residential cards, exactly one must be present: two
      is a house with a second dwelling (an accessory apartment, a cottage), and
      naming either would be a guess; none means the parcel's buildings are all
      sheds, garages or commercial structures as far as the roll says.
    * Elsewhere — Salt Lake's two-letter codes, Washington's vocabulary, the six
      counties that publish no material at all — the parcel must hold exactly one
      building. Measured where those counties do list a second one, it is a second
      house (Salt Lake: a 1918 brick house beside a 2021 frame cottage), not a shed.
    """
    cards = [b for b in buildings if _is_residential_card(b)]
    if cards:
        return cards[0] if len(cards) == 1 else None
    if len(buildings) == 1 and not _is_non_dwelling_class(buildings[0]):
        return buildings[0]
    return None


# ── the parcel-level statements ────────────────────────────────────────────────

# PROP_CLASS values that state the parcel is not anybody's home. A denylist, not
# an allowlist, for the reason Florida's dwelling count is read as it is: an
# explicit "Vacant" or "Commercial - Retail" is the county saying no one lives
# here, while "Unknown", a blank, "Greenbelt" or "Agricultural" says nothing of
# the kind — a farmhouse sits on a greenbelt parcel — and refusing on silence
# would cost Utah County 117,386 "Unknown" rows, its whole multi-unit stock.
_NOT_A_HOME_PREFIXES = ("vacant", "tax exempt", "exempt", "industrial",
                        "centrally assessed", "undeveloped")


def _says_no_home(prop_class) -> bool:
    """Whether PROP_CLASS explicitly says no dwelling stands on this parcel."""
    pc = _norm(prop_class)
    if not pc:
        return False
    if pc.startswith(_NOT_A_HOME_PREFIXES) or pc == "land":
        return True
    # "Commercial - Apartment & Condo" is housing, and so is a mobile home filed as
    # personal property; every other commercial or personal-property class is not.
    if pc.startswith("commercial") and "apartment" not in pc:
        return True
    return pc.startswith("personal property") and "mobile home" not in pc


# Building styles that are one dwelling, as Utah County writes them into
# BLDG_SQFT_INFO. The townhouse styles ("end:", "int:") are one unit on its own
# parcel. Deliberately absent: "duplex", "triplex", "fourplex:_two_story",
# "<n>_unit_building", "multiple_residence" — each is a building with more than
# one home in it, and its floor area is all of them.
_ONE_DWELLING_STYLES = frozenset({
    "one_story", "two_story", "split_level", "bi-level", "one_and_one_half",
    "two_and_one_half", "a-frame", "basement_home", "cabin",
    "end:_one_story", "end:_two_story", "end:_split_level",
    "int:_one_story", "int:_two_story", "int:_split_level",
})
_MANUFACTURED_STYLE_PREFIXES = ("one-section_", "two-section_", "three-section_")

# Stories are read only where the style and FLOORS_CNT agree. Utah County records
# 7,123 "one_story" buildings with FLOORS_CNT of 2 against 63,615 with 1, so
# either column alone is wrong often enough to matter. Split levels, bi-levels and
# half storeys have no whole-number reading — the call Cook makes for "Split
# Level" and "1.5 Story".
_STYLE_STORIES = {
    "one_story": 1, "end:_one_story": 1, "int:_one_story": 1,
    "two_story": 2, "end:_two_story": 2, "int:_two_story": 2,
}


def _one_dwelling_evidence(parcel: dict, building: dict) -> bool:
    """Whether the roll positively says this building is ONE home.

    Two sources say so, and nothing else in the layer does:

    * Utah County's building style (BLDG_SQFT_INFO), and
    * Carbon County's PROP_CLASS "Single Family".

    ``HOUSE_CNT`` — "Number of Housing Units" in the schema — is NOT such a source:
    measured in every county that fills it, it counts the parcel's building rows.
    A house with a shed reads 2; a duplex reads 1. See the module docstring.
    """
    style = _norm(building.get("BLDG_SQFT_INFO"))
    if style in _ONE_DWELLING_STYLES or style.startswith(_MANUFACTURED_STYLE_PREFIXES):
        return True
    return _norm(parcel.get("PROP_CLASS")) == "single family"


def _is_one_home(parcel: dict, building: dict) -> bool:
    """Whether the building's area and storey count describe the reader's home."""
    return (_one_dwelling_evidence(parcel, building)
            and not unit_of(parcel.get("PARCEL_ADD"))
            and not _says_no_home(parcel.get("PROP_CLASS")))


def _area(parcel: dict, building: dict) -> float | None:
    area = num(building.get("BLDG_SQFT"))
    if area is None or area <= 0 or not _is_one_home(parcel, building):
        return None
    return area


def _stories(parcel: dict, building: dict) -> int | None:
    if not _is_one_home(parcel, building):
        return None
    floors = num(building.get("FLOORS_CNT"))
    if floors is None or floors <= 0 or not float(floors).is_integer():
        return None
    style = _norm(building.get("BLDG_SQFT_INFO"))
    if style:
        # A style is published: it and the floor count must agree, and a style
        # with no whole-number reading (split level, bi-level) yields nothing.
        return int(floors) if _STYLE_STORIES.get(style) == int(floors) else None
    return int(floors)


# ── construction ───────────────────────────────────────────────────────────────

# County wording → the label's vocabulary, keyed on the normalised string. The
# UGRC schema says only that values "are expected to vary greatly by county", and
# publishes no code table (gis.utah.gov/products/sgid/cadastre/parcels/, and the
# LIR Implementation Guidelines linked there), so every entry is a wording that
# names its own structure. Anything absent is dropped; see the comment below.
_CONSTRUCTION = {
    # The common CAMA vocabulary: "<structure>: <cladding>".
    "frame: metal vinyl siding": "frame",       # metal OR vinyl: frame either way
    "frame: stucco or cement fiber siding": "frame",
    "frame: synth plaster (eifs)": "frame",
    "frame: wood siding": "frame",
    "frame: plywood hardboard": "frame",
    "frame: wood shingles or shake": "frame",
    "frame: brick veneer": "brick-frame",
    "masonry: common brick": "brick",
    "masonry: concrete block": "block",
    "masonry: stucco on block": "block",
    # Washington and Box Elder: "<structure> <cladding>", no colon.
    "frame syn plaster": "frame",
    "frame stucco": "frame",
    "frame siding": "frame",
    "frame hardboard": "frame",
    "frame aluminum": "frame",
    "frame plywood": "frame",
    "frame shingle": "frame",
    "frame vinyl": "vinyl",
    "frame brick veneer": "brick-frame",
    "masonry common brick": "brick",
    "masonry face brick": "brick",
    "masonry concrete block": "block",
    "masonry stucco block": "block",
    "masonry stone": "stone",
}
# Deliberately unmapped, each for a reason rather than by omission:
#
#   Frame: Masonry Veneer,      a framed wall with a brick OR stone face. The
#   Frame Masonry Veneer        label has brick-frame and no stone-frame, so the
#                               face material is a guess (DC's "Stone Veneer" call)
#   Frame: Stone Veneer         no stone-frame value; `stone` asserts solid masonry
#   Masonry: Face Brick Or      brick or stone, and the two are different values
#     Stone
#   Masonry: Poured Concrete,   cast concrete is not concrete block, the only
#     8" / 6" Concrete          concrete value the label has
#   Frame: Rustic Log, log      no log value in the label's vocabulary
#     diameters, Pine cabins,
#     Log, Finished Cottage
#   Frame: Other                the structure is named, the cladding is not, and
#                               the label's frame/vinyl/brick-frame split is the
#                               cladding
#   2 X 4: / 2 X 6: / Wood      manufactured-home walls. Stud-framed, but `frame`
#     Stresskin Panels: …       would score a manufactured home as a site-built
#                               frame house; the label has no manufactured value
#   Hardboard Sheet, Lap        Washington's walls with no structure named
#     Siding, Metal Siding,
#     Ribbed Aluminum, Cement
#     Fiber Sheet, Stucco
#   Wood Frame (Wasatch)        the county's single value for every building it
#                               has, so it is a default rather than an observation
#   Salt Lake's two-letter      the only published table (the Assessor's
#     codes (SO, BR, AL, …)     commercial-record field descriptions) lacks four of
#                               the codes residential rows carry — SC, MT, AS, CP —
#                               so it is not the table these rows were written
#                               against; and its BR ("Brick") would not say solid
#                               brick from brick veneer even if it were
#   the bare classes (Wood      the construction class of a shed, garage or
#     Framed, Steel Framed, …)  commercial building, never of a residential card


def _construction(building: dict) -> str | None:
    return _CONSTRUCTION.get(_norm(building.get("CONST_MATERIAL")))


# ── the parcel ─────────────────────────────────────────────────────────────────


def _parcel_id(row: dict) -> str | None:
    pid = str(row.get("PARCEL_ID") or "").strip()
    return pid or None


def _parcel_of(pid: str, rows: list[dict]) -> dict | None:
    """One candidate parcel from all the building rows that carry its id, or None.

    Each row repeats the parcel's own fields (address, class, vintage) beside one
    building's. A parcel whose rows disagree about the parcel-level facts — two
    different street addresses, two different property classes — is a join the
    roll got wrong somewhere, and confirming it against an address it may not have
    is the wrong-house failure Connecticut's contradictory rows taught; so it is
    not offered at all.
    """
    keys = {address_key(r.get("PARCEL_ADD")) for r in rows}
    keys.discard(None)
    classes = {_norm(r.get("PROP_CLASS")) for r in rows}
    if len(keys) > 1 or len(classes) > 1:
        return None
    address = next((r.get("PARCEL_ADD") for r in rows
                    if address_key(r.get("PARCEL_ADD"))), None)
    buildings, seen = [], set()
    for r in rows:
        key = tuple(r.get(c) for c in _BUILDING_COLUMNS)
        if key not in seen:
            seen.add(key)
            buildings.append({c: r.get(c) for c in _BUILDING_COLUMNS})
    asof = [v for v in (num(r.get("CURRENT_ASOF")) for r in rows) if v]
    return {"PARCEL_ID": pid, "PARCEL_ADD": address,
            "PROP_CLASS": rows[0].get("PROP_CLASS"),
            "CURRENT_ASOF": max(asof) if asof else None,
            "buildings": buildings}


def _query(url: str, lat: float, lon: float, distance_m: float,
           *, deadline: float) -> list[dict]:
    """Rows at (or within ``distance_m`` of) a point, refusing a partial answer.

    The same request ``_shared.arcgis_parcels`` makes, through the same shared
    transport, with one addition that helper cannot provide: it reads
    ``exceededTransferLimit``. These layers cap a response at 2,000 rows and write
    one row per building per polygon part — Weber has a parcel with 527 building
    rows — so an 80 m buffer downtown can be cut short. A cut-short candidate list
    is worse than an empty one: if it drops the second of two parcels sharing a
    street address, the survivor looks unique and is confirmed. So a truncated
    answer is no answer.
    """
    params = {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "inSR": "4326", "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": _FIELDS, "returnGeometry": "false", "f": "json",
    }
    if distance_m:
        params["distance"] = str(distance_m)
        params["units"] = "esriSRUnit_Meter"
    body = _shared.get_json(url, params, deadline, READ_SLICE_S) or {}
    if body.get("exceededTransferLimit"):
        raise _Truncated(url)
    return [(f or {}).get("attributes") or {} for f in (body.get("features") or [])]


def _parcels(url: str, lat: float, lon: float, distance_m: float = 0,
             *, deadline: float) -> list[dict]:
    """Candidate parcels at (or within ``distance_m`` of) a point.

    Rows are grouped by PARCEL_ID before the parcel is chosen. Without it a house
    with a shed is two rows under one coordinate, which ``select_parcel``
    correctly calls ambiguous — and refuses the most ordinary house in the state.
    Grouping is the sanctioned shape for this, the same as dropping a placeholder
    (see ``select_parcel``): it can only turn "ambiguous" into "one real parcel",
    since rows carrying one PARCEL_ID are one tax parcel, and the address check
    that follows is untouched. Rows with no id are records of nothing and dropped.
    """
    by_id: dict[str, list[dict]] = {}
    for row in _query(url, lat, lon, distance_m, deadline=deadline):
        pid = _parcel_id(row)
        if pid is not None:
            by_id.setdefault(pid, []).append(row)
    parcels = (_parcel_of(pid, rows) for pid, rows in by_id.items())
    return [p for p in parcels if p is not None]


def _county_at(lat: float, lon: float, *, deadline: float) -> str | None:
    """The FIPS of the Utah county this point is in, from UGRC's boundaries.

    Needed because the registry hands an adapter a coordinate and an address but
    not the county it routed on, and Utah's records are 29 separate services. One
    small request against a 29-polygon layer; skipped entirely when the caller
    passes the county.
    """
    body = _shared.get_json(COUNTY_URL, {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FIPS_STR", "returnGeometry": "false", "f": "json",
    }, deadline, READ_SLICE_S) or {}
    found = {str((f or {}).get("attributes", {}).get("FIPS_STR") or "").strip()
             for f in (body.get("features") or [])}
    found &= COUNTY_FIPS
    return found.pop() if len(found) == 1 else None


def _parcel_at(lat: float, lon: float, address: str | None = None,
               county_fips: str | None = None,
               *, deadline: float | None = None) -> dict | None:
    """The parcel this point belongs to, or None.

    The choice itself is ``_shared.select_parcel``'s; see it for why the nearest
    parcel is never taken. No locality trim is needed: PARCEL_ADD is the street
    address alone ("3854 S 800 W"), with the city in its own column.
    """
    deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    if fips not in COUNTY_FIPS:
        fips = _county_at(lat, lon, deadline=deadline)
    if fips is None:
        return None
    url = PARCEL_URL.format(service=COUNTY_SERVICES[fips])
    return select_parcel(lambda d: _parcels(url, lat, lon, d, deadline=deadline),
                         address, lambda p: p.get("PARCEL_ADD"))


def _vintage(parcel: dict) -> str:
    """What this record reflects, dated from the row's own CURRENT_ASOF.

    The counties deliver on their own schedules and the date is genuinely per
    county: Salt Lake's rows are current as of 2026, most counties' as of late
    2025, and Box Elder's as of July 2020. A hard-coded year would present a
    six-year-old roll at the confidence of this year's.
    """
    ms = num(parcel.get("CURRENT_ASOF"))
    if ms:
        try:
            day = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return DATA_VINTAGE
        if 1990 <= day.year <= 2100:
            return f"{DATA_VINTAGE}, current as of {day.isoformat()}"
    return DATA_VINTAGE


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   county_fips: str | None = None,
                   _bucket: int = 0) -> AssessorRecord | None:
    try:
        parcel = _parcel_at(lat, lon, address, county_fips)
    except _Truncated:
        # Too many rows to see them all: an answer ("cannot tell which"), not an
        # outage, so it is neither noted as dropped nor kept out of the cache.
        return None
    if not parcel:
        return None
    building = _the_dwelling(parcel["buildings"])
    if building is None:
        return None

    year = num(building.get("BUILT_YR"))
    # 0 is the county's "not recorded", not the year zero. And a parcel whose class
    # says no one lives there reports no year: a shop's year built is not the year
    # the reader's home went up.
    year_built = int(year) if (year and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100
                               and not _says_no_home(parcel.get("PROP_CLASS"))) else None
    sqft = _area(parcel, building)
    stories = _stories(parcel, building)
    construction = (_construction(building)
                    if not _says_no_home(parcel.get("PROP_CLASS")) else None)
    if year_built is None and sqft is None and stories is None and construction is None:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(parcel),
        parcel_id=parcel["PARCEL_ID"],
        year_built=year_built,
        sqft=sqft,
        stories=stories,
        construction=construction,
        # No foundation or condition column exists in the LIR schema.
    )


def lookup(lat: float, lon: float, address: str | None = None,
           county_fips: str | None = None) -> AssessorRecord | None:
    """What Utah's county rolls say is standing at this point, or None.

    ``address`` is the geocoder's matched address, used only to confirm the
    parcel. ``county_fips`` is optional: the registry does not pass it today, and
    without it the county is looked up from the point (one extra request).

    Fails open on everything. The caller then keeps whatever it had, which is the
    behaviour that existed before this adapter.
    """
    try:
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              county_fips, cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Utah assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
