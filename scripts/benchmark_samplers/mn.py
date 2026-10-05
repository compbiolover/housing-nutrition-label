"""Minnesota: homes drawn from the MetroGIS Regional Parcel Dataset (7-county metro).

One layer per county, allocated by housing units. Each county writes its own
class vocabulary into the standard's ``USECLASS1`` (Washington a bare number, so
its ``DWELL_TYPE`` is used instead), and the filters below keep each county's
residential classes — single units, townhouses, condominium units, duplexes and
triplexes, apartments and low-income rental housing — and leave out land, garage
and storage units, common areas, seasonal cabins, farms, commercial and exempt
parcels. None of the kept classes contains a word the adapter's
``_NO_HOME_WORDS`` refuses.

The address is the standard's situs street as the adapter reassembles it
(``mn._street``: directionals and local street types abbreviated), with the unit
(``SUB_ID1``) as "#<unit>", the postal community (else the city or township) and
the situs ZIP; the owner and taxpayer address columns are never requested. A
house number with a letter suffix, which the adapter declines to offer, is typed
as written, so its refusal is counted as the adapter's (no home record) and not
as a missing address.
"""

from __future__ import annotations

import re

from housing_label.enrich.assessor import mn
from scripts.benchmark_samplers import allocate, arcgis_random, interior_point, typed, zip_at

ADAPTER = "mn"
ASSESSMENT_YEAR = "current"     # the current quarter's export (2025-2026 rolls by county)


def _like(column: str, *prefixes: str) -> str:
    return "(" + " OR ".join(f"{column} LIKE '{p}%'" for p in prefixes) + ")"


def _in(column: str, *values: str) -> str:
    return f"{column} IN ({','.join(repr(v) for v in values)})"


#: county FIPS -> residential predicate on its layer
_FIPS = {
    "27003": _in("USECLASS1", "1a RESIDENTIAL SINGLE UNIT", "1a RES/AG SINGLE UNIT",
                 "RESIDENTIAL 1 TO 3 UNITS", "RESIDENTIAL DUPLEX/TRIPLEX",
                 "RESIDENTIAL 4+ OWNERS VALUE", "4a APARTMENT 4 OR MORE UNITS"),
    "27019": _like("USECLASS1", "1A/1B/4B", "4A APARTMENT", "4D"),
    "27037": _in("USECLASS1", "Residential", "Residential-townhouse",
                 "Residential-condominium", "Apartment"),
    "27053": _in("USECLASS1", "Residential", "Condominium (also Market Rate Cooperative)",
                 "Townhouse", "Double Bungalow", "Residential Lake Shore", "Apartment",
                 "Residential-Zero Lot Line-DB", "Cooperative (Limited Equity)",
                 "Triplex", "Residential - Misc/ B&B / Multiple",
                 "Housing - Low Income > 3 Units", "Housing - Low Income < 4 Units",
                 "Disabled", "Blind", "Apartment Condominium"),
    "27123": _like("USECLASS1", "1A/1B/4B", "4A APARTMENT", "4D"),
    "27139": _like("USECLASS1", "201 ", "202 ", "203 ", "205 ", "224 ", "225 "),
    "27163": _in("DWELL_TYPE", "Single-Family / Owner Occupied", "Single-Family / Rental Unit",
                 "Townhouse", "Condominium", "Two-Family Duplex", "Two-Family Conversion",
                 "Three-Family Conversion", "Mobile Home Housing"),
}
_FIELDS = ("OBJECTID,COUNTY_PIN,ANUMBER,ANUMBERSUF,ST_PRE_MOD,ST_PRE_DIR,ST_PRE_TYP,"
           "ST_PRE_SEP,ST_NAME,ST_POS_TYP,ST_POS_DIR,ST_POS_MOD,SUB_ID1,ZIP,POSTCOMM,CTU_NAME")
_PARTS = ("ANUMBER", "ANUMBERSUF", "ST_PRE_MOD", "ST_PRE_DIR", "ST_PRE_TYP", "ST_PRE_SEP",
          "ST_NAME", "ST_POS_TYP", "ST_POS_DIR", "ST_POS_MOD")
_ZIP5 = re.compile(r"^\d{5}")


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _has_number(a: dict) -> bool:
    try:
        return float(a.get("ANUMBER") or 0) > 0
    except (TypeError, ValueError):
        return False


def _address(a: dict, pt) -> str:
    street = mn._street(a)
    if street is None:
        # Typed as written ("123A MAIN ST") only when it has a house number at all.
        if not _has_number(a):
            return ""
        number = f"{int(float(a['ANUMBER']))}{_clean(a.get('ANUMBERSUF'))}"
        street = " ".join([number, *(p for p in (_clean(a.get(k)) for k in _PARTS[2:]) if p)])
    if not street:
        return ""
    street = street.upper()
    unit = _clean(a.get("SUB_ID1"))
    if unit:
        street = f"{street} #{unit.upper()}"
    city = _clean(a.get("POSTCOMM")) or _clean(a.get("CTU_NAME")) or None
    m = _ZIP5.match(_clean(a.get("ZIP")))
    return typed(street, city, "MN", m.group(0) if m else zip_at(*pt))


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        feats, tried = arcgis_random(mn.COUNTIES[fips].url, _FIPS[fips], _FIELDS, n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": _address(a, pt), "source_id": a.get("COUNTY_PIN")})
    return out, attempted
