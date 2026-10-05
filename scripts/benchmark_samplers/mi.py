"""Southeast Michigan: homes drawn from SEMCOG's building inventory.

The source is building footprints, not parcels, so a draw is one live residential
BUILDING — single-family (81), attached-condo building (82) or apartment building
(83), the classes the adapter answers for — and the reference is read at a point
inside that footprint. Mobile homes (84) are left out: the adapter never answers
for them.

The layer has no county column. Its ``city_id`` is SEMCOG's community code, whose
leading digit is SEMCOG's county number (checked against SEMCOG's Community
Boundaries layer, which gives each code's county: every residential building's
code lands in the county its leading digit says). Detroit's buildings carry
neighborhood codes 501-554 rather than its community code 5.

The address is SEMCOG's site ``address`` and site ``zipcode`` with the community's
name from SEMCOG's Community Boundaries layer, "Twp" and county qualifiers
trimmed ("Canton Twp" -> "Canton", "Northville (Wayne)" -> "Northville"); of a
corner building's two addresses, the first. Range addresses ("3379-3401 BURBANK
DR", attached condos and apartments) are kept as SEMCOG writes them: the adapter
refuses them, and the benchmark counts that rather than hiding it. The
layer carries no owner mailing address; ``ref_name`` (owner or business name) is
never requested.
"""

from __future__ import annotations

import re

from housing_label.enrich.assessor import mi
from scripts.benchmark_samplers import allocate, arcgis_random, get, interior_point, typed

ADAPTER = "mi"
ASSESSMENT_YEAR = "2024"      # Buildings_2024: "current as of December 31, 2024"

_COMMUNITIES_URL = ("https://gis.semcog.org/server/rest/services/Hosted/"
                    "Community_Boundaries_2017/FeatureServer/56/query")
_LIVE_HOMES = "demolished IS NULL AND build_type IN (81,82,83)"

#: county FIPS -> the city_id predicate selecting that county's buildings.
_FIPS = {
    "26163": "((city_id >= 1000 AND city_id < 2000) OR (city_id >= 500 AND city_id < 600))",
    "26125": "(city_id >= 2000 AND city_id < 3000)",   # Oakland
    "26099": "(city_id >= 3000 AND city_id < 4000)",   # Macomb
    "26161": "(city_id >= 4000 AND city_id < 5000)",   # Washtenaw
    "26115": "(city_id >= 5000 AND city_id < 6000)",   # Monroe
    "26147": "(city_id >= 6000 AND city_id < 7000)",   # St. Clair
    "26093": "(city_id >= 7000 AND city_id < 8000)",   # Livingston
}
_QUALIFIER = re.compile(r"\s*\(.*\)$|\s+Twp$", re.I)


def _community_names() -> dict[int, str]:
    body = get(_COMMUNITIES_URL, {"where": "1=1", "outFields": "semmcd,name",
                                  "returnGeometry": "false", "f": "json"}) or {}
    names = {}
    for f in body.get("features") or []:
        a = f.get("attributes") or {}
        if a.get("semmcd") is not None and a.get("name"):
            names[int(a["semmcd"])] = _QUALIFIER.sub("", str(a["name"]).strip())
    return names


def _city(names: dict[int, str], city_id) -> str | None:
    if city_id is None:
        return None
    cid = int(city_id)
    return "Detroit" if 500 <= cid < 600 else names.get(cid)


def draw(rows: int, seed: int):
    names = _community_names()
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        feats, tried = arcgis_random(
            mi.BUILDINGS_URL, f"{_LIVE_HOMES} AND {_FIPS[fips]}",
            "objectid,address,zipcode,city_id", n, seed + i, oid_field="objectid")
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            z = a.get("zipcode")
            zip5 = f"{int(z):05d}" if z else None
            # A corner building carries both streets ("1004 8TH ST | 742 PINE
            # ST"); a resident types one of them.
            street = str(a.get("address") or "").split("|")[0]
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(street, _city(names, a.get("city_id")), "MI",
                                         zip5),
                        "source_id": a.get("objectid")})
    return out, attempted
