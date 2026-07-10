#!/usr/bin/env python3
"""Tests for the tract → county → national median-home-value crosswalk
(data/home_value.py) and its use in the single-family value auto-fill.

Runs standalone (``python tests/test_home_value.py``) or via pytest.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.data import home_value as HV  # noqa: E402


def _with_table(fake: dict, fn):
    """Run fn() with HV._table swapped for a fake dict, then restore."""
    orig = HV._table
    HV._table = lambda: fake
    try:
        return fn()
    finally:
        HV._table = orig


def test_resolution_prefers_tract_then_county_then_national():
    fake = {"06037700801": 1_700_000.0, "06037": 780_000.0, "00000": 300_000.0}
    tract = _with_table(fake, lambda: HV.median_home_value_for("06037700801", "06037"))
    assert tract["value"] == 1_700_000.0 and tract["geo_level"] == "tract" and tract["resolved"]

    # tract not in table → county (derived from the tract's first 5 digits)
    county = _with_table({"06037": 780_000.0, "00000": 300_000.0},
                         lambda: HV.median_home_value_for("06037700801"))
    assert county["value"] == 780_000.0 and county["geo_level"] == "county"

    # geography given but not in table → national fallback (resolved False)
    natl = _with_table({"00000": 300_000.0},
                       lambda: HV.median_home_value_for("06037700801", "06037"))
    assert natl["value"] == 300_000.0 and natl["geo_level"] == "us" and not natl["resolved"]

    # no geography at all → no value invented from nothing
    nothing = _with_table({"00000": 300_000.0}, lambda: HV.median_home_value_for())
    assert nothing["value"] is None


def test_explicit_county_and_empty_table():
    fake = {"47157": 229_700.0, "00000": 300_000.0}
    # no tract, explicit county
    r = _with_table(fake, lambda: HV.median_home_value_for(county_fips="47157"))
    assert r["value"] == 229_700.0 and r["geo_level"] == "county"
    # nothing bundled at all → value None
    none = _with_table({}, lambda: HV.median_home_value_for("47157010000", "47157"))
    assert none["value"] is None and none["geo_level"] is None


def test_bundled_national_row_present():
    """Smoke test against the real bundled crosswalk: a positive US median exists."""
    natl = HV.median_home_value_for(county_fips="99999")
    assert natl["value"] and natl["value"] > 0 and natl["geo_level"] == "us"


def test_autofill_uses_tract_value_and_source():
    """The single-family auto-fill stores the resolved TRACT median and tags it —
    fully offline: a faked crosswalk + an injected single-family Location."""
    import unittest.mock as mock
    from housing_label.simulate import house
    from housing_label.simulate.location import Location
    from housing_label.simulate.dimensions import HOME_VALUE_SOURCE

    loc = Location(
        lat=34.07, lon=-118.40, state_fips="06", county_fips="06037",
        county_name="LA", tract="06037700801", place_label="BH", in_urban_area=True,
        climate_zone=None, egrid_subregion="CAMX", egrid_factor=None,
        climate_projection=None, wildfire=None, structure_type="single_family",
        num_units=1, stories=1, bldg_material=None, structure_source="NSI", notes=None)
    fake = {"06037700801": 1_700_000.0, "06037": 780_000.0, "00000": 300_000.0}

    def run():
        with mock.patch("housing_label.simulate.location.resolve_location", return_value=loc):
            cfg, _, _ = house.build_label_parts(
                lat=34.07, lon=-118.40, preset="baseline", allow_network=False)
        return cfg

    cfg = _with_table(fake, run)
    assert cfg["value"] == 1_700_000.0                       # the tract median, not county
    assert cfg["value_source"] == HOME_VALUE_SOURCE["tract"]


def _run_all():
    import types
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and isinstance(v, types.FunctionType)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
