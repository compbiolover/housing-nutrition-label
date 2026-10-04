"""Texas: homes drawn from the twelve appraisal-district services the adapter reads.

Allocated across the twelve counties by housing units, each county drawn from its
own service (``tx.COUNTIES``), filtered to the Comptroller's residential
categories — A single-family (houses, townhouses, condominium units), B
multifamily, M mobile homes — in the column the adapter itself reads the class
from: Harris adds its Z condominium codes; Dallas's own ``CLASSCD`` numbering is
mapped to the same categories (1-4, 35 houses, townhouses, condominiums and mobile
homes; 5, 6 apartments and duplexes); Collin's M4/M5 common areas are left out
(only M3, a HUD-numbered mobile home, is a home there); Denton's and Collin's
code LISTS ("A1,D1,E1") are matched on any listed code. Category E (rural land
with improvements), O (inventory) and X (exempt), which the adapter treats as
silent rather than as homes, are not drawn.

How each county is drawn:

* ArcGIS layers with pagination: ``arcgis_random`` (random offsets).
* **Tarrant**: TAD's ``OD_ParcelView`` refuses pagination, so the matching object
  ids are listed (``returnIdsOnly``) and drawn from directly.
* **Williamson**: WCAD's Socrata portal. The draw is over the DISTINCT property
  ids of the improvements table carrying a residential code (one row per
  property, not per improvement), each placed on its parcel polygon from the
  parcels dataset.

The address is the situs street (rebuilt by the adapter's own helpers where the
roll spells it oddly: Travis's leading directional, Tarrant's "TR", WCAD's
trailing directional), with any unit as "#<unit>" (Harris writes it bare after
the street type), and the situs city and ZIP where the service publishes them —
Harris's ``CITY``/``ZIP_CODE``; the city and ZIP after the comma in Fort Bend's,
Montgomery's and Williamson's situs; Travis's ``situs_zip`` and the city in its
situs string; Collin's, Denton's, El Paso's and Cameron's situs columns. Dallas,
Tarrant and Bexar publish no situs city or ZIP (their city columns are taxing
codes or the owner's), so their addresses carry the ZCTA at the parcel alone.
Owner and mailing columns are never requested. A situs with no house number is
counted as no address.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Callable

from housing_label.enrich.assessor import tx
from scripts.benchmark_samplers import (
    allocate, arcgis_random, get, interior_point, typed, zip_at,
)

ADAPTER = "tx"
#: Each county's latest published roll: from TCAD's (about 2023, Travis) to the
#: 2027 appraisal years Collin and Denton have opened; see the adapter docstring.
ASSESSMENT_YEAR = "current"

_ZIP = re.compile(r"(\d{5})(?:-\d{4})?\s*$")
_CITY_TX_ZIP = re.compile(r"^(.*?)[,\s]*\bTX\b\.?(?:\s+(\d{5}))?", re.IGNORECASE)


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _codes(column: str, *prefixes: str, listed: bool = False) -> str:
    """Rows whose state code starts with one of ``prefixes`` — anywhere in a
    comma-joined list when ``listed``."""
    parts = []
    for p in prefixes:
        parts.append(f"{column} LIKE '{p}%'")
        if listed:
            parts += [f"{column} LIKE '%,{p}%'", f"{column} LIKE '%, {p}%'"]
    return "(" + " OR ".join(parts) + ")"


def _with_unit(street: str, unit) -> str:
    unit = _clean(unit).lstrip("#").strip()
    if unit and not street.upper().endswith(unit.upper()):
        return f"{street} #{unit.upper()}"
    return street


def _situs_parts(text) -> tuple[str, str | None, str | None]:
    """"2018 Hilton Head DR, Missouri City, TX  77459" or "6 MCCLELLAN CIR, HUMBLE TX
    77339" as (street, city, ZIP)."""
    street, _, rest = _clean(text).partition(",")
    rest = rest.strip(" ,")
    if not rest:
        return street.strip(), None, None
    m = _CITY_TX_ZIP.match(rest)
    if m:
        return street.strip(), (m.group(1).strip(" ,") or None), m.group(2)
    return street.strip(), rest, None


# Per-county readers of a drawn row (columns upper-cased): (street, city, ZIP).

