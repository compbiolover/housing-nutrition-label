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

#: Any fixed value. These tests assert refusals and shapes, never the draw.
SEED = 20260825


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
        got, present = B._parcel_info(["1" * 14, "2" * 14])
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
        # A card for each PIN the caller actually asked about. Returning a fixed
        # one made this stub the very truncated response _primary_cards now
        # refuses — the stub has to answer the query, not a query.
        import re
        asked = re.findall(r"'([^']+)'", params.get("$where", ""))[1:]
        return [{"pin": q, "card": "1", "char_yrblt": "1990"} for q in asked]
    return fetch


def test_a_cook_row_with_no_pin_is_an_offset_that_did_not_answer():
    """A PIN is how a sampled row is looked up. A row without one cannot enter
    the draw, so it is the portal failing — not a parcel that has no PIN."""
    with _fetching(_cook_portal(lambda off: {"pin": ""})):
        msg = _refuses(lambda: B._cama_sample("2024", 3, SEED))
    assert "never answered" in msg, msg


def test_a_cook_offset_that_recovers_on_retry_is_not_fatal():
    """Retried once before the build gives up, so a blip does not cost a run."""
    tries: dict[str, int] = {}

    def pin(off):
        tries[off] = tries.get(off, 0) + 1
        return None if tries[off] == 1 else {"pin": str(off).zfill(14)}

    with _fetching(_cook_portal(pin)):
        cards, draw = B._cama_sample("2024", 3, SEED)
    assert draw["attempted"] == 3, draw
    assert all(n == 2 for n in tries.values()), tries


def test_a_repeated_cook_pin_is_deduplicated_not_retried():
    """The table has a row per card, so two offsets can land on one parcel. That
    is the intended collapse, and must not read as an offset that failed."""
    with _fetching(_cook_portal(lambda off: {"pin": "1" * 14})):
        cards, draw = B._cama_sample("2024", 3, SEED)
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
        msg = _refuses(lambda: B._dc_sample(3, SEED))
    assert "never answered" in msg, msg


def test_a_dc_offset_that_recovers_on_retry_is_not_fatal():
    tries: dict[str, int] = {}

    def attrs(off):
        tries[off] = tries.get(off, 0) + 1
        return None if tries[off] == 1 else {"SSL": f"{off} 0001", "AYB": 1920}

    with _fetching(_dc_portal(attrs)):
        rows, draw = B._dc_sample(3, SEED)
    assert draw["attempted"] == 3, draw


