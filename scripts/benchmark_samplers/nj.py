"""New Jersey: homes drawn from the NJOGIS Parcels and MOD-IV Composite.

Residential class 2 parcels, allocated across the 21 counties by housing units.
The address is the property location with its municipality and the ZCTA at the
parcel; the layer's CITY_STATE and ZIP_CODE are the OWNER's mailing address and
are never read.
"""

from __future__ import annotations

import re

from housing_label.enrich.assessor import nj
from scripts.benchmark_samplers import allocate, arcgis_random, interior_point, typed, zip_at

ADAPTER = "nj"
ASSESSMENT_YEAR = "2024"     # the composite's current MOD-IV join (layer metadata)

_COUNTIES = ["ATLANTIC", "BERGEN", "BURLINGTON", "CAMDEN", "CAPE MAY", "CUMBERLAND",
             "ESSEX", "GLOUCESTER", "HUDSON", "HUNTERDON", "MERCER", "MIDDLESEX",
             "MONMOUTH", "MORRIS", "OCEAN", "PASSAIC", "SALEM", "SOMERSET", "SUSSEX",
             "UNION", "WARREN"]
_FIPS = {f"34{2 * i + 1:03d}": name for i, name in enumerate(_COUNTIES)}
_MUNI_SUFFIX = re.compile(r"\s+(TWP|TOWNSHIP|BORO|BOROUGH|CITY|TOWN|VILLAGE)$")


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        feats, tried = arcgis_random(
            nj.PARCEL_URL, f"PROP_CLASS='2' AND COUNTY='{_FIPS[fips]}'",
            "OBJECTID,PROP_LOC,MUN_NAME", n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            city = _MUNI_SUFFIX.sub("", str(a.get("MUN_NAME") or "").strip())
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(a.get("PROP_LOC"), city, "NJ", zip_at(*pt)),
                        "source_id": a.get("OBJECTID")})
    return out, attempted
