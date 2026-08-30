#!/usr/bin/env python3
"""Tests for address → building-attribute auto-fill.

Covers the NSI field mappings (structure.py) and the build_label_parts provenance
helpers (_autofill_construction_from_nsi, _building_block). Pure logic — no
network. This file alone: ``pytest tests/test_autofill.py``.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

_ROOT = pathlib.Path(__file__).resolve().parent.parent

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


def test_cluster_site_reports_one_unit_sqft():
    """An apartment complex NSI modeled as a RES1 cluster reports one dwelling's
    sqft, not the large clubhouse/commercial building the point footprint-selects."""
    pt_lat, pt_lon = 35.0, -90.0
    com = _feat(pt_lat, pt_lon, "COM1", 20000, source="H")            # point sits in this
    res1 = [_feat(pt_lat + 0.0002 * i, pt_lon + 0.0002, "RES1", 1332, source="P")
            for i in range(10)]                                        # 10 identical units
    r = S._classify_site([com] + res1, pt_lat, pt_lon)
    assert r["structure_type"] == "multifamily" and r["detection"] == "nsi-cluster"
    assert r["sqft"] == 1332          # one unit, not the 20,000 sqft commercial building


def test_res3_district_keeps_selected_not_stray_res1():
    """A pure RES3-district detection keeps the addressed structure's sqft — a stray
    single-family footprint must not overwrite it (only a real RES1 cluster does)."""
    pt_lat, pt_lon = 35.0, -90.0
    com = _feat(pt_lat, pt_lon, "COM1", 50000, source="H")            # point sits here
    res3 = [_feat(pt_lat + 0.0002 * i, pt_lon + 0.0003, "RES3C", 8000, resunits=7)
            for i in range(16)]                                        # RES3 district (>=15)
    stray = _feat(pt_lat + 0.0001, pt_lon - 0.0003, "RES1", 1200)     # one stray house
    r = S._classify_site([com] + res3 + [stray], pt_lat, pt_lon)
    assert r["detection"] == "nsi-cluster"
    assert r["sqft"] == 50000         # selected structure, not the 1,200 sqft stray RES1


def test_estimate_cluster_units_from_repeated_footprints():
    """Cluster unit count = the templated (repeated) footprints; strays excluded."""
    from collections import Counter
    fp = Counter({1332: 30, 1510: 30, 1369: 14, 1176: 12, 1764: 1})   # + 1 stray singleton
    assert S._estimate_cluster_units(fp) == 86        # 30+30+14+12, singleton dropped
    assert S._estimate_cluster_units(Counter({1300: 3})) == 8         # below floor → default


def test_cluster_unit_deterministic_on_tied_footprints():
    """Equal-count footprint sizes resolve deterministically to the smaller size."""
    from collections import Counter
    res1 = ([{"y": 0, "x": 0, "occtype": "RES1", "sqft": 1200}] * 5
            + [{"y": 0, "x": 0, "occtype": "RES1", "sqft": 1600}] * 5)
    fp = Counter([1200] * 5 + [1600] * 5)          # a tie between 1200 and 1600
    assert S._cluster_unit(res1, fp)["sqft"] == 1200   # smaller (more unit-like) wins
    # non-finite / non-positive footprints are ignored, don't crash
    assert S._cluster_unit([], Counter()) is None


# ── Per-unit sqft for a detected multi-unit building (house.py) ───────────────
def test_per_unit_sqft_divides_detected_multifamily():
    """A genuine NSI multi-unit record's whole-building sqft is split per unit."""
    loc = _loc(sqft=294504.0, num_units=157, structure_type="multifamily",
               units_confidence="detected")
    # gross ÷ units, less the common-area allowance
    assert H._nsi_per_unit_sqft(loc) == round(294504.0 / 157 * H._MF_NET_TO_GROSS, 1)


def test_per_unit_sqft_leaves_single_family_and_cluster():
    sf = _loc(sqft=1500.0, num_units=1, structure_type="single_family",
              units_confidence="detected")
    assert H._nsi_per_unit_sqft(sf) == 1500.0                      # single unit → as-is
    cluster = _loc(sqft=1332.0, num_units=8, structure_type="multifamily",
                   units_confidence="estimated")                    # cluster heuristic
    assert H._nsi_per_unit_sqft(cluster) == 1332.0                 # already one house → not divided
    assert H._nsi_per_unit_sqft(_loc(sqft=None)) is None


