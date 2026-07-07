#!/usr/bin/env python3
"""Golden-snapshot regression test for the scored label payload.

The rest of the suite asserts *relative* invariants (higher exposure → lower
score, perils summing to the total, structural field presence). None of that
catches a change that uniformly *shifts* absolute scores — a recalibrated
breakpoint, a re-weighted composite, a tweaked EAL constant — which would sail
through while silently moving every published grade.

This test locks the numeric core of ``label_payload`` for a fixed matrix of
``(preset × location)`` cases scored **offline** (``allow_network=False``), so
the output is fully deterministic: the five construction-driven dimensions plus
the offline location signal have no network and no randomness. Any intended
recalibration must regenerate the snapshot, turning a would-be silent drift into
a reviewable diff:

    UPDATE_GOLDEN=1 python -m pytest tests/test_golden_label.py     # rewrite
    python -m pytest tests/test_golden_label.py                      # verify

Runs directly too:  ``python tests/test_golden_label.py``.
"""

import json
import os
import pathlib

from housing_label.simulate.house import build_label_parts, label_payload

GOLDEN = pathlib.Path(__file__).parent / "golden" / "label_snapshot.json"

# (name, preset, lat, lon). Two Shelby profiles spanning the score range plus a
# cross-county (Los Angeles) point, so a change to the county-resolved legs
# (infrastructure cost curve, wildfire/seismic crosswalks) is caught too.
CASES = [
    ("baseline_shelby",       "baseline",       35.13,  -89.99),
    ("worst_case_shelby",     "worst-case",     35.13,  -89.99),
    ("icf_passive_shelby",    "icf-passive",    35.13,  -89.99),
    ("fortified_gold_shelby", "fortified-gold", 35.13,  -89.99),
    ("baseline_la",           "baseline",       34.05, -118.24),
    ("icf_passive_la",        "icf-passive",    34.05, -118.24),
]

# Round every float this many places before comparing/storing, so cross-platform
# / cross-Python floating-point noise can't flake the test. Scores are already
# emitted at 0.1 and dollar flows as ints, so 4 dp is comfortably lossless.
_PLACES = 4


def _round(v):
    return round(v, _PLACES) if isinstance(v, float) else v


def _core(preset: str, lat: float, lon: float) -> dict:
    """The stable, numeric heart of the offline payload for one case."""
    cfg, r, lbl = build_label_parts(preset=preset, lat=lat, lon=lon,
                                    allow_network=False)
    p = label_payload(cfg, r, lbl)
    return {
        "dimensions": [
            {"key": d.get("key"),
             "score": _round(d.get("score")),
             "national_grade": d.get("national_grade")}
            for d in p["dimensions"]
        ],
        "composite_score": _round(p["composite_score"]),
        "composite_national_grade": p["composite_national_grade"],
        "n_scored": p["n_scored"],
        "cost": {k: _round(v) for k, v in (p.get("cost") or {}).items()},
        "total_loss": _round(p["total_loss"]),
        "fire_loss": _round(p["fire_loss"]),
    }


def _build_all() -> dict:
    return {name: _core(preset, lat, lon) for name, preset, lat, lon in CASES}


def test_label_payload_matches_golden():
    current = _build_all()

    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        print(f"  wrote golden snapshot: {GOLDEN}")
        return

    assert GOLDEN.exists(), (
        f"missing golden snapshot {GOLDEN} — generate it once with "
        "UPDATE_GOLDEN=1 python -m pytest tests/test_golden_label.py")
    expected = json.loads(GOLDEN.read_text())

    # Per-case diff so a failure names exactly what moved, not "big dict != dict".
    assert set(current) == set(expected), (
        f"case set changed: {sorted(set(current) ^ set(expected))}")
    for name in expected:
        assert current[name] == expected[name], (
            f"scoring drift in case {name!r} — if intentional, regenerate with "
            f"UPDATE_GOLDEN=1.\n  expected: {expected[name]}\n  actual:   {current[name]}")


def _run_all():
    test_label_payload_matches_golden()
    print("  ok  test_label_payload_matches_golden")
    print("\n1 test passed.")


if __name__ == "__main__":
    _run_all()