def _harris(a):
    street = _clean(a.get("ADDRESS"))
    bare = tx._unmarked_unit(street)
    if bare:
        street = f"{street.rsplit(' ', 1)[0]} #{bare.upper()}"
    return street, _clean(a.get("CITY")), _clean(a.get("ZIP_CODE"))


def _fort_bend(a):
    street, city, zip5 = _situs_parts(a.get("SITUS"))
    return _with_unit(street, a.get("SITUSAPT")), city, zip5


def _montgomery(a):
    return _situs_parts(a.get("ADDRESS"))


def _dallas(a):
    return _with_unit(_clean(a.get("SITEADDRESS")), a.get("UNIT")), None, None


def _tarrant(a):
    return tx._tarrant_address(a.get("SITUS_ADDR")), None, None


def _bexar(a):
    return _clean(a.get("SITUS")), None, None


def _travis(a):
    raw = _clean(a.get("SITUS_ADDRESS")).upper().split()
    if raw and _ZIP.match(raw[-1]):
        raw.pop()
    if raw and raw[-1] == "TX":
        raw.pop()
    city = None
    for words in tx._TRAVIS_CITIES:
        if len(raw) > len(words) + 1 and tuple(raw[-len(words):]) == words:
            city = " ".join(words)
            break
    return tx._travis_address(a.get("SITUS_ADDRESS")), city, _clean(a.get("SITUS_ZIP"))


_P = tx._COLLIN_PREFIX


def _collin(a):
    return (tx._first_line(a.get(_P + "SITUS_DISPLAY")), _clean(a.get(_P + "SITUS_CITY")),
            _clean(a.get(_P + "SITUS_ZIP")))


def _denton(a):
    return (_clean(a.get("SITUS_STREET_ADDRESS")), _clean(a.get("SITUSCITY")),
            _clean(a.get("SITUSZIP")))


def _el_paso(a):
    street = " ".join(p for p in (_clean(a.get(k)) for k in
                                  ("SITUS_NUM", "SITUS_STRE", "SITUS_DIR")) if p)
    return (_with_unit(street, a.get("SITUS_UNIT")), _clean(a.get("SITUS_CITY")),
            _clean(a.get("SITUS_ZIP")))


def _cameron(a):
    street = " ".join(p for p in (_clean(a.get(k)) for k in
                                  ("SITUSNO", "SITPFX", "SITSTR", "SITSFX")) if p)
    return street, _clean(a.get("SITCITY")), _clean(a.get("SITZIP"))


def _williamson(a):
    street, city, zip5 = _situs_parts(a.get("SITEADDRESS"))
    return _with_unit(tx._williamson_address(street), a.get("UNIT")), city, zip5


@dataclass(frozen=True)
class _Draw:
    where: str
    fields: str
    read: Callable[[dict], tuple]
    oid: str = "OBJECTID"
    #: "offset" (paginated ArcGIS), "ids" (no pagination), "socrata" (Williamson)
    how: str = "offset"


_ABM = ("A", "B", "M")
_FIPS = {
    "48201": _Draw(_codes("STATECLASS", *_ABM, "Z"), "PARCEL_ID,ADDRESS,CITY,ZIP_CODE",
                   _harris),
    "48157": _Draw(f"({_codes('building_sptb_code', *_ABM)} OR ((building_sptb_code IS NULL "
                   f"OR building_sptb_code = '') AND {_codes('land_state_code', *_ABM)}))",
                   "quickrefid,situs,situsapt", _fort_bend, oid="objectid"),
    "48339": _Draw(_codes("STATECLASS", *_ABM), "PARCEL_ID,ADDRESS", _montgomery),
    "48113": _Draw("CLASSCD IN ('1','2','3','4','35','5','6')", "PARCELID,SITEADDRESS,UNIT",
                   _dallas),
    "48439": _Draw(_codes("Property_C", *_ABM), "TAXPIN,Situs_Addr", _tarrant, oid="FID",
                   how="ids"),
    "48029": _Draw(_codes("State_cd", *_ABM), "PropID,Situs", _bexar),
    "48453": _Draw(_codes("land_state_cd", *_ABM), "PROP_ID,situs_address,situs_zip",
                   _travis),
    "48085": _Draw(_codes(f"{_P}state_cd", "A", "B", "M3", listed=True),
                   f"{_P}prop_id,{_P}situs_display,{_P}situs_city,{_P}situs_zip", _collin),
    "48121": _Draw(_codes("stateCodes", *_ABM, listed=True),
                   "pid,situs_street_address,situsCity,situsZip", _denton),
    "48141": _Draw(_codes("STATE_CD", *_ABM),
                   "PROP_ID,SITUS_NUM,SITUS_STRE,SITUS_DIR,SITUS_UNIT,SITUS_CITY,SITUS_ZIP",
                   _el_paso),
    "48061": _Draw(_codes("statecd", *_ABM),
                   "prop_id,situsno,sitpfx,sitstr,sitsfx,sitcity,sitzip", _cameron, oid="fid"),
    "48491": _Draw(" OR ".join(f"starts_with(fsptb, '{p}')" for p in _ABM),
                   "parcelid,propertyid,siteaddress,unit", _williamson, how="socrata"),
}


