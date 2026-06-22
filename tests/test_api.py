#!/usr/bin/env python3
"""Offline tests for the HTTP API (skipped if FastAPI isn't installed).

Run directly:  python tests/test_api.py
"""


def test_api_healthz_and_validation():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        # Skip only when FastAPI/TestClient is genuinely unavailable.
        print("  skip test_api_healthz_and_validation (fastapi not installed)")
        return
    # Imported outside the guard so a real import error in housing_label.api
    # (e.g. a broken import/rename) fails the test instead of being skipped.
    from housing_label.api import app
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
