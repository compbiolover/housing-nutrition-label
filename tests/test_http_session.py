#!/usr/bin/env python3
"""The shared HTTP session: one warm connection per host, not one per call.

Every fetcher used to call ``requests.get()``, which builds a throwaway Session
for the single call and closes it. A label queries a dozen-plus datasets, each
its own host, inside a 12 s per-host and 30 s whole-request budget — so it was
paying a full TCP + TLS handshake per dataset, every time.

These tests pin the three properties that make ``utils.http_session()`` safe to
share, and one that proves it actually reuses the connection: the count of TCP
accepts against a real local server, which is the thing the change is for.

Runs without external network (a loopback server stands in for the upstreams).
This file alone: ``pytest tests/test_http_session.py``.
"""

from __future__ import annotations

import http.server
import socketserver
import threading
from http import cookiejar

import requests

from housing_label import utils


class _KeepAliveServer(socketserver.ThreadingTCPServer):
    """Counts accepted connections, so a test can tell reuse from reconnection."""

    allow_reuse_address = True
    daemon_threads = True                     # or shutdown() waits on keep-alive

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.accepts = 0

    def get_request(self):
        self.accepts += 1
        return super().get_request()


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"             # keep-alive, like every real upstream

    def do_GET(self):
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        pass


def _server():
    srv = _KeepAliveServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/x"


def test_the_session_reuses_one_connection_across_a_labels_worth_of_calls():
    """The whole point, measured rather than asserted: fourteen calls to one host
    open fourteen connections through requests.get() and one through the session."""
    srv, url = _server()
    try:
        calls = 14                            # about what one label fans out to
        srv.accepts = 0
        for _ in range(calls):
            requests.get(url, timeout=5)      # the old shape: a Session per call
        per_call = srv.accepts

        srv.accepts = 0
        session = utils.http_session()
        for _ in range(calls):
            session.get(url, timeout=5)
        pooled = srv.accepts
    finally:
        srv.shutdown()

    assert per_call == calls, "a Session per call should open one connection each"
    assert pooled == 1, f"the pooled session opened {pooled} connections, not 1"


def test_one_session_per_thread():
    """requests.Session is not documented as thread-safe and the API serves its
    sync endpoints on a threadpool, so the session is per-thread. A scoring
    request runs on one thread and makes all its calls there, which is where the
    repeated handshakes were, so this keeps the win without needing that
    guarantee."""
    mine = utils.http_session()
    assert utils.http_session() is mine, "a thread must reuse its own session"

    theirs: list = []
    t = threading.Thread(target=lambda: theirs.append(utils.http_session()))
    t.start()
    t.join()
    assert theirs and theirs[0] is not mine, "threads must not share a session"


def test_the_session_keeps_no_cookies():
    """A session that outlives one call would otherwise carry an upstream's
    Set-Cookie into every later request this thread makes to it — state none of
    these fetchers asks for, and that the per-call requests.get() never had."""
    cookie = cookiejar.Cookie(
        0, "sid", "abc123", None, False, "example.gov", True, False,
        "/", True, True, None, False, None, None, {})

    class _Req:                               # the surface CookiePolicy.set_ok reads
        host = origin_req_host = "example.gov"
        unverifiable = False
        type = "https"
        def get_full_url(self): return "https://example.gov/x"
        def get_host(self): return self.host
        def get_origin_req_host(self): return self.host
        def has_header(self, _n): return False
        def get_header(self, _n, d=None): return d
        def add_unredirected_header(self, _k, _v): pass

    req = _Req()
    assert not utils.http_session().cookies._policy.set_ok(cookie, req)
    # …and that this is a real difference from the default, not a vacuous check.
    assert requests.Session().cookies._policy.set_ok(cookie, req)


def test_every_upstream_host_can_hold_its_own_warm_pool():
    """~19 distinct hosts are queried. If the adapter cached fewer host-pools than
    that, each label would evict and re-handshake its way around the roster."""
    adapter = utils.http_session().get_adapter("https://example.gov")
    assert adapter._pool_connections >= 19, "too few host-pools for the roster"
    assert adapter._pool_maxsize >= 2, "a redirect-following fetcher wants more than one"


def test_the_timing_seam_still_sees_session_calls():
    """The per-host timing and the upstream budget hang off a patch of
    Session.send. That is class-level, so it sees these pooled sessions — but the
    budget is what stops one slow dataset from eating a whole label, so it is
    worth pinning rather than assuming.

    install_timing() is called here because the *application* installs the seam
    (api.serve does), not an import; it is idempotent."""
    utils.install_timing()
    srv, url = _server()
    try:
        utils.begin(budget=30, per_host=12)
        utils.http_session().get(url, timeout=5)
        recorded = [name for name, _secs in utils.drain()]
    finally:
        srv.shutdown()
    assert "127.0.0.1" in recorded, (
        f"the seam did not record the session's call by host: {recorded}")
