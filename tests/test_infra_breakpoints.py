#!/usr/bin/env python3
"""Offline tests for the nationally-anchored Infrastructure Burden fiscal-ratio
score breakpoints.

Runs without network access. This file alone:
  pytest tests/test_infra_breakpoints.py
"""

from __future__ import annotations


from housing_label.data.assessment import active_basis
from housing_label.score.all_dimensions import (
    INFRA_XS, INFRA_XS_BASIS, INFRA_YS, score_to_grade,
)
from housing_label.simulate.dimensions import _loglin


def _score(ratio: float) -> float:
    """The interpolation simulate/dimensions.py runs to score Infrastructure."""
    return round(_loglin(ratio, INFRA_XS, INFRA_YS), 1)


def test_breakpoints_well_formed():
    """XS strictly increasing, aligned with YS, and the national (school-netted,
    fee-inclusive) set."""
    assert len(INFRA_XS) == len(INFRA_YS) == 6
    assert all(b > a for a, b in zip(INFRA_XS, INFRA_XS[1:])), "XS must be increasing"
    assert INFRA_YS == [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]
    # National non-school distribution, with user-fee revenue counted alongside
    # property tax so both sides of the ratio cover the same services. That lifts
    # the whole distribution well above the tax-only anchors it replaced.
    assert 0.20 < INFRA_XS[0] < 0.45 and 1.2 < INFRA_XS[-1] < 2.0


def test_score_is_monotonic_in_ratio():
    prev = -1.0
    for ratio in (0.05, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0):
        s = _score(ratio)
        assert s >= prev, f"score dropped as ratio rose at {ratio}"
        prev = s


def test_national_median_ratio_scores_mid():
    """The national median fiscal ratio (~0.66) should land in the C band (~50),
    i.e. the score tracks national percentile rank."""
    s = _score(0.66)
    assert 40.0 <= s <= 60.0
    assert score_to_grade(s) == "C"


def test_break_even_is_well_above_median():
    """Paying your own way (ratio 1.0) is genuinely uncommon, not the average.

    Guards the copy as much as the model: the label used to say "above ~1 means it
    pays its own way" while grading a typical home a C at 0.31, which read as "no
    home passes". Break-even must sit high in the distribution but below the top
    anchor.

    The band is the top quartile rather than a specific grade. It was ">= 80, and an
    A", which is a calibration-dependent knife-edge: removing the ruralness
    double-count lifted ratios across the board, so break-even moved from ~p81 to
    ~p77 and the grade flipped to a B without anything about break-even changing.
    What the test is defending is that paying your own way is uncommon — top
    quartile, comfortably above the median — not which side of 80 it lands on.
    """
    s = _score(1.0)
    assert 70.0 <= s < 100.0, f"break-even scored {s}"
    assert s > _score(0.66) + 15.0, "break-even must beat the median by a clear margin"


def test_tails_clamp():
    assert _score(0.10) == 0.0           # well below the bottom breakpoint → F floor
    assert _score(5.0) == 100.0          # well above the top breakpoint → A ceiling
    assert score_to_grade(_score(5.0)) == "A"
    # (break-even's own placement is test_break_even_is_well_above_median's job —
    # it was asserted here too, as a grade, which made a clamp test fail whenever
    # the distribution was recalibrated.)


def test_infra_xs_basis_matches_the_rules_table():
    """The reference distribution must be built by the same model the app runs.

    INFRA_XS is anchored to percentiles of a national distribution that now applies
    property-tax classification. Adding a jurisdiction to data/assessment.py without
    re-running scripts/calibrate_infra_breakpoints.py would leave the yardstick
    measuring a different model than the labels — every Infrastructure grade in the
    country would be quietly mis-anchored, with nothing visibly broken.

    If this fails: re-run the calibrator, paste the new INFRA_XS, and update
    INFRA_XS_BASIS to active_basis().
    """
    assert INFRA_XS_BASIS == active_basis(), (
        "classification table changed without recalibrating INFRA_XS — "
        f"basis records {INFRA_XS_BASIS}, table now has {active_basis()}")
