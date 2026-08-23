#!/usr/bin/env python3
"""What happens when a federal upstream is slow.

A label is a dozen live fetches. When one of them starts answering in minutes
the symptom is the same as an outage — a spinner — and until now nothing on
either side of the wire said which of the twelve was to blame or gave the reader
a way out. These are the two halves of that: the server records what each
upstream cost so the log names the culprit, and the page stops waiting.

No network.

Run directly:  python tests/test_slow_upstreams.py
"""

from __future__ import annotations

import logging
import pathlib
import threading

from housing_label import utils

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_FORM = _ROOT / "docs" / "label-form.js"


def test_a_call_is_recorded_under_its_host():
    utils.begin()
    with utils.timed("nsi.sec.usace.army.mil"):
        pass
    calls = utils.drain()
    assert [n for n, _t in calls] == ["nsi.sec.usace.army.mil"]
    assert calls[0][1] >= 0


def test_drain_reports_the_worst_first_and_empties():
    utils.begin()
    for name, delay in (("fast.gov", 0.0), ("slow.gov", 0.02), ("middling.gov", 0.01)):
        with utils.timed(name):
            if delay:
                threading.Event().wait(delay)
    names = [n for n, _t in utils.drain()]
    assert names == ["slow.gov", "middling.gov", "fast.gov"], names
    assert utils.drain() == [], "drain left timings behind for the next request"


def test_two_requests_do_not_braid():
    """The API serves scoring on a threadpool. One visitor's slow upstream must
    not show up in another visitor's log line, which is why the record is
    thread-local rather than a module global."""
    utils.begin()
    seen = {}

    def worker():
        utils.begin()
        with utils.timed("other-thread.gov"):
            pass
        seen["theirs"] = [n for n, _t in utils.drain()]

    with utils.timed("this-thread.gov"):
        t = threading.Thread(target=worker)
        t.start()
        t.join()
    assert seen["theirs"] == ["other-thread.gov"]
    assert [n for n, _t in utils.drain()] == ["this-thread.gov"]