def test_per_unit_sqft_effective_units_override():
    """An explicit unit override drives the divisor; else the detected count."""
    loc = _loc(sqft=294504.0, num_units=157, structure_type="multifamily",
               units_confidence="detected")
    g = H._MF_NET_TO_GROSS
    assert H._nsi_per_unit_sqft(loc, 100) == round(294504.0 / 100 * g, 1)   # override wins
    assert H._nsi_per_unit_sqft(loc, 1) == round(294504.0 / 157 * g, 1)     # 1 (default) → detected
    assert H._nsi_per_unit_sqft(loc, None) == round(294504.0 / 157 * g, 1)  # unset → detected


def test_nsi_sqft_divisor_predicate():
    """The divide decision is a single predicate — robust to a 0-sqft record."""
    mf = _loc(sqft=0.0, num_units=157, structure_type="multifamily", units_confidence="detected")
    assert H._nsi_sqft_divisor(mf) == 157           # divides even when the value is 0
    assert H._nsi_sqft_divisor(mf, 100) == 100      # override
    sf = _loc(sqft=1500.0, num_units=1, structure_type="single_family", units_confidence="detected")
    assert H._nsi_sqft_divisor(sf) is None          # single dwelling → no division
    cluster = _loc(sqft=1332.0, num_units=8, structure_type="multifamily", units_confidence="estimated")
    assert H._nsi_sqft_divisor(cluster) is None      # cluster heuristic → no division


def test_autofill_uses_per_unit_sqft_for_detected_multifamily():
    """The autofill path stores per-unit sqft (not whole-building) and tags it."""
    cfg = {}
    filled = H._autofill_construction_from_nsi(
        cfg, explicit=set(),
        location=_loc(sqft=294504.0, num_units=157, structure_type="multifamily",
                      units_confidence="detected", structure_attr_source="P"))
    assert cfg["sqft"] == round(294504.0 / 157 * H._MF_NET_TO_GROSS, 1)   # per unit, net
    # derived per-unit average → labeled as divided, one confidence notch below high
    assert filled["sqft"] == ("NSI · building area ÷ units, less common area (per unit)", "moderate")


# ── Auto-fill precedence (house.py) ───────────────────────────────────────────
def test_autofill_fills_unset_fields():
    cfg = {"year_built": 2024, "construction": "frame", "foundation": "slab", "sqft": 2000}
    filled = H._autofill_construction_from_nsi(
        cfg, explicit=set(),
        location=_loc(year_built=1960, sqft=1400.0, foundation="crawl", construction="brick"))
    assert cfg["year_built"] == 1960 and cfg["sqft"] == 1400.0
    assert cfg["foundation"] == "crawl" and cfg["construction"] == "brick"
    assert cfg["stories"] == 1                    # NSI stories now wired through
    assert set(filled) == {"year_built", "sqft", "foundation", "construction", "stories"}
    assert filled["sqft"][1] == "high"           # parcel-observed → high confidence


def test_acs_distribution_outranks_nsi_median_year():
    """Two tract medians disagree; the dated, citable one with a spread wins.

    NSI's med_yr_blt and the ACS row answer the same question about the same tract.
    The ACS one is preferred because it is versioned, attributable, and carries the
    quartiles — but it is still an area typical, so the status must stay "assumed".
    """
    loc = _loc(year_built=1960,
               year_built_distribution={"year_built": 1993, "p25": 1985, "p75": 2004,
                                        "spread": 19, "geo_level": "tract",
                                        "resolved": True,
                                        "source": "neighborhood typical year built "
                                                  "(ACS) — not this building's"})
    cfg = {}
    filled = H._autofill_construction_from_nsi(cfg, explicit=set(), location=loc)
    assert cfg["year_built"] == 1993, "the ACS median must win over NSI's"
    source, conf, status = filled["year_built"]
    assert status == "assumed" and conf == "low"
    assert "ACS" in source and "not this building" in source


def test_us_typical_must_not_outrank_the_nsi_tract_median():
    """Specificity beats citability once the ACS row stops being local.

    The ACS US typical is dated and carries a spread, but it describes the whole
    country; NSI's median describes this tract. Preferring the national number to
    gain a citation is a straight loss of specificity — and an earlier revision of
    the precedence block did exactly that while its comment claimed the opposite.
    """
    us = {"year_built": 1980, "p25": 1959, "p75": 2000, "spread": 41,
          "geo_level": "us", "resolved": False,
          "source": "US typical year built (ACS) — not this building's"}
    cfg = {}
    filled = H._autofill_construction_from_nsi(
        cfg, explicit=set(), location=_loc(year_built=1948, year_built_distribution=us))
    assert cfg["year_built"] == 1948, "the US typical displaced a tract-level number"
    assert "NSI" in filled["year_built"][0]


