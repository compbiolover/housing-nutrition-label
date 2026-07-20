#!/usr/bin/env python3
"""Tests for the residential-only screen (non-residential addresses are refused).

A workplace / store / warehouse must not receive a "home" nutrition label. The
guard lives in ``build_label_parts`` (shared by the CLI and the HTTP API) and
fires only when NSI *positively* classified the building as non-residential; an
unknown building (NSI unavailable / no match) is never blocked.

Runs without network — a pre-resolved ``Location`` is injected and the location
dimensions are left unscored (``allow_network=False``). Execute directly
(python tests/test_residential_screen.py) or via pytest.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.simulate.location import Location  # noqa: E402
from housing_label.simulate.house import (  # noqa: E402
    build_label_parts, NonResidentialProperty)


def _loc(structure_type, num_units=None):
    """A pre-resolved Location (no geocoding) carrying a detected structure type."""
    return Location(lat=35.13, lon=-89.99, county_fips="47157",
                    tract="47157003100", structure_type=structure_type,
                    num_units=num_units)


def _scores(**kwargs):
    """build_label_parts helper: offline, returns the composite score."""
    _cfg, _r, lbl = build_label_parts(allow_network=False, **kwargs)
    return lbl["composite_score"]


def test_non_residential_address_is_refused():
    """A real address (no preset) NSI flagged non-residential raises."""
    try:
        build_label_parts(location=_loc("non_residential"), allow_network=False)
    except NonResidentialProperty as exc:
        assert exc.structure_type == "non_residential"
        assert "residential" in str(exc).lower()
        return
    raise AssertionError("expected NonResidentialProperty for a non-residential address")


def test_allow_override_scores_anyway():
    """allow_non_residential=True bypasses the screen (misclassified real home)."""
    assert _scores(location=_loc("non_residential"), allow_non_residential=True) is not None


def test_preset_is_a_hypothetical_and_bypasses():
    """A preset is a 'what if you built this here' scenario — never screened."""
    assert _scores(location=_loc("non_residential"), preset="baseline") is not None


def test_entered_units_gt_1_are_treated_residential():
    """An entered unit count > 1 asserts a residence (flips to multifamily)."""
    assert _scores(location=_loc("non_residential"), units=2) is not None


def test_residential_address_scores_normally():
    for st in ("single_family", "multifamily", "manufactured", "other_residential"):
        assert _scores(location=_loc(st, num_units=1)) is not None, st


def test_unknown_structure_is_not_blocked():
    """NSI unavailable / no match leaves structure_type None — must still score."""
    assert _scores(location=_loc(None)) is not None


def test_api_maps_refusal_to_422():
    """The HTTP API returns 422 (not 400/502) with the guidance in `detail`."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_api_maps_refusal_to_422 (fastapi not installed)")
        return
    import housing_label.api as api
    from housing_label.simulate.house import _NON_RESIDENTIAL_MESSAGE

    def _fake_build(**kw):
        # Mirror the real guard: refuse only a real address that didn't opt out.
        if kw.get("preset") is None and not kw.get("allow_non_residential"):
            raise NonResidentialProperty(_NON_RESIDENTIAL_MESSAGE,
                                         structure_type="non_residential")
        raise AssertionError("should not reach scoring in this test")

    orig = api.build_label_parts
    api.build_label_parts = _fake_build
    try:
        client = TestClient(api.app)
        r = client.get("/label?lat=35.13&lon=-89.99")
        assert r.status_code == 422, r.status_code
        assert "residential" in r.json()["detail"].lower()
    finally:
        api.build_label_parts = orig


if __name__ == "__main__":
    test_non_residential_address_is_refused()
    test_allow_override_scores_anyway()
    test_preset_is_a_hypothetical_and_bypasses()
    test_entered_units_gt_1_are_treated_residential()
    test_residential_address_scores_normally()
    test_unknown_structure_is_not_blocked()
    test_api_maps_refusal_to_422()
    print("residential-screen tests passed")
