#!/usr/bin/env python3
"""Tests for address → building-attribute auto-fill.

Covers the NSI field mappings (structure.py) and the build_label_parts provenance
helpers (_autofill_construction_from_nsi, _building_block). Pure logic — no
network. Runs standalone (``python tests/test_autofill.py``) or via pytest.
"""

from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.enrich import structure as S  # noqa: E402
from housing_label.simulate import house as H  # noqa: E402


def _loc(**kw) -> SimpleNamespace:
    d = dict(year_built=1960, sqft=1400.0, foundation="crawl", construction="frame",
             num_units=1, stories=1, bldg_material="wood", structure_attr_source="P")
    d.update(kw)
    return SimpleNamespace(**d)


# ── NSI field mappings (structure.py) ─────────────────────────────────────────
def test_nsi_result_maps_construction_foundation_source():
    r = S._result(
        {"bldgtype": "W", "found_type": "B", "source": "P",
         "num_story": "2", "sqft": "1500", "med_yr_blt": "1970"},
        "single_family", 1, units_confidence="detected", detection="nsi")
    assert r["construction"] == "frame"          # bldgtype W → frame
    assert r["foundation"] == "full-basement"    # found_type B → full-basement
    assert r["attr_source"] == "P"               # parcel-observed
    assert r["sqft"] == 1500 and r["year_built"] == 1970


def test_nsi_masonry_and_slab():
    r = S._result({"bldgtype": "M", "found_type": "S", "source": "M"},
                  "single_family", 1, units_confidence="detected", detection="nsi")
    assert r["construction"] == "brick" and r["foundation"] == "slab"
    assert r["attr_source"] == "M"


def test_nsi_drop_shell_nulls_shell_attrs():
    r = S._result({"bldgtype": "W", "found_type": "B"}, "multifamily", 8,
                  units_confidence="estimated", detection="nsi-cluster", drop_shell=True)
    assert r["construction"] is None and r["foundation"] is None
    assert r["bldg_material"] is None and r["stories"] is None


# ── Addressed-structure selection (structure.py) ──────────────────────────────
def _feat(lat, lon, occtype, sqft, **kw):
    d = {"y": lat, "x": lon, "occtype": occtype, "sqft": sqft}
    d.update(kw)
    return d


def test_select_prefers_footprint_over_nearest_centroid():
    """A point inside a big tower's footprint picks the tower, even when a small
    house's centroid is closer (the downtown high-rise mis-selection)."""
    pt_lat, pt_lon = 35.0, -90.0
    house = _feat(pt_lat + 0.00027, pt_lon, "RES1", 1500)                  # ~30 m N, tiny
    tower = _feat(pt_lat + 0.00036, pt_lon, "RES3F", 294504, resunits=157,  # ~40 m N, huge
                  num_story=12, bldgtype="S", found_type="S", source="P")
    r = S._classify_site([house, tower], pt_lat, pt_lon)
    assert r["structure_type"] == "multifamily" and r["num_units"] == 157
    # the naive nearest-centroid would have picked the closer house
    assert S._dist_m(house, pt_lat, pt_lon) < S._dist_m(tower, pt_lat, pt_lon)


def test_select_prefers_residential_when_coplausible():
    """A housing address between a commercial block and an apartment tower of
    similar size resolves to the residential building."""
    pt_lat, pt_lon = 35.0, -90.0
    com = _feat(pt_lat + 0.00036, pt_lon, "COM10", 250000)               # ~40 m, commercial
    apt = _feat(pt_lat + 0.00040, pt_lon, "RES3E", 250000, resunits=45)  # ~45 m, residential
    r = S._classify_site([com, apt], pt_lat, pt_lon)
    assert r["structure_type"] == "multifamily" and r["num_units"] == 45


# ── Per-unit sqft for a detected multi-unit building (house.py) ───────────────
def test_per_unit_sqft_divides_detected_multifamily():
    """A genuine NSI multi-unit record's whole-building sqft is split per unit."""
    loc = _loc(sqft=294504.0, num_units=157, structure_type="multifamily",
               units_confidence="detected")
    assert H._nsi_per_unit_sqft(loc) == round(294504.0 / 157, 1)   # ~1875.8


def test_per_unit_sqft_leaves_single_family_and_cluster():
    sf = _loc(sqft=1500.0, num_units=1, structure_type="single_family",
              units_confidence="detected")
    assert H._nsi_per_unit_sqft(sf) == 1500.0                      # single unit → as-is
    cluster = _loc(sqft=1332.0, num_units=8, structure_type="multifamily",
                   units_confidence="estimated")                    # cluster heuristic
    assert H._nsi_per_unit_sqft(cluster) == 1332.0                 # already one house → not divided
    assert H._nsi_per_unit_sqft(_loc(sqft=None)) is None