def test_both_samplers_refuse_the_same_answers():
    """The two have drifted apart twice — once on an empty 200, once on a row
    with no identifier — and each time one jurisdiction quietly tolerated what
    the other rejected. Pin the parity rather than the two behaviours."""
    cook = (_cook_portal, lambda: B._cama_sample("2024", 2, SEED),
            {"nothing": lambda off: None, "no identifier": lambda off: {"pin": ""}})
    dc = (_dc_portal, lambda: B._dc_sample(2, SEED),
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
        got, present = B._parcel_info(["1" * 14])
    assert list(got) == ["1" * 14], got
    assert got["1" * 14]["address"] == "1 MAIN ST, CHICAGO IL 60601"
    assert got["1" * 14]["lat"] == "" and got["1" * 14]["lon"] == ""


def test_a_parcel_with_no_address_is_still_dropped():
    """The one legitimate absence: no address means nothing to geocode."""
    body = {"features": [{"attributes": {"PIN14": "1" * 14, "street_address": ""}}]}
    with _fetching(lambda url, params: body):
        assert B._parcel_info(["1" * 14])[0] == {}


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


def test_a_card_lookup_that_omits_a_requested_pin_fails_the_build():
    """Short answers are legitimate for the parcel-layer joins and not here. Every
    PIN in the chunk was returned by this same table for this same year moments
    ago, so each provably has a card; a missing one is a truncated response, and
    it would vanish from the sample and publish as a house with no address."""
    def fetch(url, params):
        asked = __import__("re").findall(r"'([^']+)'", params.get("$where", ""))[1:]
        return [{"pin": q, "card": "1"} for q in asked[:-1]]     # one short
    with _fetching(fetch):
        msg = _refuses(lambda: B._primary_cards("2024", ["1" * 14, "2" * 14]))
    assert "truncated" in msg, msg


def test_a_parcel_layer_gap_is_still_allowed_to_be_short():
    """The complement, so the distinction is pinned rather than remembered: these
    parcels really can be missing from the layer, and making that fatal would break
    the build for an honest data gap."""
    body = {"features": [{"attributes": {
        "PIN14": "1" * 14, "street_address": "1 MAIN ST",
        "city_state_zip": "CHICAGO IL 60601"}}]}
    with _fetching(lambda url, params: body):
        got, present = B._parcel_info(["1" * 14, "2" * 14])
    assert list(got) == ["1" * 14], got


def test_arcgis_saying_it_truncated_is_not_a_short_batch():
    """`exceededTransferLimit` rides along with a well-formed, non-empty feature
    list. It is the one truncation the portal actually announces, so accepting it
    as a legitimately short batch was the cheapest possible miss."""
    body = {"exceededTransferLimit": True,
            "features": [{"attributes": {"SSL": "1234 0056", "PREMISEADD": "1 A ST"}}]}
    with _fetching(lambda url, params: body):
        _refuses(lambda: B._dc_place(["1234 0056", "1234 0057"]))


def test_a_parcel_feature_with_no_join_key_stops_the_build():
    """The query is keyed by the identifier, so a feature returned without one
    cannot be joined. Skipping it made the parcel vanish and publish as a house the
    assessor never documented — blamed for a malformed response."""
    cook = {"features": [{"attributes": {"street_address": "1 MAIN ST"}}]}
    with _fetching(lambda url, params: cook):
        _refuses(lambda: B._parcel_info(["1" * 14]))
    dc = {"features": [{"attributes": {"PREMISEADD": "1 A ST NW"}}]}
    with _fetching(lambda url, params: dc):
        _refuses(lambda: B._dc_place(["1234 0056"]))


def test_a_parcel_with_a_key_but_no_address_is_still_a_plain_drop():
    """The complement: a parcel that really has no address on file is a legitimate
    `no_address`, not a malformed response. The two must not collapse together."""
    dc = {"features": [{"attributes": {"SSL": "1234 0056", "PREMISEADD": ""}}]}
    with _fetching(lambda url, params: dc):
        assert B._dc_place(["1234 0056"])[0] == {}


def test_a_parcel_identifier_outside_the_requested_batch_stops_the_build():
    """The query is an IN over the chunk, so an identifier outside it means the
    filter was ignored or a stale response was served. Storing it leaves every
    requested parcel looking absent — a whole batch published as houses with no
    address, from a response that never answered the question asked."""
    cook = {"features": [{"attributes": {
        "PIN14": "9" * 14, "street_address": "9 OTHER ST"}}]}
    with _fetching(lambda url, params: cook):
        msg = _refuses(lambda: B._parcel_info(["1" * 14]))
    assert "not in the batch" in msg, msg
    dc = {"features": [{"attributes": {"SSL": "9999 0001", "PREMISEADD": "9 X ST"}}]}
    with _fetching(lambda url, params: dc):
        msg = _refuses(lambda: B._dc_place(["1234 0056"]))
    assert "not in the batch" in msg, msg


def test_a_whitespace_only_address_is_not_an_address():
    """Cook tested the raw field for truthiness while DC stripped first — the
    fourth Cook/DC drift in this file. A whitespace address was written as a
    sampled row the scorer cannot geocode, counted as neither kept nor dropped."""
    body = {"features": [{"attributes": {
        "PIN14": "1" * 14, "street_address": "   ",
        "city_state_zip": "CHICAGO IL 60601"}}]}
    with _fetching(lambda url, params: body):
        assert B._parcel_info(["1" * 14])[0] == {}


def test_a_paged_offset_read_is_not_a_truncated_batch():
    """`exceededTransferLimit` means "more records match than were returned".

    The offset sampler asks for ONE row on purpose — it is a paged read of a
    109,273-row table — so ArcGIS sets that flag on every healthy response.
    `_batch_or_die` gives no page size, expects the whole matching set, and there
    the same flag really does mean a truncated answer.

    The asymmetry is pinned because it does not look like one: adding the check to
    the sampler "for consistency" rejected all six offsets of a live build, and the
    next person to notice the difference will be tempted to make it uniform again.
    """
    body = {"exceededTransferLimit": True,
            "features": [{"attributes": {"SSL": "1234 0056", "AYB": 1920}}]}

    def fetch(url, params):
        if params.get("returnCountOnly") == "true":
            return {"count": 1000}
        return body

    with _fetching(fetch):
        rows, draw = B._dc_sample(2, SEED)
    assert draw["attempted"] == 1, draw

    # ...while the batch helper must still refuse exactly that response.
    with _fetching(lambda url, params: body):
        _refuses(lambda: B._batch_or_die("u", {}, "parcel lookup", 40))


def test_the_join_reports_which_parcels_the_layer_actually_held():
    """"Absent from the layer" and "present with no address" are different facts
    about the assessor, and both used to leave the same trace — no entry in the
    returned map — so the build reported every addressless parcel as one the layer
    had never heard of. Splitting the drop REASONS without making the DATA carry
    the distinction only relabelled the misattribution, and left `no_address` a
    branch that could never be taken.
    """
    body = {"features": [{"attributes": {
        "PIN14": "1" * 14, "street_address": "",              # held, no address
        "city_state_zip": "CHICAGO IL 60601"}}]}
    with _fetching(lambda url, params: body):
        out, present = B._parcel_info(["1" * 14, "2" * 14])
    assert out == {}, "a parcel with no address is still not usable"
    assert "1" * 14 in present, "the layer held it; the build must be able to say so"
    assert "2" * 14 not in present, "the layer never returned this one"

    dc = {"features": [{"attributes": {"SSL": "1234 0056", "PREMISEADD": "  "}}]}
    with _fetching(lambda url, params: dc):
        out, present = B._dc_place(["1234 0056", "9999 0001"])
    assert out == {} and present == {"1234 0056"}


def test_a_body_that_is_not_a_list_of_rows_is_not_a_batch():
    """`{"features": "oops"}` made `rows` a non-empty string, which passed every
    guard and reached the callers as characters to call .get() on — an
    AttributeError deep inside a join instead of the stated refusal this helper
    exists to give. A malformed body is a portal that did not answer."""
    for bad in ({"features": "oops"}, {"features": [1, 2]}, "text", 7,
                {"features": [{"ok": 1}, "not a row"]}):
        with _fetching(lambda url, params, b=bad: b):
            _refuses(lambda: B._batch_or_die("u", {}, "parcel lookup", 40))
    # A well-formed batch still passes.
    with _fetching(lambda url, params: {"features": [{"attributes": {}}]}):
        assert B._batch_or_die("u", {}, "x", 1) == [{"attributes": {}}]


def test_a_malformed_offset_body_is_a_failed_offset_not_a_crash():
    """`{"features": "oops"}` made `feats` a non-empty string and feats[0].get()
    raised AttributeError — an incidental crash where this sampler's whole design
    is to retry an offset and then fail closed with a message about the draw."""
    def fetch(url, params):
        if params.get("returnCountOnly") == "true":
            return {"count": 1000}
        return {"features": "oops"}

    with _fetching(fetch):
        msg = _refuses(lambda: B._dc_sample(2, SEED))
    assert "never answered" in msg, msg


def test_an_unusable_rows_argument_costs_no_request_in_either_jurisdiction():
    """Cook resolved the assessment year FIRST, so --rows 0 made a live portal
    request before being told the argument was unusable — the docstring promised
    otherwise and the DC path honoured it while Cook did not."""
    calls = []

    def fetch(url, params):
        calls.append(url)
        return None

    for juris in sorted(B.JURISDICTIONS):
        calls.clear()
        argv = sys.argv
        sys.argv = ["build_benchmark.py", "--jurisdiction", juris,
                    "--rows", "0", "--seed", str(SEED)]
        try:
            with _fetching(fetch):
                B.main()
        except SystemExit as exc:
            assert "--rows must be at least 1" in str(exc), (juris, str(exc))
        else:
            raise AssertionError(f"{juris}: --rows 0 was accepted")
        finally:
            sys.argv = argv
        assert not calls, f"{juris}: {len(calls)} request(s) made before rejecting"


def test_every_parse_point_agrees_on_what_a_response_is():
    """Each parse point had its own idea of a response shape, and each crashed on
    one the others had already learned to reject: `(body or {}).get("features")`
    raises on a JSON list, `got[0]` raises on an error object, and a feature whose
    `attributes` is a string passes an isinstance check then raises one .get()
    later. All of them promise to retry the offset and fail closed instead."""
    malformed = ("text", 7, {"features": "oops"}, {"features": [1]},
                 {"features": [{"attributes": "oops"}]}, ["not a row"], None)
    for body in malformed:
        assert B._rows_of(body) is None, body

    # An EMPTY list is well-formed, not malformed: the portal answered with no
    # rows. Whether that is acceptable is the caller's question, and each one
    # already answers it — the batch helper refuses it, the samplers retry it.
    assert B._rows_of([]) == []
    assert B._rows_of({"features": []}) == []
    assert B._rows_of([{"pin": "1"}]) == [{"pin": "1"}]
    assert B._rows_of({"features": [{"attributes": {"SSL": "1"}}]}) == [
        {"attributes": {"SSL": "1"}}]


#: How each sampler asks for its table's row count, how a healthy portal answers,
#: and the shapes an unhealthy one produces. The bad bodies are per jurisdiction on
#: purpose: Socrata answers with a LIST of row dicts and ArcGIS with a single
#: object, so feeding one shape to both tests a branch the other portal can never
#: reach. That is exactly how [{"count": "oops"}] — the real Cook shape — went
#: unexercised while the test appeared to cover Cook: it was handed {"count":
#: "oops"}, which Cook rejects one branch earlier for not being a list at all.
_SIZING = {
    "cook": {
        "is_count": lambda params: params.get("$select") == "count(*)",
        "healthy": [{"count": "1000"}],
        "unhealthy": ([{"count": "oops"}], [{"count": None}], [{"nope": 1}], [],
                      [1], "text", None, {"error": {"code": 400}}),
    },
    "arcgis": {
        "is_count": lambda params: params.get("returnCountOnly") == "true",
        "healthy": {"count": 1000},
        "unhealthy": ({"count": "oops"}, {"count": None}, {}, "text", None,
                      {"error": {"code": 400}}, [{"count": 1000}]),
    },
}


def _sizing(juris):
    """The count-request predicate and a healthy count body for this sampler."""
    cfg = _SIZING["cook" if juris == "cook" else "arcgis"]
    return cfg["is_count"], cfg["healthy"]


def _unhealthy(juris):
    """Count bodies this jurisdiction's own portal could actually return."""
    return _SIZING["cook" if juris == "cook" else "arcgis"]["unhealthy"]


#: Every offset sampler, by name, so a fourth cannot quietly skip the rules below.
#: Naming two of the three was how the condominium sampler was written exempt from
#: a refusal the other two had: the test said "both samplers" and meant the two
#: that existed when it was written.
SAMPLERS = {
    "cook": lambda n: B._cama_sample("2024", n, SEED),
    "dc": lambda n: B._dc_sample(n, SEED),
    "dc-condo": lambda n: B._dc_condo_sample(n, SEED),
}


def test_every_sampler_is_covered_by_the_sampler_rules():
    """The roster below must name every jurisdiction the registry offers. A
    jurisdiction added to one and not the other is a sampler with no guards."""
    assert set(SAMPLERS) == set(B.JURISDICTIONS), (
        f"registry has {sorted(B.JURISDICTIONS)}, SAMPLERS has {sorted(SAMPLERS)}")


def test_a_malformed_body_is_a_failed_offset_in_every_sampler():
    for body in ({"features": [{"attributes": "oops"}]}, ["not a row"], "text"):
        for juris, sample in SAMPLERS.items():
            is_count, count_body = _sizing(juris)

            def fetch(url, params, b=body, ic=is_count, cb=count_body):
                return cb if ic(params) else b

            with _fetching(fetch):
                assert "never answered" in _refuses(lambda s=sample: s(2)), (juris, body)


def test_a_genuinely_empty_table_is_reported_as_empty_not_as_a_failure():
    """The complement, and the reason the check above is not simply "it refused":
    a real zero IS an empty table, and must not be reported as a portal problem.

    The two jurisdictions word this differently and that is recorded here rather
    than smoothed over. Cook can plausibly be asked about an assessment year that
    has no rows yet, so it says so. The DC tables are the whole city's stock and a
    zero from them means the service answered with something unusable, so they
    fold it into the sizing refusal. Both refuse; neither invents a fact about the
    assessor's records, which is the property that matters."""
    with _fetching(lambda url, params: [{"count": "0"}]):
        assert "no rows" in _refuses(lambda: B._cama_sample("2024", 2, SEED))
    for sample in (B._dc_sample, B._dc_condo_sample):
        with _fetching(lambda url, params: {"count": 0}):
            assert "could not size" in _refuses(lambda s=sample: s(2, SEED))


def test_an_unsizeable_table_stops_every_sampler_before_it_draws():
    """A count that is not a number is the portal changing shape, not a table with
    no rows. Reaching int() on it raised ValueError past the stated refusal."""
    for juris, sample in SAMPLERS.items():
        is_count, _ = _sizing(juris)
        for bad in _unhealthy(juris):
            def fetch(url, params, b=bad, ic=is_count):
                return b if ic(params) else {"features": []}

            # `_refuses` already pins the important half — a SystemExit rather
            # than a KeyError or ValueError escaping from the parse. The wording
            # is each jurisdiction's own and is only checked loosely, so this
            # test stays about the refusal rather than about the sentence.
            #
            # But it must be a SIZING refusal. Cook reported [{"count": "oops"}]
            # as "no rows for assessment year 2024" — a claim about the county's
            # records drawn from a response that said nothing about them, and the
            # one diagnosis that sends a reader looking in the wrong place.
            with _fetching(fetch):
                message = _refuses(lambda s=sample: s(2)).lower()
            assert "size" in message, (juris, bad, message)
            assert "no rows" not in message, (juris, bad, message)


# --- the condominium join -------------------------------------------------------
#
# A different join from the parcel one: the sample comes from the condominium CAMA
# table and is placed through the unit index, which is the only keyless
# address-and-unit edge the District publishes.


def _unit_row(ssl, addr="2123 CALIFORNIA STREET NW", unit="D7"):
    return {"attributes": {"CONDO_SSL": ssl, "PRIMARY_ADDRESS": addr,
                           "UNIT_NUMBER": unit}}


def test_a_condo_row_is_placed_at_its_own_unit_address():
    """The unit is the whole point. Without it every unit in the building is the
    same address, and the benchmark would grade eight homes against one."""
    with _fetching(lambda url, params: {"features": [_unit_row("2528    2029")]}):
        out, present = B._dc_condo_place(["2528    2029"])
    assert present == {"2528    2029"}
    assert out["2528    2029"]["address"] == \
        "2123 CALIFORNIA STREET NW #D7, Washington, DC"


def test_one_ssl_with_two_addresses_is_dropped_not_resolved():
    """Two live rows, two addresses, one SSL. Picking either would put a confident
    guess into the yardstick itself — the same refusal the adapter makes from the
    other direction."""
    rows = [_unit_row("2528    2029"),
            _unit_row("2528    2029", addr="2125 CALIFORNIA STREET NW")]
    with _fetching(lambda url, params: {"features": rows}):
        out, present = B._dc_condo_place(["2528    2029"])
    assert "2528    2029" in present      # the index did know it...
    assert "2528    2029" not in out      # ...and it still cannot be placed


def test_a_unit_index_row_with_no_unit_number_is_not_a_building_address():
    """Dropping the marker would leave the bare street address, which resolves to
    whichever unit the lookup happened to pick — the confident wrong answer."""
    with _fetching(lambda url, params: {
            "features": [_unit_row("2528    2029", unit="")]}):
        out, _ = B._dc_condo_place(["2528    2029"])
    assert out == {}


def test_a_condo_ssl_the_index_does_not_carry_is_a_missing_record():
    """A condominium SSL with no ACTIVE unit row is an honest gap, not a failure:
    the ACTIVE filter is part of the question. It must not stop the build."""
    with _fetching(lambda url, params: {"features": []}):
        out, present = B._dc_condo_place(["2528    2029"])
    assert out == {} and present == set()


def test_the_unit_index_failing_is_not_a_city_with_no_records():
    """A batch that errors would otherwise mark every SSL in it undocumented — a
    claim about the District's records made from a failed request."""
    for body in (None, {"error": {"code": 500}}):
        with _fetching(lambda url, params, b=body: b):
            assert "did not answer" in _refuses(
                lambda: B._dc_condo_place(["2528    2029"]))


def test_the_index_answering_about_a_different_unit_is_refused():
    """A row outside the requested batch means the response is not an answer to
    this query — the same guard the two parcel joins carry."""
    with _fetching(lambda url, params: {"features": [_unit_row("9999    9999")]}):
        assert "not in the batch" in _refuses(
            lambda: B._dc_condo_place(["2528    2029"]))


def test_the_condo_truth_leaves_blank_what_its_table_does_not_record():
    """The condominium table has no wall, storey, basement or condition column.
    Borrowing them from the building the unit sits in would grade the adapter
    against a different structure's record."""
    truth = B._dc_condo_truth({"SSL": "2528    2029", "AYB": 1911.0,
                               "LIVING_GBA": 680.0})
    assert truth["year_built"] == 1911
    assert truth["sqft"] == 680.0
    assert truth["stories"] == truth["construction"] == ""
    assert truth["foundation"] == truth["condition"] == ""


def test_a_condo_row_with_no_usable_year_is_ungradeable():
    """Same rule as the other two jurisdictions: with no year there is nothing to
    be right or wrong about, so the row is dropped and counted."""
    for bad in ({"AYB": None}, {"AYB": 0}, {"AYB": 1200}, {"AYB": "oops"}, {}):
        assert B._dc_condo_truth(dict(bad, LIVING_GBA=680.0)) is None, bad


# --- the draw --------------------------------------------------------------------
#
# The published rates carry confidence intervals, and an interval is a claim about
# how the rows were chosen. These pin that claim.


def test_the_draw_is_random_not_a_stride():
    """The old sampler walked a fixed stride over a PIN- or SSL-ordered table. Both
    orderings are geographic, so repeated draws differed only in where the stride
    began and under-represented their own spread — while a binomial interval was
    published beside them, which assumes independent draws."""
    off = B._draw_offsets(100_000, 40, 7)
    gaps = {off[i + 1] - off[i] for i in range(len(off) - 1)}
    assert len(gaps) > 1, f"offsets are evenly spaced: {sorted(gaps)}"


def test_the_same_seed_draws_the_same_sample():
    """A rate is published beside the seed that produced it, so the seed has to be
    enough to reproduce the draw exactly."""
    assert B._draw_offsets(50_000, 30, 99) == B._draw_offsets(50_000, 30, 99)


def test_different_seeds_draw_different_samples():
    """Replicates exist to expose run-to-run spread. Two replicates that quietly
    drew the same rows would report a spread of zero and call it stability."""
    assert B._draw_offsets(50_000, 30, 1) != B._draw_offsets(50_000, 30, 2)


def test_the_draw_stays_inside_the_table_and_repeats_no_row():
    """An offset past the end reads nothing and is scored as a portal failure; a
    repeated offset silently shrinks the sample below the size published for it."""
    off = B._draw_offsets(500, 120, 4)
    assert len(off) == len(set(off)) == 120
    assert min(off) >= 0 and max(off) < 500


def test_asking_for_more_rows_than_the_table_holds_takes_the_table():
    """Sampling without replacement cannot draw 600 from 500. Raising here would
    fail the build for asking a reasonable question at the edge."""
    assert len(B._draw_offsets(500, 600, 4)) == 500


def test_taking_the_whole_table_does_not_permute_it_first():
    """Asking for the whole table is not a sample. random.sample() would build a
    full permutation of 1.9M offsets and sort it straight back into order — minutes
    and hundreds of megabytes to compute range(total).

    Asserted by forbidding the call rather than by timing it. A wall-clock
    threshold is the wrong instrument twice over: it is flaky on a loaded runner,
    and it does not test the property — a slow machine could fail a correct
    short-circuit while a fast one passed a broken one."""
    import random as _random

    called, original = [], _random.Random.sample

    def watched(self, population, k):
        called.append(k)
        return original(self, population, k)

    _random.Random.sample = watched
    try:
        for rows in (500, 600):
            assert B._draw_offsets(500, rows, 4) == list(range(500))
        assert not called, f"sample() ran for a whole-table draw: k={called}"
        # ...and the ordinary case must still go through sample().
        assert len(B._draw_offsets(500, 40, 4)) == 40
        assert called == [40], called
    finally:
        _random.Random.sample = original


def test_a_real_draw_is_still_a_sample_not_the_whole_table():
    """The short-circuit must not swallow the ordinary case."""
    got = B._draw_offsets(1_000_000, 300, 1)
    assert len(got) == 300 and got != list(range(300))


def test_a_build_must_name_its_seed():
    """A default seed would make every build the same draw while looking like a
    fresh one, so replicate draws would be secretly identical."""
    import io
    argv, err = sys.argv, io.StringIO()
    sys.argv = ["build_benchmark.py", "--jurisdiction", "dc", "--rows", "5"]
    try:
        # argparse reports a missing required argument on stderr and exits 2, so
        # the reason is in the stream rather than in the exception.
        with contextlib.redirect_stderr(err), _fetching(lambda url, params: None):
            B.main()
    except SystemExit:
        assert "--seed" in err.getvalue(), err.getvalue()
    else:
        raise AssertionError("a build with no seed was accepted")
    finally:
        sys.argv = argv


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
