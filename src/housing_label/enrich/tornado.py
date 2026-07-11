#!/usr/bin/env python3
"""Enrich parcels with FEMA National Risk Index tornado hazard data.

Usage
-----
  python -m housing_label.enrich.tornado                 # all parcels
  python -m housing_label.enrich.tornado --limit 10      # test with 10 rows first

Data source
-----------
  FEMA National Risk Index (NRI) — tornado expected annual loss, bundled offline
  by ``scripts/build_nri_tornado.py`` and read through ``data/tornado.py``.

  Each parcel resolves tract → county → national average, yielding a tornado
  **EAL rate** (fraction of building value lost to tornadoes per year). This is the
  location-based tornado hazard that ``score/resilience.py`` folds into the EAL
  model alongside flood, seismic, and fire.

  This replaces the old NOAA SPC touchdown-count model, which counted historical
  tornadoes within 25 miles and applied a single **TN/Mid-South EF-magnitude
  distribution (Ashley 2007) nationally** — so a Great Plains home was scored with
  Mid-South intensities. NRI's EAL rate reflects the **local** frequency *and* the
  **local** historic building-loss ratio, so "tornado alley" carries a much higher
  EAL than a low-risk area (~30× in the raw data) where the old model could not
  tell them apart.

  A parcel's 11-digit ``census_tract`` GEOID (added by the health enrichment)
  resolves at tract precision; without it the lookup falls back to the county
  (Shelby = 47157) — uniform across Shelby, which is a single county — then the
  national average.

Columns added
-------------
  tornado_nri_eal_rate    NRI tornado EAL rate (fraction/yr), tract→county→US
  tornado_risk_rating     FEMA qualitative tornado risk rating (e.g. "Very High")
  tornado_geo_level       geography that answered: tract / county / us
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys

import pandas as pd

from housing_label.data.tornado import tornado_for_county, tornado_for_tract

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[3]   # repo root; data CSVs live here

# All Shelby County parcels share this county FIPS — the fallback when a parcel
# has no resolvable census tract.
SHELBY_COUNTY_FIPS = "47157"

TORNADO_COLS = ["tornado_nri_eal_rate", "tornado_risk_rating", "tornado_geo_level"]


def _norm_tract(census_tract) -> str | None:
    """Normalise a raw census_tract value to an 11-digit GEOID string, or None.

    Mirrors ``enrich/fire._norm_tract`` so the join key matches the crosswalk
    everywhere: a tract column with any missing value makes pandas store the GEOID
    as a float (e.g. ``47157006300.0``), and tracts outside TN have leading zeros
    (e.g. ``06037...``). Strip any decimal suffix and zero-pad back to 11 digits so
    the value matches rather than silently falling back to the county/US rate.
    """
    if census_tract is None or pd.isna(census_tract):
        return None
    s = str(census_tract).strip()
    if s.lower() in ("nan", "none", ""):
        return None
    if "." in s:                       # stringified/numpy float, e.g. "47157006300.0"
        s = s.split(".")[0]
    return s.zfill(11)


def _lookup(census_tract, county_fips: str = SHELBY_COUNTY_FIPS) -> dict:
    """Resolve one parcel's tornado hazard from its census tract (county fallback)."""
    tract = _norm_tract(census_tract)
    if tract:
        return tornado_for_tract(tract)
    return tornado_for_county(county_fips)


def _resolve_path(p: str) -> pathlib.Path:
    path = pathlib.Path(p)
    return path if path.is_absolute() else SCRIPT_DIR / path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich parcels with FEMA NRI tornado hazard (EAL rate + rating)."
    )
    parser.add_argument("--input", default="shelby_parcels_climate.csv",
                        help="Input CSV path (relative paths resolve to repo root).")
    parser.add_argument("--output", default="shelby_parcels_tornado.csv",
                        help="Output CSV path (relative paths resolve to repo root).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N rows (for testing).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Load and validate input, log the plan, then exit.")
    args = parser.parse_args()

    in_file = _resolve_path(args.input)
    out_file = _resolve_path(args.output)

    if not in_file.exists():
        log.error("Input file does not exist: %s", in_file)
        sys.exit(1)

    log.info("Reading %s", in_file)
    df = pd.read_csv(in_file, low_memory=False)
    log.info("  %d rows × %d columns", *df.shape)

    if args.limit:
        df = df.head(args.limit)
        log.info("--limit %d: working on first %d rows only.", args.limit, len(df))

    # census_tract is added by the health enrichment; if it's absent the lookup
    # falls back to the Shelby county-level tornado rate for every parcel.
    has_tract = "census_tract" in df.columns
    if not has_tract:
        log.warning("No 'census_tract' column — falling back to county-level "
                    "tornado (%s) for all parcels.", SHELBY_COUNTY_FIPS)

    if args.dry_run:
        log.info("Dry run – no output written.")
        log.info("  Input  : %s", in_file)
        log.info("  Output : %s", out_file)
        log.info("  Rows   : %d  (tract column: %s)", len(df), has_tract)
        return

    log.info("Enriching %d parcels with NRI tornado hazard …", len(df))
    tract_series = df["census_tract"] if has_tract else [None] * len(df)
    records = []
    for i, tract in enumerate(tract_series, start=1):
        t = _lookup(tract)
        records.append({
            "tornado_nri_eal_rate": round(float(t["eal_rate"]), 9),
            "tornado_risk_rating": t["risk_rating"],
            "tornado_geo_level": t["geo_level"],
        })
        if i % 200 == 0 or i == len(df):
            log.info("  Progress: %d / %d", i, len(df))

    enriched = pd.DataFrame(records, index=df.index)
    for col in TORNADO_COLS:
        df[col] = enriched[col]

    df.to_csv(out_file, index=False)
    log.info("Saved → %s  (%d rows × %d cols)", out_file, df.shape[0], df.shape[1])

    # ── Summary ──────────────────────────────────────────────────────────────
    rate = df["tornado_nri_eal_rate"]
    print("\n── FEMA NRI TORNADO ENRICHMENT SUMMARY ──────────────────────────")
    print(f"  Rows enriched        : {len(df):,}")
    print(f"  Tornado EAL rate     : min {rate.min():.2e}  "
          f"mean {rate.mean():.2e}  max {rate.max():.2e}")
    print(f"  Resolved at          : "
          + "  ".join(f"{k}={v}" for k, v in df["tornado_geo_level"].value_counts().items()))
    print("  Risk-rating distribution:")
    for label, n in df["tornado_risk_rating"].value_counts(dropna=False).items():
        print(f"    {str(label):<22}: {n:>6,}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted.")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        log.error("Fatal: %s", exc, exc_info=True)
        sys.exit(1)