def test_us_typical_is_still_used_when_nothing_more_local_exists():
    """Last resort before the global default, which would invent a new build."""
    us = {"year_built": 1980, "p25": 1959, "p75": 2000, "spread": 41,
          "geo_level": "us", "resolved": False,
          "source": "US typical year built (ACS) — not this building's"}
    cfg = {}
    filled = H._autofill_construction_from_nsi(
        cfg, explicit=set(), location=_loc(year_built=None, year_built_distribution=us))
    assert cfg["year_built"] == 1980
    assert "US typical" in filled["year_built"][0]


def test_no_interval_is_drawn_around_a_year_it_does_not_describe():
    """The range must belong to the number shown.

    When the precedence picks NSI's tract median, pairing it with the ACS county or
    national spread would draw an interval the value can sit outside — 1948 inside
    [1959, 2000] is not just noise, it is visibly wrong.
    """
    us = {"year_built": 1980, "p25": 1959, "p75": 2000, "spread": 41,
          "geo_level": "us", "resolved": False,
          "source": "US typical year built (ACS) — not this building's"}
    loc = _loc(year_built=1948, year_built_distribution=us)
    cfg = {"year_built": 1948, "construction": "frame", "foundation": "crawl",
           "condition": "average", "sqft": 1400.0, "units": 1}
    struct = {"stories": 1, "bldg_material": None, "num_units": 1}
    b = H._building_block(cfg, struct, set(),
                          {"year_built": ("NSI · tract median", "low", "assumed")}, loc)
    assert "typical_range" not in b["year_built"]


def test_nsi_year_is_the_fallback_when_no_distribution_resolves():
    """No geography, no ACS row — NSI's tract median is still better than nothing."""
    cfg = {}
    filled = H._autofill_construction_from_nsi(
        cfg, explicit=set(), location=_loc(year_built=1960, year_built_distribution=None))
    assert cfg["year_built"] == 1960
    source, _conf, status = filled["year_built"]
    assert status == "assumed"
    assert "NSI" in source and "not this building" in source


def test_building_block_carries_the_year_built_interval():
    """The interval rides the field, not confidence.bands — and only while the value
    is still ours to doubt."""
    dist = {"year_built": 1993, "p25": 1985, "p75": 2004, "spread": 19,
            "geo_level": "tract", "resolved": True}
    loc = _loc(year_built_distribution=dist)
    cfg = {"year_built": 1993, "construction": "frame", "foundation": "crawl",
           "condition": "average", "sqft": 1400.0, "units": 1}
    struct = {"stories": 1, "bldg_material": None, "num_units": 1}
    autofilled = {"year_built": ("neighborhood typical (ACS)", "low", "assumed")}

    assumed = H._building_block(cfg, struct, set(), autofilled, loc)["year_built"]
    assert assumed["status"] == "assumed"
    assert assumed["typical_range"] == [1985, 2004]
    assert assumed["range_geo_level"] == "tract"

    # Once the reader confirms the real year, what the neighbours did stops bearing
    # on it — the range must not linger next to a value we were told.
    confirmed = H._building_block(cfg, struct, {"year_built"}, {}, loc)["year_built"]
    assert confirmed["status"] == "confirmed"
    assert "typical_range" not in confirmed


def test_building_block_omits_the_interval_when_no_distribution():
    """No crosswalk row, no range — never a placeholder pair of years."""
    cfg = {"year_built": 1960, "construction": "frame", "foundation": "crawl",
           "condition": "average", "sqft": 1400.0, "units": 1}
    struct = {"stories": 1, "bldg_material": None, "num_units": 1}
    b = H._building_block(cfg, struct, set(),
                          {"year_built": ("NSI · tract median", "low", "assumed")},
                          _loc(year_built_distribution=None))
    assert "typical_range" not in b["year_built"]


def test_footprint_propagated_only_for_single_dwelling():
    loc = _loc(footprint_area_m2=400.0, footprint_perimeter_m=90.0)
    sf = {}
    H._autofill_construction_from_nsi(sf, explicit=set(), location=loc, units=1)
    assert sf.get("footprint_area_m2") == 400.0 and sf.get("footprint_perimeter_m") == 90.0
    # A whole-building footprint must NOT be fed to a per-unit multi-family score.
    mf = {}
    H._autofill_construction_from_nsi(mf, explicit=set(), location=loc, units=4)
    assert "footprint_area_m2" not in mf and "footprint_perimeter_m" not in mf


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
