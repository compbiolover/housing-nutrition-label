#!/usr/bin/env python3
"""Tests for the Health Impact dimension (enrich/health.py).

Pure computation over synthetic PLACES records — no network, no CSV. Execute
directly (python tests/test_health.py) or via pytest.
"""

from __future__ import annotations

from housing_label.enrich import health as H


def test_clean_tract_normalises_geoid():
    assert H._clean_tract("47157000400.0") == "47157000400"
    assert H._clean_tract("400") == "00000000400"
    for empty in (None, "nan", "None", ""):
        assert H._clean_tract(empty) is None


def _records(tracts: dict) -> list:
    """Build raw PLACES records from {tract_geoid: {measureid: prevalence}}."""
    out = []
    for geoid, measures in tracts.items():
        for measureid, val in measures.items():
            out.append({"locationid": geoid, "measureid": measureid,
                        "data_value": val, "year": 2023})
    return out


# Every PLACES measure the model consumes (all are "higher prevalence = worse").
_ALL = list(H.MEASURE_MAP)


def test_compute_health_index_orientation():
    """100 = healthiest: the low-prevalence tract must outrank the high one."""
    healthy = {m: 5.0 for m in _ALL}       # low disease prevalence everywhere
    sick    = {m: 40.0 for m in _ALL}      # high prevalence everywhere
    mid     = {m: 20.0 for m in _ALL}
    wide = H.compute_health_index(_records({"h": healthy, "s": sick, "m": mid}))

    assert wide.loc["h", "health_index"] > wide.loc["m", "health_index"]
    assert wide.loc["m", "health_index"] > wide.loc["s", "health_index"]
    # The healthiest tract tops the ranking and the sickest bottoms it. (Percentile
    # ranking puts the worst tract at exactly 0; the best sits at (1-1/n)*100, not
    # 100, so assert it holds the max rather than a fixed value.)
    assert wide["health_index"].idxmax() == "h"
    assert wide.loc["s", "health_index"] == 0.0
    # Raw prevalence columns are preserved and renamed to the friendly names.
    assert "diabetes_pct" in wide.columns
    assert wide.loc["s", "diabetes_pct"] == 40.0


def test_compute_health_index_within_bounds():
    tracts = {f"t{i}": {m: float(i * 3 + 5) for m in _ALL} for i in range(6)}
    wide = H.compute_health_index(_records(tracts))
    idx = wide["health_index"]
    assert (idx >= 0).all() and (idx <= 100).all()


def test_compute_health_index_ignores_unknown_measures():
    """A measure id outside MEASURE_MAP is dropped, not scored."""
    recs = _records({"a": {m: 10.0 for m in _ALL}, "b": {m: 20.0 for m in _ALL}})
    recs.append({"locationid": "a", "measureid": "BOGUS", "data_value": 999,
                 "year": 2023})
    wide = H.compute_health_index(recs)
    assert "BOGUS" not in wide.columns
    assert set(wide.columns) == set(H.MEASURE_MAP.values()) | {"health_index"}


def test_compute_health_index_empty_raises():
    """No matching measures → a clear error rather than a silent empty frame."""
    try:
        H.compute_health_index([{"locationid": "a", "measureid": "BOGUS",
                                 "data_value": 1, "year": 2023}])
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError on no matching measures")


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
