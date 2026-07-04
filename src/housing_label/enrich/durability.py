#!/usr/bin/env python3
"""Enrich shelby_parcels_socioeconomic.csv with a building-durability score.

This is a chained pipeline step: it reads the socioeconomic-enriched parcels file
(which carries the upstream CAMA columns YRBLT/EFFYR/GRADE/COND/CDU/EXTWALL/BSMT
forward from clean_parcels) and writes shelby_parcels_durability.csv.

Usage
-----
  python durability.py                         # all parcels
  python durability.py --limit 10              # test with 10 rows first
  python durability.py --limit 5 --dry-run     # validate without writing
  python durability.py --input X --output Y    # custom paths

Methodology — component-lifespan / effective-age model
------------------------------------------------------
  A building's durability is modeled as the blended remaining service life of its
  major components, tempered by the assessor's observed condition and adjusted for
  construction material and quality grade.

  1. EFFECTIVE AGE
     effective_age = REFERENCE_YEAR - effective_year, where effective_year is
     EFFYR (the assessor's "effective year built", which folds in major
     renovations) when present, else YRBLT. In this dataset EFFYR is populated for
     only ~1.5% of parcels, so YRBLT is the usual basis.

  2. COMPONENT BASKET (remaining-life fractions)
     Eight major building systems each carry a typical service life drawn from the
     InterNACHI "Standard Estimated Life Expectancy Chart for Homes", the NAHB/Bank
     of America "Study of Life Expectancy of Home Components" (2007), and Fannie
     Mae / Marshall & Swift component schedules. For each component the remaining
     life fraction is clamp((service_life - effective_age) / service_life, 0..1).
     The age-based score is the weighted mean of these fractions × 100. The
     long-lived structural shell is weighted heaviest; short-cycle systems (water
     heater, HVAC) lightest.

     Interpretation: the basket reflects the expected remaining life of
     *as-built* components. It does not know about un-recorded replacements — that
     real-world maintenance signal comes from the condition rating below, which is
     why the two are blended rather than multiplied.

  3. CONDITION RATING
     The Shelby County CAMA CDU field (Condition / Desirability / Utility) is the
     richest signal — a letter grade from EX (excellent) down to UN (unsound) set
     by an assessor's inspection. It is mapped to a 0-100 condition score. The
     numeric COND field (0-5) is the fallback when CDU is absent.

  4. BLEND
     base_durability = COND_WEIGHT * condition_score + AGE_WEIGHT * age_score
     Condition is weighted slightly higher than the pure-age basket because an
     inspector's rating captures upkeep and component replacements the age model
     cannot see. If only one of the two is available it is used alone.

  5. MATERIAL & GRADE MODIFIERS (multiplicative, modest)
     EXTWALL → durable masonry (brick, stone, block, brick veneer) earns a small
     bonus; thin sidings (vinyl/aluminum) a small penalty. GRADE (construction
     quality, 15-70 in this dataset, ~40 = average) scales the score linearly
     around its midpoint. Modifiers are applied only when their field is present.

  6. MISSING DATA
     A parcel with neither a build year nor a condition rating cannot be scored and
     is left blank (NaN) — these are predominantly vacant-land / non-residential
     parcels (the same ~280 that lack all CAMA building fields). The downstream
     scorer excludes NaN dimensions from the composite per-parcel.

  Upgrade path: replace the modeled component basket with actual permit / service
  records (roof-replacement permits, HVAC mechanical permits, re-pipe records) from
  the Shelby County / Memphis permit office, keyed on address, to pin real
  replacement dates instead of inferring from the build year.

CAMA field decoding (Shelby County assessor codes)
---------------------------------------------------
  YRBLT   Year built (float; NaN when unknown)
  EFFYR   Effective year built — reflects major renovations (rarely populated)
  GRADE   Construction quality grade (numeric, ~15 low … ~70 high; ~40 = average)
  COND    Overall condition (0 = unsound … 5 = excellent; 3 = average)
  CDU     Condition/Desirability/Utility letter rating:
            EX excellent  VG very good  GD good       AV average
            FR fair       PR poor       VP very poor  UN unsound
  EXTWALL Construction/exterior-wall type:
            1 = Brick        3 = Block/Concrete   4 = Stone
            5 = Alum/Vinyl   7 = Frame/Wood        8 = Stucco
            9 = Brick veneer 10 = EIFS

Columns added
-------------
  durability_effective_age      Effective age in years (REFERENCE_YEAR - eff. year)
  durability_remaining_life_pct Weighted component remaining-life basket (0-100)
  durability_components_past_life  Count of the 8 basket systems past service life
  durability_condition          Normalized condition label (excellent … unsound)
  durability_material_class     Wall durability class (masonry / veneer / frame / …)
  durability_score              Final 0-100 durability score (NaN if unscored)
  durability_data_source        Citation for the methodology used
"""

