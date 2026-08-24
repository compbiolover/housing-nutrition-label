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

import os
import pathlib
import time
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.enrich import assessor as A  # noqa: E402
from housing_label.enrich.assessor import _shared, cook_il  # noqa: E402
from housing_label.enrich.assessor._shared import (  # noqa: E402
    address_key, same_address,
)
from housing_label.enrich.assessor.base import (  # noqa: E402
    CONDITION_VALUES, CONSTRUCTION_VALUES, FOUNDATION_VALUES, AssessorRecord,
)


# ── the address rule: the whole safety story ────────────────────────────────────
def test_a_different_house_number_never_matches():
    """The case that makes a distance buffer unsafe, pinned directly."""
    asked = "213 W MAIN ST, BARRINGTON, IL, 60010"
    for neighbour in ("205 W MAIN ST", "209 W MAIN ST", "215 W MAIN ST"):
        assert not same_address(asked, neighbour), neighbour


def test_the_same_house_matches_across_formatting():
    asked = "213 W MAIN ST, BARRINGTON, IL, 60010"
    for same in ("213 W MAIN ST", "213 w main street", "213 W Main St.",
                 "213 W MAIN ST APT 2", "213 W MAIN ST #3"):
        assert same_address(asked, same), same


def test_a_different_street_never_matches():
    """Directionals and street names both have to agree.

    Dropping the directional would be the classic normalisation shortcut, and it
    would make 213 W Main and 213 E Main the same house.
    """
    assert not same_address("213 W MAIN ST", "213 E MAIN ST")
    assert not same_address("213 W MAIN ST", "213 W STATION ST")


def test_an_address_with_no_house_number_is_unusable():
    """Nothing to anchor on, so it must refuse rather than match on the street."""
    assert address_key("W MAIN ST") is None
    assert address_key("") is None
    assert address_key(None) is None
    assert not same_address("W MAIN ST", "W MAIN ST")


# ── hop 1: which parcel, if any ─────────────────────────────────────────────────
def _stub_parcels(monkey, exact, near=()):
    """Stub the parcel layer: ``exact`` at the point, ``near`` within the buffer."""
    def fake(lat, lon, distance_m=0, *, deadline=None):
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


def test_a_translated_category_does_not_claim_a_transcribed_value_s_confidence():
    """A year built is a number the county wrote down. A wall material is the
    adapter's reading of the county's vocabulary, and Cook's single "Masonry"
    category is knowingly coarser than the label's brick/block/stone. Both are
    `observed`; they are not equally certain."""
    from housing_label.simulate import house as H
    filled = H._autofill_construction_from_nsi({}, explicit=set(),
                                               location=_loc_with(_RECORD))
    assert filled["year_built"][1] == "high"
    assert filled["sqft"][1] == "high"
    assert filled["construction"][1] == "moderate"
    assert filled["condition"][1] == "moderate"


def test_the_county_s_whole_building_area_is_not_a_units_area():
    """The county records the BUILDING's floor area; the label's sqft is per
    dwelling unit. Passing the raw figure through on a multi-unit parcel would make
    the whole building the size of one apartment and tag that "observed"."""
    from housing_label.simulate import house as H
    cfg = {}
    filled = H._autofill_construction_from_nsi(
        cfg, explicit=set(), location=_loc_with(_RECORD), units=6)
    entry = filled.get("sqft") or ()
    assert len(entry) < 3 or entry[2] != "observed", (
        "published the building's area as one unit's")
    assert cfg["year_built"] == 1881, "the other observed fields still apply"


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


def test_a_different_street_type_is_not_the_same_address():
    """"213 MAIN ST" and "213 MAIN AVE" are different houses that a corner can put
    inside one 80 m buffer. An earlier revision dropped the street type entirely
    before comparing, so both normalised to "213 MAIN" and matched."""
    assert not same_address("213 W MAIN ST", "213 W MAIN AVE")
    assert not same_address("100 OAK RD", "100 OAK BLVD")


def test_a_missing_street_type_still_matches():
    """The geocoder and the parcel layer do not always both carry the suffix, so
    absence on one side must not cost a real match — only a CONFLICT may."""
    assert same_address("213 W MAIN ST", "213 W MAIN")
    assert same_address("213 W MAIN", "213 W MAIN STREET")


