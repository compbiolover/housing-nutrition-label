#!/usr/bin/env python3
"""Tests for the Durability dimension (enrich/durability.py).

Pure functions over a synthetic parcel ``pd.Series`` — no network, no CSV.
This file alone: ``pytest tests/test_durability.py``..
"""

from __future__ import annotations

import pandas as pd

from housing_label.enrich import durability as D


def _row(**kw) -> pd.Series:
    """A CAMA parcel row; only the fields under test need be supplied."""
    base = {"YRBLT": None, "EFFYR": None, "GRADE": None,
            "COND": None, "CDU": None, "EXTWALL": None}
    base.update(kw)
    return pd.Series(base)


def test_effective_year_prefers_effyr_then_yrblt():
    assert D.effective_year(1990, 2010) == 2010.0     # EFFYR wins when valid
    assert D.effective_year(1990, None) == 1990.0     # falls back to YRBLT
    assert D.effective_year(None, None) is None       # neither → None
    # Out-of-range effective year is rejected, YRBLT used instead. The low stand-in
    # is below EARLIEST_PLAUSIBLE_YEAR on purpose: 1700 used to sit here and is a
    # real construction year in the rolls this project reads, so it stopped being
    # an example of an implausible one when the floor moved to 1600.
    assert D.effective_year(1990, 1500) == 1990.0
    assert D.effective_year(1990, D.REFERENCE_YEAR + 5) == 1990.0


def test_a_colonial_year_is_a_year_not_a_typo():
    """1600 is a plausibility floor, and the rolls this project reads are full of
    real years beneath the old one: 8,375 Connecticut dwellings are recorded as
    built between 1600 and 1800, and Washington's residential CAMA holds 29 dated
    1776 to 1797."""
    for year in (1600, 1641, 1725, 1776, 1799):
        assert D._valid_year(year), year
        assert D.effective_year(year, None) == float(year)


def test_a_year_below_the_floor_is_still_refused():
    """What the floor is actually for. Every one of these is a real value sitting
    in Connecticut's statewide roll today, and none of them is a building."""
    for junk in (1, 2, 15, 203, 630, 1020, 1500):
        assert not D._valid_year(junk), junk
    assert D.effective_year(1500, None) is None


def test_the_floor_does_not_hand_out_a_bonus_for_being_older():
    """The bug the floor used to be.

    A rejected year is not scored as old — it is dropped, ``effective_year``
    returns None, and the model falls back to the condition rating alone. So the
    boundary inverted the dimension: a house built in 1799 scored 60.0 where the
    same house built in 1800 scored 33.0, a 27-point bonus for being older, on the
    dimension whose whole subject is age.

    Pinned as a property rather than as two numbers: no year in this range may
    score better than the year after it."""
    scores = [D.model_parcel_durability(_row(YRBLT=y))["durability_score"]
              for y in (1725, 1780, 1799, 1800, 1850, 1900)]
    assert all(a <= b for a, b in zip(scores, scores[1:])), scores
    assert len(set(scores)) == 1, (
        f"every year here predates the 100-year structural shell, so all should "
        f"land on the same saturated figure, got {scores}")


def test_widening_the_floor_added_no_new_regime_below_it():
    """The component basket saturates at the longest service life — 100 years for
    the structural shell — so every building from 1926 back already reported 0%
    remaining life and all 8 components past life.

    A 1725 house therefore lands on exactly the figures a 1900 one does. That is
    what makes the wider floor a removal of a discontinuity rather than an
    extrapolation into years the model was never fitted for."""
    old = D.model_parcel_durability(_row(YRBLT=1725))
    ref = D.model_parcel_durability(_row(YRBLT=1900))
    assert old["durability_remaining_life_pct"] == ref["durability_remaining_life_pct"] == 0.0
    assert old["durability_components_past_life"] == ref["durability_components_past_life"] == len(D.COMPONENTS)
    assert old["durability_score"] == ref["durability_score"]
    # The one figure that legitimately differs is the age itself.
    assert old["durability_effective_age"] > ref["durability_effective_age"]


def test_age_basket_monotonic_and_bounded():
    new, past_new = D.age_basket(0.0)
    old, past_old = D.age_basket(200.0)
    # A brand-new building has ~full remaining life; a 200-yr-old one none.
    assert new > 95.0
    assert old == 0.0 and past_old == len(D.COMPONENTS)
    # Remaining life falls monotonically with age; components-past grows.
    ages = [0, 15, 30, 60, 120]
    scores = [D.age_basket(float(a))[0] for a in ages]
    assert scores == sorted(scores, reverse=True)
    pasts = [D.age_basket(float(a))[1] for a in ages]
    assert pasts == sorted(pasts)


def test_age_basket_multifamily_shell_extends_life():
    """A durable shared shell (concrete) decays slower than the wood baseline."""
    age = 90.0
    baseline, _ = D.age_basket(age)
    concrete, _ = D.age_basket(age, shell_life=D._MF_SHELL_SERVICE_LIFE["concrete"])
    assert concrete > baseline


def test_condition_score_cdu_primary_cond_fallback():
    assert D.condition_score("EX", None) == (100.0, "excellent")
    assert D.condition_score("un", None) == (0.0, "unsound")   # case-insensitive
    # CDU missing/invalid → numeric COND fallback.
    assert D.condition_score(None, 3) == (60.0, "average")
    assert D.condition_score("??", 5) == (100.0, "excellent")
    # Neither present → unscored.
    assert D.condition_score(None, None) == (None, None)


def test_wall_and_grade_factors():
    assert D.wall_class_factor(4)[0] == "masonry" and D.wall_class_factor(4)[1] > 1.0
    assert D.wall_class_factor(5)[1] < 1.0          # light siding penalized
    assert D.wall_class_factor(7) == ("frame", 1.00)  # wood baseline
    assert D.wall_class_factor(None) == (None, 1.0)   # absent → no-op
    # Grade scales around the midpoint and is clamped.
    assert D.grade_factor(D.GRADE_MIDPOINT) == 1.0
    assert D.grade_factor(70) > 1.0 and D.grade_factor(70) <= D.GRADE_MAX_F
    assert D.grade_factor(15) < 1.0 and D.grade_factor(15) >= D.GRADE_MIN_F
    assert D.grade_factor(None) == 1.0


def test_model_parcel_durability_unscored_without_building_data():
    out = D.model_parcel_durability(_row())     # no year, no condition
    assert all(v is None for v in out.values())


def test_model_parcel_durability_newer_beats_older():
    new = D.model_parcel_durability(_row(YRBLT=2020, CDU="GD"))
    old = D.model_parcel_durability(_row(YRBLT=1940, CDU="GD"))
    assert new["durability_score"] > old["durability_score"]
    # Effective age is measured from the fixed reference year.
    assert new["durability_effective_age"] == D.REFERENCE_YEAR - 2020


def test_model_parcel_durability_condition_only_path():
    """A parcel with a condition rating but no build year is still scored (on
    condition alone) rather than dropped."""
    out = D.model_parcel_durability(_row(CDU="AV"))
    assert out["durability_score"] is not None
    assert out["durability_remaining_life_pct"] is None   # no age basket
    assert out["durability_condition"] == "average"


def test_model_parcel_durability_masonry_beats_frame():
    frame = D.model_parcel_durability(_row(YRBLT=1990, CDU="AV", EXTWALL=7))
    stone = D.model_parcel_durability(_row(YRBLT=1990, CDU="AV", EXTWALL=4))
    assert stone["durability_score"] > frame["durability_score"]
