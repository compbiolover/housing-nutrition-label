#!/usr/bin/env python3
"""score_all_dimensions.py — multi-dimension scoring & grading for the Housing
Nutrition Label.

Until now only *disaster resilience* carried a full 0–100 score with national and
local A–F grades (score_resilience.py).  Every other dimension lived in the data
as a raw metric (EUI, fiscal ratio, health index, socioeconomic index) without a
grade.  This script reads the fully-enriched, already-resilience-scored CSV and
extends the same dual-grading treatment to **all** dimensions, then rolls them up
into a single composite score.

Dimensions
----------
  resilience      EAL-based disaster-resilience score from score_resilience.py
                  (already 0–100; carried through unchanged).
  energy          EUI (kBTU/sqft/yr) → 0–100, log-linear between breakpoints.
  durability      Component-lifespan / effective-age durability score from
                  enrich/durability.py (already 0–100; used directly). NaN for
                  parcels with no CAMA building data (vacant/non-residential).
  infrastructure  Municipal fiscal ratio → 0–100, log-linear between breakpoints.
  health          CDC PLACES health_index (already 0–100; used directly).
  socioeconomic   Census ACS socioeconomic_index (already 0–100, higher = less
                  economic stress; used directly).
  walkability     Walk Score API.  Walk Score is already 0–100 and used directly
                  as the dimension score; where transit and bike scores are also
                  available a composite is taken (60% walk + 25% transit + 15%
                  bike), weighted toward walkability since it matters most for
                  daily life.  Walk scores live in shelby_parcels_enriched.csv
                  (a separate, API-gated enrichment) and are merged in on PARID.
  climate         Placeholder: uniform 50 for every parcel until per-parcel
                  climate projections exist.  Excluded from the composite.

For every dimension X this writes four columns:
  X_score            raw 0–100 score
  X_national_grade   absolute thresholds  (A≥80, B≥60, C≥40, D≥20, F<20)
  X_local_grade      percentile bands within this dataset
                     (A=top 10%, B=next 25%, C=next 30%, D=next 25%, F=bottom 10%)
  X_percentile       0–100 percentile rank within this dataset

Composite
---------
  composite_score            simple mean of the dimension scores, EXCLUDING the
                             climate placeholder (and skipping any dimension that
                             is missing for a given parcel).
  composite_national_grade   national grade of composite_score.
  composite_local_grade      local (percentile) grade of composite_score.
  composite_percentile       composite percentile rank within this dataset.

The national/local grade thresholds intentionally match score_resilience.py so a
parcel's resilience grade means exactly the same thing whether it is read from
the resilience dimension or any other.

Usage
-----
  python score_all_dimensions.py                       # default in/out
  python score_all_dimensions.py --input X --output Y
  python score_all_dimensions.py --limit 50            # quick subset (ranks reflect subset)
  python score_all_dimensions.py --dry-run             # validate + plan, write nothing
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger("score_all")

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[3]   # repo root; data lives here

DEFAULT_INPUT  = "shelby_parcels_scored.csv"   # last enrichment + resilience scores
DEFAULT_OUTPUT = "shelby_parcels_final.csv"
DEFAULT_WALKSCORE = "shelby_parcels_enriched.csv"  # Walk Score enrichment (API-gated, run separately)

# Walk Score columns and the composite weighting (walk dominates, then transit,
# then bike) used when all three sub-scores are present for a parcel.
WALK_COLS    = ["walk_score", "transit_score", "bike_score"]
WALK_WEIGHTS = {"walk_score": 0.60, "transit_score": 0.25, "bike_score": 0.15}

CLIMATE_PLACEHOLDER = 50.0   # uniform climate score until per-parcel projections exist
SOCIO_PLACEHOLDER   = 50.0   # uniform socioeconomic fallback when ACS data is absent
                             # (e.g. no Census API key); excluded from the composite.


# ---------------------------------------------------------------------------
# Grade helpers — identical thresholds to score_resilience.py so grades are
# directly comparable across scripts.
# ---------------------------------------------------------------------------
def score_to_grade(score: float) -> str:
    """Absolute 0–100 score → letter grade (national grade)."""
    if pd.isna(score):
        return "—"
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    if score >= 20:
        return "D"
    return "F"


def percentile_to_local_grade(pct: float) -> str:
    """0–100 percentile rank → local letter grade.

    A = top 10%   (≥90th)   B = next 25% (≥65th)   C = middle 30% (≥35th)
    D = next 25%  (≥10th)   F = bottom 10% (<10th)
    """
    if pd.isna(pct):
        return "—"
    if pct >= 90:
        return "A"
    if pct >= 65:
        return "B"
    if pct >= 35:
        return "C"
    if pct >= 10:
        return "D"
    return "F"


def _loglinear(values: pd.Series, xs: list[float], ys: list[float]) -> pd.Series:
    """Piecewise-linear interpolation of `values` in log10(x) space.

    `xs` must be strictly increasing; `ys` are the matching 0–100 scores.
    Values below xs[0] / above xs[-1] clamp to ys[0] / ys[-1] (numpy.interp
    default).  Inputs ≤ 0 are floored to a tiny positive number before the log
    so they clamp cleanly to the bottom breakpoint rather than producing -inf.
    """
    v = pd.to_numeric(values, errors="coerce")
    log_x = np.log10(np.clip(v.to_numpy(dtype="float64"), 1e-9, None))
    scored = np.interp(log_x, np.log10(xs), ys)
    out = pd.Series(scored, index=values.index)
    out[v.isna()] = np.nan          # preserve missing inputs as missing scores
    return out.round(1)


# ---------------------------------------------------------------------------
# Per-dimension raw scorers (each returns a 0–100 Series, NaN where unscored).
# ---------------------------------------------------------------------------
# Energy: lower EUI is better.  Breakpoints (EUI kBTU/sqft/yr → score):
#   ≤15→100, 25→80, 40→60, 55→40, 70→20, ≥90→0   (log-linear between).
ENERGY_XS = [15.0, 25.0, 40.0, 55.0, 70.0, 90.0]
ENERGY_YS = [100.0, 80.0, 60.0, 40.0, 20.0, 0.0]

# Infrastructure: higher fiscal ratio (revenue / cost of services) is better.
#   ≥1.5→100, 1.0→80, 0.6→60, 0.3→40, 0.15→20, ≤0.05→0   (log-linear between).
INFRA_XS = [0.05, 0.15, 0.30, 0.60, 1.00, 1.50]
INFRA_YS = [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]


def score_energy(df: pd.DataFrame) -> pd.Series:
    return _loglinear(df["eui_kbtu_sqft_yr"], ENERGY_XS, ENERGY_YS)


def score_infrastructure(df: pd.DataFrame) -> pd.Series:
    return _loglinear(df["fiscal_ratio"], INFRA_XS, INFRA_YS)


def score_passthrough(col: str):
    """A scorer that uses an existing 0–100 column directly (clipped to range)."""
    def _fn(df: pd.DataFrame) -> pd.Series:
        return pd.to_numeric(df[col], errors="coerce").clip(0, 100).round(1)
    return _fn


def score_climate(df: pd.DataFrame) -> pd.Series:
    return pd.Series(CLIMATE_PLACEHOLDER, index=df.index)


def score_walkability(df: pd.DataFrame) -> pd.Series:
    """Walk Score → 0–100 walkability score.

    Walk Score is already a 0–100 score, so the raw ``walk_score`` is used
    directly.  Where a parcel also has a transit and bike score, a composite is
    taken — 60% walk + 25% transit + 15% bike — weighted toward walkability
    because it matters most for daily life.  Parcels missing one of the optional
    sub-scores fall back to the raw walk score; parcels with no walk score at all
    stay NaN (unscored)."""
    walk    = pd.to_numeric(df.get("walk_score"),    errors="coerce").clip(0, 100)
    transit = pd.to_numeric(df.get("transit_score"), errors="coerce").clip(0, 100)
    bike    = pd.to_numeric(df.get("bike_score"),    errors="coerce").clip(0, 100)

    composite = (WALK_WEIGHTS["walk_score"]    * walk
                 + WALK_WEIGHTS["transit_score"] * transit
                 + WALK_WEIGHTS["bike_score"]    * bike)
    # Use the composite only when both optional sub-scores exist; otherwise the
    # raw walk score.  np.where keeps it vectorised and NaN-safe.
    have_all = transit.notna() & bike.notna()
    out = np.where(have_all, composite, walk)
    return pd.Series(out, index=df.index).round(1)


def const_scorer(value: float):
    """A scorer that returns a uniform constant for every parcel (placeholder)."""
    def _fn(df: pd.DataFrame) -> pd.Series:
        return pd.Series(float(value), index=df.index)
    return _fn


# ---------------------------------------------------------------------------
# Dimension registry.  `requires` is the source column that must be present;
# `composite` flags whether the dimension feeds the composite average.
# ---------------------------------------------------------------------------
class Dimension:
    def __init__(self, key, label, scorer, requires, composite=True, fallback=None):
        self.key = key
        self.label = label
        self.scorer = scorer
        self.requires = requires        # source column that must exist, or None
        self.composite = composite      # whether it feeds the composite average
        self.fallback = fallback        # constant placeholder score to use if
                                        # `requires` is absent (None = skip instead)


DIMENSIONS: list[Dimension] = [
    Dimension("resilience",     "Disaster Resilience",  score_passthrough("resilience_score"),   "resilience_score"),
    Dimension("energy",         "Energy Efficiency",    score_energy,                            "eui_kbtu_sqft_yr"),
    Dimension("durability",     "Durability",           score_passthrough("durability_score"),   "durability_score"),
    Dimension("infrastructure", "Infrastructure Burden", score_infrastructure,                   "fiscal_ratio"),
    Dimension("health",         "Health Impact",        score_passthrough("health_index"),       "health_index"),
    Dimension("socioeconomic",  "Socioeconomic",        score_passthrough("socioeconomic_index"), "socioeconomic_index",
              fallback=SOCIO_PLACEHOLDER),
    Dimension("walkability",    "Walkability",          score_walkability,                       "walk_score"),
    Dimension("climate",        "Climate Projections",  score_climate,                           None, composite=False),
]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def add_dimension_columns(df: pd.DataFrame, dim: Dimension) -> None:
    """Score a single dimension in place: <key>_score / _national_grade /
    _local_grade / _percentile."""
    score = dim.scorer(df).astype("float64")
    df[f"{dim.key}_score"] = score
    df[f"{dim.key}_national_grade"] = score.apply(score_to_grade)
    pct = score.rank(pct=True) * 100.0
    df[f"{dim.key}_percentile"] = pct.round(1)
    df[f"{dim.key}_local_grade"] = pct.apply(percentile_to_local_grade)


def add_composite(df: pd.DataFrame, composite_keys: list[str]) -> None:
    """Composite = mean of the composite dimensions' scores (NaN-skipping),
    plus its national grade, percentile, and local grade."""
    score_cols = [f"{k}_score" for k in composite_keys]
    df["composite_score"] = df[score_cols].mean(axis=1, skipna=True).round(1)
    df["composite_national_grade"] = df["composite_score"].apply(score_to_grade)
    pct = df["composite_score"].rank(pct=True) * 100.0
    df["composite_percentile"] = pct.round(1)
    df["composite_local_grade"] = pct.apply(percentile_to_local_grade)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
GRADES = ["A", "B", "C", "D", "F"]


def _grade_row(counts: pd.Series, total: int) -> str:
    cells = []
    for g in GRADES:
        n = int(counts.get(g, 0))
        cells.append(f"{g}:{n:>4} ({n / total * 100:4.1f}%)")
    return "  ".join(cells)


def print_summary(df: pd.DataFrame, dims: list[Dimension], composite_keys: list[str]) -> None:
    total = len(df)

    print("\n" + "═" * 86)
    print("MULTI-DIMENSION SCORING SUMMARY")
    print("═" * 86)
    print(f"Parcels scored: {total:,}")
    print(f"Composite = mean of {len(composite_keys)} dimensions "
          f"({', '.join(composite_keys)}); climate excluded as placeholder.\n")

    # --- Grade distribution per dimension (national vs local) ---
    print("GRADE DISTRIBUTION PER DIMENSION")
    print("─" * 86)
    for dim in dims:
        score = df[f"{dim.key}_score"]
        scored_n = int(score.notna().sum())
        tag = "  (placeholder)" if not dim.composite else ""
        mean_s = score.mean(skipna=True)
        print(f"\n{dim.label} [{dim.key}_score]  mean={mean_s:5.1f}  scored={scored_n}/{total}{tag}")
        nat = df[f"{dim.key}_national_grade"].value_counts()
        loc = df[f"{dim.key}_local_grade"].value_counts()
        print(f"  national  {_grade_row(nat, total)}")
        print(f"  local     {_grade_row(loc, total)}")

    # --- Composite distribution ---
    print("\n" + "─" * 86)
    print("COMPOSITE GRADE DISTRIBUTION")
    print("─" * 86)
    cs = df["composite_score"]
    print(f"composite_score  min={cs.min():.1f}  median={cs.median():.1f}  "
          f"mean={cs.mean():.1f}  max={cs.max():.1f}")
    print(f"  national  {_grade_row(df['composite_national_grade'].value_counts(), total)}")
    print(f"  local     {_grade_row(df['composite_local_grade'].value_counts(), total)}")

    # --- 5 example parcels spanning the composite range ---
    print("\n" + "─" * 86)
    print("EXAMPLE PARCELS — spanning the composite range (0/25/50/75/100th pct)")
    print("─" * 86)
    id_col = next((c for c in ("PARCELID", "parcel_id", "PARID") if c in df.columns), None)
    ordered = df.sort_values("composite_score").reset_index(drop=True)
    positions = [0, int(0.25 * (total - 1)), int(0.50 * (total - 1)),
                 int(0.75 * (total - 1)), total - 1]
    dim_score_cols = [f"{d.key}_score" for d in dims]
    cols = ([id_col] if id_col else []) + dim_score_cols + \
           ["composite_score", "composite_national_grade", "composite_local_grade"]
    example = ordered.loc[positions, cols]
    with pd.option_context("display.max_columns", None, "display.width", 200,
                           "display.float_format", "{:.1f}".format):
        print(example.to_string(index=False))

    # --- Correlation matrix between dimension scores ---
    print("\n" + "─" * 86)
    print("CORRELATION MATRIX — dimension scores (Pearson)")
    print("─" * 86)
    corr_cols = [f"{d.key}_score" for d in dims if d.composite]  # constant climate → undefined corr
    corr = df[corr_cols].corr()
    corr.index = [c.replace("_score", "") for c in corr.index]
    corr.columns = [c.replace("_score", "") for c in corr.columns]
    with pd.option_context("display.width", 200, "display.float_format", "{:+.2f}".format):
        print(corr.to_string())
    print("═" * 86 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _resolve(path_str: str) -> pathlib.Path:
    p = pathlib.Path(path_str)
    return p if p.is_absolute() else (SCRIPT_DIR / p)


def merge_walkscore(df: pd.DataFrame, ws_path: pathlib.Path) -> pd.DataFrame:
    """Merge Walk Score columns into ``df`` on PARID.

    Walk scores come from a separate, API-gated enrichment
    (shelby_parcels_enriched.csv) rather than the chained pipeline, so they are
    joined in here on the parcel id.  No-ops (with a warning) if the file or join
    key is absent, or if the columns are already present in ``df``."""
    if all(c in df.columns for c in WALK_COLS):
        return df  # already carried in the input
    if not ws_path.exists():
        log.warning("Walk Score file not found (%s) — walkability will be skipped.", ws_path)
        return df
    if "PARID" not in df.columns:
        log.warning("No PARID column to join Walk Score on — walkability skipped.")
        return df

    ws = pd.read_csv(ws_path, low_memory=False)
    if "PARID" not in ws.columns:
        log.warning("Walk Score file has no PARID column — walkability skipped.")
        return df

    keep = ["PARID"] + [c for c in WALK_COLS if c in ws.columns]
    ws = ws[keep].drop_duplicates(subset="PARID")
    merged = df.merge(ws, on="PARID", how="left")
    n = int(merged["walk_score"].notna().sum()) if "walk_score" in merged.columns else 0
    log.info("Merged Walk Score for %s/%s parcels from %s", f"{n:,}", f"{len(df):,}", ws_path.name)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score and grade every dimension (0–100, national + local "
                    "A–F grades) and compute a composite for Shelby County parcels."
    )
    parser.add_argument("--input", default=DEFAULT_INPUT,
                        help=f"Input CSV (default: {DEFAULT_INPUT}).")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"Output CSV (default: {DEFAULT_OUTPUT}).")
    parser.add_argument("--walkscore-file", default=DEFAULT_WALKSCORE,
                        help=f"Walk Score enrichment CSV to merge on PARID "
                             f"(default: {DEFAULT_WALKSCORE}).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Score only the first N rows (ranks reflect the subset).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate input and report the plan; write nothing.")
    args = parser.parse_args()

    in_path  = _resolve(args.input)
    out_path = _resolve(args.output)

    if not in_path.exists():
        log.error("Input file not found: %s", in_path)
        sys.exit(1)

    df = pd.read_csv(in_path, low_memory=False)
    log.info("Loaded %s rows × %d cols from %s", f"{len(df):,}", df.shape[1], in_path)

    # Walk scores live in a separate, API-gated enrichment; merge them on PARID
    # so the walkability dimension has its source columns.
    df = merge_walkscore(df, _resolve(args.walkscore_file))

    if args.limit is not None:
        df = df.head(args.limit).copy()
        log.info("Limited to first %s rows.", f"{len(df):,}")

    # --- Validate required source columns. A dimension whose source is missing
    #     either falls back to a uniform placeholder (if it defines one, e.g.
    #     socioeconomic with no Census API key) or is skipped entirely. ---------
    active: list[Dimension] = []
    for dim in DIMENSIONS:
        if dim.requires is not None and dim.requires not in df.columns:
            if dim.fallback is not None:
                log.warning("Dimension '%s' source column '%s' missing — using "
                            "uniform placeholder %.0f (excluded from composite).",
                            dim.key, dim.requires, dim.fallback)
                dim = Dimension(dim.key, dim.label, const_scorer(dim.fallback),
                                requires=None, composite=False)
            else:
                log.warning("Dimension '%s' skipped — missing source column '%s'.",
                            dim.key, dim.requires)
                continue
        active.append(dim)

    composite_keys = [d.key for d in active if d.composite]
    if not composite_keys:
        log.error("No composite dimensions available — cannot score.")
        sys.exit(1)

    if args.dry_run:
        log.info("DRY RUN — no output written.")
        log.info("  input : %s", in_path)
        log.info("  output: %s", out_path)
        log.info("  dimensions: %s", ", ".join(d.key for d in active))
        log.info("  composite : %s", ", ".join(composite_keys))
        return

    # --- Score every active dimension, then the composite ---
    for dim in active:
        add_dimension_columns(df, dim)
        log.info("Scored dimension '%s'.", dim.key)
    add_composite(df, composite_keys)
    log.info("Computed composite from %d dimensions.", len(composite_keys))

    df.to_csv(out_path, index=False)
    log.info("Saved → %s (%s rows × %d cols)", out_path, f"{len(df):,}", df.shape[1])

    print_summary(df, active, composite_keys)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        log.error("Fatal: %s", exc, exc_info=True)
        sys.exit(1)