def test_a_longer_street_name_is_not_the_same_street():
    """"MAIN" vs "MAIN STATION" are two streets. The old subset rule accepted them
    because one token set contained the other."""
    assert not same_address("213 W MAIN ST", "213 W MAIN STATION ST")


def test_a_containing_parcel_with_the_wrong_address_does_not_win():
    """A sole polygon under the point is not proof of anything when the point was
    interpolated: 38 m of error is wider than a city lot, so it can land inside the
    neighbour. The number must still agree, and when it does not the search widens
    rather than accepting the neighbour."""
    orig = cook_il._parcels
    try:
        _stub_parcels(_patch,
                      [{"PIN14": "01011000050000", "street_address": "209 W MAIN ST"}],
                      near=[{"PIN14": "01011000050000", "street_address": "209 W MAIN ST"},
                            {"PIN14": "01011000040000", "street_address": "213 W MAIN ST"}])
        got = cook_il._pin_at(42.154164, -88.139354, "213 W MAIN ST, BARRINGTON, IL")
        assert got == "01011000040000", "took the containing neighbour, not the address"
    finally:
        cook_il._parcels = orig


def test_an_open_ended_storey_bucket_is_not_a_storey_count():
    """"3 Story +" has no top. Recording it as exactly 3 would report a precise
    observed height for every 4- and 6-storey building in the bucket."""
    assert cook_il._STORIES.get("3 Story +") is None
    assert cook_il._STORIES["2 Story"] == 2


def test_a_record_with_nothing_in_it_is_not_a_resolved_lookup():
    """A parcel can match and still carry no usable fact: an unrecorded year and
    area, with every category outside the label's vocabulary. Both the "county
    record" tag and the published coverage rate read non-None as "the assessor
    answered", so an empty record would be counted as a parcel that contributed
    something. Unmapping "3 Story +" and "Stucco" made this reachable, so it is
    pinned. Enforced in the registry, not the adapter, so a second adapter cannot
    reintroduce it.
    """
    import housing_label.enrich.assessor as reg
    from housing_label.enrich.assessor.base import AssessorRecord

    empty = AssessorRecord(source="Cook County", data_vintage="2026",
                           parcel_id="17031000000000")
    assert empty.fields() == {}, "precondition: this record carries no attribute"

    populated = AssessorRecord(source="Cook County", data_vintage="2026",
                               parcel_id="17031000000000", year_built=1971)

    class _Stub:
        __name__ = "stub"
        returns = None

        @classmethod
        def lookup(cls, lat, lon, address=None):
            return cls.returns

    orig, fips = dict(reg.ADAPTERS), "17031"
    prev = os.environ.get(reg.ENABLE_ENV)
    try:
        os.environ[reg.ENABLE_ENV] = "1"
        reg.ADAPTERS[fips] = _Stub

        _Stub.returns = empty
        assert reg.assessor_for_point(41.9, -88.1, fips) is None, (
            "an empty record must not be reported as a resolved lookup")

        _Stub.returns = populated
        assert reg.assessor_for_point(41.9, -88.1, fips) is populated, (
            "a record with a real field must still pass through untouched")
    finally:
        reg.ADAPTERS.clear()
        reg.ADAPTERS.update(orig)
        if prev is None:
            os.environ.pop(reg.ENABLE_ENV, None)
        else:
            os.environ[reg.ENABLE_ENV] = prev


def test_a_preset_build_does_not_pay_for_an_assessor_lookup():
    """Scoring a hypothetical preset skips the construction autofill entirely, so
    a record fetched for it is discarded — two upstream hops of latency bought and
    thrown away, on a path sharing a 12-second budget with every other upstream.

    Checked against the source of build_label_parts rather than by running it,
    because exercising the real path needs network that CI does not have. That
    makes this a guard on the wiring, not the behaviour: it catches the flag being
    dropped from an existing call site, which is how this regressed once.
    """
    import inspect

    from housing_label.simulate.house import build_label_parts
    from housing_label.simulate.location import resolve_location

    params = inspect.signature(resolve_location).parameters
    assert "want_assessor" in params, "resolve_location lost its opt-out"
    assert params["want_assessor"].default is True, (
        "the opt-out must default to on; a caller that forgets it should still get "
        "the county record, not silently lose it")

    src = inspect.getsource(build_label_parts)
    resolves = src.count("resolve_location(")
    gated = src.count("want_assessor=preset is None")
    assert resolves == gated, (
        f"{resolves} resolve_location call(s) in build_label_parts but {gated} pass "
        f"want_assessor=preset is None; a preset build would fetch a county record "
        f"it then discards")


