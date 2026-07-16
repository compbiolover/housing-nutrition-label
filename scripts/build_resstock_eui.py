#!/usr/bin/env python3
"""Build the bundled ResStock site-EUI benchmarks (by building type × climate zone
× vintage) plus the ResStock-derived within-cell factor table.

Writes two offline tables the Energy dimension reads at runtime (stdlib ``csv``,
no new runtime dependency):

``src/housing_label/data/resstock_eui.csv``  (building_type, climate_zone,
    vintage_bin, eui_kbtu_sqft_yr) — the base site EUI for a home. Keying on
    **building type** adds real medians for Single-Family Attached, Multi-Family
    (2-4 and 5+ units), and Mobile/Manufactured homes, instead of scoring every
    dwelling off the Single-Family-Detached curve. The multi-family medians make
    the modeled shared-wall credit unnecessary (the effect is now *measured*), and
    mobile homes — previously mis-scored as detached — get their own, higher curve.

``src/housing_label/data/resstock_factors.csv``  (axis, key, factor) — the
    within-cell multiplicative adjustments the model applies off the base EUI,
    now grounded in ResStock rather than hand-guessed: **foundation** type and
    **HVAC/heating** type. Each factor is a within-cell (zone × vintage) weighted-
    median EUI ratio vs. the cell's overall median, computed within Single-Family
    Detached — a climate-controlled deviation that keeps base_eui × factor unbiased.

Source (keyless, public)
------------------------
NREL ResStock 2024 (TMY3 release 2) baseline — one row per modeled dwelling
(~550k samples, ACS-derived stock, calibrated to utility data), on the OEDI data
lake. https://registry.opendata.aws/nrel-pds-building-stock/

  metric = out.site_energy.total.energy_consumption.kwh  (annual site energy)
  EUI (kBTU/sqft/yr) = metric * 3.412 / in.sqft
Each cell / factor is the ResStock-**weighted median** over its samples (weight =
each sample's representation of real homes).

Primary EUI rows emitted, per building type:
  • full zone × vintage        e.g. ("mf_5plus", "4A", "1950_1979")
  • digit-only zone × vintage  e.g. ("mf_5plus", "4",  "1950_1979") — the
    moisture-weighted fallback for a bundled zone string that is a bare digit
    (7, 8) or a regime ResStock doesn't sample; and
  • an "unknown" vintage row per zone/digit (all-vintage weighted median).
Zones a building type doesn't cover fall back (in the loader) to the digit, then
to Single-Family Detached, then to the legacy scaled-4A curve
(enrich/energy._FALLBACK_BASE_EUI × zone factor).

Run:  python scripts/build_resstock_eui.py                 # downloads the parquet
      python scripts/build_resstock_eui.py --parquet local.parquet
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import pathlib
import sys
import time

_DATA = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"
OUT_EUI = _DATA / "resstock_eui.csv"
OUT_FACTORS = _DATA / "resstock_factors.csv"

BASELINE_URL = (
    "https://oedi-data-lake.s3.amazonaws.com/nrel-pds-building-stock/"
    "end-use-load-profiles-for-us-building-stock/2024/resstock_tmy3_release_2/"
    "metadata_and_annual_results/national/parquet/"
    "baseline_metadata_and_annual_results.parquet"
)
KWH_TO_KBTU = 3.412

# A cell (building type × zone × vintage) needs at least this many modeled samples
# for a stable weighted median. Thin cells — e.g. "pre-1950 mobile home" (a near-
# empty category, 1-2 samples) — otherwise emit garbage (an 8.5 kBTU/sqft/yr
# median). Below the floor the cell is omitted; the loader falls back to the robust
# digit-zone / all-vintage / detached aggregates instead.
MIN_SAMPLES = 30

# ResStock RECS building type → the model's coarser dwelling category. A label not
# listed here fails the build (see main) rather than being silently dropped.
BUILDING_TYPE = {
    "Single-Family Detached": "sf_detached",
    "Single-Family Attached": "sf_attached",
    "Multi-Family with 2 - 4 Units": "mf_2_4",
    "Multi-Family with 5+ Units": "mf_5plus",
    "Mobile Home": "mobile_home",
}
BUILDING_TYPE_ORDER = ["sf_detached", "sf_attached", "mf_2_4", "mf_5plus", "mobile_home"]

# ResStock vintage label → the model's coarser vintage bin. Matches
# enrich/energy.vintage_bin (year >= 2010 → "2010_plus"), so 2020s maps there too.
VINTAGE_BIN = {
    "<1940": "pre_1950", "1940s": "pre_1950",
    "1950s": "1950_1979", "1960s": "1950_1979", "1970s": "1950_1979",
    "1980s": "1980_1999", "1990s": "1980_1999",
    "2000s": "2000_2009",
    "2010s": "2010_plus", "2020s": "2010_plus",
}
VINTAGE_ORDER = ["pre_1950", "1950_1979", "1980_1999", "2000_2009", "2010_plus", "unknown"]

# ── Within-cell factor axes (computed within SF Detached, normalized to baseline) ──
# ResStock foundation type → the model's foundation label (enrich/energy._foundation_factor:
# BSMT 1=crawl/slab, 2=partial basement, 3=full basement). Slab & crawl & pier
# (Ambient) all read as the crawl/slab baseline the model uses today.
FOUNDATION_TO_LABEL = {
    "Slab": "crawlspace_slab",
    "Vented Crawlspace": "crawlspace_slab",
    "Unvented Crawlspace": "crawlspace_slab",
    "Ambient": "crawlspace_slab",
    "Unheated Basement": "partial_basement",
    "Heated Basement": "full_basement",
}
FOUNDATION_ORDER = ["crawlspace_slab", "partial_basement", "full_basement"]

# ResStock (hvac_heating_type, heating_fuel) → the model's HVAC label
# (enrich/energy._hvac_factor: heat_pump / electric_resistance / gas_furnace).
HEAT_PUMP_TYPES = {"Ducted Heat Pump", "Non-Ducted Heat Pump"}
DUCTED_HEATING_TYPES = {"Ducted Heating", "Non-Ducted Heating"}
HVAC_ORDER = ["heat_pump", "electric_resistance", "gas_furnace"]


def _hvac_label(heating_type: str, heating_fuel: str) -> str | None:
    if heating_type in HEAT_PUMP_TYPES:
        return "heat_pump"
    if heating_type in DUCTED_HEATING_TYPES:
        return "electric_resistance" if heating_fuel == "Electricity" else "gas_furnace"
    return None  # "None" heating type — excluded from the factor


COLS = ["in.geometry_building_type_recs", "in.ashrae_iecc_climate_zone_2004",
        "in.vintage", "in.sqft", "out.site_energy.total.energy_consumption.kwh",
        "in.geometry_foundation_type", "in.hvac_heating_type", "in.heating_fuel",
        "weight"]


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

    # Fail fast with actionable guidance on the build-time deps (pyarrow/pandas/
    # numpy always; requests only when downloading), rather than a bare ImportError
    # from deep inside a lazy import later.
    needed = ["pyarrow", "pandas", "numpy"] + ([] if args.parquet else ["requests"])
    missing = [m for m in needed if importlib.util.find_spec(m) is None]
    if missing:
        raise SystemExit(f"build_resstock_eui needs build-time deps not installed: "
                         f"{missing} — pip install {' '.join(missing)}")

    import pyarrow.parquet as pq

    if args.parquet:
        path = pathlib.Path(args.parquet)
    else:
        cache = pathlib.Path(args.cache_dir
                             or (pathlib.Path(__file__).resolve().parents[1] / ".resstock_cache"))
        path = _download(BASELINE_URL, cache / "resstock_baseline.parquet")

    df = pq.read_table(path, columns=COLS).to_pandas()
    df = df[(df["in.sqft"] > 0) & df["out.site_energy.total.energy_consumption.kwh"].notna()]
    df["eui"] = df["out.site_energy.total.energy_consumption.kwh"] * KWH_TO_KBTU / df["in.sqft"]

    df["btype"] = df["in.geometry_building_type_recs"].map(BUILDING_TYPE)
    # Fail fast: an unmapped building type / vintage would be silently dropped and
    # skew (or omit) that stock. Force a mapping update instead.
    unmapped_bt = sorted(df.loc[df["btype"].isna(),
                                "in.geometry_building_type_recs"].dropna().unique())
    if unmapped_bt:
        raise SystemExit(f"unmapped ResStock building types {unmapped_bt} — add them to BUILDING_TYPE")
    df["vbin"] = df["in.vintage"].map(VINTAGE_BIN)
    unmapped_v = sorted(df.loc[df["vbin"].isna(), "in.vintage"].dropna().unique())
    if unmapped_v:
        raise SystemExit(f"unmapped ResStock vintage labels {unmapped_v} — add them to VINTAGE_BIN")

    df["zone"] = df["in.ashrae_iecc_climate_zone_2004"].astype(str)
    df["digit"] = df["zone"].str[0]
    print(f"Aggregating {len(df):,} ResStock samples across {df['btype'].nunique()} "
          f"building types.", file=sys.stderr)

    # ── Primary EUI table: building_type × zone × vintage (+ digit & unknown) ──
    eui_rows: dict[tuple[str, str, str], float] = {}

    def add(btype: str, zone_key: str, frame) -> None:
        # Per-vintage cells, each only if it clears the sample floor (thin cells
        # fall back in the loader). The all-vintage "unknown" cell pools every
        # vintage, so it clears the floor for any real zone.
        for vb, g in frame.groupby("vbin"):
            if len(g) >= MIN_SAMPLES:
                eui_rows[(btype, zone_key, vb)] = round(_weighted_median(g["eui"], g["weight"]), 1)
        if len(frame) >= MIN_SAMPLES:
            eui_rows[(btype, zone_key, "unknown")] = round(
                _weighted_median(frame["eui"], frame["weight"]), 1)

    for (btype, zone), g in df.groupby(["btype", "zone"]):
        add(btype, zone, g)              # full zone, e.g. ("mf_5plus", "4A")
    for (btype, digit), g in df.groupby(["btype", "digit"]):
        add(btype, digit, g)             # digit fallback, e.g. ("mf_5plus", "4")

    bt_rank = {b: i for i, b in enumerate(BUILDING_TYPE_ORDER)}
    with OUT_EUI.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["building_type", "climate_zone", "vintage_bin", "eui_kbtu_sqft_yr"])
        for btype in sorted({b for b, _, _ in eui_rows}, key=lambda b: bt_rank.get(b, 99)):
            zones = sorted({z for b, z, _ in eui_rows if b == btype})
            for zone_key in zones:
                for vb in VINTAGE_ORDER:
                    if (btype, zone_key, vb) in eui_rows:
                        w.writerow([btype, zone_key, vb, eui_rows[(btype, zone_key, vb)]])

    # ── Within-cell factor table (foundation, HVAC), within SF Detached ──
    # Each factor is a *deviation from the cell base* so that base_eui × factor stays
    # unbiased: within each (zone × vintage) cell it is the ratio of the label's
    # weighted-median EUI to the cell's OVERALL weighted median (the same population
    # the base EUI is built from), aggregated across cells (weighted by the label's
    # sample count). Controlling for zone × vintage isolates the foundation/HVAC
    # effect from the climate/vintage confound (basements and gas furnaces cluster in
    # cold, older stock); dividing by the cell overall — not by a chosen baseline
    # label — keeps the majority label near 1.0 and the base + factor consistent.
    import numpy as np
    sfd = df[df["btype"] == "sf_detached"]
    factor_rows: list[tuple[str, str, float]] = []

    def _factors(axis: str, label_series, order: list[str]) -> None:
        g = sfd.assign(_lab=label_series)
        ratios: dict[str, list[tuple[float, float]]] = {lab: [] for lab in order}
        for _, cell in g.groupby(["zone", "vbin"]):
            cell_med = _weighted_median(cell["eui"], cell["weight"])   # base population
            if cell_med <= 0:
                continue
            for lab, sub in cell.dropna(subset=["_lab"]).groupby("_lab"):
                if lab in ratios:
                    med = _weighted_median(sub["eui"], sub["weight"])
                    ratios[lab].append((med / cell_med, float(sub["weight"].sum())))
        for lab in order:
            pairs = ratios[lab]
            if pairs:
                r = np.array([p[0] for p in pairs])
                w = np.array([p[1] for p in pairs])
                factor_rows.append((axis, lab, round(_weighted_median(r, w), 3)))

    _factors("foundation", sfd["in.geometry_foundation_type"].map(FOUNDATION_TO_LABEL),
             FOUNDATION_ORDER)
    _factors("hvac", [_hvac_label(ht, hf) for ht, hf
                      in zip(sfd["in.hvac_heating_type"], sfd["in.heating_fuel"])],
             HVAC_ORDER)

    with OUT_FACTORS.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["axis", "key", "factor"])
        for row in factor_rows:
            w.writerow(row)

    n_bt = len({b for b, _, _ in eui_rows})
    print(f"Wrote {OUT_EUI.relative_to(_DATA.parents[2])} — {len(eui_rows)} EUI cells "
          f"across {n_bt} building types.", file=sys.stderr)
    print(f"Wrote {OUT_FACTORS.relative_to(_DATA.parents[2])} — {len(factor_rows)} "
          f"within-cell factors.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
