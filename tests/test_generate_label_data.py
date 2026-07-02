#!/usr/bin/env python3
"""Offline tests for the label-data generator's confidence/band helpers.

No network and no simulator run — these exercise the pure provenance → tier
rubric (research/uncertainty-confidence-research.md §3) and the climate-band
parser directly, against a mock label. Run directly:

    python tests/test_generate_label_data.py

(pytest will also collect the test_* functions if it is installed.)
"""

import pathlib
import sys

# Make this runnable without an editable install: put the repo root (for the
# ``scripts`` package) and ``src`` (for ``housing_label``) on the path.
_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.generate_label_data import _confidence, _bands, DIMENSIONS  # noqa: E402


def _mock_label(**over):
    """A stand-in for simulate_all_dimensions() output, carrying just the
    provenance fields the helpers read."""
    label = {
        "location_notes": {
            "health": "CDC PLACES (tract 47157003100)",
            "socioeconomic": "no CENSUS_API_KEY",
            "walkability": "no WALKSCORE_API_KEY",
            "climate": "CMIP6-LOCA2 (tract 47157003100, SSP2-4.5 mid-century)",
        },
        "metrics": {"Climate band (SSP2-4.5–5-8.5, mid-century)": "49.6–47.0"},
    }
    label.update(over)
    return label


def test_confidence_tiers_match_research_doc():
    """Reproduces the §3.3 worked table for the Cooper-Young sample."""
    scores = {"resilience": 64.1, "energy": 77.0, "durability": 46.1,
              "environmental": 68.4, "infrastructure": 40.2, "health": 87.6,
              "socioeconomic": None, "walkability": None, "climate": 49.6}
    tiers = _confidence(_mock_label(), scores)
    assert tiers == {
        "resilience": "high", "energy": "high", "durability": "high",
        "environmental": "moderate", "infrastructure": "moderate", "health": "high",
        "socioeconomic": "low", "walkability": "low", "climate": "moderate",
    }, tiers


def test_confidence_low_when_unscored():
    """A dimension with no score (e.g. vacant-parcel durability) → Low."""
    scores = {k: 50.0 for k, _ in DIMENSIONS}
    scores["durability"] = None
    tiers = _confidence(_mock_label(), scores)
    assert tiers["durability"] == "low", tiers


def test_confidence_wide_band_dims_are_moderate():
    """Env / infrastructure / climate carry documented wide/scenario bands →
    held at Moderate even when fully scored."""
    scores = {k: 70.0 for k, _ in DIMENSIONS}
    tiers = _confidence(_mock_label(), scores)
    for k in ("environmental", "infrastructure", "climate"):
        assert tiers[k] == "moderate", (k, tiers[k])
    for k in ("resilience", "energy", "durability", "health"):
        assert tiers[k] == "high", (k, tiers[k])


def test_bands_parse_climate_interval():
    """'49.6–47.0' parses to {low: 47.0, high: 49.6} (ordered by magnitude)."""
    assert _bands(_mock_label()) == {"climate": {"low": 47.0, "high": 49.6}}


def test_bands_absent_without_climate_metric():
    assert _bands(_mock_label(metrics={})) == {}


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
