#!/usr/bin/env python3
"""Offline tests for the nationally-anchored Infrastructure Burden fiscal-ratio
score breakpoints.

Runs without network access and without pytest — execute directly:
  python tests/test_infra_breakpoints.py
"""

from __future__ import annotations

import pandas as pd

from housing_label.score.all_dimensions import (
    INFRA_XS, INFRA_YS, score_infrastructure, score_to_grade,
)


def _score(ratio: float) -> float:
    return float(score_infrastructure(pd.DataFrame({"fiscal_ratio": [ratio]})).iloc[0])


def test_breakpoints_well_formed():
    """XS strictly increasing, aligned with YS, and the national (school-netted) set."""
    assert len(INFRA_XS) == len(INFRA_YS) == 6
    assert all(b > a for a, b in zip(INFRA_XS, INFRA_XS[1:])), "XS must be increasing"
    assert INFRA_YS == [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]
    # National non-school distribution: lower than the Shelby pilot's top anchor
    # (1.5) since school property tax is netted out of the revenue side.
    assert 0.05 < INFRA_XS[0] < 0.20 and 0.7 < INFRA_XS[-1] < 1.5


def test_score_is_monotonic_in_ratio():
    prev = -1.0
    for ratio in (0.05, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0):
        s = _score(ratio)
        assert s >= prev, f"score dropped as ratio rose at {ratio}"
        prev = s


def test_national_median_ratio_scores_mid():
    """The national (school-netted) median fiscal ratio (~0.31) should land in the
    C band (~50), i.e. the score tracks national percentile rank."""
    s = _score(0.31)
    assert 40.0 <= s <= 60.0
    assert score_to_grade(s) == "C"


def test_tails_clamp():
    assert _score(0.02) == 0.0           # well below the bottom breakpoint → F floor
    assert _score(5.0) == 100.0          # well above the top breakpoint → A ceiling
    assert score_to_grade(_score(1.0)) == "A"


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