# --- end-to-end, network-free -------------------------------------------------
#
# Everything above tests a helper in isolation. None of it would notice the one
# failure mode that matters most in practice: a renamed response key, a broken PIN
# join, or a mapping applied to the wrong column. The adapter fails open, so all of
# those look identical to "this county has no record here" — the label keeps
# working and quietly stops observing anything. These drive lookup() end to end
# over recorded response shapes so that silence has to announce itself.


def _stub_transport(monkey_target, parcels, cama):
    """Replace cook_il._get with one that answers from recorded bodies."""
    def fake(url, params, deadline):
        if url == cook_il.PARCEL_URL:
            return {"features": [{"attributes": a} for a in parcels]}
        return cama
    # cook_il binds get_json into its own namespace at import, and the shared
    # parcel query is called through cook_il too, so both names are swapped.
    monkey_target.append((cook_il, cook_il.get_json))
    cook_il.get_json = fake
    monkey_target.append((_shared, _shared.get_json))
    _shared.get_json = fake


def _restore(saved):
    for module, original in saved:
        module.get_json = original


def _lookup(parcels, cama, lat=41.9, lon=-88.1, address=None):
    from housing_label.enrich.assessor import cook_il
    cook_il._lookup_cached.cache_clear()
    saved = []
    _stub_transport(saved, parcels, cama)
    try:
        return cook_il.lookup(lat, lon, address)
    finally:
        _restore(saved)
        cook_il._lookup_cached.cache_clear()


_PARCEL = {"PIN14": "17031000000000", "street_address": "213 W MAIN ST"}
_CAMA = [{"pin": "17031000000000", "char_yrblt": "1971", "char_bldg_sf": "1840",
          "char_ext_wall": "Frame", "char_bsmt": "Full",
          "char_repair_cnd": "Average", "char_type_resd": "2 Story"}]


def test_a_full_row_maps_end_to_end_into_the_labels_vocabulary():
    rec = _lookup([_PARCEL], _CAMA, address="213 W Main St")
    assert rec is not None, "a containing parcel with a matching address must resolve"
    assert rec.parcel_id == "17031000000000"
    assert rec.fields() == {
        "year_built": 1971, "sqft": 1840.0, "stories": 2,
        "construction": "frame", "foundation": "full-basement",
        "condition": "average",
    }


def test_a_renamed_response_key_does_not_pass_silently():
    """The whole point of this file: the adapter fails open, so a schema change
    reads as "no record here". Pinning the mapped output means a renamed column
    breaks a test instead of quietly turning observation off in production."""
    broken = [dict(_CAMA[0])]
    broken[0]["char_year_built"] = broken[0].pop("char_yrblt")
    rec = _lookup([_PARCEL], broken, address="213 W Main St")
    assert rec is not None
    assert "year_built" not in rec.fields(), (
        "precondition: the renamed key is not read — this test exists so that the "
        "positive test above fails loudly when that happens for real")


def test_the_record_is_dated_by_the_assessment_roll_it_came_from():
    """"Observed" without a date is half a fact: the roll advances underneath the
    same wording, so an observed value can change while its provenance string does
    not. The row carries the year the query already sorts on; it travels with it."""
    rec = _lookup([_PARCEL], [dict(_CAMA[0], year="2026")], address="213 W Main St")
    assert rec is not None and "2026 roll" in rec.data_vintage


def test_a_row_without_a_usable_year_still_produces_a_record():
    """The date is an improvement to the provenance string, not a precondition for
    reporting what the county recorded."""
    row = [{k: v for k, v in _CAMA[0].items()}]
    row[0]["year"] = ""
    rec = _lookup([_PARCEL], row, address="213 W Main St")
    assert rec is not None and rec.fields()["year_built"] == 1971
    assert "roll" not in rec.data_vintage


