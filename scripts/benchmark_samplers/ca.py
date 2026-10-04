"""California (Contra Costa, San Joaquin, Riverside): homes drawn from each county's layer.

Allocated across the three counties by housing units, then drawn uniformly from
the records each county's rules in the adapter read as homes:

* Contra Costa — the residential ``USE_CODE`` values the adapter reads as homes
  (including the two "several residences" codes, whose year it then refuses).
  Address from the situs parts with the layer's situs city ``s_city`` and ZIP
  ``S_ZIP``; the ``N_*`` columns are the owner's mailing address and are never read.
* San Joaquin — category RESIDENTIAL less the vacant, garage-only and pool-only
  use codes, plus farms the county describes "W/RESIDENCE". ``SITUSCITY`` is a
  jurisdiction code ("UNTR"), not a city, and ``SITUSZIP`` is blank on most rows,
  so the postal city and ZIP are read from the situs line ``FULL_ADDRESS``
  ("... TRACY CA 95377"), never from the MAIL* columns.
* Riverside — residential ``CLASS_CODE`` values on BOTH the parcel layer (50)
  and the condominium layer (30), drawn from their union: at a condominium the
  parcel layer holds only the common lot, so the units exist only on layer 30.
  Address from the situs parts with the situs ``CITY`` and ``ZIP_CODE``
  (MAIL_STREET/MAIL_CITY are the owner's and are never read).

Condominium units are typed with their unit, as their residents would.
"""

from __future__ import annotations

import random
import re

from housing_label.enrich.assessor import ca
from scripts.benchmark_samplers import (allocate, arcgis_count, arcgis_random,
                                        interior_point, typed, zip_at)

ADAPTER = "ca"
# Each county's own roll: San Joaquin's rows carry VALUE_ROLL_YEAR 2026; Contra
# Costa and Riverside publish no roll year on these layers.
ASSESSMENT_YEAR = "current"


def _txt(v) -> str:
    return " ".join(str(v if v is not None else "").split())


def _zip5(v) -> str | None:
    if isinstance(v, (int, float)) and v > 0:
        return f"{int(v):05d}"
    z = _txt(v)[:5]
    return z if len(z) == 5 and z.isdigit() else None


def _with_unit(street: str, unit) -> str:
    u = _txt(unit).lstrip("#").strip()
    return f"{street} #{u}" if street and u else street


def _number(v) -> str:
    n = _txt(v)
    if n.endswith(".0"):
        n = n[:-2]
    return n if n.isdigit() and int(n) > 0 else ""


# ── Contra Costa ────────────────────────────────────────────────────────────────

_CC_WHERE = "USE_CODE IN (%s)" % ",".join(
    str(c) for c in sorted(ca._CC_HOMES | ca._CC_SEVERAL))
_CC_FIELDS = "OBJECTID,APN,S_STR_NBR,S_STR_NM,S_STR_SUF,S_APT_NBR,s_city,S_ZIP"


def _cc(a: dict, pt) -> tuple[str, str]:
    number = _number(a.get("S_STR_NBR"))
    name = _txt(a.get("S_STR_NM"))
    street = " ".join(p for p in (number, name, _txt(a.get("S_STR_SUF"))) if p) \
        if number and name else ""
    zip5 = _zip5(a.get("S_ZIP")) or zip_at(*pt)
    city = _txt(a.get("s_city")) or None
    return typed(_with_unit(street, a.get("S_APT_NBR")), city, "CA", zip5), _txt(a.get("APN"))


# ── San Joaquin ─────────────────────────────────────────────────────────────────

_SJ_WHERE = ("(CATEGORY='RESIDENTIAL' AND (USECODE IS NULL OR USECODE NOT IN (%s))) "
             "OR (CATEGORY='AGRICULTURAL' AND DESCRIPTION LIKE '%%W/RESIDENCE')"
             % ",".join(f"'{c}'" for c in sorted(ca._SJ_NOT_A_HOME)))
_SJ_FIELDS = ("OBJECTID,APN,SITUSNUMBER,SITUSDIRECTION,SITUSTREET,SITUSTYPE,SITUSUNIT,"
              "SITUSZIP,FULL_ADDRESS")
# The county's two-letter street types in the words a resident writes: the
# adapter's own respellings plus the two the shared table reads as written.
_SJ_TYPES = {**ca._SJ_TYPES, "WY": "WAY", "AV": "AVE"}
_SJ_TAIL = re.compile(r"^(?P<head>.*?)\s+CA\s+(?P<zip>\d{5})(?:-\d{4})?$")


