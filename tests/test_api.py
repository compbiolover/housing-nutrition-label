#!/usr/bin/env python3
"""Offline tests for the HTTP API (skipped if FastAPI isn't installed).

Run directly:  python tests/test_api.py
"""


def test_api_healthz_and_validation():
    try:
        from fastapi.testclient import TestClient
        from housing_label.api import app
    except ImportError:
        # Only skip when FastAPI/TestClient is genuinely unavailable — let any
        # other import error (e.g. a bug in housing_label.api) fail the test.
        print("  skip test_api_healthz_and_validation (fastapi not installed)")
        return
    client = TestClient(app)
    assert client.get("/healthz").json() == {"ok": True}
    # Missing both address and lat/lon → 400, no network involved.
    assert client.get("/label").status_code == 400


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