def test_the_log_names_the_one_that_dragged():
    """A label that takes 20 seconds because twelve datasets each took under two
    is healthy. The line worth waking up to is the one where a single service ate
    the budget — so the threshold is per call, not on the total."""
    utils.begin()
    records = []

    class Catch(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = Catch()
    logger = logging.getLogger("housing_label.utils")
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        # Twelve brisk calls: busy, not broken.
        utils.begin()
        for i in range(12):
            with utils.timed(f"dataset{i}.gov"):
                pass
        utils.log_upstreams("somewhere", 20.0)
        assert records and records[-1].levelno == logging.INFO, "a healthy score warned"

        # One that ate the budget: say so, and say which.
        records.clear()
        utils._timings.calls = [("hog.gov", 61.0), ("quick.gov", 0.2)]
        utils.log_upstreams("somewhere", 62.0)
        assert records and records[-1].levelno == logging.WARNING
        assert "hog.gov" in records[-1].getMessage()

        # Nothing recorded (a cache hit, a non-scoring endpoint) says nothing.
        records.clear()
        utils.log_upstreams("somewhere", 0.1)
        assert not records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        utils.drain()


def test_logging_always_drains():
    """Whatever it decides to log. A request whose timings survive into the next
    one on the same thread reports another visitor's upstreams as its own."""
    utils.begin()
    utils._timings.calls = [("x.gov", 0.1)]
    utils.log_upstreams("somewhere", 0.2)
    assert utils.drain() == []


def test_the_seam_is_installed_once_and_by_the_application():
    """Wrapping requests.Session.send is what an APM agent does to a process; it
    is defensible only while it stays loud and idempotent. The library never does
    it on import — the API asks for it at boot, so the CLI and batch jobs run
    uninstrumented."""
    import requests
    # Restored afterwards: this patches a third-party class for the whole process,
    # and a test that leaves it installed makes every test collected after it run
    # through a wrapper it never asked for — the kind of order dependence that
    # surfaces as a failure in an unrelated file months later.
    before = requests.sessions.Session.send
    try:
        utils.install_timing()
        first = requests.sessions.Session.send
        assert getattr(first, "_hnl_timed", False), "the seam is not marked"
        utils.install_timing()
        assert requests.sessions.Session.send is first, "installing twice stacked a wrapper"
    finally:
        requests.sessions.Session.send = before
    src = (_ROOT / "src" / "housing_label" / "api.py").read_text(encoding="utf-8")
    assert "utils.install_timing()" in src, "the API never installs it"
    assert "utils.begin()" in src, "the API records without opening a window"
    # And the window closes however the request ends. Recording is per-thread and
    # threads are reused, so one left open by a request that raised is one the
    # next request starts filling.
    manager = src.split("def _upstream_timing", 1)[1].split("\n@app", 1)[0]
    assert "utils.begin()" in manager and "finally:" in manager, \
        "the timing window is not closed in a finally"


def test_nothing_is_recorded_when_nobody_is_listening():
    """The seam is process-wide, so it also sees the geocoder calls behind
    /suggest — and nothing drains a /suggest. Recording unconditionally grew a
    list on every reused worker thread for the life of the process, which on this
    deployment is the slow RSS climb into an OOM that render.yaml already has a
    paragraph about. Recording is opt-in, per request."""
    utils.drain()                       # ensure no window is open
    with utils.timed("suggest-geocoder.example"):
        pass
    assert utils.drain() == [], "a call outside a scoring request was recorded"
    # And a window closes for good when it is drained.
    utils.begin()
    with utils.timed("in.example"):
        pass
    assert [n for n, _t in utils.drain()] == ["in.example"]
    with utils.timed("after.example"):
        pass
    assert utils.drain() == []


def test_recording_is_capped():
    """A scoring request makes twenty-odd calls. A list past the cap is a bug
    somewhere else, and must not be allowed to become a leak here."""
    utils.begin()
    for _ in range(utils._MAX_RECORDED * 2):
        with utils.timed("flood.example"):
            pass
    assert len(utils.drain()) == utils._MAX_RECORDED


def test_a_url_never_logs_a_credential():
    """None of our URLs carry userinfo today. A log that would print one if they
    ever did is not a thing to leave lying around."""
    # Assembled rather than written out: a credential-shaped literal in source
    # trips secret scanners, and this is dummy data making a point about logging.
    authority = "%s:%s@nsi.example.gov" % ("someone", "a-secret")
    assert utils.host_of("https://" + authority + "/x") == "nsi.example.gov"
    assert utils.host_of("https://someone@nsi.example.gov/x") == "nsi.example.gov"


def test_host_of_survives_anything():
    assert utils.host_of("https://nsi.sec.usace.army.mil/x?y=1") == "nsi.sec.usace.army.mil"
    assert utils.host_of("not a url") == "not a url"
    assert utils.host_of("") == "unknown"


# ── the page's half ──────────────────────────────────────────────────────────
def test_no_scoring_request_waits_forever():
    """The spinner used to be unbounded: the API's own budget lets one stuck
    upstream cost tens of seconds and several of them minutes, and the page had
    no deadline at all, so a slow score was indistinguishable from a dead one and
    the reader had nothing to do but leave."""
    form = _FORM.read_text(encoding="utf-8")
    assert "AbortController" in form, "the scoring fetch has no deadline"
    assert "SCORE_TIMEOUT_MS" in form
    # Every scoring call goes through the wrapper — one that doesn't is a request
    # that can still hang forever, and it would be the one nobody tested.
    assert "fetch(API_BASE" not in form, "a scoring fetch bypasses the deadline"
    for path in ('"/label"', '"/presets"', '"/density?"', '"/timeline?"'):
        assert "fetchScoring(API_BASE + " + path in form, path


def test_a_timeout_says_what_happened_and_offers_a_way_out():
    """Not the generic failure: the address is fine, the datasets are slow, and
    the reader should not have to retype anything to try again."""
    form = _FORM.read_text(encoding="utf-8")
    assert "state.timedOut" in form
    assert "taking longer than it should" in form
    assert "lf-retry" in form and "function retryLoad" in form
    # The deadline has to beat the API's own worst case or it never fires.
    assert "45000" in form


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
