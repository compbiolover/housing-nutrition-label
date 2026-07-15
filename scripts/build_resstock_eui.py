#!/usr/bin/env python3
"""Build the bundled ResStock site-EUI benchmark table (by climate zone × vintage).

Writes ``src/housing_label/data/resstock_eui.csv`` (climate_zone, vintage_bin,
eui_kbtu_sqft_yr) — the offline benchmark the Energy dimension uses as the base
site-EUI for a home, replacing the old single national 4A curve scaled by a crude
per-zone multiplier. Grounding the base EUI in real simulation medians captures
what the old scalar could not: the large A/B/C moisture-regime spread within a
zone (e.g. humid 3A vs dry 3B) and empirical per-vintage decay.

Source (keyless, public)
------------------------
NREL ResStock 2024 (TMY3 release 2) baseline — one row per modeled dwelling
(~550k samples, ACS-derived stock, calibrated to utility data), on the OEDI data
lake. https://registry.opendata.aws/nrel-pds-building-stock/

  metric = out.site_energy.total.energy_consumption.kwh  (annual site energy)
  EUI (kBTU/sqft/yr) = metric * 3.412 / in.sqft
  We keep **Single-Family Detached** — the standalone-home base the model's
  archetype represents; the multi-unit shared-wall credit is applied separately
  (dimensions.attachment_eui_factor), and mobile / attached stock differs enough
  to warrant its own benchmark if ever added.

Each cell is the ResStock-**weighted median** EUI over its samples (weight =
each sample's representation of real homes). Rows emitted:
  • full zone × vintage        e.g. ("4A", "1950_1979")
  • digit-only zone × vintage  e.g. ("4",  "1950_1979") — the moisture-weighted
    fallback for counties whose bundled zone string is a bare digit (7, 8) or a
    regime ResStock doesn't sample; and
  • an "unknown" vintage row per zone/digit (all-vintage weighted median), for
    homes with no year built.
Zones ResStock doesn't cover at all (e.g. 8 / interior Alaska) are left out — the
Energy model falls back to its prior scaled-4A curve (enrich/energy._FALLBACK_BASE_EUI
× zone factor) there.

Run:  python scripts/build_resstock_eui.py                 # downloads the parquet
      python scripts/build_resstock_eui.py --parquet local.parquet
"""

from __future__ import annotations

import argparse
import csv
import pathlib
import sys
import time

_DATA = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"
OUT = _DATA / "resstock_eui.csv"

BASELINE_URL = (
    "https://oedi-data-lake.s3.amazonaws.com/nrel-pds-building-stock/"
    "end-use-load-profiles-for-us-building-stock/2024/resstock_tmy3_release_2/"
    "metadata_and_annual_results/national/parquet/"
    "baseline_metadata_and_annual_results.parquet"
)
KWH_TO_KBTU = 3.412

# ResStock vintage label → the model's coarser vintage bin. Matches
# enrich/energy.vintage_bin (year >= 2010 → "2010_plus"), so 2020s maps there too.
# A ResStock label not listed here fails the build (see main) rather than being
# silently dropped from the aggregation.
VINTAGE_BIN = {
    "<1940": "pre_1950", "1940s": "pre_1950",
    "1950s": "1950_1979", "1960s": "1950_1979", "1970s": "1950_1979",
    "1980s": "1980_1999", "1990s": "1980_1999",
    "2000s": "2000_2009",
    "2010s": "2010_plus", "2020s": "2010_plus",
}
VINTAGE_ORDER = ["pre_1950", "1950_1979", "1980_1999", "2000_2009", "2010_plus", "unknown"]

COLS = ["in.ashrae_iecc_climate_zone_2004", "in.vintage",
        "in.geometry_building_type_recs", "in.sqft",
        "out.site_energy.total.energy_consumption.kwh", "weight"]


def _download(url: str, dest: pathlib.Path) -> pathlib.Path:
    if dest.exists() and dest.stat().st_size > (1 << 24):
        print(f"  cached {dest.name} ({dest.stat().st_size/1e6:.0f} MB)", file=sys.stderr)
        return dest
    import requests
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        try:
            with requests.get(url, timeout=600, stream=True) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                tmp.replace(dest)
            print(f"  downloaded {dest.name} ({dest.stat().st_size/1e6:.0f} MB)", file=sys.stderr)
            return dest
        except requests.RequestException as exc:
            print(f"  attempt {attempt+1} failed: {exc}", file=sys.stderr)
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return dest


def _weighted_median(values, weights) -> float:
    import numpy as np
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    order = np.argsort(v)
    v, w = v[order], w[order]
    return float(np.interp(0.5 * w.sum(), np.cumsum(w), v))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parquet", default=None, help="local baseline parquet (skip download)")
    ap.add_argument("--cache-dir", default=None, help="download cache directory")
    args = ap.parse_args()

    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit("build_resstock_eui needs pyarrow (build-time only): "
                         "pip install pyarrow") from exc

    if args.parquet:
        path = pathlib.Path(args.parquet)
    else:
        cache = pathlib.Path(args.cache_dir
                             or (pathlib.Path(__file__).resolve().parents[1] / ".resstock_cache"))
        path = _download(BASELINE_URL, cache / "resstock_baseline.parquet")

    df = pq.read_table(path, columns=COLS).to_pandas()
    df = df[df["in.geometry_building_type_recs"] == "Single-Family Detached"].copy()
    df = df[(df["in.sqft"] > 0) & df["out.site_energy.total.energy_consumption.kwh"].notna()]
    df["eui"] = df["out.site_energy.total.energy_consumption.kwh"] * KWH_TO_KBTU / df["in.sqft"]
    df["vbin"] = df["in.vintage"].map(VINTAGE_BIN)
    # Fail fast: an unmapped ResStock vintage would be silently dropped, skewing
    # the medians for that stock. Force a VINTAGE_BIN update instead.
    unmapped = sorted(df.loc[df["vbin"].isna(), "in.vintage"].dropna().unique())
    if unmapped:
        raise SystemExit(f"unmapped ResStock vintage labels {unmapped} — add them to VINTAGE_BIN")
    df["zone"] = df["in.ashrae_iecc_climate_zone_2004"].astype(str)
    df["digit"] = df["zone"].str[0]
    print(f"Aggregating {len(df):,} SF-detached ResStock samples.", file=sys.stderr)

    rows: dict[tuple[str, str], float] = {}

    def add(zone_key: str, frame) -> None:
        # per-vintage cells + an all-vintage "unknown" cell
        for vb, g in frame.groupby("vbin"):
            rows[(zone_key, vb)] = round(_weighted_median(g["eui"], g["weight"]), 1)
        rows[(zone_key, "unknown")] = round(_weighted_median(frame["eui"], frame["weight"]), 1)

    for zone, g in df.groupby("zone"):
        add(zone, g)              # full zone, e.g. "4A"
    for digit, g in df.groupby("digit"):
        add(digit, g)             # digit fallback, e.g. "4" (moisture-weighted)

    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["climate_zone", "vintage_bin", "eui_kbtu_sqft_yr"])
        for zone_key in sorted({z for z, _ in rows}):
            for vb in VINTAGE_ORDER:
                if (zone_key, vb) in rows:
                    w.writerow([zone_key, vb, rows[(zone_key, vb)]])
    n_zones = len({z for z, _ in rows})
    print(f"Wrote {OUT.relative_to(_DATA.parents[2])} — {len(rows)} cells across "
          f"{n_zones} zone keys.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
