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
    # Monotonicity within the exposed branch: more exposure ⇒ lower score.
    cleaner = W._interp(1.0, W._EXPOSED_XS, W._EXPOSED_YS)
    dirtier = W._interp(50.0, W._EXPOSED_XS, W._EXPOSED_YS)
    assert cleaner > dirtier


def test_hurdle_spotless_scores_100():
    """Hurdle model: a spotless (0%) county has reached the optimum → top score,
    not the old ~86.5 tie-adjusted rank."""
    table = W._table()
    spotless = next(f for f, r in table.items() if r["pct_pop_hb_violation"] == 0.0)
    assert W.water_for_county(spotless)["score"] == 100.0


def test_hurdle_exposed_branch_is_continuous_no_cliff():
    """The exposed branch starts at ~100 for X→0+, so the clean class (100) and the
    least-exposed county are adjacent — not separated by the old ~14-point (86.5→73)
    cliff. A modestly-exposed 0.2% county still scores well into the A/B range."""
    assert W._EXPOSED_YS[0] == 100.0
    assert W._EXPOSED_XS[0] <= 0.01                  # first anchor sits just above 0
    assert W._interp(0.2, W._EXPOSED_XS, W._EXPOSED_YS) > 85.0


def test_spotless_county_beats_exposed_county():
    """Find a spotless (0%) and an exposed (>0%) county in the bundled table and
    confirm the spotless one scores strictly higher."""
    table = W._table()
    spotless = next(f for f, r in table.items() if r["pct_pop_hb_violation"] == 0.0)
    exposed = next(f for f, r in table.items() if r["pct_pop_hb_violation"] > 5.0)
    assert W.water_for_county(spotless)["score"] > W.water_for_county(exposed)["score"]


def test_hardcoded_anchors_match_bundled_data():
    """The exposed-branch anchors hardcoded in water.py must equal the conditional
    survival of the exposed distribution recomputed from the shipped CSV, so the
    hurdle score can't silently drift from the data it summarizes. (Mirrors what
    scripts/build_water.py emits.)"""
    exposed = []
    with W._CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            pct = float(row["pct_pop_hb_violation"])
            pop = float(row["cws_pop"] or 0)
            if pct > 0 and pop > 0:
                exposed.append((pct, pop))
    ep = sum(p for _, p in exposed)
    recomputed = [round(100.0 * sum(p for pct, p in exposed if pct > x) / ep, 1)
                  for x in W._EXPOSED_XS]
    assert recomputed == W._EXPOSED_YS, (recomputed, W._EXPOSED_YS)


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
