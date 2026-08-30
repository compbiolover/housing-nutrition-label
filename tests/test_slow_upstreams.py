#!/usr/bin/env python3
"""What happens when a federal upstream is slow.

A label is a dozen live fetches. When one of them starts answering in minutes
the symptom is the same as an outage — a spinner — and until now nothing on
either side of the wire said which of the twelve was to blame or gave the reader
a way out. These are the two halves of that: the server records what each
upstream cost so the log names the culprit, and the page stops waiting.

And then the part that makes the wait unnecessary: the record doubles as a
spending limit, so a dataset that has used its share of a score is refused, its
dimension comes back N/A with a note, and the reader gets the rest of the label
instead of losing all of it to the one service having a bad afternoon.

No network.

This file alone:  pytest tests/test_slow_upstreams.py
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
    assert "utils.begin(" in src, "the API records without opening a window"
    # And the window closes however the request ends. Recording is per-thread and
    # threads are reused, so one left open by a request that raised is one the
    # next request starts filling.
    manager = src.split("def _upstream_timing", 1)[1].split("\n@app", 1)[0]
    assert "utils.begin(" in manager and "finally:" in manager, \
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


def test_the_seam_costs_a_getattr_when_nobody_is_recording():
    """Every non-scoring request in the process comes through the seam —
    /suggest, /place, the geocoder proxies — and none of them has anyone to
    report to. The comment claims they pay a getattr; this is what makes that
    true rather than a urlsplit and a context manager per call."""
    import types
    import requests

    before = requests.sessions.Session.send
    real_host_of = utils.host_of
    seen = {"parsed": 0}

    def counting(url):
        seen["parsed"] += 1
        return real_host_of(url)

    try:
        requests.sessions.Session.send = lambda self, request, **kw: "sent"
        utils.install_timing()
        utils.host_of = counting
        req = types.SimpleNamespace(url="https://x.example.gov/y")

        utils.drain()                       # no window open
        requests.sessions.Session().send(req)
        assert seen["parsed"] == 0, "the seam parsed a URL with nobody listening"

        utils.begin()
        requests.sessions.Session().send(req)
        assert seen["parsed"] == 1
        assert [n for n, _t in utils.drain()] == ["x.example.gov"]
    finally:
        utils.host_of = real_host_of
        requests.sessions.Session.send = before


def test_host_of_survives_anything():
    assert utils.host_of("https://nsi.sec.usace.army.mil/x?y=1") == "nsi.sec.usace.army.mil"
    assert utils.host_of("not a url") == "not a url"
    assert utils.host_of("") == "unknown"


def test_the_timing_log_does_not_write_down_where_somebody_lives():
    """This module argues elsewhere that a scored URL carries an address that is
    very often the visitor's own home, and that it should not be handed around
    casually. A log line at INFO on every successful score is exactly the casual
    place — before the timing window, an address reached the log only when
    scoring raised."""
    try:
        import fastapi  # noqa: F401
    except ImportError:
        print("  skip test_the_timing_log_does_not_write_down_where_somebody_lives"
              " (fastapi not installed)")
        return
    from housing_label.api import _timing_context

    addr = "1664 Botsford Drive, Knoxville, TN"
    line = _timing_context("label", addr, None, None)
    assert "Botsford" not in line and "Knoxville" not in line, line
    assert line.startswith("label addr#")
    # Still useful: the same address is the same token, so retries group and two
    # concurrent requests stay apart.
    assert line == _timing_context("label", "1664 botsford  drive, knoxville, tn", None, None)
    assert line != _timing_context("label", "1 Other St, Memphis, TN", None, None)

    # Coordinates are the handle an operator needs to reproduce a slow score, and
    # they are kept — but only when there are two of them.
    assert _timing_context("label", None, 35.13, -89.99) == "label 35.13,-89.99"
    assert _timing_context("presets", None, None, None) == "presets"
    assert "None" not in _timing_context("presets", None, 35.13, None)


def test_every_scoring_endpoint_carries_a_window():
    """The one that hangs is never the one you instrumented — /badge was among
    the endpoints observed hanging. /label.svg is the exception on purpose: it
    scores through label(), which opens its own."""
    src = (_ROOT / "src" / "housing_label" / "api.py").read_text(encoding="utf-8")
    for name in ("badge", "presets", "density", "timeline"):
        assert f'@_times_upstreams("{name}")' in src, f"/{name} has no timing window"
    assert "with _upstream_timing(" in src, "/label lost its window"
    sheet = src.split('@app.get("/label.svg")', 1)[1][:120]
    assert "_times_upstreams" not in sheet, "/label.svg nests a second, empty window"


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


# ── what one slow dataset is allowed to cost ─────────────────────────────────
# Naming the upstream that dragged told the operator what happened; it did nothing
# for the reader, who still lost the whole label — the nine dimensions that had
# answered along with the one that hadn't — because one federal service was having
# a bad afternoon. These are the limits that end that: a dataset that has used its
# share of a score is refused where it stands, its own module raises the same
# "unavailable" it raises for an outage, and its rows come back N/A while the rest
# of the label is returned.


import contextlib
import types

import requests


@contextlib.contextmanager
def _seam(fake_send):
    """Run the real seam over ``fake_send``, and put the process back afterwards."""
    import requests
    before = requests.sessions.Session.send
    try:
        requests.sessions.Session.send = fake_send
        utils.install_timing()
        yield
    finally:
        requests.sessions.Session.send = before
        utils.drain()


def _sent(url="https://slow.example.gov/x"):
    return types.SimpleNamespace(url=url)


def test_a_host_that_used_its_share_is_refused_rather_than_waited_for():
    """The whole point. Without this the third attempt against a wedged service is
    made in full — another TIMEOUT seconds of a request the reader is watching —
    for an answer the first two already showed was not coming."""
    calls = []
    with _seam(lambda self, request, **kw: calls.append(kw) or "sent"):
        utils.begin(per_host=10)
        utils._timings.calls = [("slow.example.gov", 10.0)]   # its share, spent
        try:
            requests.sessions.Session().send(_sent())
        except utils.UpstreamTooSlow as exc:
            assert "slow.example.gov" in str(exc), exc
        else:
            raise AssertionError("a spent host was allowed to keep the reader waiting")
        assert calls == [], "the refused call still went out"
        assert utils.starved() == ["slow.example.gov"]


def test_a_slow_dataset_costs_nobody_else_its_speed():
    """A per-host limit rather than one pot everybody drinks from: the dataset that
    is slow is the one that pays. A shared pot would make the *next* dataset in the
    sequence pay for the previous one's afternoon, which is how a label ends up N/A
    in the rows that had nothing wrong with them."""
    with _seam(lambda self, request, **kw: "sent"):
        utils.begin(budget=60, per_host=5)
        utils._timings.calls = [("slow.example.gov", 5.0)]
        assert requests.sessions.Session().send(_sent("https://fine.example.gov/x")) == "sent"
        assert utils.starved() == [], "a healthy host was refused for somebody else's cost"


def test_the_whole_score_has_a_deadline_too():
    """The case the per-host limit cannot see: not one dataset in trouble but six,
    each comfortably inside its own share, together past what the page will wait."""
    with _seam(lambda self, request, **kw: "sent"):
        utils.begin(budget=0.0001, per_host=30)
        try:
            requests.sessions.Session().send(_sent("https://anyone.example.gov/x"))
        except utils.UpstreamTooSlow as exc:
            assert "no time left" in str(exc), exc
        else:
            raise AssertionError("the request's own deadline never fired")


def test_one_call_cannot_outlive_the_budget():
    """A 12s read timeout with 4s left in the window would blow through the window
    on its own, so what is left is also the ceiling on the next call."""
    seen = {}
    with _seam(lambda self, request, **kw: seen.update(kw) or "sent"):
        utils.begin(budget=3, per_host=30)
        requests.sessions.Session().send(_sent(), timeout=60)
        assert seen["timeout"] <= 3, seen
        # A (connect, read) pair is capped on both halves — a 60s connect with 3s
        # left is the same overrun wearing a different shape.
        utils.begin(budget=3, per_host=30)
        requests.sessions.Session().send(_sent(), timeout=(60, 60))
        assert max(seen["timeout"]) <= 3, seen
        # And a call that already fits keeps its own, shorter timeout.
        utils.begin(budget=30, per_host=30)
        requests.sessions.Session().send(_sent(), timeout=2)
        assert seen["timeout"] == 2, seen


def test_a_redirect_is_one_call_not_two():
    """requests resolves a redirect by calling Session.send again from inside the
    send already being timed. Counted at both levels, one 10.8s USGS request read
    as two slow calls in the log — and, worse, billed a redirecting host twice for
    a single answer, so a service could be refused at half its real share."""
    def redirecting(self, request, **kw):
        # What resolve_redirects does: the same Session, the same seam, one hop in.
        if not getattr(request, "hopped", False):
            hop = _sent("https://usgs.example.gov/moved")
            hop.hopped = True
            return requests.sessions.Session().send(hop, **kw)
        return "sent"

    with _seam(redirecting):
        utils.begin(per_host=10)
        requests.sessions.Session().send(_sent("https://usgs.example.gov/x"))
        calls = utils.drain()
        assert len(calls) == 1, calls
        assert calls[0][0] == "usgs.example.gov"


def test_a_refusal_is_a_timeout_every_fetcher_already_handles():
    """Nothing in the tree had to be taught to degrade gracefully: eleven modules
    already turn a timeout into their own 'unavailable', and those paths were
    written years before this. A bespoke exception class would have walked past
    every one of them and reached the reader as a 502."""
    assert issubclass(utils.UpstreamTooSlow, requests.exceptions.Timeout)


def test_nothing_is_budgeted_unless_the_caller_asks():
    """The CLI and batch jobs open no window at all, and a window opened without
    limits imposes none: there, nobody is watching a spinner and the complete
    answer is worth waiting for."""
    utils.begin()
    assert utils.allowance("anywhere.example.gov") is None
    assert utils.remaining("anywhere.example.gov") == (None, None)
    utils.drain()


def test_a_closed_window_lifts_the_limits():
    """Threads are reused. A deadline left behind by a request that has already
    answered is one the next request on that thread is refused by, having spent
    nothing — the same bug as timings that survive their request, with a worse
    symptom."""
    with _seam(lambda self, request, **kw: "sent"):
        utils.begin(budget=0.0001, per_host=0.0001)
        utils.drain()
        assert requests.sessions.Session().send(_sent()) == "sent"


def test_retrying_never_sleeps_into_a_budget_that_is_spent():
    """The fetchers back off between attempts, which is right for a flaky upstream
    and wrong for one whose budget is gone: that retry will be refused the moment
    it is made, so the sleep buys nothing and spends seconds the datasets that are
    still healthy have not had yet."""
    slept = []
    # Patching the stdlib module's attribute, and putting it back in the finally:
    # the alternative is a test that really sleeps the back-off it is asserting on.
    real_sleep = utils.time.sleep
    utils.time.sleep = lambda s: slept.append(s)
    try:
        # Unbudgeted: exactly the sleep it replaced.
        utils.begin()
        utils.retry_wait(2, 2)
        assert slept == [4.0], slept

        # Spent: no sleep at all.
        slept.clear()
        utils.begin(per_host=5)
        utils._timings.calls = [("slow.example.gov", 5.0)]
        utils._timings.last = "slow.example.gov"
        utils.retry_wait(1, 2)
        assert slept == [], slept

        # Some left, but less than the back-off wants: wait what there is, and
        # leave enough of it for the attempt the wait is for.
        slept.clear()
        utils.begin(per_host=5)
        utils._timings.calls = [("slow.example.gov", 3.0)]
        utils._timings.last = "slow.example.gov"
        utils.retry_wait(3, 2)          # wants 8s, has 2s
        assert slept and slept[0] < 2, slept
    finally:
        utils.time.sleep = real_sleep
        utils.drain()


def test_no_fetcher_backs_off_behind_the_budgets_back():
    """A module that sleeps on its own is a module that spends the request's
    seconds without asking, and it would be the one nobody noticed — this is the
    grep that notices."""
    src = _ROOT / "src" / "housing_label"
    offenders = [p.name for p in src.rglob("*.py")
                 if "time.sleep(BACKOFF" in p.read_text(encoding="utf-8")]
    assert not offenders, offenders


def test_the_label_says_which_dataset_it_gave_up_on():
    """An N/A with no explanation reads as 'we know nothing about your address'.
    What happened is that one public service was slow for a minute, and the same
    address scores completely on the next try — so the payload carries the name a
    reader would recognise, and the host an operator would search for."""
    try:
        import fastapi  # noqa: F401
    except ImportError:
        print("  skip test_the_label_says_which_dataset_it_gave_up_on (fastapi not installed)")
        return
    from housing_label.api import _dropped_datasets, _may_cache

    utils.begin(per_host=1)
    utils._timings.starved = ["nsi.sec.usace.army.mil", "made.up.example"]
    assert _dropped_datasets() == [
        {"host": "nsi.sec.usace.army.mil", "dataset": "the USACE National Structure Inventory"},
        # An upstream nobody added to the roster is still named, by its host: a
        # dataset that says "made.up.example" is searchable, one that says "a
        # public dataset" is not.
        {"host": "made.up.example", "dataset": "made.up.example"},
    ]
    # And a label with a hole in it is never cached: the hole is a minute old, the
    # cache entry would be six hours old, and the URL gets bookmarked and shared.
    assert not _may_cache(False)
    utils.drain()
    assert _may_cache(False)


def test_the_api_asks_for_the_budget_it_documents():
    """The limits are worth nothing if the one process that serves readers doesn't
    ask for them, and they must come from config (where render.yaml's env vars land)
    rather than from numbers typed into the endpoint."""
    src = (_ROOT / "src" / "housing_label" / "api.py").read_text(encoding="utf-8")
    assert "utils.begin(budget=config.UPSTREAM_BUDGET, per_host=config.UPSTREAM_HOST_BUDGET)" in src
    from housing_label import config
    # Inside the page's own deadline (docs/label-form.js), with room to score.
    assert 0 < config.UPSTREAM_BUDGET <= 40
    assert 0 < config.UPSTREAM_HOST_BUDGET <= config.UPSTREAM_BUDGET


def test_the_log_says_what_it_dropped():
    """A score that answers in 20 seconds having quietly abandoned a dataset looks
    healthy in the log, and is the one an operator most needs to see."""
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
        utils.begin(per_host=1)
        utils._timings.calls = [("quick.gov", 0.2)]
        utils._timings.starved = ["wedged.gov"]
        utils.log_upstreams("somewhere", 0.4)
        assert records and records[-1].levelno == logging.WARNING
        assert "wedged.gov" in records[-1].getMessage()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        utils.drain()


def test_the_page_says_it_in_a_sentence():
    """The API names the datasets; the wording is the page's job, and it has to
    make the trade legible: what is missing, that the rest is complete, that the
    address is fine, and a way to ask again without retyping it."""
    form = _FORM.read_text(encoding="utf-8")
    assert "function slowDataNote" in form
    assert "slowDataNote()" in form, "the note is written but never rendered"
    assert "slow_upstreams" in form, "the page never reads the field the API sends"
    assert "state.presetsSlow" in form, "the profile grid drops what /presets reported"
    note = form.split("function slowDataNote", 1)[1].split("\n    function ", 1)[0]
    assert "N/A" in note, "the note never says what a missing dataset leaves behind"
    assert "lf-retry" in note, "the note offers no way to try again"
    # Reading whichever payload the current mode renders from looked tidier and
    # silently dropped the disclosure in the combined view, which can reach its
    # profile list through /presets with no /label scored at all. Every payload on
    # screen is consulted instead, so no view can lose the notice by being added.
    for source in ("state.detected", "state.presetsSlow", "densityCache()", "state.timeline"):
        assert source in note, f"the note never looks at {source}"
    assert "state.mode" not in note, "the note is gated on the mode again"
