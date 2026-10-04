"""New York City: tax lots drawn from DCP's MapPLUTO, borough by borough.

Lots recording at least one residential unit (``UnitsRes >= 1``) — the rule the
adapter uses for whether a home stands on the lot — allocated across the five
boroughs by housing units. A condominium is one billing lot here, as it is to the
adapter: MapPLUTO draws no unit lots. The address is PLUTO's ``Address`` (Queens
numbers hyphenated, as residents write them), the borough's postal city and the
lot's own ``ZipCode``; owner columns are never read.
"""

from __future__ import annotations

from housing_label.enrich.assessor import nyc
from scripts.benchmark_samplers import allocate, arcgis_random, interior_point, typed, zip_at

ADAPTER = "nyc"
ASSESSMENT_YEAR = "26v2"     # the MapPLUTO release on the layer (Version column)

# County FIPS -> (PLUTO borough code, the city a resident writes on an envelope).
_FIPS = {
    "36005": ("BX", "Bronx"),
    "36047": ("BK", "Brooklyn"),
    "36061": ("MN", "New York"),
    "36081": ("QN", "Queens"),
    "36085": ("SI", "Staten Island"),
}
_FIELDS = "OBJECTID,BBL,Address,ZipCode"



def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        boro, city = _FIPS[fips]
        feats, tried = arcgis_random(nyc.PARCEL_URL,
                                     f"Borough='{boro}' AND UnitsRes >= 1",
                                     _FIELDS, n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            z = a.get("ZipCode")
            zip5 = f"{int(z):05d}" if isinstance(z, (int, float)) and z > 0 else zip_at(*pt)
            bbl = nyc._parcel_id(a)
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(a.get("Address"), city, "NY", zip5),
                        "source_id": bbl or a.get("OBJECTID")})
    return out, attempted
