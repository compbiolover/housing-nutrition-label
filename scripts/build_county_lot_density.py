#!/usr/bin/env python3
"""Build the county typical-lot-density crosswalk.

Why
---
``enrich/infrastructure.py`` costs a parcel with two layers: the Halifax/Memphis
density curves give the *shape* (cost per household falls as density rises) and
the Census of Governments per-capita multipliers give the local *level*.
Multiplying them raw DOUBLE-COUNTS a rural county — its measured per-capita
spending is already elevated partly *because* its households are spread out, and
the rural end of the curve then charges for the same sparseness a second time. The
model consequently asserted that one rural household costs the public $9,137/yr in
non-school services, implying ~$178M/yr of local spending for a county of 47,694.

The fix needs one number per county: the density its measured spending was
observed at, **on the same axis as a parcel's lot density**, so the shape can be
expressed relative to it. An earlier attempt used gross county density (households
over every acre of dry land) and was abandoned before shipping: gross density is
dominated by how much forest or rangeland a county happens to contain, so it
overstated the difference between counties by more than an order of magnitude and
conflated two different quantities.

Method (reproducible, keyless — one Census reference workbook)
--------------------------------------------------------------
The 2020 Census urban/rural county table splits each county's HOUSING UNITS *and*
its LAND AREA into urban and rural parts. That separation is what makes a real lot
density computable: urban housing units over URBAN land, rural units over RURAL
land, so the empty hinterland is excluded from the developed figure instead of
diluting it.

    du_acre_urban = HOU_URB / (ALAND_URB acres)
    du_acre_rural = HOU_RUR / (ALAND_RUR acres)
    du_acre       = geometric mean of the two, weighted by housing units

Geometric rather than arithmetic because the cost curve is log-log: the blend has
to be taken in the space the curve interpolates in, or a county with any urban
core would be dragged to it.

The check that this axis is the right one
----------------------------------------
Shelby County — the pilot the whole cost model is calibrated to — comes out at
**1.41 DU/acre**, and ``enrich/infrastructure.py``'s own Memphis calibration notes
independently state the city runs "roughly 1.0-1.5 DU/acre at the city average".
The two were derived separately and agree, which is the corroboration the gross-
density attempt never had.

Source
------
US Census Bureau, 2020 Census Urban and Rural — county-level urban/rural table:
https://www2.census.gov/geo/docs/reference/ua/2020_UA_COUNTY.xlsx
Public domain. ``openpyxl`` is a BUILD-TIME dependency only; the shipped artifact
is the small CSV below.

Outputs (bundled, committed)
----------------------------
  src/housing_label/data/county_lot_density.csv
      geoid(5) + name + housing_units + du_acre_urban + du_acre_rural + du_acre
      (plus a national row, geoid 00000)

Run:  python scripts/build_county_lot_density.py
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import math
import pathlib
import sys

import requests

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

_DATA = _ROOT / "src" / "housing_label" / "data"
_OUT = _DATA / "county_lot_density.csv"

UA_COUNTY_URL = "https://www2.census.gov/geo/docs/reference/ua/2020_UA_COUNTY.xlsx"
_M2_PER_ACRE = 4046.8564224
NATIONAL_GEOID = "00000"

log = logging.getLogger("build_county_lot_density")


def _density(housing_units, aland_m2) -> float | None:
    """Housing units per acre of the given land class, or None when either side is
    absent — a county with no urban land has no urban density, which is different
    from having a density of zero."""
    try:
        hu = float(housing_units or 0)
        acres = float(aland_m2 or 0) / _M2_PER_ACRE
    except (TypeError, ValueError):
        return None
    if hu <= 0 or acres <= 0:
        return None
    return hu / acres


def _blend(pairs: list[tuple[float | None, float]]) -> float | None:
    """Housing-unit-weighted GEOMETRIC mean of (density, weight) pairs.

    Geometric because the cost curve interpolates in log space; an arithmetic mean
    would let a small dense core dominate a county that is overwhelmingly rural.
    """
    usable = [(d, w) for d, w in pairs if d and d > 0 and w and w > 0]
    total = sum(w for _, w in usable)
    if not usable or total <= 0:
        return None
    return math.exp(sum(w * math.log(d) for d, w in usable) / total)


def fetch_rows() -> list[dict]:
    try:
        import openpyxl
    except ImportError:  # pragma: no cover - build-time only
        raise SystemExit(
            "openpyxl is required to build this crosswalk (build-time only, not a "
            "runtime dependency): pip install openpyxl")
    log.info("fetching %s", UA_COUNTY_URL)
    r = requests.get(UA_COUNTY_URL, timeout=300)
    r.raise_for_status()
    ws = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True).worksheets[0]
    it = ws.iter_rows(values_only=True)
    hdr = next(it)
    idx = {h: i for i, h in enumerate(hdr) if h}
    out = []
    for row in it:
        state, county = row[idx["STATE"]], row[idx["COUNTY"]]
        if not state or not county:
            continue
        out.append({
            "geoid": f"{state}{county}".zfill(5),
            "name": f'{row[idx["COUNTY_NAME"]]}, {row[idx["STATE_NAME"]]}',
            "hou_urb": row[idx["HOU_URB"]] or 0,
            "hou_rur": row[idx["HOU_RUR"]] or 0,
            "aland_urb": row[idx["ALAND_URB"]] or 0,
            "aland_rur": row[idx["ALAND_RUR"]] or 0,
        })
    log.info("  %d counties", len(out))
    return out


def build() -> list[dict]:
    rows = []
    tot_hu_urb = tot_hu_rur = tot_a_urb = tot_a_rur = 0.0
    for r in fetch_rows():
        du_urb = _density(r["hou_urb"], r["aland_urb"])
        du_rur = _density(r["hou_rur"], r["aland_rur"])
        blended = _blend([(du_urb, r["hou_urb"]), (du_rur, r["hou_rur"])])
        if blended is None:
            # No housing units on record at all (a handful of territories) — skip
            # rather than invent a density; the runtime falls back to the national
            # row, which is a real measured figure.
            continue
        tot_hu_urb += r["hou_urb"]; tot_hu_rur += r["hou_rur"]
        tot_a_urb += r["aland_urb"]; tot_a_rur += r["aland_rur"]
        rows.append({
            "geoid": r["geoid"], "name": r["name"],
            "housing_units": int(r["hou_urb"] + r["hou_rur"]),
            "du_acre_urban": round(du_urb, 6) if du_urb else "",
            "du_acre_rural": round(du_rur, 6) if du_rur else "",
            "du_acre": round(blended, 6),
        })
    nat_urb = _density(tot_hu_urb, tot_a_urb)
    nat_rur = _density(tot_hu_rur, tot_a_rur)
    rows.append({
        "geoid": NATIONAL_GEOID, "name": "US national average",
        "housing_units": int(tot_hu_urb + tot_hu_rur),
        "du_acre_urban": round(nat_urb, 6) if nat_urb else "",
        "du_acre_rural": round(nat_rur, 6) if nat_rur else "",
        "du_acre": round(_blend([(nat_urb, tot_hu_urb), (nat_rur, tot_hu_rur)]), 6),
    })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=pathlib.Path, default=_OUT)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    rows = build()
    if len(rows) < 3000:
        print(f"only {len(rows)} rows — check the Census input; not writing",
              file=sys.stderr)
        return 1
    fields = ["geoid", "name", "housing_units", "du_acre_urban", "du_acre_rural",
              "du_acre"]
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    log.info("wrote %s (%d rows)", args.out, len(rows))
    by_geoid = {r["geoid"]: r for r in rows}
    for fips, label in (("47157", "Shelby TN (pilot)"), ("00000", "US national")):
        if fips in by_geoid:
            log.info("  %-20s du_acre = %s", label, by_geoid[fips]["du_acre"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