def _ids_random(url: str, where: str, fields: str, n: int, seed: int):
    """``arcgis_random`` for a layer that refuses pagination: list the matching
    object ids, draw from them, fetch each drawn row by id."""
    body = get(url, {"where": where, "returnIdsOnly": "true", "f": "json"})
    ids = sorted((body or {}).get("objectIds") or [])
    if not ids:
        return [], 0
    feats = []
    picks = sorted(random.Random(seed).sample(ids, min(n, len(ids))))
    for oid in picks:
        got = get(url, {"objectIds": str(oid), "outFields": fields, "returnGeometry": "true",
                        "outSR": 4326, "f": "json"})
        fs = (got or {}).get("features") or []
        if fs:
            feats.append(fs[0])
    return feats, len(picks)


def _largest_polygon(geojson: dict) -> dict | None:
    """A GeoJSON (Multi)Polygon's largest part as ArcGIS rings."""
    if not geojson:
        return None
    polys = geojson.get("coordinates") or []
    if geojson.get("type") == "Polygon":
        polys = [polys]

    def area(poly):
        ring = poly[0] if poly else []
        return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:])))
    polys = [p for p in polys if p and p[0]]
    return {"rings": max(polys, key=area)} if polys else None


def _williamson_random(cfg: _Draw, n: int, seed: int):
    """Distinct WCAD property ids with a residential improvement, drawn uniformly,
    each with its parcel row and polygon. Returns (ArcGIS-shaped features,
    attempted)."""
    url = tx.WILLIAMSON_CHARACTERISTICS_URL
    body = get(url, {"$select": "count(distinct propertyid) AS n", "$where": cfg.where})
    total = int(body[0]["n"]) if isinstance(body, list) and body else 0
    if not total:
        return [], 0
    offsets = sorted(random.Random(seed).sample(range(total), min(n, total)))
    feats = []
    for off in offsets:
        rows = get(url, {"$select": "propertyid", "$where": cfg.where, "$group": "propertyid",
                         "$order": "propertyid", "$offset": str(off), "$limit": "1"})
        pid = tx._whole_number((rows[0] if isinstance(rows, list) and rows else {})
                               .get("propertyid"))
        if not pid.isdigit():
            continue
        parcels = get(tx.WILLIAMSON_URL, {"$select": cfg.fields + ",geometry",
                                          "$where": f"propertyid = '{pid}'"})
        if not isinstance(parcels, list) or not parcels:
            continue
        p = parcels[0]
        feats.append({"attributes": {k: v for k, v in p.items() if k != "geometry"},
                      "geometry": _largest_polygon(p.get("geometry"))})
    return feats, len(offsets)


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        cfg, county = _FIPS[fips], tx.COUNTIES[fips]
        if cfg.how == "socrata":
            feats, tried = _williamson_random(cfg, n, seed + i)
        elif cfg.how == "ids":
            feats, tried = _ids_random(county.url, cfg.where, cfg.fields, n, seed + i)
        else:
            feats, tried = arcgis_random(county.url, cfg.where, cfg.fields, n, seed + i,
                                         oid_field=cfg.oid)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = {str(k).upper(): v for k, v in (f.get("attributes") or {}).items()}
            street, city, zip5 = cfg.read(a)
            street = _clean(street)
            m = _ZIP.search(_clean(zip5)) if zip5 else None
            address = (typed(street, _clean(city) or None, "TX",
                             m.group(1) if m else zip_at(*pt))
                       if street[:1].isdigit() else "")
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1], "address": address,
                        "source_id": a.get(cfg.fields.split(",")[0].upper())})
    return out, attempted
