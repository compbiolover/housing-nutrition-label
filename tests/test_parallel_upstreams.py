#!/usr/bin/env python3
"""A label's independent upstreams are asked at the same time, inside one window.

The speed-up is the easy half. The half worth pinning is that running a fetch on
another thread changes nothing else a label depends on:

1. The request's **timing and budget window follows the work** onto the worker
   thread — a host's spend is metered across threads, a host dropped in a worker
   is still named (and still keeps the label out of the cache), and a worker does
   not carry one request's window into the next task it runs.
2. ``resolve_location`` **waits for the slowest** enricher rather than the sum,
   and applies the answers exactly as the sequential code did — same fields, same
   notes, in the same order, with an NSI outage still flagged.
3. The **warming fetches** really are the calls the label build makes later:
   the build's own calls find them memoised and make no second request.
4. Two identical ``/label`` requests in flight **share one scoring pass**.

No network: every upstream is stubbed. This file alone:
``pytest tests/test_parallel_upstreams.py``
"""

from __future__ import annotations

import threading
import time

import pytest

from housing_label import utils

_NAP = 0.3


def _sleepy(value=None, nap=_NAP):
    def fetch(*_a, **_k):
        time.sleep(nap)
        return value
    return fetch


# --- 1. the window follows the work ----------------------------------------------


def test_a_worker_records_into_the_requests_own_window():
    utils.begin(budget=30, per_host=12)
    try:
        def call():
            with utils.timed("slow.example.gov"):
                time.sleep(0.05)
        utils.gather(utils.fan_out(call, call))
        calls = utils.drain()
    finally:
        utils.drain()
    assert [n for n, _ in calls] == ["slow.example.gov", "slow.example.gov"], (
        "a fetch made on a worker thread vanished from the request's timing line")


def test_a_host_dropped_in_a_worker_is_dropped_for_the_request():
    """The payload names it and api._may_cache refuses the label — both read the
    request thread's list, so the worker must write to that same list."""
    utils.begin(budget=30, per_host=12)
    try:
        utils.gather(utils.fan_out(lambda: utils.note_dropped("county.example.gov")))
        assert utils.starved() == ["county.example.gov"]
    finally:
        utils.drain()


def test_a_hosts_share_is_metered_across_threads():
    utils.begin(budget=30, per_host=1.0)
    try:
        def spend():
            with utils.timed("usgs.example.gov"):
                time.sleep(0.6)
        utils.gather(utils.fan_out(spend, spend))
        assert utils.allowance("usgs.example.gov") <= 0, (
            "two workers each under the per-host share, together over it, were "
            "not charged as one host — the budget is per label, not per thread")
    finally:
        utils.drain()


def test_a_worker_lets_go_of_the_window_when_its_task_ends():
    """Pool threads are reused. One still holding a finished request's window
    would record into it forever, and refuse calls against its spent deadline."""
    utils.begin(budget=30, per_host=12)
    try:
        utils.gather(utils.fan_out(*[lambda: None] * 40))
    finally:
        utils.drain()
    seen = utils.fan_out(*[utils._window] * 40)
    utils.gather(seen)
    assert all(f.result() is None for f in seen)


def test_outside_a_window_a_task_simply_runs():
    """The CLI and batch jobs open no window; fan_out must not invent one."""
    (f,) = utils.fan_out(lambda: utils._window())
    utils.gather([f])
    assert f.result() is None


# --- 2. resolve_location waits for the slowest, applies like before --------------


@pytest.fixture
def stubbed_point(monkeypatch):
    """Every network enricher stubbed to take _NAP seconds."""
    from housing_label.enrich import assessor, footprint, structure, water_system
    from housing_label.enrich.assessor.base import AssessorRecord
    from housing_label.simulate import location as L

    geo = {"lat": 41.0, "lon": -87.0, "matched_address": "1 MAIN ST, X, IL, 60000",
           "county_fips": "17031", "tract": "17031010100", "state_fips": "17"}
    monkeypatch.setattr(L, "geocode_address", lambda a: dict(geo))
    record = AssessorRecord(source="Test County", data_vintage="2026", parcel_id="P1",
                            year_built=1925)
    monkeypatch.setattr(assessor, "assessor_for_point", _sleepy(record))
    monkeypatch.setattr(structure, "structure_for_point", _sleepy(
        {"structure_type": "single_family", "num_units": 1, "stories": 2,
         "sqft": 1800.0, "source": "NSI"}))
    monkeypatch.setattr(water_system, "water_system_for_point",
                        _sleepy({"status": "outside"}))
    monkeypatch.setattr(footprint, "warm", _sleepy())
    seen = {}

    def fp(lat, lon, allow_network=True, expected_footprint_m2=None):
        seen["expected"] = expected_footprint_m2
        return {"footprint_area_m2": 90.0, "footprint_perimeter_m": 40.0,
                "occ_cls": "Residential"}
    monkeypatch.setattr(footprint, "footprint_for_point", fp)
    return L, seen