def test_an_unmarked_unit_suffix_does_not_block_a_condo_match():
    """The parcel layer writes "234 W STATION ST B12" with no unit marker. The
    module documented that as noise while the code kept it, so a condo failed to
    match its own address — a documented rule the implementation did not have."""
    from housing_label.enrich.assessor._shared import same_address
    assert same_address("234 W STATION ST B12", "234 W STATION ST")
    assert same_address("234 W STATION ST", "234 W STATION ST APT 4")


def test_a_digit_bearing_street_name_is_not_mistaken_for_a_unit():
    """The counterweight to the rule above: "100 ROUTE 66" ends in a digit-bearing
    token that is the street's name, not a unit. Only a digit-bearing token sitting
    directly after a street type is dropped."""
    from housing_label.enrich.assessor._shared import same_address
    assert same_address("100 ROUTE 66", "100 ROUTE 66")
    assert not same_address("100 ROUTE 66", "100 ROUTE")


def test_the_cache_key_ages_out_so_a_long_lived_worker_cannot_serve_a_stale_roll():
    """The source refreshes bi-weekly and the roll advances. A process-lifetime
    cache would pin an observed value, and its now-wrong roll date, to the worker's
    uptime; the key carries a time bucket so entries expire on their own."""
    assert _shared.CACHE_TTL_S > 0
    bucket = _shared.cache_bucket()
    assert isinstance(bucket, int)
    # The bucket must be a function of wall-clock time, not a constant, or the key
    # never changes and the TTL is decorative.
    later = int((time.time() + _shared.CACHE_TTL_S * 2) // _shared.CACHE_TTL_S)
    assert later > bucket


def test_a_pin_with_no_characteristics_row_yields_nothing():
    assert _lookup([_PARCEL], [], address="213 W Main St") is None


def test_a_zero_year_and_zero_area_are_read_as_not_recorded():
    row = [dict(_CAMA[0], char_yrblt="0", char_bldg_sf="0")]
    rec = _lookup([_PARCEL], row, address="213 W Main St")
    assert rec is not None
    assert "year_built" not in rec.fields() and "sqft" not in rec.fields(), (
        "a county zero means 'not recorded', not the year zero or a zero-area house")


def test_a_containing_parcel_whose_address_disagrees_is_not_accepted():
    """The interpolated point can land inside the neighbour's lot, so containment
    alone is not evidence. With no second candidate to fall back to, the answer is
    nothing rather than the neighbour."""
    assert _lookup([_PARCEL], _CAMA, address="209 W Main St") is None


def test_two_overlapping_parcels_are_ambiguous_rather_than_a_coin_flip():
    other = {"PIN14": "17031000000001", "street_address": "213 W MAIN ST"}
    assert _lookup([_PARCEL, other], _CAMA, address="213 W Main St") is None


# --- the request budget --------------------------------------------------------


class _FakeResponse:
    """A response that dribbles its body, the way a stalled portal does."""

    def __init__(self, chunks, pause=0.0):
        self._chunks, self._pause = chunks, pause
        self.closed = False

    def raise_for_status(self):
        pass

    def iter_content(self, _size):
        for c in self._chunks:
            yield c
            if self._pause:
                time.sleep(self._pause)

    def close(self):
        self.closed = True


def _with_fake_get(response):
    """Swap cook_il's requests for one returning `response`. Returns a restorer."""
    class _Stub:
        @staticmethod
        def get(*_a, **_k):
            return response
    original = _shared.requests
    _shared.requests = _Stub
    return lambda: setattr(_shared, "requests", original)


def test_a_dribbling_response_cannot_outlive_the_budget():
    """requests' timeout bounds the gap BETWEEN reads, not the total read. A portal
    sending one byte inside every window would otherwise hold the label open past
    the advertised budget — on a path sharing a 12-second allowance with every other
    upstream. The deadline is checked as the body arrives, so it cannot."""
    # Chunks that concatenate to VALID json, deliberately: without the in-loop
    # deadline check this test must fail on its own assertion ("a slow body must
    # hit the deadline"), not incidentally on a parse error, or it would still go
    # red after a regression while pointing at the wrong cause.
    resp = _FakeResponse([b"[1,", b"2,", b"3,", b"4,", b"5]"], pause=0.05)
    restore = _with_fake_get(resp)
    try:
        raised = None
        try:
            _shared.get_json("http://x", {}, time.monotonic() + 0.06)
        except TimeoutError as exc:
            raised = exc
        assert raised is not None, "a slow body must hit the deadline, not run on"
        assert "reading" in str(raised), f"unexpected message: {raised}"
        assert resp.closed, "the connection must be released, not leaked"
    finally:
        restore()


def test_a_response_that_arrives_in_time_is_parsed_normally():
    """The counterweight: the deadline check must not break the ordinary path."""

    restore = _with_fake_get(_FakeResponse([b'[{"pin":', b'"17031"}]']))
    try:
        assert _shared.get_json("http://x", {}, time.monotonic() + 5) == [{"pin": "17031"}]
    finally:
        restore()


def test_no_single_read_may_block_longer_than_the_slice():
    """Streaming alone does not make the budget wall-clock: the deadline check can
    only run once a chunk has ARRIVED, so a gap shorter than the read timeout but
    longer than the remaining budget would be waited out in full and overshoot by
    nearly the whole budget. Capping the READ half of the timeout bounds any single
    stall, and therefore the overshoot, to the slice.

    The connect half deliberately keeps the full remainder — a slow handshake is the
    one wait that cannot be broken into slices.
    """
    from housing_label.enrich.assessor import _shared

    seen = {}

    class _Stub:
        @staticmethod
        def get(*_a, **kw):
            seen["timeout"] = kw.get("timeout")
            return _FakeResponse([b"[]"])

    original = _shared.requests
    _shared.requests = _Stub
    try:
        _shared.get_json("http://x", {}, time.monotonic() + 30)
    finally:
        _shared.requests = original

    timeout = seen["timeout"]
    assert isinstance(timeout, tuple), "a scalar timeout applies to reads too"
    connect, read = timeout
    assert read <= _shared._READ_SLICE_S, f"read timeout {read} exceeds the slice"
    assert connect > _shared._READ_SLICE_S, (
        "the connect half should keep the remaining budget, not the slice")


def test_the_slice_never_outlives_what_is_left_of_the_budget():
    """With almost no budget left, the slice must shrink to it rather than grant a
    fresh second — otherwise the last hop of three could overrun on its own."""
    from housing_label.enrich.assessor import _shared

    seen = {}

    class _Stub:
        @staticmethod
        def get(*_a, **kw):
            seen["timeout"] = kw.get("timeout")
            return _FakeResponse([b"[]"])

    original = _shared.requests
    _shared.requests = _Stub
    try:
        _shared.get_json("http://x", {}, time.monotonic() + 0.2)
    finally:
        _shared.requests = original

    connect, read = seen["timeout"]
    assert read <= 0.2 and connect <= 0.2


def test_an_empty_body_is_a_failure_not_an_answer():
    """A 200 with no body is a portal glitch. Parsed as `null` it flows on as "no
    parcels here" and is CACHED as absence for the bucket's lifetime, so a
    momentary upstream blip would suppress the county record for six hours. It has
    to stay on the fail-open path, where nothing is cached."""
    restore = _with_fake_get(_FakeResponse([b"", b"   "]))
    try:
        raised = None
        try:
            _shared.get_json("http://x", {}, time.monotonic() + 5)
        except RuntimeError as exc:
            raised = exc
        assert raised is not None and "empty response" in str(raised)
    finally:
        restore()


def test_an_implausibly_large_body_is_refused_rather_than_read_to_the_end():
    """These responses are one row or a few parcels. Something orders of magnitude
    bigger is a misrouted query or an error page, and reading it would spend the
    budget on something that cannot be an answer."""

    oversize = [b"x" * _shared._CHUNK_BYTES] * (_shared._MAX_BYTES // _shared._CHUNK_BYTES + 2)
    restore = _with_fake_get(_FakeResponse(oversize))
    try:
        raised = None
        try:
            _shared.get_json("http://x", {}, time.monotonic() + 30)
        except RuntimeError as exc:
            raised = exc
        assert raised is not None and "exceeded" in str(raised)
    finally:
        restore()


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