import argparse, logging, pathlib, sys
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── File paths ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[3]   # repo root; data lives here

# ── Reference year for effective-age computation ──────────────────────────────
# Fixed constant (not the wall clock) so a re-run produces identical scores and the
# pipeline stays reproducible. Bump this when refreshing the dataset's vintage.
REFERENCE_YEAR = 2026

REQUIRED_COLS = ["YRBLT"]   # minimum needed; EFFYR/GRADE/COND/CDU/EXTWALL optional

# ── Component basket: (label, service_life_years, weight) ─────────────────────
# Service lives: InterNACHI Standard Estimated Life Expectancy Chart; NAHB/Bank of
# America "Study of Life Expectancy of Home Components" (2007); Fannie Mae /
# Marshall & Swift schedules. Weights sum to 1.0 (long-lived shell heaviest).
COMPONENTS: list[tuple[str, float, float]] = [
    ("structural_shell", 100.0, 0.30),   # foundation, framing, masonry shell
    ("plumbing",          55.0, 0.10),   # supply/waste piping
    ("electrical",        35.0, 0.10),   # wiring, panel
    ("roof_covering",     25.0, 0.15),   # asphalt shingle roof
    ("windows",           25.0, 0.08),   # glazing units
    ("interior_finishes", 20.0, 0.10),   # flooring, cabinets, fixtures
    ("hvac",              18.0, 0.12),   # furnace / heat pump / AC
    ("water_heater",      12.0, 0.05),   # tank water heater
]

# ── Multi-family shared structural shell ──────────────────────────────────────
# For a building detected as multi-family (NSI), the structural shell — foundation,
# frame, and load-bearing walls — is a *shared, building-level* element, not a
# single wood-framed house's. A reinforced-concrete or steel mid-rise frame (and a
# load-bearing masonry shell) is a fundamentally longer-lived building element, so
# a representative unit's shell decays more slowly than the wood-frame baseline.
# Only the 0.30-weighted structural_shell life is lengthened; the shorter-cycle
# unit-level systems (roof covering, interior finishes, in-unit HVAC/water heater)
# keep their per-unit schedules. Wood/unknown multi-family keeps the 100 yr
# baseline (a wood multi-family shell is no longer-lived per unit than a house).
# Service lives: reinforced-concrete & structural-steel frames ~100–120 yr and
# load-bearing masonry ~100+ yr (ISO 15686 / CIRIA design service lives; InterNACHI
# & Fannie Mae structural schedules).
_MF_SHELL_SERVICE_LIFE = {"concrete": 120.0, "steel": 120.0, "masonry": 110.0}

# ── Blend weights (condition weighted slightly over the pure-age basket) ──────
COND_WEIGHT = 0.55
AGE_WEIGHT  = 0.45

# ── CDU letter → 0-100 condition score ────────────────────────────────────────
CDU_SCORE = {
    "EX": 100.0,   # excellent
    "VG":  88.0,   # very good
    "GD":  75.0,   # good
    "AV":  60.0,   # average
    "FR":  42.0,   # fair
    "PR":  25.0,   # poor
    "VP":  12.0,   # very poor
    "UN":   0.0,   # unsound
}
CDU_LABEL = {
    "EX": "excellent", "VG": "very good", "GD": "good", "AV": "average",
    "FR": "fair", "PR": "poor", "VP": "very poor", "UN": "unsound",
}

# ── COND numeric (0-5) → 0-100 condition score (fallback when CDU absent) ──────
COND_SCORE = {0: 0.0, 1: 20.0, 2: 40.0, 3: 60.0, 4: 80.0, 5: 100.0}
COND_LABEL = {0: "unsound", 1: "poor", 2: "fair", 3: "average",
              4: "good", 5: "excellent"}