def test_autofill_uses_per_unit_sqft_for_detected_multifamily():
    """The autofill path stores per-unit sqft (not whole-building) and tags it."""
    cfg = {}
    filled = H._autofill_construction_from_nsi(
        cfg, explicit=set(),
        location=_loc(sqft=294504.0, num_units=157, structure_type="multifamily",
                      units_confidence="detected", structure_attr_source="P"))
    assert cfg["sqft"] == round(294504.0 / 157, 1)        # per unit, not 294504
    assert filled["sqft"] == ("NSI · structure record", "high")   # parcel-observed → high


# ── Auto-fill precedence (house.py) ───────────────────────────────────────────
def test_autofill_fills_unset_fields():
    cfg = {"year_built": 2024, "construction": "frame", "foundation": "slab", "sqft": 2000}
    filled = H._autofill_construction_from_nsi(
        cfg, explicit=set(),
        location=_loc(year_built=1960, sqft=1400.0, foundation="crawl", construction="brick"))
    assert cfg["year_built"] == 1960 and cfg["sqft"] == 1400.0
    assert cfg["foundation"] == "crawl" and cfg["construction"] == "brick"
    assert set(filled) == {"year_built", "sqft", "foundation", "construction"}
    assert filled["sqft"][1] == "high"           # parcel-observed → high confidence


def test_autofill_respects_explicit_user_fields():
    cfg = {"year_built": 1990, "construction": "stone", "foundation": "slab", "sqft": 2000}
    filled = H._autofill_construction_from_nsi(
        cfg, explicit={"year_built", "construction"}, location=_loc())
    assert cfg["year_built"] == 1990 and cfg["construction"] == "stone"   # untouched
    assert "year_built" not in filled and "construction" not in filled
    assert "sqft" in filled and "foundation" in filled                    # unset → filled


def test_autofill_modeled_source_lowers_sqft_confidence():
    cfg = {"sqft": 2000}
    filled = H._autofill_construction_from_nsi(
        cfg, explicit=set(), location=_loc(structure_attr_source="M"))
    assert filled["sqft"][1] == "moderate"       # modeled, not parcel-observed


# ── Provenance block (house.py) ───────────────────────────────────────────────
def test_building_block_statuses():
    cfg = {"year_built": 1960, "construction": "frame", "foundation": "crawl",
           "condition": "average", "sqft": 1400.0, "units": 1, "lot_acres": 0.25,
           "value": 200000, "bldg_material": None, "stories": 1}
    struct = {"stories": 1, "bldg_material": None, "num_units": 1}
    explicit = {"condition"}                      # user typed condition
    autofilled = {"year_built": ("NSI · neighborhood median", "low"),
                  "sqft": ("NSI · structure record", "high"),
                  "value": ("county median (ACS)", "low")}
    b = H._building_block(cfg, struct, explicit, autofilled, _loc())
    assert b["condition"]["status"] == "confirmed"
    assert b["year_built"]["status"] == "estimated"
    assert b["sqft"]["status"] == "estimated"
    assert b["value"]["status"] == "estimated"
    assert b["lot_acres"]["status"] == "assumed"  # no source → assumed default
    # every entry carries value + source + confidence
    for entry in b.values():
        assert set(entry) == {"value", "status", "source", "confidence"}


def test_building_block_units_detected_not_confirmed():
    """A supplied units of 1 is not a real override: an NSI-detected multi-unit
    building shows the detected count tagged 'estimated', not 'you entered'; a
    genuine >1 entry is 'confirmed'."""
    loc = _loc(num_units=30)
    cfg = {"units": 1, "year_built": 1980, "construction": "frame",
           "foundation": "slab", "condition": "average", "sqft": 1000,
           "lot_acres": 0.1, "value": 250000}
    detected = H._building_block(cfg, {"num_units": 30, "stories": 3,
                                       "bldg_material": "concrete"},
                                 explicit={"units"}, autofilled={}, location=loc)
    assert detected["units"] == {"value": 30, "status": "estimated",
                                 "source": "NSI · structure record", "confidence": "moderate"}
    confirmed = H._building_block(dict(cfg, units=12),
                                  {"num_units": 12, "stories": 3, "bldg_material": "concrete"},
                                  explicit={"units"}, autofilled={}, location=loc)
    assert confirmed["units"]["status"] == "confirmed" and confirmed["units"]["value"] == 12


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
