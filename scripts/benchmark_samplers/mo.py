"""Missouri: homes drawn from Jackson County's Parcel Viewer (Ascend CAMA table).

The draw is over the assessor's record table (``Ascend_GisInfo``), restricted to
the land-use codes the adapter itself reads as dwellings (``mo._DWELLING``), and
ordered by ``property_id`` (the table's own OBJECTID is not a usable key: it read
0 on the rows probed). Each drawn record is then placed on its parcel polygon by
``PropertyID`` — the same join the adapter makes, in the other direction. A record
with no polygon cannot be reached from a point and counts as a failed draw.

The address is the record's situs street with its situs city and ZIP (the table's
``mtgco_*`` columns are the mortgage company's and are never read). The roll
writes "UNINCORPORATED" for homes outside a city, which no resident types, so
those addresses carry the ZIP alone; a missing situs ZIP falls back to the ZCTA
at the parcel.
"""

from __future__ import annotations

import re

from housing_label.enrich.assessor import mo
from scripts.benchmark_samplers import (
    allocate, arcgis_random, get, interior_point, typed, zip_at,
)

ADAPTER = "mo"
ASSESSMENT_YEAR = "2024"     # every record's tax_year (see the adapter's docstring)

_FIPS = {"29095": "Jackson"}
_HOMES = "landuse_cd IN ({})".format(",".join(f"'{c}'" for c in sorted(mo._DWELLING)))
_ZIP5 = re.compile(r"^\d{5}")


def _polygon_point(property_id: int):
    """A point inside the parcel polygon of this property, or None."""
    body = get(mo.PARCEL_URL, {"where": f"PropertyID = {property_id}",
                               "outFields": "PropertyID", "returnGeometry": "true",
                               "outSR": 4326, "f": "json"})
    for f in (body or {}).get("features") or []:
        pt = interior_point(f.get("geometry"))
        if pt is not None:
            return pt
    return None


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        recs, tried = arcgis_random(
            mo.RECORD_URL, _HOMES, "property_id,situs_address,situs_city,situs_zip",
            n, seed + i, oid_field="property_id", geometry=False)
        attempted += tried
        for r in recs:
            a = r["attributes"]
            pid = a.get("property_id")
            if not pid:
                continue
            pt = _polygon_point(int(pid))
            if pt is None:
                continue
            city = " ".join(str(a.get("situs_city") or "").split())
            if city.upper() == "UNINCORPORATED":
                city = ""
            m = _ZIP5.match(str(a.get("situs_zip") or "").strip())
            zip5 = m.group(0) if m else zip_at(*pt)
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(a.get("situs_address"), city or None, "MO", zip5),
                        "source_id": pid})
    return out, attempted
