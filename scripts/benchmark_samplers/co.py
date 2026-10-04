"""Colorado: homes drawn from the five Denver-metro assessors the adapter reads.

Allocated across Denver, Jefferson, Adams, Douglas and Boulder by housing units.
Each county is drawn from its own parcel layer, filtered to the classes the
adapter reads as dwellings:

* **Denver** — ``D_CLASS_CN`` single-family ("SFR ...") and residential classes
  (condominium units, rowhouses, duplexes to apartments), less the land classes
  and recorded zero-unit parcels the adapter drops (``_denver_no_home``).
* **Jefferson** — the first structure type is one of ``co._JEFFERSON_DWELLINGS``.
* **Adams** — the parcel layer has no class, so the draw is over the DISTINCT
  parcel numbers of the improvements table that carry a dwelling row
  (``co._DWELLING_TYPES``), each then placed on its parcel polygon: uniform over
  parcels with a home, not over buildings.
* **Douglas** — ``ACCOUNT_TYPE_CODE`` Residential or Mobile Home.
* **Boulder** — ``AcctType`` of a residential account (houses, condominiums,
  manufactured homes, apartments, affordable housing). Boulder writes one parcel
  row per street address of an account, so an account with two addresses is
  twice as likely to be drawn (rare; the adapter merges such rows).

The address is the situs street as the adapter's own reader assembles it (with
any unit as "#<unit>"), with the situs city and ZIP each layer publishes
(Boulder publishes no situs ZIP, so the ZCTA at the parcel is used); owner and
mailing columns are never requested. Denver's roll writes the implicit "N" of
its north-half streets, which no resident types and the Postal Service omits,
so it is dropped as the adapter's own ``_without_implicit_north`` does.
"""

from __future__ import annotations

import random
import re

from housing_label.enrich.assessor import co
from scripts.benchmark_samplers import (
    allocate, arcgis_random, get, interior_point, typed, zip_at,
)

ADAPTER = "co"
ASSESSMENT_YEAR = "current"      # every source is queried live (daily to weekly)


def _in(column: str, values) -> str:
    return f"{column} IN ({','.join(repr(v) for v in sorted(values))})"


_DENVER_WHERE = ("(D_CLASS_CN LIKE 'SFR%' OR D_CLASS_CN LIKE 'RESIDENTIAL%') "
                 "AND D_CLASS_CN NOT LIKE '%LAND%' AND D_CLASS_CN NOT LIKE '%VACANT%' "
                 "AND (TOT_UNITS IS NULL OR TOT_UNITS > 0)")
_JEFFERSON_WHERE = _in("UPPER(STTSTRC)", co._JEFFERSON_DWELLINGS)
_ADAMS_WHERE = _in("UPPER(proptype)", co._DWELLING_TYPES)
_DOUGLAS_WHERE = "ACCOUNT_TYPE_CODE IN ('Residential','Mobile Home')"
_BOULDER_WHERE = _in("AcctType", {"RESIDENTIAL", "RESIDENTIAL CONDO", "MANUFACTURED HOME",
                                  "APARTMENT", "AFFORDABLE RES"})

#: fips -> (where, situs city column, situs ZIP column or None)
_FIPS = {
    "08031": (_DENVER_WHERE, "SITUS_CITY", "SITUS_ZIP"),
    "08059": (_JEFFERSON_WHERE, "PRPCTYNAM", "PRPZIP5"),
    "08001": (None, "LOCCITY", "LOCZIP"),          # drawn through the improvements
    "08035": (_DOUGLAS_WHERE, "CITY_NAME", "LOCATION_ZIP_CODE"),
    "08013": (_BOULDER_WHERE, "StrCity", None),
}
_ZIP5 = re.compile(r"^\d{5}")


def _address(fips: str, a: dict, pt) -> str:
    cfg = co.COUNTIES[fips]
    street = cfg.street(a) or ""
    if not street[:1].isdigit():
        return ""                      # no house number: nothing a resident types
    if cfg.implicit_north:
        street = co._without_implicit_north(street) or street
    unit = cfg.unit(a)
    if unit:
        street = f"{street} #{unit.upper()}"
    _where, city_col, zip_col = _FIPS[fips]
    m = _ZIP5.match(str(a.get(zip_col) or "").strip()) if zip_col else None
    city = " ".join(str(a.get(city_col) or "").split()) or None
    return typed(street, city, "CO", m.group(0) if m else zip_at(*pt))


def _adams_parcels(n: int, seed: int):
    """``n`` Adams parcel features drawn uniformly from the distinct parcel numbers
    whose improvements include a dwelling. Returns (features, attempted)."""
    total = (get(co.ADAMS_IMPROVEMENTS_URL, {"where": _ADAMS_WHERE, "outFields": "parcelnb",
                                             "returnDistinctValues": "true",
                                             "returnCountOnly": "true", "f": "json"})
             or {}).get("count")
    if not total:
        return [], 0
    offsets = sorted(random.Random(seed).sample(range(total), min(n, total)))
    fields = ",".join(co.COUNTIES["08001"].fields) + ",LOCCITY,LOCZIP"
    feats = []
    for off in offsets:
        body = get(co.ADAMS_IMPROVEMENTS_URL, {
            "where": _ADAMS_WHERE, "outFields": "parcelnb", "returnDistinctValues": "true",
            "orderByFields": "parcelnb", "resultOffset": off, "resultRecordCount": 1,
            "returnGeometry": "false", "f": "json"})
        rows = (body or {}).get("features") or []
        pnb = str((rows[0]["attributes"].get("parcelnb") if rows else "") or "").strip()
        if not pnb or not co._KEY_RE.match(pnb):
            continue
        parcel = get(co.ADAMS_URL, {"where": f"PARCELNB = '{pnb}'", "outFields": fields,
                                    "returnGeometry": "true", "outSR": 4326, "f": "json"})
        ps = (parcel or {}).get("features") or []
        if ps:
            feats.append(ps[0])
    return feats, len(offsets)


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        cfg = co.COUNTIES[fips]
        where, city_col, zip_col = _FIPS[fips]
        if where is None:
            feats, tried = _adams_parcels(n, seed + i)
        else:
            fields = ",".join([cfg.pid, *cfg.address_fields, city_col]
                              + ([zip_col] if zip_col else []))
            feats, tried = arcgis_random(cfg.url, where, fields, n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": _address(fips, a, pt), "source_id": a.get(cfg.pid)})
    return out, attempted

