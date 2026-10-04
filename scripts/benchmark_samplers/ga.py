"""Georgia: homes drawn from each answered county's own parcel layer.

Fulton, Clayton, Chatham (SAGIS) and Forsyth, allocated by housing units. Each
county's draw is filtered to the residential parcels the adapter reads as homes:

* Fulton — a residential digest class (R*) and an improved residential land use
  (one-family, duplex to four-plex, condominium, townhouse, residential
  acreage); vacant lots and common areas are left out. Condominium parcels are
  drawn: the adapter reads them, but they almost never have a structure
  footprint, so they fall out as ``no_home_record``. That is the adapter's
  behavior, and the benchmark reports it.
* Clayton — the same improved residential land uses (the layer has no class).
* Chatham — digest class R3 with a building value above zero (the adapter reads
  a zero building value as "no building").
* Forsyth — digest class R3, without the four common-area and undeveloped land
  uses the adapter refuses.

Addresses: Clayton's SITECITY/SITEZIP5 and Chatham's PropAddress_City/_Zip are the
property's own. Fulton and Forsyth publish no site city or ZIP (only the owner's
mailing columns, never read), so those get the ZCTA at the parcel and no city.
Forsyth keeps the unit in its own column ("UNIT 207"), appended as a resident
would type it.
"""

from __future__ import annotations

from housing_label.enrich.assessor import ga
from scripts.benchmark_samplers import allocate, arcgis_random, interior_point, typed, zip_at

ADAPTER = "ga"
# Four rolls, four years, each read from the record itself by the adapter.
ASSESSMENT_YEAR = "2024-2026 by county (Fulton 2026, Chatham 2025, Forsyth 2024, Clayton current)"

_IMPROVED_RESIDENTIAL = ("'101','102','103','104','105','106','107','109','110',"
                         "'112','114','115'")
_FORSYTH_NOT_HOMES = ",".join(f"'{c}'" for c in sorted(ga._FORSYTH_NOT_A_HOME_LUCS))


def _fulton(a, pt):
    return typed(a.get("Address"), None, "GA", zip_at(*pt))


def _clayton(a, pt):
    return typed(a.get("SITEADDRES"), a.get("SITECITY"), "GA", a.get("SITEZIP5"))


def _chatham(a, pt):
    # The digest doubles the unit marker ("111 SAN MARCO DR ##A").
    street = str(a.get("PropAddress_Full") or "").replace("##", "#")
    return typed(street, a.get("PropAddress_City"), "GA", a.get("PropAddress_Zip"))


def _forsyth(a, pt):
    unit = " ".join(str(a.get("UNIT") or "").split())
    street = f"{a.get('SITEADDRES') or ''} {unit}".strip()
    return typed(street, None, "GA", zip_at(*pt))


#: county FIPS -> (layer, where, outFields, object id field, address builder)
_FIPS = {
    "13121": (ga.FULTON_PARCEL_URL,
              f"ClassCode LIKE 'R%' AND LUCode IN ({_IMPROVED_RESIDENTIAL})",
              "OBJECTID,Address", "OBJECTID", _fulton),
    "13063": (ga.CLAYTON_URL, f"LANDUSEC IN ({_IMPROVED_RESIDENTIAL})",
              "OBJECTID,SITEADDRES,SITECITY,SITEZIP5", "OBJECTID", _clayton),
    "13051": (ga.CHATHAM_URL, "Property_Use='R3' AND FMV_Building>0",
              "OBJECTID,PropAddress_Full,PropAddress_City,PropAddress_Zip", "OBJECTID",
              _chatham),
    "13117": (ga.FORSYTH_URL, ("P_CLASS='R3' AND (P_LUC IS NULL OR "
               f"P_LUC NOT IN ({_FORSYTH_NOT_HOMES}))"),
              "FID,SITEADDRES,UNIT", "FID", _forsyth),
}


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        url, where, fields, oid, address_of = _FIPS[fips]
        feats, tried = arcgis_random(url, where, fields, n, seed + i, oid_field=oid)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": address_of(a, pt),
                        "source_id": a.get(oid)})
    return out, attempted
