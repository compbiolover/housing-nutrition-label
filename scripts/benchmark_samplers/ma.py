"""Massachusetts: homes drawn from MassGIS's Level 3 statewide assessor parcels.

Records whose Department of Revenue use code is one the adapter reads as "a home"
(``ma._HOME_CODES``, plus multiple-use codes with a residential digit), allocated
across the 14 counties by housing units. The layer has no county column, so each
county is the set of MassGIS ``TOWN_ID``s that MassGIS's own municipalities layer
places in it (fetched once per draw). Condominium units are drawn as records, each
typed with its own unit, which is what the adapter needs to pick a unit off a
stacked polygon.

The address is the record's own site address (ADDR_NUM/FULL_STR, else SITE_ADDR),
with the site CITY and ZIP the Level 3 standard carries for the property — the
ZCTA at the parcel where the ZIP is blank or a placeholder, and the MassGIS town
name where the city is blank. OWN_ADDR/OWN_CITY/OWN_ZIP are the OWNER's and are
never read.
"""

from __future__ import annotations

from housing_label.enrich.assessor import ma
from housing_label.enrich.assessor._shared import unit_of
from scripts.benchmark_samplers import (
    allocate, arcgis_random, get, interior_point, typed, zip_at,
)

ADAPTER = "ma"
ASSESSMENT_YEAR = "FY2026"    # FY on 1,505,063 of the layer's features (2026-10-03)

_FIPS = {
    "25001": "BARNSTABLE", "25003": "BERKSHIRE", "25005": "BRISTOL", "25007": "DUKES",
    "25009": "ESSEX", "25011": "FRANKLIN", "25013": "HAMPDEN", "25015": "HAMPSHIRE",
    "25017": "MIDDLESEX", "25019": "NANTUCKET", "25021": "NORFOLK",
    "25023": "PLYMOUTH", "25025": "SUFFOLK", "25027": "WORCESTER",
}

_TOWNS_URL = ("https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services"
              "/Massachusetts_Municipalities/FeatureServer/1/query")

_FIELDS = "OBJECTID,TOWN_ID,SITE_ADDR,ADDR_NUM,FULL_STR,LOCATION,CITY,ZIP"

# The adapter's home codes as LIKE patterns on the four-character column (towns
# use the fourth character for local subdivisions: 1010, 102U), plus multiple-use
# codes with a residential class digit (01x, 0x1).
_HOME_WHERE = "(" + " OR ".join(
    [f"USE_CODE LIKE '{c}%'" for c in sorted(ma._HOME_CODES)]
    + ["USE_CODE LIKE '01%'", "USE_CODE LIKE '0_1%'"]) + ")"


def _towns() -> tuple[dict[str, list[int]], dict[int, str]]:
    body = get(_TOWNS_URL, {"where": "1=1", "outFields": "TOWN,TOWN_ID,FIPS_STCO",
                            "returnGeometry": "false", "resultRecordCount": 2000,
                            "f": "json"})
    by_county: dict[str, list[int]] = {}
    names: dict[int, str] = {}
    for f in (body or {}).get("features") or []:
        a = f["attributes"]
        by_county.setdefault(str(a["FIPS_STCO"]), []).append(int(a["TOWN_ID"]))
        names[int(a["TOWN_ID"])] = a["TOWN"]
    if sum(len(v) for v in by_county.values()) != 351:
        raise SystemExit("MassGIS municipalities layer did not return all 351 towns")
    return by_county, names


def _street(a: dict) -> str:
    number = str(a.get("ADDR_NUM") or "").strip()
    street = str(a.get("FULL_STR") or "").strip()
    base = f"{number} {street}" if number.isdigit() and street \
        else " ".join(str(a.get("SITE_ADDR") or "").split())
    unit = ma._row_unit(a)
    # Not where the street already names it ("22 COBB AVE UNIT 58A").
    if unit and unit.strip("0") and not unit_of(base):
        base = f"{base} #{unit}"
    return base


def _zip(a: dict, pt) -> str | None:
    z = str(a.get("ZIP") or "").strip()[:5]
    return z if z.isdigit() and len(z) == 5 and z != "00000" else zip_at(*pt)


def draw(rows: int, seed: int):
    by_county, names = _towns()
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        towns = ",".join(str(t) for t in sorted(by_county[fips]))
        feats, tried = arcgis_random(
            ma.PARCEL_URL, f"TOWN_ID IN ({towns}) AND {_HOME_WHERE}",
            _FIELDS, n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            city = str(a.get("CITY") or "").strip() or names.get(a.get("TOWN_ID"))
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(_street(a), city, "MA", _zip(a, pt)),
                        "source_id": a.get("OBJECTID")})
    return out, attempted
