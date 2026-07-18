#!/usr/bin/env python3
"""Tests for the Water Quality lookup + scoring (data/water.py).

Offline — reads the bundled water_county.csv only. Execute directly
(python tests/test_water.py) or via pytest.
"""

from __future__ import annotations

import csv
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.data import water as W  # noqa: E402


def test_county_resolves_and_cleaner_scores_higher():
    """A real county scores at county resolution; less health-based exposure
    outscores more."""
    fips = next(iter(W._table()))
    rec = W.water_for_county(fips)
    assert rec is not None and rec["geo_level"] == "county"
    assert 0.0 <= rec["score"] <= 100.0
    assert W.WATER_VINTAGE in rec["label"]
    # Monotonicity: more exposure ⇒ lower (cleaner=higher) score.
    clean = W._interp(0.0, W._PCT_XS, W._PCT_YS)
    dirty = W._interp(50.0, W._PCT_XS, W._PCT_YS)
    assert clean > dirty
    # Zero-inflation: a spotless county maps to the tie-adjusted mass, not 100.
    assert clean == W._PCT_YS[0] < 100.0


def test_spotless_county_beats_exposed_county():
    """Find a spotless (0%) and an exposed (>0%) county in the bundled table and
    confirm the spotless one scores strictly higher."""
    table = W._table()
    spotless = next(f for f, r in table.items() if r["pct_pop_hb_violation"] == 0.0)
    exposed = next(f for f, r in table.items() if r["pct_pop_hb_violation"] > 5.0)
    assert W.water_for_county(spotless)["score"] > W.water_for_county(exposed)["score"]


def test_missing_and_absent_return_none():
    assert W.water_for_county(None) is None
    assert W.water_for_county("") is None
    assert W.water_for_county("99999") is None      # not a real county


def test_fips_zero_padded():
    fips5 = next(f for f in W._table() if f.startswith("0"))
    assert W.water_for_county(fips5.lstrip("0")) == W.water_for_county(fips5)


def test_bundled_table_well_formed():
    seen = 0
    with W._CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            assert len(row["county_fips"]) == 5 and row["county_fips"].isdigit()
            assert 0.0 <= float(row["pct_pop_hb_violation"]) <= 100.0
            assert int(row["cws_pop"]) > 0 and int(row["n_cws"]) > 0
            seen += 1
    assert seen > 2500     # ~3.1k US counties with a community water system


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
