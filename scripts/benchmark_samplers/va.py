"""Virginia: homes drawn from Chesterfield County's parcels and the City of
Richmond's assessor improvement records.

* Chesterfield — records whose UseCode is one of the adapter's homes: the
  residential classes (SD, TH, TN, CD, CN, DU) and "100", the code the county
  gives apartment complexes. Condominium units are stacked on their complex's
  outline, one record each, so a drawn unit's point is inside the complex. The
  address is the site ``Address`` and site ``Zip`` with no city: the layer's only
  city column is the owner's, never read.
* Richmond — improvement records (points, each inside its parcel) whose
  property class is one of the adapter's homes. The improvement layer is the
  adapter's source and the only one carrying a full street address; a
  condominium unit's own unit ("3510 East Richmond Road U9", Richmond's spelling)
  is typed as a resident would ("... #9"). City "Richmond" and the ZCTA at the
  point.
"""

from __future__ import annotations

from housing_label.enrich.assessor import va
from scripts.benchmark_samplers import allocate, arcgis_random, interior_point, typed, zip_at

ADAPTER = "va"
# Chesterfield's AssessmentYear is 2026 on every residential record; Richmond's
# improvement layer is the 2025 assessment snapshot.
ASSESSMENT_YEAR = "2025-2026 by locality (Chesterfield 2026, Richmond 2025)"

_CHESTERFIELD_HOMES = ",".join(
    f"'{c}'" for c in sorted(va.COUNTIES["51041"].home_uses))
_RICHMOND_HOMES = ",".join(sorted(va.COUNTIES["51760"].home_uses))


def _chesterfield(a, pt):
    return typed(a.get("Address"), None, "VA", str(a.get("Zip") or "").strip()[:5] or None)


def _richmond(a, pt):
    street, unit = va._richmond_street(a.get("prop_street"))
    if street and unit:
        street = f"{street} #{unit}"
    return typed(street, "Richmond", "VA", zip_at(*pt))


#: locality FIPS -> (layer, where, outFields, address builder)
_FIPS = {
    "51041": (va.CHESTERFIELD_URL, f"UseCode IN ({_CHESTERFIELD_HOMES})",
              "OBJECTID,Address,Zip", _chesterfield),
    "51760": (va.RICHMOND_IMPROVEMENT_URL, f"property_class IN ({_RICHMOND_HOMES})",
              "OBJECTID,prop_street", _richmond),
}


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        url, where, fields, address_of = _FIPS[fips]
        feats, tried = arcgis_random(url, where, fields, n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": address_of(a, pt), "source_id": a.get("OBJECTID")})
    return out, attempted