def _sj(a: dict, pt) -> tuple[str, str]:
    number = _number(a.get("SITUSNUMBER"))
    raw_type = _txt(a.get("SITUSTYPE")).upper()
    prefix = " ".join(p for p in (number, _txt(a.get("SITUSDIRECTION")),
                                  _txt(a.get("SITUSTREET")), raw_type) if p)
    unit = _txt(a.get("SITUSUNIT"))
    words = [number] + (["1/2"] if unit == "1/2" else []) + \
        [p for p in (_txt(a.get("SITUSDIRECTION")), _txt(a.get("SITUSTREET")),
                     _SJ_TYPES.get(raw_type, raw_type)) if p]
    street = " ".join(words) if number and _txt(a.get("SITUSTREET")) else ""
    if unit != "1/2":
        street = _with_unit(street, unit)
    city, zip5 = None, _zip5(a.get("SITUSZIP"))
    m = _SJ_TAIL.match(_txt(a.get("FULL_ADDRESS")).upper())
    if m:
        zip5 = zip5 or m["zip"]
        head = m["head"]
        if prefix and head.startswith(prefix + " "):
            city = head[len(prefix) + 1:].strip() or None
    return typed(street, city, "CA", zip5 or zip_at(*pt)), _txt(a.get("APN"))


# ── Riverside ───────────────────────────────────────────────────────────────────

_RV_CLASSES = (
    "Single Family Dwelling", "Condo or PUD", "SFD with Secondary Unit(s)",
    "MH on Foundation (MF)", "MH Lot with MH on LPT (MO)", "MH Lot with MH on ILT (MR)",
    "Duplex", "Triplex", "Fourplex", "Residential Exceptional", "Residential Restricted",
    "Residential Use Zoned Commercial", "Multiple Living Units (MH)",
    "Agricultural Land with SFR", "Agricultural Land with MH on Foundation",
    "Factory Built SFD", "Cooperative",
)
_RV_WHERE = ("CLASS_CODE IN (%s) OR CLASS_CODE LIKE 'HOMESITE%%' "
             "OR CLASS_CODE LIKE 'Apartment%%'"
             % ",".join(f"'{c}'" for c in _RV_CLASSES))
_RV_FIELDS = ("OBJECTID,APN,STREET_NUMBER,STREET_PREDIRECTION,STREET_NAME,STREET_TYPE,"
              "STREET_SUFFIX,UNIT_NUMBER,CITY,ZIP_CODE")


def _rv(a: dict, pt) -> tuple[str, str]:
    number = _number(a.get("STREET_NUMBER"))
    name = _txt(a.get("STREET_NAME"))
    suffix = _txt(a.get("STREET_SUFFIX")).upper()
    words = [number] + (["1/2"] if suffix == "1/2" else []) + \
        [p for p in (_txt(a.get("STREET_PREDIRECTION")), name,
                     _txt(a.get("STREET_TYPE"))) if p]
    if suffix in ca._RV_DIRECTIONS:
        words.append(suffix)
    street = " ".join(words) if number and name else ""
    zip5 = _zip5(a.get("ZIP_CODE")) or zip_at(*pt)
    return (typed(_with_unit(street, a.get("UNIT_NUMBER")), _txt(a.get("CITY")) or None,
                  "CA", zip5), _txt(a.get("APN")))


def _riverside(n: int, seed: int) -> tuple[list[tuple[dict, object]], int]:
    """``n`` homes from the union of the parcel and condominium layers.

    The offsets are drawn over the two filtered sets end to end, so each layer
    gets its share by chance in proportion to its size, as one table would.
    """
    t50 = arcgis_count(ca.RIVERSIDE_PARCEL_URL, _RV_WHERE) or 0
    t30 = arcgis_count(ca.RIVERSIDE_CONDO_URL, _RV_WHERE) or 0
    if not t50 + t30:
        return [], 0
    picks = random.Random(seed).sample(range(t50 + t30), min(n, t50 + t30))
    n50 = sum(p < t50 for p in picks)
    out, attempted = [], 0
    for url, k, s in ((ca.RIVERSIDE_PARCEL_URL, n50, seed + 101),
                      (ca.RIVERSIDE_CONDO_URL, len(picks) - n50, seed + 103)):
        if k:
            feats, tried = arcgis_random(url, _RV_WHERE, _RV_FIELDS, k, s)
            out += feats
            attempted += tried
    return out, attempted


# ── the draw ────────────────────────────────────────────────────────────────────

#: County FIPS -> how to draw it: (url, where, fields, address-of) or Riverside's
#: two-layer draw.
_FIPS = {
    "06013": (ca.CONTRA_COSTA_URL, _CC_WHERE, _CC_FIELDS, _cc),
    "06077": (ca.SAN_JOAQUIN_URL, _SJ_WHERE, _SJ_FIELDS, _sj),
    "06065": (None, None, None, _rv),
}


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        url, where, fields, address_of = _FIPS[fips]
        if url is None:
            feats, tried = _riverside(n, seed + i)
        else:
            feats, tried = arcgis_random(url, where, fields, n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            address, apn = address_of(f["attributes"], pt)
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1], "address": address,
                        "source_id": apn or f["attributes"].get("OBJECTID")})
    return out, attempted