# ── EXTWALL → (durability class, multiplicative factor) ───────────────────────
WALL_FACTOR = {
    1:  ("masonry",      1.06),  # solid brick
    3:  ("masonry",      1.05),  # block / concrete
    4:  ("masonry",      1.08),  # stone
    5:  ("light_siding", 0.97),  # aluminum / vinyl
    7:  ("frame",        1.00),  # wood frame (baseline)
    8:  ("stucco",       1.00),  # stucco
    9:  ("veneer",       1.04),  # brick veneer
    10: ("eifs",         0.98),  # exterior insulation finish system
}

# ── GRADE → quality factor ────────────────────────────────────────────────────
# Construction quality grade scales the score linearly around the dataset midpoint
# (~40 = average construction). Clamped to a modest ±12% so grade refines, not
# dominates, the lifespan/condition signal.
GRADE_MIDPOINT = 40.0
GRADE_SLOPE    = 0.004   # per grade point
GRADE_MIN_F, GRADE_MAX_F = 0.90, 1.12

DURABILITY_COLS = [
    "durability_effective_age",
    "durability_remaining_life_pct",
    "durability_components_past_life",
    "durability_condition",
    "durability_material_class",
    "durability_score",
    "durability_data_source",
]

DATA_SOURCE = (
    "Component-lifespan / effective-age model: InterNACHI Standard Estimated Life "
    "Expectancy Chart; NAHB/BoA Study of Life Expectancy of Home Components (2007); "
    "Fannie Mae / Marshall & Swift component schedules; Shelby County CAMA "
    "condition (CDU/COND), grade & material fields"
)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _valid_year(yr) -> bool:
    return not pd.isna(yr) and 1800 <= int(yr) <= REFERENCE_YEAR


def effective_year(yrblt, effyr) -> float | None:
    """Return the year to use for effective age: EFFYR if valid, else YRBLT."""
    if _valid_year(effyr):
        return float(effyr)
    if _valid_year(yrblt):
        return float(yrblt)
    return None


def age_basket(effective_age: float, shell_life: float | None = None) -> tuple[float, int]:
    """Return (weighted remaining-life % 0-100, count of components past life).

    ``shell_life`` overrides the structural_shell component's service life (used
    for a detected multi-family building's longer-lived shared shell); the other
    components keep their per-unit schedules."""
    weighted = 0.0
    past = 0
    for label, life, weight in COMPONENTS:
        if label == "structural_shell" and shell_life is not None:
            life = shell_life
        remaining = (life - effective_age) / life
        if remaining <= 0.0:
            past += 1
        remaining = min(1.0, max(0.0, remaining))
        weighted += weight * remaining
    return weighted * 100.0, past


def condition_score(cdu, cond) -> tuple[float | None, str | None]:
    """Return (0-100 condition score, label) from CDU (primary) or COND (fallback)."""
    if isinstance(cdu, str):
        key = cdu.strip().upper()
        if key in CDU_SCORE:
            return CDU_SCORE[key], CDU_LABEL[key]
    if not pd.isna(cond):
        code = int(cond)
        if code in COND_SCORE:
            return COND_SCORE[code], COND_LABEL[code]
    return None, None


def wall_class_factor(extwall) -> tuple[str | None, float]:
    """Return (durability class label, multiplicative factor) for an EXTWALL code."""
    if pd.isna(extwall):
        return None, 1.0
    return WALL_FACTOR.get(int(extwall), ("other", 1.00))


def grade_factor(grade) -> float:
    """Construction-quality grade → clamped multiplicative factor (~1.0 at avg)."""
    if pd.isna(grade):
        return 1.0
    f = 1.0 + (float(grade) - GRADE_MIDPOINT) * GRADE_SLOPE
    return min(GRADE_MAX_F, max(GRADE_MIN_F, f))


