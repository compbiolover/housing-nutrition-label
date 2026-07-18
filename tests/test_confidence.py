#!/usr/bin/env python3
"""Offline tests for the shared confidence rubric (housing_label.confidence).

No network — exercises the provenance → tier rubric
(research/uncertainty-confidence-research.md §3) and the climate score-band
parser against a mock label dict (the shape produced by
simulate_all_dimensions and consumed by both the API payload and the generator).

Run directly:  python tests/test_confidence.py
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.confidence import (  # noqa: E402
    confidence_for_label, bands_for_label,
)

_DIM_KEYS = ["resilience", "energy", "durability", "environmental",
             "infrastructure", "health", "air_quality", "noise", "socioeconomic",
             "walkability", "climate", "solar"]


def _mock_label(scores=None, notes=None, metrics=None):
    """A stand-in for simulate_all_dimensions() output."""
    scores = scores or {}
    return {
        "dimensions": [{"key": k, "score": scores.get(k, 70.0)} for k in _DIM_KEYS],
        "location_notes": notes if notes is not None else {
            "health": "CDC PLACES (tract 47157003100)",
            "air_quality": "CDC Tracking PM2.5/ozone (tract 47157003100) + EPA radon zone (county 47157)",
            "noise": "BTS transportation-noise exposure (tract 47157003100)",
            "socioeconomic": "no CENSUS_API_KEY",
            "walkability": "EPA National Walkability Index (tract 47157003100)",
            "climate": "CMIP6-LOCA2 (tract 47157003100, SSP2-4.5 mid-century)",
            "solar": "PVGIS-NSRDB rooftop yield (county 47157)",
        },
        "metrics": metrics if metrics is not None else {
            "Climate band (SSP2-4.5–5-8.5, mid-century)": "49.6–47.0",
        },
    }


def test_tiers_match_research_doc_sample():
    """Reproduces the §3.3 worked table for the Cooper-Young sample
    (socioeconomic/walkability null → Low; env/infra/climate → Moderate)."""
    scores = {"socioeconomic": None, "walkability": None}
    tiers = confidence_for_label(_mock_label(scores=scores))
    assert tiers == {
        "resilience": "high", "energy": "high", "durability": "high",
        "environmental": "moderate", "infrastructure": "moderate", "health": "high",
        "air_quality": "high", "noise": "high", "solar": "high",
        "socioeconomic": "low", "walkability": "low", "climate": "moderate",
    }, tiers


def test_unscored_dimension_is_low():
    """A dimension with no score (e.g. vacant-parcel durability) → Low."""
    tiers = confidence_for_label(_mock_label(scores={"durability": None}))
    assert tiers["durability"] == "low", tiers


def test_measured_survey_dims_high_when_scored():
    """With a measured-source note (no 'no …KEY' signal) and a real score, socio/
    walk are measured → High, not Low."""
    tiers = confidence_for_label(_mock_label(notes={
        "socioeconomic": "Census ACS (tract 47157003100)",
        "walkability": "EPA National Walkability Index (tract 47157003100)",
    }))
    assert tiers["socioeconomic"] == "high", tiers
    assert tiers["walkability"] == "high", tiers


def test_wide_band_dims_capped_at_moderate():
    tiers = confidence_for_label(_mock_label())
    for k in ("environmental", "infrastructure", "climate"):
        assert tiers[k] == "moderate", (k, tiers[k])


def test_bands_parse_climate_interval():
    """'49.6–47.0' → {low: 47.0, high: 49.6} (ordered by magnitude)."""
    assert bands_for_label(_mock_label()) == {"climate": {"low": 47.0, "high": 49.6}}


def test_bands_absent_without_climate_metric():
    assert bands_for_label(_mock_label(metrics={})) == {}


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
