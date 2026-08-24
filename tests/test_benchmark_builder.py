#!/usr/bin/env python3
"""A drawn parcel reaches the benchmark, or the build stops and says why.

Why this exists
---------------
``scripts/build_benchmark.py`` needs network for every row, so what it *builds*
is checked by hand. What can be checked offline is the one property the whole
measurement rests on: **the only reason a drawn parcel may be absent from the
written benchmark is that the assessor's own record is unusable.** Every other
absence — an offset that did not answer, a batch request that never landed, a
row carrying no parcel identifier — must stop the build.

That property is worth pinning rather than reviewing, because breaking it is
invisible downstream. An evenly spaced draw with a slice deleted from it is
still a well-formed CSV with a real digest and plausible rates; it reads as a
smaller clean sample rather than a biased one, and the published page then
attributes the missing rows to gaps in the assessor's documentation — the wrong
cause, on a page whose whole purpose is stating causes accurately.

Three review rounds found three instances of exactly that failure at three
different layers, each fixed where it was found. These tests state the rule for
both jurisdictions at once, so the next layer inherits it instead of repeating
the round.

The complement matters just as much and is tested beside it: a batch that comes
back *short* is not a failure. Those parcels really are missing from the layer,
and turning that into a fatal error would make the build unrunnable for an
honest data gap.

No network — ``_fetch`` is replaced throughout.

Run standalone: ``python tests/test_benchmark_builder.py``
"""

from __future__ import annotations

import contextlib
import sys
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import scripts.build_benchmark as B  # noqa: E402


@contextlib.contextmanager
def _fetching(fn):
    """Swap the module's single network entry point for the duration."""
    original = B._fetch
    B._fetch = fn
    try:
        yield
    finally:
        B._fetch = original


def _refuses(fn) -> str:
    """Run `fn`, requiring it to stop the build. Returns the message."""
    try:
        fn()
    except SystemExit as exc:
        return str(exc)
    raise AssertionError(
        "the build continued. A request that never landed was folded into the "
        "sample as an absence, which is the one thing this file exists to stop.")


# --- the shared batch rule ----------------------------------------------------

def test_the_batch_helper_reads_both_portal_shapes():
    """Socrata answers with a list, ArcGIS with a dict carrying `features`. One
    helper has to understand both or one jurisdiction silently loses its guard."""
    with _fetching(lambda url, params: [{"pin": "1"}]):
        assert B._batch_or_die("u", {}, "x", 1) == [{"pin": "1"}]
    with _fetching(lambda url, params: {"features": [{"attributes": {}}]}):
        assert B._batch_or_die("u", {}, "x", 1) == [{"attributes": {}}]


def test_an_exhausted_batch_stops_the_build():
    """The message has to name the stage and the size, because this stops a build
    someone is watching and the next move depends on which request died."""
    with _fetching(lambda url, params: None):
        msg = _refuses(lambda: B._batch_or_die("u", {}, "card lookup", 40))
    assert "card lookup" in msg and "40" in msg, msg


def test_an_arcgis_error_body_is_not_a_successful_batch():
    """ArcGIS reports failure inside a 200, sometimes alongside rows. Trusting
    the row list would accept a partial answer as a complete one."""
    body = {"error": {"code": 500}, "features": [{"attributes": {"SSL": "1"}}]}
    with _fetching(lambda url, params: body):
        _refuses(lambda: B._batch_or_die("u", {}, "parcel lookup", 40))


def test_an_empty_batch_stops_the_build():
    for empty in ([], {"features": []}, {}):
        with _fetching(lambda url, params, e=empty: e):
            _refuses(lambda: B._batch_or_die("u", {}, "parcel lookup", 40))


# --- the rule as the callers actually use it ----------------------------------

def test_a_dead_batch_stops_cooks_card_lookup():
    with _fetching(lambda url, params: None):
        _refuses(lambda: B._primary_cards("2024", ["1" * 14]))


def test_a_dead_batch_stops_cooks_parcel_lookup():
    with _fetching(lambda url, params: None):
        _refuses(lambda: B._parcel_info(["1" * 14]))


def test_a_dead_batch_stops_dcs_parcel_lookup():
    with _fetching(lambda url, params: None):
        _refuses(lambda: B._dc_place(["1234    0056"]))


def test_a_short_batch_is_not_a_failure():
    """The legitimate gap: asked about two parcels, the layer holds one. That is
    what the drawn-versus-sampled figure is for, and it must not be fatal."""
    body = {"features": [{"attributes": {
        "PIN14": "1" * 14, "street_address": "1 MAIN ST",
        "city_state_zip": "CHICAGO IL 60601", "latitude": 41.0, "longitude": -87.0}}]}
    with _fetching(lambda url, params: body):
        got = B._parcel_info(["1" * 14, "2" * 14])
    assert list(got) == ["1" * 14], got


# --- an offset that answers with nothing usable -------------------------------

def _cook_portal(pin_for_offset):
    """A Socrata stand-in: sizes the table, then answers offset queries."""
    def fetch(url, params):
        if params.get("$select") == "count(*)":
            return [{"count": "1000"}]
        if params.get("$select") == "pin":
            row = pin_for_offset(params.get("$offset"))
            return None if row is None else [row]
        return [{"pin": "1" * 14, "card": "1", "char_yrblt": "1990"}]
    return fetch


def test_a_cook_row_with_no_pin_is_an_offset_that_did_not_answer():
    """A PIN is how a sampled row is looked up. A row without one cannot enter
    the draw, so it is the portal failing — not a parcel that has no PIN."""
    with _fetching(_cook_portal(lambda off: {"pin": ""})):
        msg = _refuses(lambda: B._cama_sample("2024", 3))
    assert "never answered" in msg, msg


