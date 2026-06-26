#!/usr/bin/env python3
"""Build the bundled county FIPS → climate-projection crosswalk.

Writes ``src/housing_label/data/climate_projections.csv`` — the offline lookup
that lets ``data/climate_projections.py`` return real downscaled climate-hazard
projections for any US county instead of a uniform placeholder.

Source (fully keyless, government-sourced)
------------------------------------------
NOAA / DOI **Climate Mapping for Resilience and Adaptation (CMRA)** screening
dataset, served as a public ArcGIS FeatureServer. CMRA aggregates LOCA-downscaled
CMIP5 projections (the NCA4 downscaling) to county polygons as 30-year means for
historical, early-, mid-, and late-century windows under two emissions pathways,
RCP4.5 (lower) and RCP8.5 (higher). RCP4.5/RCP8.5 are the standard low/high
analogs of SSP2-4.5 / SSP5-8.5.

We pull the **mid-century (≈2050) ensemble-mean** for each county under both
pathways, plus the historical baseline, for five hazard metrics:

  • TMAX95F     — annual days with max temperature > 95 °F      (extreme heat)
  • TMAX100F    — annual days with max temperature > 100 °F     (extreme heat)
  • PR1IN       — annual days with > 1 inch precipitation       (heavy precip)
  • PRMAX5DAY   — annual highest 5-day precipitation total [in] (flood)
  • CONSECDD    — annual max consecutive dry days               (drought)

Caveats (documented in data/climate_projections.py too): CMRA is a ~6 km
downscaled grid aggregated to counties — a county aggregate, never parcel-scale
precision. CMIP5/RCP (not CMIP6/SSP); RCP4.5/8.5 are treated as low/high analogs
of SSP2-4.5/5-8.5. CMRA carries no native Fire Weather Index, so the drought leg
(consecutive dry days) stands in for the fire/drought hazard until a 12 km ClimRR
FWI layer is added.

Geo level (county vs tract)
---------------------------
``--geo-level county`` (default) builds the bundled county crosswalk. ``--geo-level
tract`` builds a tract crosswalk from CMRA's Tracts layer — but **we do not bundle
it**, because that layer carries **no sub-county signal**: it broadcasts the county
value onto every tract polygon (verified — hundreds of tracts across San Bernardino
/ LA / Maricopa report a single value equal to the county figure). The tract mode
exists for reproducibility and as a drop-in slot; the data module loads a tract
crosswalk if one is present. Genuinely finer resolution requires sampling the LOCA2
~6 km grid at the parcel lat/lon — a separate, network-gated build, not this offline
aggregate crosswalk.

Service
-------
  https://services3.arcgis.com/0Fs3HcaFfvzXvm7w/arcgis/rest/services/CMRA_Screening_Data/FeatureServer
  layer 0 = Counties, layer 1 = Census Tracts

Run:  python scripts/build_climate_projections.py                 # county (bundled)
      python scripts/build_climate_projections.py --geo-level tract  # tract (not bundled)
"""

from __future__ import annotations

import argparse
import csv
import gzip
import pathlib
import statistics
import sys
import time

import requests

_DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"

SERVICE_BASE = (
    "https://services3.arcgis.com/0Fs3HcaFfvzXvm7w/arcgis/rest/services/"
    "CMRA_Screening_Data/FeatureServer"
)
HEADERS = {"User-Agent": "housing-nutrition-label/0.1 (climate crosswalk build)"}

# Per geo level: ArcGIS layer id, the id field, its zero-pad width, the value
# written to the geo_level column, and the default output path. The county layer
# is the bundled crosswalk; the tract layer is opt-in and intentionally not
# bundled (it carries no sub-county signal — see module docstring).
GEO_LEVELS: dict[str, dict] = {
    "county": {
        "layer": 0, "id_field": "GEOID", "width": 5, "geo_level": "county",
        "out": _DATA_DIR / "climate_projections.csv", "expected": 3233,
    },
    "tract": {
        "layer": 1, "id_field": "GEOID", "width": 11, "geo_level": "tract",
        "out": _DATA_DIR / "climate_projections_tracts.csv.gz", "expected": 74000,
    },
}

# Hazard metric → output column stem. The CMRA fields follow the pattern
# {PERIOD}_MEAN_{METRIC}, where PERIOD ∈ {HISTORIC, RCP45MID, RCP85MID}.
METRICS = {
    "TMAX95F": "heat_days95",
    "TMAX100F": "heat_days100",
    "PR1IN": "precip_days1in",
    "PRMAX5DAY": "precip_max5day",
    "CONSECDD": "drought_consecdd",
}
# (period prefix, output band suffix)
BANDS = [("HISTORIC", "hist"), ("RCP45MID", "low"), ("RCP85MID", "high")]


def _cmra_fields(id_field: str) -> list[str]:
    fields = [id_field, "CountyName", "StateAbbr"]
    for metric in METRICS:
        for period, _ in BANDS:
            fields.append(f"{period}_MEAN_{metric}")
    return fields


