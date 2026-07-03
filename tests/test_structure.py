#!/usr/bin/env python3
"""Tests for the NSI building-structure lookup (enrich/structure.py).

Runs without network — the NSI HTTP call is monkeypatched. Execute directly
(python tests/test_structure.py) or via pytest.
"""

from __future__ import annotations

from housing_label.enrich import structure as S


def test_classify_occupancy():
    assert S._classify("RES1-1SNB") == "single_family"
    assert S._classify("RES1-2SWB") == "single_family"
    assert S._classify("RES2") == "manufactured"
    assert S._classify("RES3A") == "multifamily"
    assert S._classify("RES3F") == "multifamily"
    assert S._classify("RES5") == "other_residential"
    assert S._classify("COM1") == "non_residential"
    assert S._classify("") == "non_residential"


def test_units_for():
    assert S._units_for("RES3B", 12) == 12          # NSI resunits wins
    assert S._units_for("RES3C", None) == 7          # bin representative fallback
    assert S._units_for("RES1", None) is None        # no residential bin for RES1
    assert S._units_for("RES3B", "0") == 3           # zero/blank → bin fallback


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _patch_nsi(monkeypatch, features):
    S._nsi_nearest.cache_clear()
    monkeypatch.setattr(S.requests, "get",
                        lambda *a, **k: _FakeResp({"type": "FeatureCollection",
                                                   "features": features}))


def _feat(occ, resunits, story, x, y, sqft=1500, bt="W", yr=1990):
    return {"properties": {"occtype": occ, "resunits": resunits, "num_story": story,
                           "sqft": sqft, "bldgtype": bt, "med_yr_blt": yr,
                           "x": x, "y": y}}


def test_structure_for_point_multifamily(monkeypatch):
    # Two structures; the nearest to the query point is the RES3 building.
    feats = [_feat("RES1-1SNB", 1, 1, x=-87.700, y=41.900),      # far
             _feat("RES3B", 3, 4, x=-87.6531, y=41.9436, sqft=4600, bt="M")]  # near
    _patch_nsi(monkeypatch, feats)
    out = S.structure_for_point(41.9436, -87.6531)
    assert out["structure_type"] == "multifamily"
    assert out["num_units"] == 3
    assert out["stories"] == 4
    assert out["bldg_material"] == "masonry"
    assert out["source"] == "NSI"


def test_structure_for_point_offline_and_empty(monkeypatch):
    # Offline never touches the network.
    assert S.structure_for_point(41.9, -87.6, allow_network=False) is None
    # No structures returned → None.
    _patch_nsi(monkeypatch, [])
    assert S.structure_for_point(41.9, -87.6) is None
    # Features present but all missing usable coordinates → None (no silent
    # mis-detection of the first feature).
    _patch_nsi(monkeypatch, [{"properties": {"occtype": "RES1", "x": None, "y": None}}])
    assert S.structure_for_point(41.9, -87.6) is None


def test_detected_multifamily_fires_caveat():
    """A resolved location detected as multi-family triggers the dense-housing
    caveat even when the caller didn't pass units > 1."""
    from types import SimpleNamespace
    from housing_label.simulate import house
    loc = SimpleNamespace(county_fips="17031", egrid_subregion="RFCW",
                          structure_type="multifamily", num_units=12)
    msg = " ".join(house._approx_caveats(loc, units=1)).lower()
    assert "multi-unit building" in msg
    assert "12 units" in msg


if __name__ == "__main__":
    import types
    mp = types.SimpleNamespace(setattr=lambda o, n, v: setattr(o, n, v))
    test_classify_occupancy()
    test_units_for()
    test_structure_for_point_multifamily(mp)
    test_structure_for_point_offline_and_empty(mp)
    test_detected_multifamily_fires_caveat()
    print("structure tests passed")
