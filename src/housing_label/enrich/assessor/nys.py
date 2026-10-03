#!/usr/bin/env python3
"""New York State — the 33 opt-in counties outside New York City, in a single request.

PLACEHOLDER DOCSTRING — filled in after measurement.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    SUFFIXES, address_key, arcgis_parcels, cache_bucket, deadline_from, num,
    same_address, select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

COUNTY_FIPS = frozenset({
    "36001",   # Albany
    "36007",   # Broome
    "36011",   # Cayuga
    "36013",   # Chautauqua
    "36023",   # Cortland
    "36029",   # Erie
    "36037",   # Genesee
    "36039",   # Greene
    "36041",   # Hamilton
    "36049",   # Lewis
    "36051",   # Livingston
    "36057",   # Montgomery
    "36065",   # Oneida
    "36067",   # Onondaga
    "36069",   # Ontario
    "36071",   # Orange
    "36075",   # Oswego
    "36077",   # Otsego
    "36079",   # Putnam
    "36083",   # Rensselaer
    "36087",   # Rockland
    "36089",   # St. Lawrence
    "36097",   # Schuyler
    "36101",   # Steuben
    "36103",   # Suffolk
    "36105",   # Sullivan
    "36107",   # Tioga
    "36109",   # Tompkins
    "36111",   # Ulster
    "36113",   # Warren
    "36117",   # Wayne
    "36119",   # Westchester
    "36121",   # Wyoming
})

NAME = "NYS ITS Geospatial Services"
ATTRIBUTION = ("New York county and municipal assessors via NYS ORPTS and NYS ITS "
               "Geospatial Services (public tax parcels, keyless)")
DATA_VINTAGE = "NYS public tax parcels (ORPTS assessment roll joined to county parcel maps)"

PARCEL_URL = ("https://nysgeohub.ny.gov/arcgis/rest/services/Parcels"
              "/NYS_Tax_Parcels_Public/FeatureServer/1/query")

_FIELDS = ("SWIS_SBL_ID,SBL,PARCEL_ADDR,LOC_ST_NBR,LOC_STREET,LOC_UNIT,PROP_CLASS,"
           "YR_BLT,SQFT_LIVING,NBR_KITCHENS,ROLL_YR")

_ORDINALS = {
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th",
    "sixth": "6th", "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th",
    "eleventh": "11th", "twelfth": "12th", "thirteenth": "13th",
    "fourteenth": "14th", "fifteenth": "15th", "sixteenth": "16th",
    "seventeenth": "17th", "eighteenth": "18th", "nineteenth": "19th",
    "twentieth": "20th",
}
_DIRECTIONS = {"north": "N", "south": "S", "east": "E", "west": "W"}
_TYPE_SPELLINGS = {"la": "Ln", "terr": "Ter"}
_STREET_TYPES = frozenset(SUFFIXES) | frozenset(_TYPE_SPELLINGS)
_LOCALITY_TAILS = tuple(tuple(p.split()) for p in (
    "NEW CITY", "NANUET", "CONGERS", "WEST NYACK", "W NYACK", "W NYK",
    "VALLEY COTTAGE", "VALLEY COTTAG", "VALLEY COTTA", "VALLEY COTT", "VALL COTT",
    "VLY CTG", "BARDONIA", "UPPER NYACK", "U NYACK", "U NYK", "CENTRAL NYACK",
    "C NYACK", "CENTRAL NYK", "SPRING VALLEY", "SPR VLY",
))

UNIQUENESS_RADIUS_M = 500

_NON_DWELLING_CATEGORIES = frozenset("35789")
_DWELLING_EXCEPTIONS = frozenset({"480", "481", "482", "483"})


def _parcel_id(attrs: dict) -> str | None:
    pid = str(attrs.get("SWIS_SBL_ID") or "").strip()
    return pid or None


def _base_tokens(raw: str) -> list[str]:
    tokens = raw.replace("'", "").replace("\u2019", "").split()
    for tail in _LOCALITY_TAILS:
        n = len(tail)
        if (len(tokens) > n + 1
                and tuple(t.upper() for t in tokens[-n:]) == tail
                and tokens[-n - 1].lower() in _STREET_TYPES):
            tokens = tokens[:-n]
            break
    if tokens and tokens[-1].lower() in _TYPE_SPELLINGS:
        tokens = tokens[:-1] + [_TYPE_SPELLINGS[tokens[-1].lower()]]
    return tokens


def _numeral_ordinal(tokens: list[str]) -> list[str] | None:
    if len(tokens) >= 2 and tokens[-1].lower() in SUFFIXES \
            and tokens[-2].lower() in _ORDINALS:
        return tokens[:-2] + [_ORDINALS[tokens[-2].lower()], tokens[-1]]
    return None


def _abbreviate_leading_direction(tokens: list[str]) -> list[str] | None:
    if len(tokens) >= 3 and tokens[0].lower() in _DIRECTIONS:
        return [_DIRECTIONS[tokens[0].lower()]] + tokens[1:]
    return None


def _lead_trailing_direction(tokens: list[str]) -> list[str] | None:
    if len(tokens) >= 3 and tokens[-2].lower() in SUFFIXES:
        word = tokens[-1].lower()
        abbr = _DIRECTIONS.get(word) or (word.upper() if word in ("n", "s", "e", "w") else None)
        if abbr:
            return [abbr] + tokens[:-1]
    return None


def _street_spellings(raw: str) -> list[str]:
    spellings = [_base_tokens(raw)]
    for transform in (_numeral_ordinal, _abbreviate_leading_direction,
                      _lead_trailing_direction):
        for tokens in list(spellings):
            changed = transform(tokens)
            if changed and changed not in spellings:
                spellings.append(changed)
    return [" ".join(t) for t in spellings if t]


def _address_for(attrs: dict, query: str | None) -> str | None:
    number = str(attrs.get("LOC_ST_NBR") or "").strip()
    street = str(attrs.get("LOC_STREET") or "").strip()
    if not (number and street):
        return (str(attrs.get("PARCEL_ADDR") or "").strip()) or None
    spellings = [f"{number} {s}" for s in _street_spellings(street)]
    if not spellings:
        return None
    if query:
        for spelling in spellings:
            if same_address(query, spelling):
                return spelling
    return spellings[0]


def _address_of(attrs: dict) -> str | None:
    return _address_for(attrs, None)


def _norm_unit(raw) -> str:
    text = " ".join(str(raw or "").upper().replace("#", " # ").split())
    for marker in ("UNIT ", "APT ", "STE ", "SUITE ", "# "):
        if text.startswith(marker):
            text = text[len(marker):]
            break
    return "".join(ch for ch in text if ch.isalnum())


def _same_fact_key(attrs: dict) -> tuple:
    return (str(attrs.get("SBL") or "").strip(), _address_of(attrs),
            attrs.get("YR_BLT"), attrs.get("SQFT_LIVING"),
            attrs.get("PROP_CLASS"), attrs.get("NBR_KITCHENS"))


def _candidates(rows: list[dict], unit: str | None) -> list[dict]:
    rows = [r for r in rows if _parcel_id(r) is not None]
    if unit:
        wanted = _norm_unit(unit)
        rows = [r for r in rows if _norm_unit(r.get("LOC_UNIT")) in ("", wanted)]
    seen, out = set(), []
    for r in rows:
        key = _same_fact_key(r)
        if key[0] and key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _parcels(lat: float, lon: float, distance_m: float = 0, unit: str | None = None,
             *, deadline: float) -> list[dict]:
    rows = arcgis_parcels(PARCEL_URL, lat, lon, _FIELDS, distance_m,
                          deadline=deadline)
    return _candidates(rows, unit)


def _same_number_nearby(lat: float, lon: float, number: str, unit: str | None,
                        *, deadline: float) -> list[dict]:
    body = _shared.get_json(PARCEL_URL, {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "inSR": "4326", "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "distance": str(UNIQUENESS_RADIUS_M), "units": "esriSRUnit_Meter",
        "where": f"LOC_ST_NBR='{number}' OR PARCEL_ADDR LIKE '{number} %'",
        "outFields": _FIELDS, "returnGeometry": "false", "f": "json",
    }, deadline)
    rows = [(f or {}).get("attributes") or {}
            for f in ((body or {}).get("features") or [])]
    return _candidates(rows, unit)


def _address_is_unique(lat: float, lon: float, address: str, chosen: dict,
                       unit: str | None, *, deadline: float) -> bool:
    key = address_key(address)
    if not key or not key[0].isdigit():
        return False
    ids = {_parcel_id(r)
           for r in _same_number_nearby(lat, lon, key[0], unit, deadline=deadline)
           if same_address(address, _address_for(r, address))}
    ids.add(_parcel_id(chosen))
    return len(ids) == 1


def _parcel_at(lat: float, lon: float, address: str | None = None,
               *, deadline: float | None = None) -> dict | None:
    deadline = deadline_from(deadline)
    unit = unit_of(address)
    chosen = select_parcel(
        lambda d: _parcels(lat, lon, d, unit, deadline=deadline),
        address, lambda attrs: _address_for(attrs, address))
    if chosen is None or not address:
        return chosen
    return chosen if _address_is_unique(lat, lon, address, chosen, unit,
                                        deadline=deadline) else None


def _vintage(row: dict) -> str:
    year = num(row.get("ROLL_YR"))
    if year and 1900 <= year <= 2100:
        return f"{DATA_VINTAGE}, {int(year)} assessment roll"
    return DATA_VINTAGE


def _has_residential_inventory(row: dict) -> bool:
    area = num(row.get("SQFT_LIVING"))
    kitchens = num(row.get("NBR_KITCHENS"))
    return bool((area and area > 0) or (kitchens and kitchens >= 1))


def _class_says_no_dwelling(prop_class) -> bool:
    code = str(prop_class or "").strip()
    if len(code) != 3 or not code.isdigit():
        return False
    if code == "105":
        return True
    if code[0] in _NON_DWELLING_CATEGORIES:
        return True
    if code[0] == "4":
        return code[:2] != "41" and code not in _DWELLING_EXCEPTIONS
    if code[0] == "6":
        return code[:2] != "63"
    return False


def _says_a_home_is_here(row: dict) -> bool:
    return _has_residential_inventory(row) or not _class_says_no_dwelling(
        row.get("PROP_CLASS"))


def _area_of_one_home(row: dict) -> float | None:
    area = num(row.get("SQFT_LIVING"))
    if area is None or area <= 0:
        return None
    if str(row.get("PROP_CLASS") or "").strip() != "210":
        return None
    kitchens = num(row.get("NBR_KITCHENS"))
    if kitchens is not None and kitchens >= 2:
        return None
    return area


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    row = _parcel_at(lat, lon, address)
    if not row:
        return None
    year = num(row.get("YR_BLT"))
    year_built = int(year) if (year and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100
                               and _says_a_home_is_here(row)) else None
    sqft = _area_of_one_home(row)
    if year_built is None and sqft is None:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(row),
        parcel_id=_parcel_id(row),
        year_built=year_built,
        sqft=sqft,
    )


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    try:
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("New York State assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
