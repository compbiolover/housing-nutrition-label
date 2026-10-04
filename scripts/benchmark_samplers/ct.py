"""Connecticut: homes drawn from the CT GIS Office's statewide CAMA and parcel layer.

Residential parcels (state use code in the 1xx/1xxx residential series, or none
filed) whose roll records a plausible actual year built (``AYB``) and does not
record zero dwelling units (``Occupancy`` 0 is the adapter's "no home here"),
allocated across the nine planning regions by housing units. The layer's ``COG``
column names each parcel's Council of Governments, one per planning region.

The adapter also registers the eight legacy county codes, because a geocoder may
return either set. They are listed here so every code the adapter serves is
covered, but no rows are allocated to them: they describe the same land as the
planning regions, the repository's housing-unit table weights only the regions,
and drawing from both would count the state twice.

The address is the street address the adapter itself reads (CAMA ``Location_1``
first, else the parcel map's ``Location``; Greenwich's inverted "OLD MILL ROAD
0200" is put back in the order a resident types it), the town or village the
CAMA filing names for the property (``Property_City``, else ``Town_Name``) and
the ZCTA at the parcel. The layer's ``Property_Zip`` has lost its leading zero
and often disagrees with the parcel map's ``ZIP_CODE``, so neither is used. The
Owner, Co_Owner and Mailing_* columns are never requested.
"""

from __future__ import annotations

import re

from housing_label.enrich.assessor import ct
from scripts.benchmark_samplers import allocate, arcgis_random, interior_point, typed, zip_at

ADAPTER = "ct"
ASSESSMENT_YEAR = "2026"     # CAMA_Collection_Year on all but 3,909 rows

_REGIONS = {
    "09110": "Capitol Region",
    "09120": "CT Metropolitan",           # Greater Bridgeport (MetroCOG)
    "09130": "Lower CT River Valley",
    "09140": "Naugatuck Valley",
    "09150": "Northeastern CT",
    "09160": "Northwest Hills",
    "09170": "South Central Regional",
    "09180": "Southeastern CT",
    "09190": "Western CT",
}
_FIPS = {**_REGIONS, **dict.fromkeys(sorted(ct._LEGACY_COUNTIES))}
_WHERE = ("COG='{}' AND AYB>=1600 AND AYB<=2100 "
          "AND (Occupancy IS NULL OR Occupancy>=1) "
          "AND (State_Use LIKE '1%' OR State_Use IS NULL)")
_INVERTED = re.compile(r"^(\D+?)\s+0*(\d+[A-Z]?)$")


def _street(a: dict) -> str:
    street = ct._address_of(a)
    if street:
        return street
    for column in ("Location_1", "Location"):
        raw = " ".join(str(a.get(column) or "").split())
        m = _INVERTED.match(raw.upper())
        if m:
            return f"{m.group(2)} {raw[:m.end(1)]}"
        if raw:
            return raw
    return ""


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _REGIONS, seed).items())):
        feats, tried = arcgis_random(
            ct.PARCEL_URL, _WHERE.format(_REGIONS[fips]),
            "OBJECTID,Location,Location_1,Property_City,Town_Name", n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            city = a.get("Property_City") or a.get("Town_Name")
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(_street(a), city, "CT", zip_at(*pt)),
                        "source_id": a.get("OBJECTID")})
    return out, attempted