def test_a_cook_offset_that_recovers_on_retry_is_not_fatal():
    """Retried once before the build gives up, so a blip does not cost a run."""
    tries: dict[str, int] = {}

    def pin(off):
        tries[off] = tries.get(off, 0) + 1
        return None if tries[off] == 1 else {"pin": str(off).zfill(14)}

    with _fetching(_cook_portal(pin)):
        cards, draw = B._cama_sample("2024", 3)
    assert draw["attempted"] == 3, draw
    assert all(n == 2 for n in tries.values()), tries


def test_a_repeated_cook_pin_is_deduplicated_not_retried():
    """The table has a row per card, so two offsets can land on one parcel. That
    is the intended collapse, and must not read as an offset that failed."""
    with _fetching(_cook_portal(lambda off: {"pin": "1" * 14})):
        cards, draw = B._cama_sample("2024", 3)
    assert draw["attempted"] == 1, draw


def _dc_portal(attrs_for_offset):
    def fetch(url, params):
        if params.get("returnCountOnly") == "true":
            return {"count": 1000}
        a = attrs_for_offset(params.get("resultOffset"))
        return {} if a is None else {"features": [{"attributes": a}]}
    return fetch


def test_a_dc_row_with_no_ssl_is_an_offset_that_did_not_answer():
    with _fetching(_dc_portal(lambda off: {"SSL": "  ", "AYB": 1920})):
        msg = _refuses(lambda: B._dc_sample(3))
    assert "never answered" in msg, msg


def test_a_dc_offset_that_recovers_on_retry_is_not_fatal():
    tries: dict[str, int] = {}

    def attrs(off):
        tries[off] = tries.get(off, 0) + 1
        return None if tries[off] == 1 else {"SSL": f"{off} 0001", "AYB": 1920}

    with _fetching(_dc_portal(attrs)):
        rows, draw = B._dc_sample(3)
    assert draw["attempted"] == 3, draw


def test_both_samplers_refuse_the_same_answers():
    """The two have drifted apart twice — once on an empty 200, once on a row
    with no identifier — and each time one jurisdiction quietly tolerated what
    the other rejected. Pin the parity rather than the two behaviours."""
    cook = (_cook_portal, lambda: B._cama_sample("2024", 2),
            {"nothing": lambda off: None, "no identifier": lambda off: {"pin": ""}})
    dc = (_dc_portal, lambda: B._dc_sample(2),
          {"nothing": lambda off: None, "no identifier": lambda off: {"SSL": ""}})
    for portal, build, answers in (cook, dc):
        for kind, answer in answers.items():
            with _fetching(portal(answer)):
                msg = _refuses(build)
            assert "never answered" in msg, (kind, msg)


# --- a coordinate the harness never reads must not drop a good parcel ----------


def test_a_parcel_with_no_coordinates_still_reaches_the_benchmark():
    """lat/lon are carried for inspection only — the harness geocodes the address,
    exactly as a visitor would. Requiring them dropped rows whose address and year
    were fine, and the published note then reported those as records the assessor
    never documented: a real row, blamed on the wrong party."""
    body = {"features": [{"attributes": {
        "PIN14": "1" * 14, "street_address": "1 MAIN ST",
        "city_state_zip": "CHICAGO IL 60601", "latitude": None, "longitude": None}}]}
    with _fetching(lambda url, params: body):
        got = B._parcel_info(["1" * 14])
    assert list(got) == ["1" * 14], got
    assert got["1" * 14]["address"] == "1 MAIN ST, CHICAGO IL 60601"
    assert got["1" * 14]["lat"] == "" and got["1" * 14]["lon"] == ""


def test_a_parcel_with_no_address_is_still_dropped():
    """The one legitimate absence: no address means nothing to geocode."""
    body = {"features": [{"attributes": {"PIN14": "1" * 14, "street_address": ""}}]}
    with _fetching(lambda url, params: body):
        assert B._parcel_info(["1" * 14]) == {}


def test_both_scripts_read_one_jurisdiction_registry():
    """They kept the list twice, so a third adapter would be accepted by one script
    and unknown to the other — and that only shows up in the measurement."""
    import scripts.measure_accuracy as M
    assert set(M.LABELS) == set(B.JURISDICTIONS)
    for key, cfg in B.JURISDICTIONS.items():
        assert M.LABELS[key] == cfg["label"]


def test_a_registered_jurisdiction_with_no_sampler_fails_rather_than_drawing_dc():
    """The CLI takes its choices from the registry, so a third entry is selectable
    the moment it is added — before anyone writes its sampler. A bare `else` ran
    DC's, writing DC parcels under the new name with the new name stamped on the
    metadata: a fabricated benchmark, indistinguishable downstream from a real one.

    Asserted on the source rather than by running main(), which needs network: the
    dispatch must name each jurisdiction explicitly and end in a refusal.
    """
    src = pathlib.Path(B.__file__).read_text()
    dispatch = src[src.index('    if juris == "cook":'):src.index('    log.info("Fetched')]
    assert 'elif juris == "dc":' in dispatch, (
        "the DC branch must be explicit; a bare `else` claims every future "
        "jurisdiction and draws DC for it")
    assert "raise SystemExit" in dispatch, (
        "the dispatch must refuse a registered jurisdiction it has no sampler for")
    for key in B.JURISDICTIONS:
        assert f'juris == "{key}"' in dispatch, (
            f"{key} is registered but the builder's dispatch does not name it, so "
            f"it would fall through to the refusal or to another jurisdiction's draw")


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
