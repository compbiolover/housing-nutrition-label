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
    code_era_factor, fire_age_factor, calc_brm_row,
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


# --- The uncapped regime -----------------------------------------------------

def test_the_uncapped_regime_holds_across_representative_rows():
    """These four rows used to exist to pin the vectorized batch scorer against
    this scalar one; the batch scorer is gone and the rows are worth keeping on
    their own. Every BRM must be finite and positive, and the deliberately
    extreme row must compound well past the old 1.5 cap rather than clamp."""
    extreme = calc_brm_row(_row(1935, 1, 4, 0))
    interpolated = calc_brm_row(_row(1965, 4, 3, 1))   # vinyl, partial basement, poor
    modern = calc_brm_row(_row(2005, 8, 1, 5))         # stone, floor-governed
    non_cama = calc_brm_row(_row(float("nan"), float("nan"), float("nan"), float("nan")))

    for name, brm in (("extreme", extreme), ("interpolated", interpolated),
                      ("modern", modern), ("non_cama", non_cama)):
        for k in ("flood_brm", "wind_seismic_brm", "fire_brm"):
            assert np.isfinite(brm[k]) and brm[k] > 0, (name, k)

    assert extreme["flood_brm"] > 1.5, "the uncapped regime must not clamp at 1.5"
    assert modern["flood_brm"] < extreme["flood_brm"]
    assert all(non_cama[k] == 1.0 for k in ("flood_brm", "wind_seismic_brm", "fire_brm"))


def test_simulator_shares_one_implementation():
    from housing_label.simulate import house
    assert house.code_era_factor is code_era_factor
    assert house.fire_age_factor is fire_age_factor


def _seismic(**kw):
    """seismic_adj for a Shelby parcel with the given overrides."""
    from housing_label.simulate.house import simulate, PRESETS
    cfg = dict(PRESETS["baseline"])
    cfg.update(lat=35.13, lon=-89.99)
    cfg.update(kw)
    return simulate(cfg)


def test_seismic_foundation_retrofits_require_a_foundation_to_retrofit():
    """Both foundation retrofit tiers act on the framing-to-foundation connection,
    so they only score where that connection exists. A slab has no cripple wall and
    no raised sill; a full basement has full-height walls rather than a cripple
    wall. A claimed-but-impossible upgrade earns no credit and is named in a note."""
    from housing_label.simulate.house import BONUS_CRIPPLE_WALL, BONUS_SEISMIC_RET

    # Cripple-wall bracing: credited on a raised foundation, ignored on slab and
    # on a full basement.
    for foundation in ("crawl", "partial-basement"):
        plain = _seismic(foundation=foundation)["seismic_adj"]
        braced = _seismic(foundation=foundation, cripple_wall_bracing=True)
        assert np.isclose(braced["seismic_adj"], plain * BONUS_CRIPPLE_WALL), foundation
        assert braced["seismic_applicability_note"] is None, foundation

    for foundation in ("slab", "full-basement"):
        plain = _seismic(foundation=foundation)["seismic_adj"]
        braced = _seismic(foundation=foundation, cripple_wall_bracing=True)
        assert np.isclose(braced["seismic_adj"], plain), foundation
        assert "Cripple wall bracing" in braced["seismic_applicability_note"], foundation
        # The CLI reads this key to avoid printing a modifier that never applied.
        assert braced["inapplicable_upgrades"] == ["cripple_wall_bracing"], foundation

    # Sill anchorage is the broader tier: any non-slab foundation, never slab.
    for foundation in ("crawl", "partial-basement", "full-basement"):
        plain = _seismic(foundation=foundation)["seismic_adj"]
        bolted = _seismic(foundation=foundation, seismic_retrofit=True)
        assert np.isclose(bolted["seismic_adj"], plain * BONUS_SEISMIC_RET), foundation

    plain = _seismic(foundation="slab")["seismic_adj"]
    bolted = _seismic(foundation="slab", seismic_retrofit=True)
    assert np.isclose(bolted["seismic_adj"], plain)
    assert "anchorage" in bolted["seismic_applicability_note"].lower()


def test_inapplicable_note_gives_the_reason_that_actually_applies():
    """The two tiers fail for different reasons, so the note must not use one
    blanket explanation. A full basement genuinely has a sill to bolt — saying it
    has none would contradict the anchorage tier being credited there."""
    full = _seismic(foundation="full-basement", cripple_wall_bracing=True)
    note = full["seismic_applicability_note"]
    assert "full-height basement walls" in note, note
    assert "sill" not in note, note        # it HAS a sill; only the cripple wall is absent

    slab = _seismic(foundation="slab", cripple_wall_bracing=True, seismic_retrofit=True)
    note = slab["seismic_applicability_note"]
    assert "no cripple wall to brace" in note, note
    assert "bolted into the slab itself" in note, note


def test_seismic_tiers_supersede_and_degrade_gracefully():
    """Cripple-wall bracing supersedes sill anchorage where both apply (they are
    two tiers of one retrofit). Where bracing is impossible but anchorage is not,
    anchorage still scores rather than being swallowed by the superseded branch."""
    from housing_label.simulate.house import BONUS_CRIPPLE_WALL, BONUS_SEISMIC_RET

    plain = _seismic(foundation="crawl")["seismic_adj"]
    both = _seismic(foundation="crawl", cripple_wall_bracing=True, seismic_retrofit=True)
    assert np.isclose(both["seismic_adj"], plain * BONUS_CRIPPLE_WALL)   # not the product
    assert "supersedes" in both["seismic_retrofit_note"]

    # Full basement: bracing cannot apply, so anchorage takes effect on its own.
    plain = _seismic(foundation="full-basement")["seismic_adj"]
    both = _seismic(foundation="full-basement",
                    cripple_wall_bracing=True, seismic_retrofit=True)
    assert np.isclose(both["seismic_adj"], plain * BONUS_SEISMIC_RET)
    assert both["seismic_retrofit_note"] is None
    assert "Cripple wall bracing" in both["seismic_applicability_note"]
