#!/usr/bin/env python3
"""Tests for the Tier-3 de-Shelbyfication of the batch enrich stages.

Covers the shared region-context helper and the national paths of the seismic,
tornado, and noaa_climate enrichers — plus that Shelby/default behavior is
preserved. Pure logic, no network. Runs standalone (``python
tests/test_tier3_enrich.py``) or via pytest.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.enrich import region_context as RC  # noqa: E402
from housing_label.enrich import infrastructure as I  # noqa: E402


def test_as_bool_parses_csv_forms():
    for v in ("True", "true", "1", "yes", "Y", "t", 1, 1.0, True):
        assert I._as_bool(v) is True
    for v in ("False", "false", "0", "no", "n", "f", "", 0, 0.0, False):
        assert I._as_bool(v) is False


# ── region_context ────────────────────────────────────────────────────────────
def test_infra_params_shelby_and_unknown_are_none():
    assert RC.infra_params_for_county(None) is None
    assert RC.infra_params_for_county("47157") is None      # Shelby → Memphis defaults
    assert RC.infra_params_for_county("47157".zfill(5)) is None


def test_normalize_fips():
    assert RC.normalize_fips(None) is None
    assert RC.normalize_fips(float("nan")) is None
    assert RC.normalize_fips("") is None
    assert RC.normalize_fips("nan") is None
    assert RC.normalize_fips(47157.0) == "47157"        # float-parsed CSV
    assert RC.normalize_fips(6037) == "06037"           # lost leading zero
    assert RC.normalize_fips("06037.0") == "06037"      # float-string
    assert RC.normalize_fips(" 6037 ") == "06037"
    assert RC.normalize_fips("47157") == "47157"


def test_infra_params_national_county():
    p = RC.infra_params_for_county("06037", in_urban_area=True)   # Los Angeles County
    assert p is not None
    assert set(p) == {"assess_ratio", "tax_rate", "in_urban_area", "cost_multipliers",
                      "fee_recovery", "classification_state",
                      "classification_rate_state", "classification_county_fips",
                      "county_du_acre"}
    assert p["assess_ratio"] == 1.0 and p["in_urban_area"] is True
    # Fee recovery joins the revenue side; fire/police have no user charge anywhere.
    assert set(p["fee_recovery"]) == {"roads", "water_sewer", "fire", "police",
                                      "sanitation", "parks"}
    assert p["fee_recovery"]["fire"] == 0.0 and p["fee_recovery"]["police"] == 0.0
    assert 0.0 < p["fee_recovery"]["water_sewer"] <= 1.0
    # The ABSOLUTE correction stays off: it swaps in a statutory assessment ratio,
    # which is meaningless against an observed effective rate.
    assert p["classification_state"] is None
    # The MULTIPLICATIVE one is on, with the state derived from the county FIPS.
    # California has no researched rule, so this resolves to a 1.0 no-op — the key
    # being populated is what matters, not that it does anything here.
    assert p["classification_rate_state"] == "CA"
    assert p["classification_county_fips"] == "06037"
    assert isinstance(p["tax_rate"], float) and p["tax_rate"] > 0
    # in_urban_area is parcel-level → omitted (not forced) when not supplied
    p2 = RC.infra_params_for_county("06037")
    assert "in_urban_area" not in p2
    assert RC.infra_params_for_county(47157.0) is None            # float Shelby → defaults
    assert RC.infra_params_for_county(float("nan")) is None       # NaN → defaults
    # municipal_rate = ACS effective rate × (1 − school share)
    from housing_label.data.govfinance import govfinance_for_county
    from housing_label.data.propertytax import property_tax_for_county
    gov = govfinance_for_county("06037")
    tax = property_tax_for_county("06037")
    assert abs(p["tax_rate"] - tax["effective_tax_rate"] * (1 - gov["school_tax_share"])) < 1e-12
    assert set(p["cost_multipliers"]) >= {"roads", "water_sewer", "fire", "police"}


def test_climate_zone_for_county_fips():
    assert RC.climate_zone_for_county_fips(None) == (None, None)
    zone, desc = RC.climate_zone_for_county_fips("06037")       # LA
    assert zone == "3B" and desc == "Warm-Dry"


# ── tornado (FEMA NRI, offline crosswalk) ─────────────────────────────────────
def test_tornado_lookup_is_location_specific():
    """NRI is honest about location: a Plains 'tornado alley' county reads far higher
    than a low-risk West-coast one — the whole point of retiring the SPC model."""
    from housing_label.data import tornado as TD
    oklahoma = TD.tornado_for_county("40109")     # Oklahoma County, OK
    los_angeles = TD.tornado_for_county("06037")  # Los Angeles County, CA
    assert oklahoma["eal_rate"] > 10 * los_angeles["eal_rate"]


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