def test_enrichers_cost_the_slowest_not_the_sum(stubbed_point):
    L, seen = stubbed_point
    # The first resolve in a process decodes the bundled tract tables; that is
    # local CPU, paid once (the API does it at boot), and not what is measured.
    L.resolve_location(address="1 Main St")
    warmed = []
    started = time.monotonic()
    loc = L.resolve_location(address="1 Main St", also_fetch=(
        lambda la, lo: (time.sleep(_NAP), warmed.append((la, lo))),))
    elapsed = time.monotonic() - started
    # Five tasks of _NAP each: 1.5 s in a row, one _NAP side by side.
    assert elapsed < 3 * _NAP, f"enrichers ran in series ({elapsed:.2f}s)"
    assert warmed == [(41.0, -87.0)], "the caller's warming fetch was not run at the point"
    assert loc.assessor.year_built == 1925
    assert loc.structure_type == "single_family" and loc.stories == 2
    assert loc.water_system == {"status": "outside"}
    assert loc.footprint_area_m2 == 90.0 and loc.occ_cls == "Residential"
    # The footprint still gets NSI's floor area ÷ stories as its tie-breaker.
    assert seen["expected"] == pytest.approx(1800.0 * 0.092903 / 2)


def test_notes_keep_their_order(stubbed_point):
    """Source-of-truth first: the assessor note was deliberately written before
    NSI's, and concurrency must not reorder what a reader sees."""
    L, _ = stubbed_point
    loc = L.resolve_location(address="1 Main St")
    keys = list(loc.notes)
    assert keys.index("assessor") < keys.index("water_system")


def test_an_nsi_outage_is_still_flagged(stubbed_point, monkeypatch):
    """The flag is what keeps a defaults-only label out of the API's cache."""
    from housing_label.enrich import structure
    L, _ = stubbed_point

    def down(*_a, **_k):
        raise structure.NSIUnavailable("down")
    monkeypatch.setattr(structure, "structure_for_point", down)
    loc = L.resolve_location(address="1 Main St")
    assert loc.structure_unavailable is True
    assert "temporarily unavailable" in loc.notes["structure"]


def test_a_failing_warming_fetch_is_not_the_locations_problem(stubbed_point):
    L, _ = stubbed_point

    def boom(lat, lon):
        raise RuntimeError("PVGIS is having a day")
    loc = L.resolve_location(address="1 Main St", also_fetch=(boom,))
    assert loc.assessor is not None


def test_a_preset_still_skips_the_assessor(stubbed_point, monkeypatch):
    from housing_label.enrich import assessor
    L, _ = stubbed_point
    asked = []
    monkeypatch.setattr(assessor, "assessor_for_point",
                        lambda *a, **k: asked.append(1))
    L.resolve_location(address="1 Main St", want_assessor=False)
    assert not asked


# --- 3. warming fetches are the build's own calls ---------------------------------


def test_warmed_footprint_candidates_are_not_fetched_again(monkeypatch):
    from housing_label.enrich import footprint as F
    F._candidates_at.cache_clear()
    F._footprint_at.cache_clear()
    calls = []
    ring = [[-87.0, 41.0], [-87.0001, 41.0], [-87.0001, 41.0001], [-87.0, 41.0001],
            [-87.0, 41.0]]
    feat = {"attributes": {"SQMETERS": 120.0, "OCC_CLS": "Residential",
                           "OUTBLDG": "N", "LONGITUDE": -87.00005, "LATITUDE": 41.00005},
            "geometry": {"rings": [ring]}}
    monkeypatch.setattr(F, "_query", lambda g, t: calls.append(t) or [feat])
    F.warm(41.0000004, -87.0000004)
    before = len(calls)
    out = F.footprint_for_point(41.0000004, -87.0000004, expected_footprint_m2=100.0)
    assert out and out["footprint_area_m2"] == 120.0
    assert len(calls) == before == 1, "the build re-asked for warmed candidates"


