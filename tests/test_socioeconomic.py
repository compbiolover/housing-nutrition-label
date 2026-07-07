#!/usr/bin/env python3
"""Tests for the Socioeconomic dimension (enrich/socioeconomic.py).

Pure computation over a synthetic ACS frame — no network, no CSV, no API key.
Execute directly (python tests/test_socioeconomic.py) or via pytest.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from housing_label.enrich import socioeconomic as S


def test_clean_tract_normalises_geoid():
    assert S._clean_tract("47157000400.0") == "47157000400"   # strip decimal suffix
    assert S._clean_tract(47157000400) == "47157000400"
    assert S._clean_tract("400") == "00000000400"             # zero-padded to 11
    for empty in (None, "nan", "None", "", "  "):
        assert S._clean_tract(empty) is None


def test_safe_div_guards_zero_denominator():
    num = pd.Series([50.0, 30.0, 10.0])
    den = pd.Series([100.0, 0.0, -5.0])
    out = S._safe_div(num, den)
    assert out.iloc[0] == 50.0                # 50/100*100
    assert pd.isna(out.iloc[1])               # zero denominator → NaN
    assert pd.isna(out.iloc[2])               # negative denominator → NaN


def _tract(pov_below, pov_total, income, burden_30, hh_total):
    """One synthetic ACS tract row keyed by every column _compute_socio reads.

    ``burden_30`` is spread across the owner 30%+ buckets; ``hh_total`` is the
    computable-denominator household count. Not-computed buckets are 0 so the
    denominators equal the totals.
    """
    row = {c: 0.0 for c in S.ACS_VARS}
    row[S.POVERTY_BELOW] = pov_below
    row[S.POVERTY_TOTAL] = pov_total
    row[S.MEDIAN_INCOME] = income
    row[S.B25106_TOTAL] = hh_total
    row[S.B25106_OWNER_TOTAL] = hh_total
    row[S.B25106_OWNER_30PLUS[0]] = burden_30    # all cost-burdened owners in one bucket
    return row


def test_compute_socio_index_orientation():
    """100 = least economic stress: the affluent, low-poverty, low-burden tract
    must outrank the distressed one."""
    df = pd.DataFrame(
        {
            "good": _tract(pov_below=20, pov_total=1000, income=140000, burden_30=50, hh_total=1000),
            "mid":  _tract(pov_below=150, pov_total=1000, income=70000, burden_30=250, hh_total=1000),
            "bad":  _tract(pov_below=400, pov_total=1000, income=28000, burden_30=600, hh_total=1000),
        }
    ).T
    df.index.name = "census_tract"

    out = S._compute_socio(df)
    idx = out["socioeconomic_index"]
    assert idx["good"] > idx["mid"] > idx["bad"]
    # Derived headline metrics are oriented correctly.
    assert out.loc["good", "poverty_rate_pct"] < out.loc["bad", "poverty_rate_pct"]
    assert out.loc["good", "housing_cost_burden_pct"] < out.loc["bad", "housing_cost_burden_pct"]
    # Index stays within bounds.
    assert (idx.dropna() >= 0).all() and (idx.dropna() <= 100).all()


def test_compute_socio_output_columns():
    df = pd.DataFrame(
        {"t1": _tract(50, 1000, 90000, 100, 1000),
         "t2": _tract(200, 1000, 45000, 300, 1000)}
    ).T
    df.index.name = "census_tract"
    out = S._compute_socio(df)
    assert list(out.columns) == [c for c in S.SOCIO_COLS if c != "census_tract"]


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
