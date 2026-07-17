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
    S._structure_at.cache_clear()
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


def test_cluster_of_mislabeled_res1_detects_multifamily(monkeypatch):
    """NSI models a garden-apartment complex as many identical single-family
    footprints (the Spruce Ridge case). The identical-footprint cluster is detected
    as multi-family with an *estimated* unit count and no (unreliable) shell."""
    # 10 RES1 structures all sharing the same 1332 sqft footprint, near the point.
    feats = [_feat("RES1-1SNB", 1, 1, x=-83.9288 + i * 1e-4, y=35.9373, sqft=1332)
             for i in range(10)]
    _patch_nsi(monkeypatch, feats)
    out = S.structure_for_point(35.9373, -83.9288)
    assert out["structure_type"] == "multifamily"
    assert out["detection"] == "nsi-cluster"
    assert out["units_confidence"] == "estimated"
    assert out["num_units"] == 10          # the 10 repeated (templated) footprints = the units
    assert out["bldg_material"] is None and out["stories"] is None   # shell unreliable


def test_res3_district_detects_multifamily_when_nearest_is_a_house(monkeypatch):
    """An apartment district where the nearest centroid is a single house is still
    detected as multi-family via the RES3-count signal, with an estimated count."""
    feats = [_feat("RES1-1SNB", 1, 1, x=-87.6531, y=41.9436, sqft=1500)]      # nearest house
    feats += [_feat("RES3D", None, 5, x=-87.6531 + (i + 1) * 2e-4, y=41.9436, sqft=9000)
              for i in range(16)]                                            # 16 RES3 → district
    _patch_nsi(monkeypatch, feats)
    out = S.structure_for_point(41.9436, -87.6531)
    assert out["structure_type"] == "multifamily"
    assert out["detection"] == "nsi-cluster"
    assert out["units_confidence"] == "estimated"
    assert out["num_units"] == 14                            # median RES3D bin (10–19 → 14)


def test_single_family_not_false_flagged(monkeypatch):
    """A normal single-family address — a house plus a few varied-footprint
    neighbors — stays single-family (no cluster, no RES3 district)."""
    feats = [_feat("RES1-1SNB", 1, 1, x=-83.90, y=35.90, sqft=1800),         # the house
             _feat("RES1-2SNB", 1, 2, x=-83.9002, y=35.9001, sqft=2400),
             _feat("RES1-1SNB", 1, 1, x=-83.8998, y=35.9002, sqft=1600)]
    _patch_nsi(monkeypatch, feats)
    out = S.structure_for_point(35.90, -83.90)
    assert out["structure_type"] == "single_family"
    assert out["detection"] == "nsi" and out["units_confidence"] == "detected"


def test_widens_box_when_narrow_query_has_no_usable_coords(monkeypatch):
    """The narrow box returns features but none with usable centroids; the wider box
    has a valid RES3. Detection must widen rather than give up (no false negative)."""
    S._structure_at.cache_clear()

    def fake_query(lat, lon, half):
        if half == S._BOX_DEG:
            return [{"occtype": "RES1", "x": None, "y": None}]          # present but unusable
        return [{"occtype": "RES3B", "resunits": 3, "num_story": 4,
                 "sqft": 4600, "bldgtype": "M", "x": lon, "y": lat}]    # valid in wide box
    monkeypatch.setattr(S, "_nsi_query", fake_query)
    out = S.structure_for_point(41.9436, -87.6531)
    assert out is not None
    assert out["structure_type"] == "multifamily" and out["num_units"] == 3


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


def test_nsi_unavailable_raises_distinct_from_empty(monkeypatch):
    """A transient NSI outage raises NSIUnavailable (not an empty result), so the
    caller can fall back to defaults *without* caching a degraded single-family
    label onto the coordinate. A genuine empty response still returns None."""
    import pytest

    S._structure_at.cache_clear()
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)   # no back-off waits

    def boom(*a, **k):
        raise S.requests.exceptions.ConnectionError("nsi down")

    monkeypatch.setattr(S.requests, "get", boom)
    with pytest.raises(S.NSIUnavailable):
        S.structure_for_point(41.9436, -87.6531)

    # A genuine empty response is a real "no building here" answer, not an outage.
    _patch_nsi(monkeypatch, [])
    assert S.structure_for_point(41.9436, -87.6531) is None


def test_detected_multifamily_fires_caveat():
    """A resolved location detected as multi-family triggers the dense-housing
    caveat even when the caller didn't pass units > 1."""
    from types import SimpleNamespace
    from housing_label.simulate import house
    loc = SimpleNamespace(county_fips="17031", egrid_subregion="RFCW",
                          structure_type="multifamily", num_units=12)
    msg = " ".join(house._approx_caveats(loc, {"units": 1})).lower()
    assert "multi-unit building" in msg
    assert "12 units" in msg
    # NSI gave no usable material/stories here, so Resilience/Durability can't adjust:
    # the caveat prompts for those rather than over-claiming the full building context.
    assert "number of stories" in msg
    assert "single-family" in msg
    # With a usable material + height, it becomes the full building-context caveat.
    loc_full = SimpleNamespace(county_fips="17031", egrid_subregion="RFCW",
                               structure_type="multifamily", num_units=12,
                               bldg_material="concrete", stories=5)
    full = " ".join(house._approx_caveats(loc_full, {"units": 1})).lower()
    assert "single-family" not in full
    assert "12 units" in full


if __name__ == "__main__":
    import types
    mp = types.SimpleNamespace(setattr=lambda o, n, v: setattr(o, n, v))
    test_classify_occupancy()
    test_units_for()
    test_structure_for_point_multifamily(mp)
    test_structure_for_point_offline_and_empty(mp)
    test_detected_multifamily_fires_caveat()
    print("structure tests passed")