def test_warmed_noise_layers_are_not_fetched_again(monkeypatch):
    from housing_label.enrich import road_noise as R
    R._nearest_on_layer.cache_clear()
    R._sources_at.cache_clear()
    calls = []
    monkeypatch.setattr(R, "_query", lambda lat, lon, layer: calls.append(layer) or [])
    for warm in R.layer_fetches():
        warm(41.12345678, -87.12345678)
    assert sorted(calls) == sorted(layer for layer, _ in R._SOURCES.values())
    R.noise_sources_near(41.12345678, -87.12345678)
    assert len(calls) == len(R._SOURCES), "the build re-asked for a warmed layer"


def test_a_failed_noise_layer_is_retried_not_memoised(monkeypatch):
    from housing_label.enrich import road_noise as R
    R._nearest_on_layer.cache_clear()
    R._sources_at.cache_clear()
    state = {"down": True}

    def query(lat, lon, layer):
        if state["down"]:
            raise R.RoadDataUnavailable("down")
        return []
    monkeypatch.setattr(R, "_query", query)
    with pytest.raises(R.RoadDataUnavailable):
        R.noise_sources_near(40.5, -88.5)
    state["down"] = False
    assert R.noise_sources_near(40.5, -88.5)["any_within_threshold"] is False


def test_flood_is_not_warmed_when_the_caller_gave_a_zone():
    from housing_label.enrich.fema_flood import fetch_flood_zone
    from housing_label.simulate.house import _point_fetches
    assert fetch_flood_zone in _point_fetches(None)
    assert fetch_flood_zone not in _point_fetches("AE")


def test_warming_fetches_round_like_the_calls_they_stand_in_for(monkeypatch):
    """The build calls the public functions with cfg's coordinate; the warm entry
    must land under the same memo key or it is a wasted request."""
    from housing_label.enrich import road_noise as R
    seen = []
    monkeypatch.setattr(R, "_nearest_on_layer", lambda la, lo, layer: seen.append((la, lo)))
    R.layer_fetches()[0](41.123456789, -87.987654321)
    assert seen == [(round(41.123456789, 6), round(-87.987654321, 6))]


# --- 4. one scoring pass per question in flight -----------------------------------


