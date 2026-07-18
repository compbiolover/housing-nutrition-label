#!/usr/bin/env python3
"""Tests for the Noise lookup + scoring (data/noise.py).

Offline — reads the bundled noise_tracts.csv.gz (tract) and noise_county.csv
(county) only. Execute directly (python tests/test_noise.py) or via pytest.
"""

from __future__ import annotations

import csv
import gzip
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.data import noise as N  # noqa: E402


def test_tract_resolves_and_quieter_scores_higher():
    """A real tract scores at tract resolution; a quieter tract (less exposure)
    outscores a noisier one."""
    geoid = next(iter(N._tract_table()))
    rec = N.noise_for_tract(geoid)
    assert rec is not None and rec["geo_level"] == "tract"
    assert 0.0 <= rec["score"] <= 100.0
    assert N.NOISE_VINTAGE in rec["label"]
    # Monotonicity: more exposure ⇒ lower (quieter=higher) score.
    quiet = N._interp(0.0, N._PCT_XS, N._PCT_YS)
    loud = N._interp(50.0, N._PCT_XS, N._PCT_YS)
    assert quiet > loud
    assert quiet == 100.0


def test_tract_falls_back_to_county():
    """A tract absent from the table falls back to its county mean, never None
    when the county is present."""
    fake = "06037" + "999999"          # LA county, non-existent tract
    assert fake not in N._tract_table()
    rec = N.noise_for_tract(fake)
    assert rec is not None and rec["geo_level"] == "county"
    assert rec["score"] == N.noise_for_county("06037")["score"]


def test_missing_and_absent_return_none():
    assert N.noise_for_tract(None) is None
    assert N.noise_for_tract("") is None
    assert N.noise_for_county("99999") is None      # not a real county


def test_fips_zero_padded():
    assert N.noise_for_county("6037") == N.noise_for_county("06037")


def test_bundled_tables_well_formed():
    seen = 0
    with gzip.open(N._TRACT_CSV_GZ, "rt") as f:
        for row in csv.DictReader(f):
            g = row["geoid"]
            assert len(g) == 11 and g.isdigit()
            assert 0.0 <= float(row["pct_ge60db"]) <= 100.0
            seen += 1
    assert seen > 50000    # ~84k US tracts
    with N._CSV.open() as f:
        for row in csv.DictReader(f):
            assert len(row["county_fips"]) == 5 and row["county_fips"].isdigit()
            assert 0.0 <= float(row["pct_ge60db"]) <= 100.0


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
