"""Ohio: homes drawn from the nine county auditors' layers the adapter reads.

A home is what the adapter calls one: a DTE land-use code of the agricultural
(1xx, a farmhouse), residential (5xx) or apartment (401-403) class — the
adapter's ``_is_a_home_code`` — that is not vacant land (``_VACANT`` and the
county's ``vacant_codes``) or a placeholder (the county's ``placeholder_codes``:
common areas, association land, condominium garages), with a recorded year
built. Codes are matched by prefix, as the adapter's ``_dte`` reads them, so
Cuyahoga's four-digit codes and Lorain's padded ones are read the same way.

The address is the site address, with the site's own city and ZIP where the
layer publishes them: Cuyahoga's ``parcel_city``/``parcel_zip``, Delaware's
``ADDR2`` (the site's "CITY, OH ZIP" line; its owner's are ``MAILADDR*``),
Lorain's ``SITEADDRESS`` tail, and the ``ZIPCD`` of Franklin and the Columbus
mirror. Elsewhere (Summit, Montgomery, Butler) the ZCTA at the parcel stands in:
Montgomery's ``LOC_ZIP`` disagrees with the street it is written beside often
enough (4060 Delphos Ave, Dayton, filed under 45402) that it is not used.
Owner and mailing columns are never read.
"""

from __future__ import annotations

import re

from housing_label.enrich.assessor import oh
from scripts.benchmark_samplers import allocate, arcgis_random, interior_point, typed, zip_at

ADAPTER = "oh"
ASSESSMENT_YEAR = "current"   # five live layers; Butler's 2024 and Licking's 2024 snapshots

_M, _P = "SDE.WEB_CAMA.", "SDE.mc_parcel_polygon."


def _home(cfg: oh.County, column: str) -> str:
    """The adapter's home-code rule for one land-use column, as a where clause."""
    homes = " OR ".join(f"{column} LIKE '{p}%'" for p in ("1", "5", *sorted(oh._APARTMENTS)))
    refused = sorted(oh._VACANT | cfg.vacant_codes | cfg.placeholder_codes)
    not_refused = " AND ".join(f"{column} NOT LIKE '{c}%'" for c in refused)
    return f"({homes}) AND {not_refused}"


def _where(fips: str, extra: str = "") -> str:
    cfg = oh.COUNTIES[fips]
    parts = [f"{cfg.year} > 0", _home(cfg, cfg.land_use[0])]
    if cfg.where:
        parts.insert(0, cfg.where)
    if extra:
        parts.append(extra)
    return " AND ".join(parts)


def _zip5(value) -> str | None:
    z = str(value or "").strip()[:5]
    return z if len(z) == 5 and z.isdigit() else None


_CITY_ZIP = re.compile(r"^\s*(?P<city>[^,]+?)\s*,\s*OH\s+(?P<zip>\d{5})")


def _city_zip(line) -> tuple[str | None, str | None]:
    m = _CITY_ZIP.match(str(line or ""))
    return (m.group("city"), m.group("zip")) if m else (None, None)


def _cuyahoga(a):
    street = str(a.get("par_addr_all") or "").split(",")[0]
    unit = str(a.get("parcel_unit") or "").strip()
    if unit and unit.upper() not in street.upper().split():
        street = f"{street} UNIT {unit}"
    return street, a.get("parcel_city"), _zip5(a.get("parcel_zip"))


#: Lorain's site city is what follows the LAST run of two or more spaces before
#: the comma ("5683   BOXWOOD DR  LORAIN, OH 44053") — the adapter's own reading.
_LORAIN_TAIL = re.compile(r"^.*\S\s{2,}(?P<city>\S[^,]*?)\s*,\s*OH\s+(?P<zip>\d{5})")


def _lorain(a):
    raw = str(a.get("SITEADDRESS") or "")
    m = _LORAIN_TAIL.match(raw)
    return (oh._lorain_street(raw), m.group("city") if m else None,
            m.group("zip") if m else None)


def _delaware(a):
    city, zip5 = _city_zip(a.get("ADDR2"))
    return a.get("ADDR1"), city, zip5


def _summit(a):
    unit = " ".join(str(a.get("unit") or "").split())
    return " ".join(f"{a.get('siteaddress') or ''} {unit}".split()), None, None


# fips: (url, where, outFields, oid field, reader -> (street, city, zip or None))
_FIPS = {
    "39049": (oh.FRANKLIN_URL, _where("39049"), "OBJECTID,SITEADDRESS,ZIPCD", "OBJECTID",
              lambda a: (a.get("SITEADDRESS"), None, _zip5(a.get("ZIPCD")))),
    "39035": (oh.CUYAHOGA_URL, _where("39035", "res_bldg_count > 0"),
              "ObjectID,par_addr_all,parcel_unit,parcel_city,parcel_zip", "ObjectID",
              _cuyahoga),
    "39153": (oh.SUMMIT_URL, _where("39153"), "OBJECTID,siteaddress,unit", "OBJECTID",
              _summit),
    "39113": (oh.MONTGOMERY_URL, _where("39113"), f"{_P}OBJECTID,{_M}PARLOC",
              f"{_P}OBJECTID", lambda a: (a.get(f"{_M}PARLOC"), None, None)),
    "39041": (oh.DELAWARE_URL, _where("39041"), "OBJECTID,ADDR1,ADDR2", "OBJECTID",
              _delaware),
    "39017": (oh.BUTLER_URL, _where("39017"), "OBJECTID,LOCATION", "OBJECTID",
              lambda a: (a.get("LOCATION"), None, None)),
    "39093": (oh.LORAIN_URL, _where("39093"), "OBJECTID,SITEADDRESS", "OBJECTID", _lorain),
    "39045": (oh.COLUMBUS_URL, _where("39045"), "OBJECTID,SITEADDRESS,ZIPCD", "OBJECTID",
              lambda a: (a.get("SITEADDRESS"), None, _zip5(a.get("ZIPCD")))),
    "39089": (oh.COLUMBUS_URL, _where("39089"), "OBJECTID,SITEADDRESS,ZIPCD", "OBJECTID",
              lambda a: (a.get("SITEADDRESS"), None, _zip5(a.get("ZIPCD")))),
}


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        url, where, fields, oid, read = _FIPS[fips]
        feats, tried = arcgis_random(url, where, fields, n, seed + i, oid_field=oid)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            street, city, zip5 = read(a)
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(street, city, "OH", zip5 or zip_at(*pt)),
                        "source_id": a.get(oid)})
    return out, attempted