def test_identical_requests_in_flight_share_one_pass():
    pytest.importorskip("fastapi")
    from housing_label import api
    runs, results = [], []

    def compute():
        runs.append(1)
        time.sleep(_NAP)
        return {"ok": len(runs)}

    threads = [threading.Thread(target=lambda: results.append(
        api._single_flight(("label", "k"), compute))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(runs) == 1 and results == [{"ok": 1}] * 4
    assert not api._inflight, "a finished key was left in flight"


def test_a_waiter_does_not_inherit_its_leaders_failure():
    pytest.importorskip("fastapi")
    from housing_label import api
    attempts = []
    gate = threading.Event()
    leading = threading.Event()

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            leading.set()          # the leader is inside _single_flight now
            gate.wait(2)
            raise RuntimeError("the leader's bad minute")
        return "fine"

    out = {}

    def lead():
        try:
            api._single_flight(("label", "f"), flaky)
        except RuntimeError:
            out["leader"] = "raised"

    leader = threading.Thread(target=lead)
    leader.start()
    assert leading.wait(2), "the leader never started computing"
    waiter = threading.Thread(target=lambda: out.update(
        waiter=api._single_flight(("label", "f"), flaky)))
    waiter.start()
    time.sleep(0.05)
    gate.set()
    leader.join()
    waiter.join()
    assert out == {"leader": "raised", "waiter": "fine"}


# --- review follow-ups ----------------------------------------------------------


def test_a_task_the_window_ran_out_on_is_named_as_dropped():
    """Otherwise a saturated pool reads as 'no record here' and the degraded label
    is cached onto the coordinate for the whole TTL."""
    from concurrent.futures import Future
    from housing_label.simulate.location import _outcome
    utils.begin(budget=30, per_host=12)
    try:
        assert _outcome(Future(), "fallback", "nsi.sec.usace.army.mil") == "fallback"
        assert utils.starved() == ["nsi.sec.usace.army.mil"]
    finally:
        utils.drain()


def test_a_finished_task_is_not_named_as_dropped():
    from concurrent.futures import Future
    from housing_label.simulate.location import _outcome
    f = Future()
    f.set_result("answer")
    utils.begin(budget=30, per_host=12)
    try:
        assert _outcome(f, "fallback", "x.example.gov") == "answer"
        assert utils.starved() == []
    finally:
        utils.drain()


def test_memoised_footprint_candidates_keep_no_geometry(monkeypatch):
    """A memo of thousands of raw polygon collections is what a 512 MB host
    cannot hold; each candidate keeps its attributes and its perimeter only."""
    from housing_label.enrich import footprint as F
    F._candidates_at.cache_clear()
    ring = [[-87.0, 41.0], [-87.0001, 41.0], [-87.0001, 41.0001], [-87.0, 41.0001],
            [-87.0, 41.0]]
    feat = {"attributes": {"SQMETERS": 120.0, "OCC_CLS": "Residential", "OUTBLDG": "N",
                           "LONGITUDE": -87.00005, "LATITUDE": 41.00005, "EXTRA": "x"},
            "geometry": {"rings": [ring]}}
    monkeypatch.setattr(F, "_query", lambda g, t: [feat] if t == "esriGeometryEnvelope" else [])
    best, nearby = F._candidates_at(41.2, -87.2)
    assert best is None and len(nearby) == 1
    assert "geometry" not in nearby[0] and "EXTRA" not in nearby[0]["attributes"]
    assert nearby[0]["perimeter_m"] == pytest.approx(F._ring_perimeter_m(ring))


def test_waiters_wait_without_limit_when_the_budget_is_off(monkeypatch):
    pytest.importorskip("fastapi")
    from housing_label import api, config
    monkeypatch.setattr(config, "UPSTREAM_BUDGET", 0.0)
    assert api._waiter_timeout() is None
    monkeypatch.setattr(config, "UPSTREAM_BUDGET", 30.0)
    assert api._waiter_timeout() == 35.0


def test_queued_warmers_are_cancelled_when_the_window_runs_out(monkeypatch):
    """A warmer still queued when the request stops waiting must not stay in the
    shared pool's queue, holding a slot for a request that has moved on."""
    from housing_label.simulate import location as L
    from concurrent.futures import Future
    made = []

    def fake_fan_out(*tasks):
        out = []
        for _ in tasks:
            f = Future()          # never started: what a saturated pool leaves
            made.append(f)
            out.append(f)
        return out
    monkeypatch.setattr(utils, "fan_out", fake_fan_out)
    monkeypatch.setattr(utils, "gather", lambda futures, timeout=None: None)
    monkeypatch.setattr(L, "geographies_for_coords", lambda lat, lon: None)
    L.resolve_location(lat=41.0, lon=-87.0, also_fetch=(lambda la, lo: None,))
    assert made and all(f.cancelled() for f in made)


def test_a_call_joining_a_busy_host_gets_only_what_is_left_of_its_share():
    """A call that starts while a sibling to the same host is still running must
    not be handed the host's whole share again — that let one dataset hold the
    label for share + head start."""
    utils.begin(budget=30, per_host=1.0)
    try:
        release = threading.Event()

        def first():
            with utils._running("usgs.example.gov"):
                release.wait(2)
        (f,) = utils.fan_out(first)
        time.sleep(0.6)
        left = utils.allowance("usgs.example.gov")
        assert left is not None and left < 0.5, (
            f"a joining call was offered {left:.2f}s of a 1s share already 0.6s busy")
        release.set()
        utils.gather([f])
    finally:
        utils.drain()


def test_calls_started_together_still_run_together():
    """The in-flight charge starts from the earliest running call; siblings
    launched at the same moment each still get (nearly) the whole share."""
    utils.begin(budget=30, per_host=12)
    try:
        offered, ready = [], threading.Barrier(3)

        def call():
            ready.wait(2)
            offered.append(utils.allowance("tigerweb.example.gov"))
            with utils._running("tigerweb.example.gov"):
                time.sleep(0.05)
        utils.gather(utils.fan_out(call, call, call))
        assert len(offered) == 3 and min(offered) > 11.5
    finally:
        utils.drain()
