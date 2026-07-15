"""Regression tests for the Building Resilience Modifier (BRM).

Locks the v2 BRM contract so future edits can't silently shift it:

  * code-era / fire-age factors are CONTINUOUS (anchored + interpolated), with
    the endpoints clamping (pre-1940 balloon-frame plateau, post-2010 modern
    plateau) and no bin cliffs;
  * the BRM has a construction-type-specific lower FLOOR but NO upper ceiling,
    so vulnerability compounds above the code-current baseline;
  * the foundation factor is flood-only (it must not touch wind/seismic);
  * parcels without CAMA data fall back to a neutral BRM of 1.0;
  * the offline batch scorer and the live simulator share one implementation.
"""

import numpy as np
import pandas as pd

from housing_label.score.resilience import (
    code_era_factor, fire_age_factor, calc_brm_row, brm_columns_vec,
    CODE_ERA_ANCHOR_YEARS, CODE_ERA_ANCHOR_FACTORS,
    FIRE_AGE_ANCHOR_YEARS, FIRE_AGE_ANCHOR_FACTORS,
    EXTWALL_BRM_FLOOR, FIRE_BRM_FLOOR,
)


# --- Continuous year-built curves -------------------------------------------

def test_code_era_anchors_and_clamps():
    for yr, fac in zip(CODE_ERA_ANCHOR_YEARS, CODE_ERA_ANCHOR_FACTORS):
        assert code_era_factor(yr) == fac
    # np.interp clamps outside the anchored range.
    assert code_era_factor(1850) == CODE_ERA_ANCHOR_FACTORS[0]   # pre-1940 plateau
    assert code_era_factor(2100) == CODE_ERA_ANCHOR_FACTORS[-1]  # post-2010 plateau


def test_fire_age_anchors_and_clamps():
    for yr, fac in zip(FIRE_AGE_ANCHOR_YEARS, FIRE_AGE_ANCHOR_FACTORS):
        assert fire_age_factor(yr) == fac
    assert fire_age_factor(1900) == FIRE_AGE_ANCHOR_FACTORS[0]
    assert fire_age_factor(2100) == FIRE_AGE_ANCHOR_FACTORS[-1]


def test_code_era_is_monotone_and_cliff_free():
    years = list(range(1900, 2031))
    vals = [code_era_factor(y) for y in years]
    # Non-increasing in year built (newer codes never more vulnerable).
    assert all(b <= a + 1e-12 for a, b in zip(vals, vals[1:]))
    # No cliffs: adjacent years never jump more than a small step. Old bins
    # jumped 0.15-0.20 at a single boundary; the steepest interpolated leg
    # (2003->2010, 0.15 over 7yr) is ~0.021/yr, an order of magnitude smaller.
    assert max(abs(a - b) for a, b in zip(vals, vals[1:])) < 0.03


def test_year_factor_nan_is_neutral():
    assert code_era_factor(float("nan")) == 1.0
    assert fire_age_factor(float("nan")) == 1.0


# --- BRM assembly: uncapped, floored, flood-specific foundation --------------

def _row(yrblt, extwall, bsmt, cond):
    return pd.Series({"YRBLT": yrblt, "EXTWALL": extwall, "BSMT": bsmt, "COND": cond})


def test_brm_has_no_upper_ceiling():
    # Pre-1940 (1.6) x frame (1.20) x full basement (1.4) x unsound (1.5) = 4.032,
    # which the old BRM_MAX=1.5 cap would have clipped away.
    b = calc_brm_row(_row(1935, 1, 4, 0))
    assert b["flood_brm"] > 1.5
    assert np.isclose(b["flood_brm"], 1.6 * 1.20 * 1.4 * 1.5)
    # Wind/seismic drops the flood-only foundation factor.
    assert np.isclose(b["wind_seismic_brm"], 1.6 * 1.20 * 1.5)


def test_foundation_is_flood_only():
    # Two identical houses differing only in basement: wind/seismic BRM is equal,
    # flood BRM is not (full basement is more flood-exposed than a slab).
    full = calc_brm_row(_row(1980, 1, 4, 3))
    slab = calc_brm_row(_row(1980, 1, 1, 3))
    assert full["wind_seismic_brm"] == slab["wind_seismic_brm"]
    assert full["flood_brm"] > slab["flood_brm"]


def test_brm_never_below_construction_floor():
    # The type-specific floor is a hard lower bound on the adjusted-EAL multiplier
    # (no over-crediting), across every CAMA attribute combination.
    for extwall, floor in EXTWALL_BRM_FLOOR.items():
        for yrblt in (1935, 1965, 1985, 2005, 2025):
            for bsmt in (1, 2, 3, 4):
                for cond in (0, 1, 2, 3, 4, 5):
                    b = calc_brm_row(_row(yrblt, extwall, bsmt, cond))
                    assert b["flood_brm"] >= floor - 1e-12
                    assert b["wind_seismic_brm"] >= floor - 1e-12


def test_fire_brm_floor_and_no_ceiling():
    hot = calc_brm_row(_row(1935, 1, 4, 0))   # knob-and-tube frame, unsound
    assert hot["fire_brm"] > 1.0              # combustibility compounds, uncapped
    cool = calc_brm_row(_row(2015, 8, 1, 5))  # modern stone, excellent
    assert cool["fire_brm"] < hot["fire_brm"]         # more resilient
    assert cool["fire_brm"] >= FIRE_BRM_FLOOR - 1e-12  # never below the fire floor


def test_non_cama_row_is_neutral():
    b = calc_brm_row(_row(float("nan"), float("nan"), float("nan"), float("nan")))
    assert b["brm_source"] == "default"
    for k in ("flood_brm", "wind_seismic_brm", "fire_brm",
              "code_era_factor", "construction_factor",
              "foundation_factor", "condition_factor"):
        assert b[k] == 1.0


# --- Scalar and vectorized paths agree (incl. the uncapped regime) ----------

def test_vectorized_matches_scalar_uncapped():
    rows = [
        _row(1935, 1, 4, 0),   # extreme: compounds well above 1.5
        _row(1965, 4, 3, 1),   # interpolated era, vinyl, partial basement, poor
        _row(2005, 8, 1, 5),   # modern stone, floor-governed
        _row(float("nan"), float("nan"), float("nan"), float("nan")),  # non-CAMA
    ]
    df = pd.DataFrame(rows).reset_index(drop=True)
    vec = brm_columns_vec(df)
    for i, row in enumerate(rows):
        scal = calc_brm_row(row)
        for k in ("flood_brm", "wind_seismic_brm", "fire_brm"):
            assert np.isclose(vec[k].iloc[i], scal[k]), (i, k)


def test_simulator_shares_one_implementation():
    from housing_label.simulate import house
    assert house.code_era_factor is code_era_factor
    assert house.fire_age_factor is fire_age_factor


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
