#!/usr/bin/env python3
"""Offline tests for the confidence/cost fields in the shared label payload.

Confirms label_payload (used by both the CLI --json and the HTTP API) carries
the data-quality confidence channel and the lifetime-cost flows, so the live
label can render dots, the climate whisker, and the cost strip. No network.

Run directly:  python tests/test_label_payload.py
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.simulate.house import (  # noqa: E402
    label_payload, cost_flows, dimension_details)


def _parts():
    cfg = {"year_built": 2000, "construction": "frame", "foundation": "slab",
           "condition": "average", "units": 1, "sqft": 2000, "lot_acres": 0.25,
           "flood_zone": "X", "value": 250000, "value_source": None,
           "lat": 35.13, "lon": -89.99}
    r = {"total_loss": 115.4, "fire_loss": 7.0, "total_score": 64.0}
    label = {
        "dimensions": [
            {"key": "resilience", "label": "Disaster Resilience", "score": 64.1, "national_grade": "B"},
            {"key": "energy", "label": "Energy Efficiency", "score": 77.0, "national_grade": "B"},
            {"key": "socioeconomic", "label": "Socioeconomic", "score": None, "national_grade": None},
            {"key": "climate", "label": "Climate Projections", "score": 49.6, "national_grade": "C"},
        ],
        "composite_score": 63.6, "composite_national_grade": "B", "n_scored": 3,
        "metrics": {"est_monthly_energy_cost": 133.0,
                    "Climate band (SSP2-4.5–5-8.5, mid-century)": "49.6–47.0"},
        "census_tract": "47157003100",
        "location_notes": {"socioeconomic": "no CENSUS_API_KEY", "climate": "CMIP6-LOCA2 (tract …)"},
    }
    return cfg, r, label


def test_payload_carries_confidence_channel():
    cfg, r, label = _parts()
    p = label_payload(cfg, r, label)
    assert p["confidence"] == {
        "resilience": "high", "energy": "high",
        "socioeconomic": "low", "climate": "moderate",
    }, p["confidence"]
    assert p["bands"] == {"climate": {"low": 47.0, "high": 49.6}}, p["bands"]
    assert p["confidence_notes"] and "socioeconomic" in p["confidence_notes"]
    assert isinstance(p["confidence_legend"], str) and p["confidence_legend"]


def test_payload_carries_cost_flows():
    cfg, r, label = _parts()
    p = label_payload(cfg, r, label)
    # $133/mo → $1,596/yr energy; total_loss 115.4 → 115 expected annual loss.
    assert p["cost"] == {"expectedAnnualLoss": 115, "annualEnergyCost": 1596}, p["cost"]


def test_cost_flows_without_energy():
    """When the energy metric is absent, only the loss flow is emitted."""
    _cfg, r, label = _parts()
    label["metrics"].pop("est_monthly_energy_cost")
    assert cost_flows(r, label) == {"expectedAnnualLoss": 115}


def _rich_parts():
    """A fixture with the driver metrics the models emit, so the per-dimension
    detail rows are fully populated."""
    cfg, r, label = _parts()
    r.update({"flood_loss": 60.2, "tornado_loss": 40.0, "seismic_loss": 1.1})
    label["metrics"].update({
        "eui_kbtu_sqft_yr": 42.3, "fiscal_ratio": 1.12,
        "est_property_tax": 2100.0, "est_annual_infra_cost": 1875.0,
        "durability_material_class": "wood frame", "durability_remaining_life_pct": 78.0,
        "durability_components_past_life": 1, "durability_condition": "average",
        "env_total_co2e_kg_yr": 8421.0, "env_operational_co2e_kg_yr": 6100.0,
        "env_embodied_co2e_kg_yr": 1800.0, "env_water_gal_yr": 41000.0,
    })
    return cfg, r, label


def _rowmap(rows):
    return {row["label"]: row["value"] for row in rows}


def test_details_present_for_every_dimension():
    cfg, r, label = _rich_parts()
    det = label_payload(cfg, r, label)["details"]
    for key in ("resilience", "energy", "durability", "environmental",
                "infrastructure", "health", "socioeconomic", "walkability", "climate"):
        assert key in det, key
        assert isinstance(det[key], list)


def test_details_carry_real_formatted_numbers():
    cfg, r, label = _rich_parts()
    det = dimension_details(cfg, r, label)
    res = _rowmap(det["resilience"])
    assert res["Expected annual loss"] == "$115/yr"
    assert res["Flood"] == "$60/yr" and res["Wildfire"] == "$7/yr"
    assert _rowmap(det["energy"])["Energy use intensity"] == "42.3 kBTU/sqft·yr"
    assert _rowmap(det["durability"])["Remaining service life"] == "78%"
    assert _rowmap(det["environmental"])["Total carbon footprint"] == "8,421 kg CO₂e/yr"
    assert _rowmap(det["infrastructure"])["Fiscal ratio (tax ÷ cost to serve)"] == "1.12"


def test_details_explain_unscored_and_omit_missing():
    cfg, r, label = _rich_parts()
    det = dimension_details(cfg, r, label)
    # Socioeconomic is None here → a single explanatory Status row with the note.
    socio = _rowmap(det["socioeconomic"])
    assert "Not scored here" in socio["Status"] and "CENSUS_API_KEY" in socio["Status"]
    # Climate is scored → carries the mid-century band from metrics.
    climate = _rowmap(det["climate"])
    assert climate["Mid-century band (SSP2-4.5 – 5-8.5)"] == "49.6–47.0"
    # A row whose value is unavailable is dropped, never emitted blank.
    assert all(row["value"] is not None for rows in det.values() for row in rows)


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
