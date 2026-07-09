#!/usr/bin/env python3
"""Tests for address → building-attribute auto-fill.

Covers the NSI field mappings (structure.py) and the build_label_parts provenance
helpers (_autofill_construction_from_nsi, _building_block). Pure logic — no
network. Runs standalone (``python tests/test_autofill.py``) or via pytest.
"""

from __future__ import annotations

from types import SimpleNamespace

from housing_label.enrich import structure as S
from housing_label.simulate import house as H


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


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
