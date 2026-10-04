"""Indiana: homes drawn from Vanderburgh County's own tax-parcel layer.

The adapter's home classes (510-515, 520-525, 530-535, 540-545, 550, 401-403,
and an agricultural parcel whose dwelling record is single-family occupancy)
with a recorded year built. The address is the property's own PROPSTREET,
PROPCITY and PROPZIP; the OWNER* mailing columns are never read.
"""

from __future__ import annotations

from housing_label.enrich.assessor import ind
from scripts.benchmark_samplers import allocate, arcgis_random, interior_point, typed, zip_at

ADAPTER = "ind"
ASSESSMENT_YEAR = "current"   # the layer is refreshed nightly from the assessor's CAMA

_HOME_CLASSES = ",".join(f"'{c}'" for c in sorted(ind._HOMES))
_FIPS = {
    "18163": (ind.VANDERBURGH_URL,
              f"YearBuilt > 0 AND (PROPERTYCLASS IN ({_HOME_CLASSES}) OR "
              "(PROPERTYCLASS LIKE '1%' AND occupancy = '1'))"),
}


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        url, where = _FIPS[fips]
        feats, tried = arcgis_random(url, where, "OBJECTID,PROPSTREET,PROPCITY,PROPZIP",
                                     n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            zip5 = str(a.get("PROPZIP") or "").strip()[:5]
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(a.get("PROPSTREET"), a.get("PROPCITY"), "IN",
                                         zip5 if zip5.isdigit() else zip_at(*pt)),
                        "source_id": a.get("OBJECTID")})
    return out, attempted