# ── Per-parcel durability model ───────────────────────────────────────────────
def model_parcel_durability(row: pd.Series, mf_material: str | None = None) -> dict:
    """Compute durability metrics for a single parcel.

    ``mf_material`` is the detected building material (NSI ``bldg_material``) when
    the address is a multi-family building; a durable material (concrete/steel/
    masonry) lengthens the shared structural shell's service life for the
    representative unit. None (single-family, or wood/unknown multi-family) keeps
    the wood-frame baseline.

    Returns all-None (unscored) when the parcel has neither a build year nor a
    condition rating — i.e. it carries no CAMA building data (vacant land / non-
    residential)."""
    eff_yr = effective_year(row.get("YRBLT"), row.get("EFFYR"))
    cond_s, cond_label = condition_score(row.get("CDU"), row.get("COND"))

    # No build year and no condition → not a scoreable structure.
    if eff_yr is None and cond_s is None:
        return {c: None for c in DURABILITY_COLS}

    # A detected multi-family building's shared shell (concrete/steel/masonry) is
    # longer-lived than a single wood-framed house; other components stay per-unit.
    shell_life = _MF_SHELL_SERVICE_LIFE.get(mf_material) if mf_material else None

    # --- Age-based component basket (only if we have a build year) ---
    if eff_yr is not None:
        eff_age = max(0.0, REFERENCE_YEAR - eff_yr)
        age_s, past = age_basket(eff_age, shell_life=shell_life)
    else:
        eff_age, age_s, past = None, None, None

    # --- Blend condition and age into the base score ---
    if cond_s is not None and age_s is not None:
        base = COND_WEIGHT * cond_s + AGE_WEIGHT * age_s
    elif age_s is not None:
        base = age_s
    else:
        base = cond_s   # condition only (no build year)

    # --- Material & grade modifiers (no-op when their field is absent) ---
    wall_label, wall_f = wall_class_factor(row.get("EXTWALL"))
    grade_f = grade_factor(row.get("GRADE"))

    score = min(100.0, max(0.0, base * wall_f * grade_f))

    return {
        "durability_effective_age":        round(eff_age, 0) if eff_age is not None else None,
        "durability_remaining_life_pct":   round(age_s, 1) if age_s is not None else None,
        "durability_components_past_life": past,
        "durability_condition":            cond_label,
        "durability_material_class":       wall_label,
        "durability_score":                round(score, 1),
        "durability_data_source":          DATA_SOURCE,
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def _resolve_path(raw: str) -> pathlib.Path:
    """Resolve a CLI path: bare names are relative to the repo root."""
    p = pathlib.Path(raw)
    return p if p.is_absolute() else (SCRIPT_DIR / p)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich Shelby County parcels with a component-lifespan durability score."
    )
    parser.add_argument("--input", default="shelby_parcels_socioeconomic.csv",
                        help="Input CSV (chained from the socioeconomic step).")
    parser.add_argument("--output", default="shelby_parcels_durability.csv",
                        help="Output CSV with durability columns appended.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N rows (for testing).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Load and validate only; log the plan without writing.")
    args = parser.parse_args()

    in_file  = _resolve_path(args.input)
    out_file = _resolve_path(args.output)

    # --- Input validation ---
    if not in_file.exists():
        log.error("Input file does not exist: %s", in_file)
        sys.exit(1)

    log.info("Reading %s", in_file)
    df = pd.read_csv(in_file, low_memory=False)
    log.info("  %d rows × %d columns", *df.shape)
    input_rows = len(df)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        log.error("Missing required CAMA column(s): %s", ", ".join(missing))
        sys.exit(1)

    optional = ["EFFYR", "GRADE", "COND", "CDU", "EXTWALL"]
    absent = [c for c in optional if c not in df.columns]
    if absent:
        log.warning("Optional CAMA column(s) absent (modifiers degrade gracefully): %s",
                    ", ".join(absent))

    if args.limit:
        df = df.head(args.limit)
        log.info("--limit %d applied.", args.limit)

    # --- Dry run ---
    if args.dry_run:
        log.info("[dry-run] Plan:")
        log.info("[dry-run]   input  : %s", in_file)
        log.info("[dry-run]   output : %s", out_file)
        log.info("[dry-run]   reference year : %d", REFERENCE_YEAR)
        log.info("[dry-run]   rows to model  : %d", len(df))
        log.info("[dry-run]   columns to add : %s", DURABILITY_COLS)
        log.info("[dry-run] Validation passed; no output written.")
        return

    log.info("Modelling durability for %d parcels (reference year %d) …",
             len(df), REFERENCE_YEAR)
    results = [model_parcel_durability(row) for _, row in df.iterrows()]
    enriched = pd.DataFrame(results, index=df.index)
    for col in DURABILITY_COLS:
        df[col] = enriched[col]

    df.to_csv(out_file, index=False)
    log.info("Saved → %s", out_file)

    out_rows, out_cols = df.shape
    log.info("wrote %d rows × %d cols", out_rows, out_cols)
    if args.limit is None and out_rows != input_rows:
        log.warning("Output rows (%d) != input rows (%d)", out_rows, input_rows)

    _print_summary(df, out_file)


