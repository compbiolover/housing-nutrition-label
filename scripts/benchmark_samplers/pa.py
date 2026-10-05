"""Pennsylvania: homes drawn from the four county parcel layers the adapter reads.

Each county's own statement that a home stands on the parcel, with a recorded
year built, allocated across the four counties by housing units:

* Montgomery: class R, at least one living unit (``LIV_UNITS`` not 0), and not
  a common-area, private-road, railroad or "other" parcel.
* York: a recorded ``YRBLT`` — the residential card's year — on a land use the
  adapter does not call vacant or common (its ``_YORK_NO_HOME``).
* Northampton: a recorded ``RES_YEAR_BUILT`` on a land use outside the adapter's
  ``_NORTHAMPTON_NO_HOME``.
* Cumberland: a recorded dwelling type, a year that is not the 1776 placeholder,
  and not residential vacant land (100).

The address is the site address with the site's municipality: Montgomery's
``LOCATION1`` (plus its unit), ``Muni_Name`` and ``LOC_ZIP1_Z`` (the location
ZIP); Cumberland's ``SITUS``, ``MUNI_NAME`` and ``SITUS_ZIP``; York's and
Northampton's site address with the ZCTA at the parcel (both publish their
municipality only as a code). Owner and mailing columns are never read.
"""

from __future__ import annotations

import re

from housing_label.enrich.assessor import pa
from scripts.benchmark_samplers import allocate, arcgis_random, interior_point, typed, zip_at

ADAPTER = "pa"
ASSESSMENT_YEAR = "current"   # four live county layers (monthly to nightly)


def _codes(codes) -> str:
    return ",".join(f"'{c}'" for c in sorted(codes))


# "Abington Township", "Municipality of Norristown", "CARLISLE BORO 3RD WRD",
# "NEW CUMBERLAND 2ND WD", "SHIPPENSBURG EAST WRD", "EAST PENNSBORO TWP/WF".
_WARD = re.compile(r"\s+(\d+(ST|ND|RD|TH)|EAST|WEST|NORTH|SOUTH)\s+(WRD|WD|WARD)$", re.I)
_MUNI_SUFFIX = re.compile(r"\s+(TWP|TOWNSHIP|BORO|BOROUGH|CITY|TOWN)$", re.I)


def _muni(name) -> str | None:
    text = " ".join(str(name or "").split())
    text = re.sub(r"^MUNICIPALITY OF\s+", "", text, flags=re.I)
    text = re.sub(r"/WF$", "", text, flags=re.I)
    text = _MUNI_SUFFIX.sub("", _WARD.sub("", text))
    return text or None


def _zip5(value) -> str | None:
    z = str(value or "").strip()[:5]
    return z if len(z) == 5 and z.isdigit() else None


def _montgomery(a: dict):
    # The unit as a resident writes it, "UNIT 406"; LOC_UNITDE's own words
    # ("CONDO", "BLDG 3", "SPACE") are not what anyone types before a number.
    unit = "".join(str(a.get("LOC_UNITNO") or "").split())
    street = " ".join(f"{a.get('LOCATION1') or ''} {'UNIT ' + unit if unit else ''}".split())
    return street, _muni(a.get("Muni_Name")), _zip5(a.get("LOC_ZIP1_Z"))


def _cumberland(a: dict):
    return a.get("SITUS"), _muni(a.get("MUNI_NAME")), _zip5(a.get("SITUS_ZIP"))


# fips: (url, where, outFields, reader -> (street, city, zip or None))
_FIPS = {
    "42091": (pa.MONTGOMERY_URL,
              "CLASS = 'R' AND YEAR_BUILT > 0 AND LIV_UNITS <> '0' AND PARCELTYPE NOT IN "
              "('COMMON AREA', 'PRIVATE ROAD', 'RAILROAD', 'OTHER')",
              "OBJECTID,LOCATION1,LOC_UNITNO,LOC_ZIP1_Z,Muni_Name", _montgomery),
    "42133": (pa.YORK_URL,
              f"YRBLT > 0 AND LUC NOT IN ({_codes(pa._YORK_NO_HOME)})",
              "OBJECTID,PROPADR", lambda a: (a.get("PROPADR"), None, None)),
    "42095": (pa.NORTHAMPTON_URL,
              f"RES_YEAR_BUILT > 0 AND LUC NOT IN ({_codes(pa._NORTHAMPTON_NO_HOME)})",
              "OBJECTID,LOCATION", lambda a: (a.get("LOCATION"), None, None)),
    "42041": (pa.CUMBERLAND_URL,
              "DWELLING_T IS NOT NULL AND DWELLING_T <> '' AND YEAR_BLT IS NOT NULL AND "
              f"YEAR_BLT <> '' AND YEAR_BLT <> '{pa._CUMBERLAND_PLACEHOLDER_YEAR}' AND "
              "LUC NOT LIKE '%(100)'",
              "OBJECTID,SITUS,SITUS_ZIP,MUNI_NAME", _cumberland),
}


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        url, where, fields, read = _FIPS[fips]
        feats, tried = arcgis_random(url, where, fields, n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            street, city, zip5 = read(f["attributes"])
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(street, city, "PA", zip5 or zip_at(*pt)),
                        "source_id": f["attributes"].get("OBJECTID")})
    return out, attempted