def _out_columns() -> list[str]:
    cols = ["geoid", "geo_level", "county_name", "state"]
    for stem in METRICS.values():
        for _, band in BANDS:
            cols.append(f"{stem}_{band}")
    return cols


def _layer_max_record_count(service: str, default: int = 2000) -> int:
    """The layer's server-enforced maxRecordCount (default if metadata fails)."""
    try:
        r = requests.get(service, params={"f": "json"}, headers=HEADERS, timeout=60)
        r.raise_for_status()
        return int(r.json().get("maxRecordCount") or default)
    except (requests.RequestException, ValueError, TypeError):
        return default


def fetch_features(service: str, id_field: str) -> list[dict]:
    """Page through every feature in a layer, newest ArcGIS pagination."""
    fields = ",".join(_cmra_fields(id_field))
    rows: list[dict] = []
    # Cap the page size at the layer's maxRecordCount so the server can't
    # silently return fewer rows than requested.
    page = min(2000, _layer_max_record_count(service))
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": fields,
            "returnGeometry": "false",
            "orderByFields": id_field,
            "resultOffset": offset,
            "resultRecordCount": page,
            "f": "json",
        }
        for attempt in range(4):
            try:
                r = requests.get(f"{service}/query", params=params,
                                 headers=HEADERS, timeout=90)
                r.raise_for_status()
                data = r.json()
                break
            except (requests.RequestException, ValueError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        feats = data.get("features", [])
        if not feats:
            break
        rows.extend(f["attributes"] for f in feats)
        if not data.get("exceededTransferLimit"):
            break
        # Advance by the number actually returned (the server may cap a page
        # below the requested size), never by the requested page size.
        offset += len(feats)
    return rows


def to_output_row(attrs: dict, level: dict) -> dict | None:
    width = level["width"]
    geoid = str(attrs.get(level["id_field"]) or "").strip().zfill(width)
    if not geoid or len(geoid) != width:
        return None
    out = {
        "geoid": geoid,
        "geo_level": level["geo_level"],
        "county_name": (attrs.get("CountyName") or "").strip(),
        "state": (attrs.get("StateAbbr") or "").strip(),
    }
    for metric, stem in METRICS.items():
        for period, band in BANDS:
            val = attrs.get(f"{period}_MEAN_{metric}")
            out[f"{stem}_{band}"] = "" if val is None else round(float(val), 3)
    return out


def _print_quantiles(rows: list[dict]) -> None:
    """Print national quantiles of the low/high bands to anchor score breakpoints."""
    qs = [0.05, 0.25, 0.50, 0.75, 0.90, 0.95]
    print("\nNational quantiles (anchors for scoring breakpoints):", file=sys.stderr)
    for stem in METRICS.values():
        for band in ("low", "high"):
            vals = sorted(float(r[f"{stem}_{band}"]) for r in rows
                          if r[f"{stem}_{band}"] != "")
            if not vals:
                continue
            quants = statistics.quantiles(vals, n=100)
            picks = [quants[int(q * 100) - 1] for q in qs]
            joined = "  ".join(f"p{int(q*100)}={v:.1f}" for q, v in zip(qs, picks))
            print(f"  {stem+'_'+band:<26} {joined}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geo-level", choices=sorted(GEO_LEVELS), default="county",
                    help="county (bundled) or tract (opt-in, not bundled)")
    ap.add_argument("--service-base", default=SERVICE_BASE,
                    help="CMRA FeatureServer base URL (layer id appended per geo level)")
    ap.add_argument("--out", default=None, help="output path (defaults per geo level)")
    args = ap.parse_args()

    level = GEO_LEVELS[args.geo_level]
    service = f"{args.service_base}/{level['layer']}"
    out_path = pathlib.Path(args.out) if args.out else level["out"]

    if args.geo_level == "tract":
        print("NOTE: CMRA's Tracts layer carries NO sub-county signal — it broadcasts\n"
              "      the county value onto every tract. This output is intentionally\n"
              "      NOT bundled; it exists only for reproducibility / a drop-in slot.\n"
              "      Genuinely finer resolution needs LOCA2 ~6 km grid sampling.\n",
              file=sys.stderr)

    print(f"Fetching {args.geo_level} features from {service} …", file=sys.stderr)
    attrs = fetch_features(service, level["id_field"])
    rows = [r for r in (to_output_row(a, level) for a in attrs) if r]
    rows.sort(key=lambda r: r["geoid"])
    expected = level["expected"]
    if len(rows) < expected * 0.9:
        print(f"WARNING: only {len(rows)} {args.geo_level} rows fetched "
              f"(expected ~{expected}).", file=sys.stderr)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if out_path.suffix == ".gz" else open
    with opener(out_path, "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_out_columns())
        w.writeheader()
        w.writerows(rows)

    _print_quantiles(rows)
    print(f"\nWrote {len(rows)} {args.geo_level} rows → {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