# ── Summary ──────────────────────────────────────────────────────────────────
def _print_summary(df: pd.DataFrame, out_file: pathlib.Path) -> None:
    total   = len(df)
    score   = df["durability_score"]
    scored  = score.notna()
    n_sc    = int(scored.sum())
    age     = df["durability_effective_age"]
    cond_d  = df["durability_condition"].value_counts(dropna=True).to_dict()
    mat_d   = df["durability_material_class"].value_counts(dropna=True).to_dict()
    w = 44

    print("\n╔══ BUILDING DURABILITY ENRICHMENT SUMMARY ═════════════════════════╗")
    print(f"║ Total parcels               : {total:<{w}}║")
    print(f"║ Scored (had CAMA building)  : {f'{n_sc}  ({n_sc/total*100:.1f}%)':<{w}}║")
    print(f"║ Unscored (vacant/non-resid) : {f'{total-n_sc}  ({(total-n_sc)/total*100:.1f}%)':<{w}}║")
    print(f"║ Reference year              : {REFERENCE_YEAR:<{w}}║")
    print(f"║ Methodology                 : {'Component-lifespan + condition (CDU/COND)':<{w}}║")
    if n_sc:
        print("║ ── Durability score (0-100) ─────────────────────────────────────── ║")
        print(f"║   min    : {score.min():<{w-2}.1f}║")
        print(f"║   p25    : {score.quantile(0.25):<{w-2}.1f}║")
        print(f"║   median : {score.median():<{w-2}.1f}║")
        print(f"║   mean   : {score.mean():<{w-2}.2f}║")
        print(f"║   p75    : {score.quantile(0.75):<{w-2}.1f}║")
        print(f"║   max    : {score.max():<{w-2}.1f}║")
        print("║ ── Effective age (years) ────────────────────────────────────────── ║")
        print(f"║   median : {age.median():<{w-1}.0f}║")
        print(f"║   mean   : {age.mean():<{w-1}.1f}║")
        print(f"║   max    : {age.max():<{w-1}.0f}║")
        print("║ ── Condition distribution ───────────────────────────────────────── ║")
        for label in ("excellent", "very good", "good", "average", "fair",
                      "poor", "very poor", "unsound"):
            if label in cond_d:
                cnt = cond_d[label]
                print(f"║   {label:<12}: {cnt:>5}  ({cnt/total*100:5.1f}%){'':>19}║")
        print("║ ── Material class distribution ──────────────────────────────────── ║")
        for label, cnt in sorted(mat_d.items(), key=lambda kv: -kv[1]):
            print(f"║   {label:<12}: {cnt:>5}  ({cnt/total*100:5.1f}%){'':>19}║")
    print(f"║ New columns added           : {len(DURABILITY_COLS):<{w}}║")
    print(f"║ Output                      : {out_file.name:<{w}}║")
    print("╚═══════════════════════════════════════════════════════════════════╝\n")

    sample_cols = [
        "PARCELID", "YRBLT", "EFFYR", "GRADE", "COND", "CDU", "EXTWALL",
        "durability_effective_age", "durability_remaining_life_pct",
        "durability_components_past_life", "durability_condition",
        "durability_material_class", "durability_score",
    ]
    avail = [c for c in sample_cols if c in df.columns]
    shown = df[scored] if scored.any() else df
    print("Sample scored rows (first 10):")
    with pd.option_context("display.max_columns", None, "display.width", 220,
                           "display.float_format", "{:.1f}".format):
        print(shown[avail].head(10).to_string(index=False))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted.")
        sys.exit(0)
    except Exception as exc:
        log.error("Fatal: %s", exc, exc_info=True)
        sys.exit(1)
