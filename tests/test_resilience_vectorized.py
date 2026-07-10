#!/usr/bin/env python3
"""Equivalence test: the vectorized batch-scorer helpers in score/resilience.py
must produce exactly what the scalar per-row reference functions produce.

main() scores the whole parcel table with the column-wise ``*_vec`` helpers
instead of ``df.apply(scalar, axis=1)`` (much less Python overhead). The scalar
functions remain the single-row reference used by the CLI simulator and the
other tests, so this file pins the two paths together: build a randomized parcel
frame that exercises the edge cases (missing CAMA, unknown/NaN codes, zero
tornado frequency, out-of-range PGA, garbage wildfire values) and assert the
vectorized output matches the apply output element-for-element. A separate case
drops the wildfire column entirely.

Runs directly too:  ``python tests/test_resilience_vectorized.py``.
"""

import numpy as np
import pandas as pd

from housing_label.score import resilience as R


def _random_frame(n: int = 400, seed: int = 12345) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # Codes drawn to include both known table keys and unlisted codes (→ default),
    # plus NaN to exercise the missing-data branches.
    extwall = rng.choice([1, 2, 4, 7, 8, 9, 3, 99, np.nan], n)
    bsmt    = rng.choice([1, 2, 3, 4, 6, np.nan], n)
    cond    = rng.choice([0, 1, 2, 3, 4, 5, 9, np.nan], n)
    yrblt   = rng.choice([1900, 1949, 1950, 1969, 1970, 1989, 2002, 2003,
                          2020, np.nan], n)
    return pd.DataFrame({
        "flood_risk": rng.choice(["high", "moderate", "minimal", "unknown"], n),
        "tornado_nri_eal_rate": rng.choice([0.0, 3.7e-5, 1.6e-4, 6.3e-4, -1.0, np.nan], n),
        "pga_2pct_50yr":  rng.uniform(0.0, 0.8, n),
        "pga_10pct_50yr": rng.uniform(0.0, 0.8, n),
        "wildfire_eal_rate": rng.choice([0.0, 0.0001, 0.0025, -1.0, np.nan], n),
        "YRBLT": yrblt, "EXTWALL": extwall, "BSMT": bsmt, "COND": cond,
    })


def test_eal_helpers_match_scalar():
    df = _random_frame()
    for col, scalar, vec in [
        ("flood",   R.calc_flood_eal,   R.flood_eal_vec),
        ("tornado", R.calc_tornado_eal, R.tornado_eal_vec),
        ("seismic", R.calc_seismic_eal, R.seismic_eal_vec),
        ("fire",    R.calc_fire_eal,    R.fire_eal_vec),
    ]:
        expected = df.apply(scalar, axis=1).to_numpy(dtype=float)
        got = np.asarray(vec(df), dtype=float)
        assert np.allclose(got, expected, rtol=1e-12, atol=0), f"{col} EAL mismatch"


def test_fire_eal_missing_wildfire_column():
    """The absent-``wildfire_eal_rate`` branch: fire_eal_vec must still return a
    length-matched Series equal to the scalar (structural baseline for every row),
    never a bare scalar."""
    df = _random_frame().drop(columns=["wildfire_eal_rate"])
    got = R.fire_eal_vec(df)
    assert len(got) == len(df)          # a Series, not a broadcast scalar
    expected = df.apply(R.calc_fire_eal, axis=1).to_numpy(dtype=float)
    assert np.allclose(np.asarray(got, dtype=float), expected, rtol=1e-12, atol=0)


def test_tornado_eal_missing_nri_column():
    """The absent-``tornado_nri_eal_rate`` branch: tornado_eal_vec must still return
    a length-matched Series of zeros (matching the scalar), never a bare scalar."""
    df = _random_frame().drop(columns=["tornado_nri_eal_rate"])
    got = R.tornado_eal_vec(df)
    assert len(got) == len(df)          # a Series, not a broadcast scalar
    expected = df.apply(R.calc_tornado_eal, axis=1).to_numpy(dtype=float)
    assert np.allclose(np.asarray(got, dtype=float), expected, rtol=1e-12, atol=0)


def test_score_and_grade_helpers_match_scalar():
    df = _random_frame()
    # Interior spread plus the edge inputs where the scalar's guards/fall-through
    # matter: NaN (missing tornado rate) → 0.0, negatives and 0 → 100, the exact
    # breakpoints, and values past both ends.
    rates = np.concatenate([
        R.fire_eal_vec(df).to_numpy() + R.seismic_eal_vec(df),
        np.array([np.nan, -1.0, 0.0, 0.00005, 0.0002, 0.001, 0.020, 0.5, 1e-9]),
    ])
    expected = np.array([R.eal_rate_to_score(x) for x in rates], dtype=float)
    got = R.eal_rate_to_score_vec(rates)
    assert np.allclose(got, expected, rtol=1e-12, atol=1e-9, equal_nan=True)

    scores = np.linspace(-5, 105, 223)
    assert list(R.score_to_grade_vec(scores)) == [R.score_to_grade(s) for s in scores]
    assert (list(R.percentile_to_local_grade_vec(scores))
            == [R.percentile_to_local_grade(s) for s in scores])


def test_brm_columns_match_scalar():
    df = _random_frame()
    expected = df.apply(R.calc_brm_row, axis=1, result_type="expand")
    got = R.brm_columns_vec(df)
    assert list(got.columns) == list(expected.columns)
    for col in expected.columns:
        if col == "brm_source":
            assert list(got[col]) == list(expected[col]), "brm_source mismatch"
        else:
            assert np.allclose(got[col].to_numpy(dtype=float),
                               expected[col].to_numpy(dtype=float),
                               rtol=1e-12, atol=0), f"{col} mismatch"


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
