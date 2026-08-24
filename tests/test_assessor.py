#!/usr/bin/env python3
"""County assessor adapters — the registry, the gate, and the parcel match.

Nothing here touches the network. The county portals are stubbed, because what is
worth pinning is the *decision logic*, and that logic exists almost entirely to
avoid one specific catastrophe.

The catastrophe: the Census geocoder interpolates a large share of addresses
along the street centerline, which puts the point in the roadway where no parcel
polygon exists. Measured at 213 W Main St, Barrington — the geocode falls 38 m
from its parcel and hits nothing. Widening to the nearest parcel looks like the
obvious repair, and at a 10 m buffer the two nearest parcels there are **205 and
209**, neither of which is the address asked for. A nearest-match would have
reported a neighbour's 1881 house as this one's, tagged ``observed`` with high
confidence — strictly worse than the tract typical it replaced, because the
reader has no reason to doubt it.

So the buffer never decides anything; the house number does. Most of this file is
that rule.

Run standalone: ``python tests/test_assessor.py``
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.enrich import assessor as A  # noqa: E402
from housing_label.enrich.assessor import cook_il  # noqa: E402
from housing_label.enrich.assessor.base import (  # noqa: E402
    CONDITION_VALUES, CONSTRUCTION_VALUES, FOUNDATION_VALUES, AssessorRecord,
)


# ── the address rule: the whole safety story ────────────────────────────────────
def test_a_different_house_number_never_matches():
    """The case that makes a distance buffer unsafe, pinned directly."""
    asked = "213 W MAIN ST, BARRINGTON, IL, 60010"
    for neighbour in ("205 W MAIN ST", "209 W MAIN ST", "215 W MAIN ST"):
        assert not cook_il._same_address(asked, neighbour), neighbour


def test_the_same_house_matches_across_formatting():
    asked = "213 W MAIN ST, BARRINGTON, IL, 60010"
    for same in ("213 W MAIN ST", "213 w main street", "213 W Main St.",
                 "213 W MAIN ST APT 2", "213 W MAIN ST #3"):
        assert cook_il._same_address(asked, same), same


def test_a_different_street_never_matches():
    """Directionals and street names both have to agree.

    Dropping the directional would be the classic normalisation shortcut, and it
    would make 213 W Main and 213 E Main the same house.
    """
    assert not cook_il._same_address("213 W MAIN ST", "213 E MAIN ST")
    assert not cook_il._same_address("213 W MAIN ST", "213 W STATION ST")


def test_an_address_with_no_house_number_is_unusable():
    """Nothing to anchor on, so it must refuse rather than match on the street."""
    assert cook_il._addr_key("W MAIN ST") is None
    assert cook_il._addr_key("") is None
    assert cook_il._addr_key(None) is None
    assert not cook_il._same_address("W MAIN ST", "W MAIN ST")


# ── hop 1: which parcel, if any ─────────────────────────────────────────────────
def _stub_parcels(monkey, exact, near=()):
    """Stub the parcel layer: ``exact`` at the point, ``near`` within the buffer."""
    def fake(lat, lon, distance_m=0):
        return list(near) if distance_m else list(exact)
    monkey(cook_il, "_parcels", fake)


def _patch(obj, name, value):
    setattr(obj, name, value)


def test_a_point_inside_exactly_one_parcel_uses_it():
    orig = cook_il._parcels
    try:
        _stub_parcels(_patch, [{"PIN14": "01011000040000", "street_address": "213 W MAIN ST"}])
        assert cook_il._pin_at(42.15, -88.13) == "01011000040000"
    finally:
        cook_il._parcels = orig


def test_overlapping_parcels_are_ambiguous_and_refused():
    """Two polygons over one point cannot both be the house."""
    orig = cook_il._parcels
    try:
        _stub_parcels(_patch, [{"PIN14": "1", "street_address": "213 W MAIN ST"},
                               {"PIN14": "2", "street_address": "213 W MAIN ST"}])
        assert cook_il._pin_at(42.15, -88.13) is None
    finally:
        cook_il._parcels = orig


def test_an_offparcel_geocode_is_rescued_by_the_house_number():
    """The Barrington case: no polygon at the point, the right parcel 38 m away."""
    orig = cook_il._parcels
    try:
        _stub_parcels(_patch, [], near=[
            {"PIN14": "01011000060000", "street_address": "205 W MAIN ST"},
            {"PIN14": "01011000050000", "street_address": "209 W MAIN ST"},
            {"PIN14": "01011000040000", "street_address": "213 W MAIN ST"},
        ])
        got = cook_il._pin_at(42.154164, -88.139354,
                              "213 W MAIN ST, BARRINGTON, IL, 60010")
        assert got == "01011000040000", "picked a neighbour instead of the address"
    finally:
        cook_il._parcels = orig


def test_an_offparcel_geocode_without_an_address_refuses():
    """A lat/lon caller has no address, so there is nothing safe to do."""
    orig = cook_il._parcels
    try:
        _stub_parcels(_patch, [], near=[
            {"PIN14": "01011000060000", "street_address": "205 W MAIN ST"},
            {"PIN14": "01011000050000", "street_address": "209 W MAIN ST"},
        ])
        assert cook_il._pin_at(42.154164, -88.139354, None) is None
    finally:
        cook_il._parcels = orig


def test_an_address_matching_two_parcels_refuses():
    """Duplicate street addresses in the layer are not a licence to pick one."""
    orig = cook_il._parcels
    try:
        _stub_parcels(_patch, [], near=[
            {"PIN14": "aaa", "street_address": "213 W MAIN ST"},
            {"PIN14": "bbb", "street_address": "213 W MAIN ST"},
        ])
        assert cook_il._pin_at(42.15, -88.13, "213 W MAIN ST") is None
    finally:
        cook_il._parcels = orig


def test_a_pin_is_zero_padded_to_fourteen():
    """The county's own guidance — exports drop leading zeros, and the CAMA join
    is on the padded form."""
    assert cook_il._clean_pin({"PIN14": "1011000040000"}) == "01011000040000"
    assert cook_il._clean_pin({"PIN14": None}) is None
    assert cook_il._clean_pin({"PIN14": "None"}) is None


# ── the record contract ─────────────────────────────────────────────────────────
def test_every_mapping_lands_in_the_labels_vocabulary():
    """A typo in a mapping table would reach the scorer as an unknown string and
    be silently treated as neutral, so the tables are checked as data."""
    assert set(cook_il._EXT_WALL.values()) <= CONSTRUCTION_VALUES
    assert set(cook_il._BASEMENT.values()) <= FOUNDATION_VALUES
    assert set(cook_il._CONDITION.values()) <= CONDITION_VALUES
    assert all(isinstance(v, int) and v >= 1 for v in cook_il._STORIES.values())


def test_a_record_refuses_a_value_outside_the_vocabulary():
    try:
        AssessorRecord(source="x", data_vintage="y", construction="Masonry")
    except ValueError as exc:
        assert "vocabulary" in str(exc)
    else:
        raise AssertionError("an untranslated county value must not be accepted")


def test_fields_omits_what_the_county_does_not_say():
    rec = AssessorRecord(source="x", data_vintage="y", year_built=1881,
                         foundation="full-basement")
    assert rec.fields() == {"year_built": 1881, "foundation": "full-basement"}


# ── registry and gate ───────────────────────────────────────────────────────────
def test_cook_county_resolves_and_pads():
    assert A.adapter_for_county("17031") is cook_il
    assert A.adapter_for_county(17031) is cook_il          # int, unpadded
    assert A.adapter_for_county("06037") is None           # LA — no adapter
    assert A.adapter_for_county(None) is None


def test_the_gate_is_off_unless_switched_on(monkeypatch=None):
    import os
    prior = os.environ.get(A.ENABLE_ENV)
    try:
        for off in ("", "0", "off", "false", "no"):
            os.environ[A.ENABLE_ENV] = off
            assert not A.enabled(), off
        for on in ("1", "true", "yes", "on"):
            os.environ[A.ENABLE_ENV] = on
            assert A.enabled(), on
        os.environ.pop(A.ENABLE_ENV, None)
        assert not A.enabled(), "must default to off"
    finally:
        if prior is None:
            os.environ.pop(A.ENABLE_ENV, None)
        else:
            os.environ[A.ENABLE_ENV] = prior


def test_disabled_means_no_lookup_is_attempted():
    """Not merely a discarded result — the network call must not happen."""
    import os
    called = []
    orig = cook_il.lookup
    prior = os.environ.get(A.ENABLE_ENV)
    try:
        os.environ.pop(A.ENABLE_ENV, None)
        cook_il.lookup = lambda *a, **k: called.append(1)
        assert A.assessor_for_point(42.15, -88.13, "17031") is None
        assert not called, "queried a county portal while adapters were disabled"
    finally:
        cook_il.lookup = orig
        if prior is not None:
            os.environ[A.ENABLE_ENV] = prior


def test_an_adapter_that_raises_cannot_break_a_label():
    """Fail open is the whole contract: a county portal having a bad day must be
    indistinguishable from a county with no adapter."""
    import os
    orig = cook_il.lookup
    prior = os.environ.get(A.ENABLE_ENV)
    try:
        os.environ[A.ENABLE_ENV] = "1"
        cook_il.lookup = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("portal down"))
        assert A.assessor_for_point(42.15, -88.13, "17031") is None
    finally:
        cook_il.lookup = orig
        if prior is None:
            os.environ.pop(A.ENABLE_ENV, None)
        else:
            os.environ[A.ENABLE_ENV] = prior


def test_no_coordinates_means_no_lookup():
    assert A.assessor_for_point(None, None, "17031") is None


# ── precedence, where the record meets the label ────────────────────────────────
def _loc_with(record, **kw):
    from types import SimpleNamespace
    base = dict(assessor=record, year_built=1960, sqft=1400.0, foundation="crawl",
                construction="frame", num_units=1, stories=1, bldg_material="wood",
                structure_attr_source="P", year_built_distribution=None)
    base.update(kw)
    return SimpleNamespace(**base)


_RECORD = AssessorRecord(
    source="Cook County Assessor's Office", data_vintage="v", parcel_id="p",
    year_built=1881, sqft=1573.0, stories=2, construction="brick",
    foundation="full-basement", condition="good")


def test_an_observed_record_outranks_nsi_field_by_field():
    from housing_label.simulate import house as H
    cfg = {}
    filled = H._autofill_construction_from_nsi(cfg, explicit=set(),
                                               location=_loc_with(_RECORD))
    assert cfg["year_built"] == 1881          # NSI said 1960
    assert cfg["foundation"] == "full-basement"   # NSI said crawl
    assert cfg["construction"] == "brick"     # NSI said frame
    assert cfg["sqft"] == 1573.0
    for f in ("year_built", "foundation", "construction", "sqft", "stories"):
        assert filled[f][2] == "observed", f


def test_the_reader_still_outranks_the_county():
    """A county record can be decades stale; the person in the house cannot be
    overruled by it. This inverted once during development — the assessor was
    consulted before `explicit` — so it is pinned rather than assumed."""
    from housing_label.simulate import house as H
    cfg = {"year_built": 2005}
    filled = H._autofill_construction_from_nsi(
        cfg, explicit={"year_built"}, location=_loc_with(_RECORD))
    assert cfg["year_built"] == 2005, "the county overrode an entered year"
    assert "year_built" not in filled


def test_a_field_the_county_omits_falls_through_to_nsi():
    """Partial records contribute what they have instead of all-or-nothing."""
    from housing_label.simulate import house as H
    partial = AssessorRecord(source="s", data_vintage="v", year_built=1881)
    cfg = {}
    filled = H._autofill_construction_from_nsi(cfg, explicit=set(),
                                               location=_loc_with(partial))
    assert cfg["year_built"] == 1881 and filled["year_built"][2] == "observed"
    assert cfg["construction"] == "frame", "NSI should still fill what the county omits"
    assert filled["construction"][2:] == () or filled["construction"][1] == "low"


def test_condition_is_applied_even_though_nsi_has_no_equivalent():
    """`condition` has no entry in the NSI plan, so an observed value would be
    looked up, found, and silently dropped without the extra pass that covers
    fields the plan does not mention."""
    from housing_label.simulate import house as H
    cfg = {}
    H._autofill_construction_from_nsi(cfg, explicit=set(), location=_loc_with(_RECORD))
    assert cfg.get("condition") == "good"


def test_no_record_leaves_the_previous_behaviour_untouched():
    from housing_label.simulate import house as H
    cfg = {}
    filled = H._autofill_construction_from_nsi(cfg, explicit=set(),
                                               location=_loc_with(None))
    assert cfg["year_built"] == 1960                 # NSI's, as before adapters
    assert all(len(v) < 3 or v[2] != "observed" for v in filled.values())


def _run_all() -> int:
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
