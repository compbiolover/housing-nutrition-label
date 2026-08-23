#!/usr/bin/env python3
"""Offline tests for national location generalization (no network, no pytest).

Run directly:  python tests/test_location.py
"""

import pandas as pd

from housing_label.simulate.location import resolve_location, Location
from housing_label.data.climate import climate_zone_for_county
from housing_label.data.egrid import egrid_for_county, US_AVG_FACTOR_KG_PER_KWH, US_AVG_LABEL
from housing_label.enrich.energy import climate_zone_factor, model_parcel_energy


def test_climate_zone_lookup():
    assert climate_zone_for_county("47157") == "3A"     # Shelby County, TN
    assert climate_zone_for_county("06037") == "3B"     # Los Angeles County, CA
    assert climate_zone_for_county("17031") == "5A"     # Cook County, IL
    # Guards the 2021 IECC vintage: Coffee County, AL moved 3A→2A in the 2021
    # update, so a table rebuilt from the pre-2021 (2015) map would fail here.
    assert climate_zone_for_county("01031") == "2A"
    # Puerto Rico is null in the PNNL numeric table; it must still resolve to a
    # real zone (carried forward, tropical 1A), not a "**********" placeholder.
    assert climate_zone_for_county("72001") == "1A"
    assert climate_zone_for_county("99999") is None     # unknown
    assert climate_zone_for_county(None) is None


def test_climate_zones_all_wellformed():
    """Every bundled county zone is a valid IECC token (1–6 with A/B/C, or 7/8) —
    guards against a rebuild leaking dBASE null placeholders or dropped moisture
    letters into the data, since climate_zone_for_county returns the value verbatim."""
    import csv
    import pathlib
    import re

    from housing_label.data import climate as _c

    zone_re = re.compile(r"^(?:[1-6][ABC]|[78])$")
    path = pathlib.Path(_c.__file__).resolve().parent / "climate_zones.csv"
    with path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) > 3000
    bad = [(r["county_fips"], r["iecc_zone"]) for r in rows
           if not zone_re.match(r["iecc_zone"].strip())]
    assert not bad, f"malformed IECC zones in climate_zones.csv: {bad[:10]}"


def test_egrid_subregion_lookup():
    # Shelby County, TN → SRTV (the pilot's TVA subregion); exactly 0.4097 kgCO2e/kWh
    # (eGRID2023 Rev 2 SRTV CO2e total-output 903.306 lb/MWh, rounded to 4 decimals).
    sub, factor = egrid_for_county("47157")
    assert "SRTV" in sub
    assert factor == 0.4097
    # Los Angeles County, CA → CAMX, a much cleaner grid than SRTV.
    ca_sub, ca_factor = egrid_for_county("06037")
    assert "CAMX" in ca_sub
    assert ca_factor < factor
    # Cook County, IL (Chicago/ComEd) → RFC West.
    il_sub, _ = egrid_for_county("17031")
    assert "RFCW" in il_sub


def test_egrid_crosswalk_integrity():
    """The bundled county→subregion crosswalk is complete and every subregion it
    references has a factor (guards a regenerated egrid_subregions.csv)."""
    from housing_label.data import egrid as e
    xwalk = e._crosswalk()
    assert len(xwalk) > 3000                       # ~3,200 US counties + territories
    assert all(len(fips) == 5 and fips.isdigit() for fips in xwalk)
    assert set(xwalk.values()) <= set(e._SUBREGION_LB_PER_MWH)   # all map to known subregions
    # Every referenced subregion resolves to a positive kgCO2e/kWh factor.
    for acro in set(xwalk.values()):
        assert e._factor_kg_per_kwh(acro) > 0


def test_egrid_fallback_to_us_average():
    for missing in ("99999", None):
        sub, factor = egrid_for_county(missing)
        assert factor == US_AVG_FACTOR_KG_PER_KWH
        assert sub == US_AVG_LABEL
        assert "average" in sub.lower()


def test_resolve_offline_sets_us_average_grid_factor():
    """Offline (no county) still gets a grid factor — the US-average fallback —
    so Environmental never silently uses the Shelby pilot default elsewhere."""
    from housing_label.data.egrid import US_AVG_FACTOR_KG_PER_KWH, US_AVG_LABEL
    loc = resolve_location(lat=35.13, lon=-89.99, allow_network=False)
    assert loc.county_fips is None
    assert loc.egrid_factor == US_AVG_FACTOR_KG_PER_KWH
    assert loc.egrid_subregion == US_AVG_LABEL


def test_environmental_caveat_tracks_grid_fallback():
    """The Environmental grid caveat fires exactly when the US-average fallback is
    used (unresolved or unmapped county), not merely when county_fips is None."""
    from housing_label.simulate.house import _approx_caveats
    from housing_label.data.egrid import US_AVG_LABEL, egrid_for_county

    sub, _ = egrid_for_county("47157")                  # Shelby → real SRTV subregion
    mapped = Location(lat=35.1, lon=-90.0, county_fips="47157", egrid_subregion=sub)
    assert not any("grid factor" in c for c in _approx_caveats(mapped))

    # Resolved but unmapped county → US-average fallback → caveat must appear.
    unmapped = Location(lat=0.0, lon=0.0, county_fips="99999",
                        egrid_subregion=US_AVG_LABEL)
    assert any("US-average grid factor" in c for c in _approx_caveats(unmapped))

    # Unresolved county (but US-average factor applied) → also flagged.
    no_county = Location(lat=0.0, lon=0.0, county_fips=None,
                         egrid_subregion=US_AVG_LABEL)
    assert any("US-average grid factor" in c for c in _approx_caveats(no_county))

    # Total resolution failure → accurate pilot-default message, not "US-average".
    assert any("pilot default" in c for c in _approx_caveats(None))


def test_climate_zone_factor_ordering():
    assert climate_zone_factor("4A") == 1.0             # baseline
    assert climate_zone_factor(None) == 1.0             # missing → no scaling
    assert climate_zone_factor("1A") < 1.0              # hot → less site energy
    assert climate_zone_factor("7") > climate_zone_factor("5A") > 1.0   # colder → more


def test_energy_scales_with_climate_zone():
    row = pd.Series({"YRBLT": 2000, "SFLA": 2000})
    hot = model_parcel_energy(row, "1A")["eui_kbtu_sqft_yr"]
    base = model_parcel_energy(row, "4A")["eui_kbtu_sqft_yr"]
    cold = model_parcel_energy(row, "7")["eui_kbtu_sqft_yr"]
    assert hot < base < cold


def test_location_dataclass_helpers():
    loc = Location(lat=34.05, lon=-118.25, county_fips="06037",
                   county_name="Los Angeles County", place_label="Los Angeles city")
    assert loc.county3 == "037"
    assert loc.label == "Los Angeles city"
    bare = Location(lat=1.0, lon=2.0)
    assert "1.0" in bare.label and "2.0" in bare.label   # falls back to coords


def test_resolve_location_offline():
    """Without network, lat/lon is preserved and geographies stay None (noted)."""
    loc = resolve_location(lat=35.13, lon=-89.99, allow_network=False)
    assert loc.lat == 35.13 and loc.lon == -89.99
    assert loc.county_fips is None and loc.tract is None
    assert "geocoder" in loc.notes


def test_year_built_distribution_resolves_from_supplied_geography():
    """Bundled, so it resolves with no network — the same as the hazard crosswalks."""
    from unittest import mock
    geo = {"county_fips": "47157", "county_name": "Shelby County",
           "state_fips": "47", "tract": "47157003100"}
    with mock.patch("housing_label.simulate.location._get",
                    side_effect=AssertionError("geocoder called")):
        loc = resolve_location(lat=35.13, lon=-89.99, allow_network=False, geography=geo)
    d = loc.year_built_distribution
    assert d and d["geo_level"] == "tract" and d["resolved"] is True
    assert d["p25"] <= d["year_built"] <= d["p75"]
    assert "year_built" not in (loc.notes or {}), "a resolved tract owes no note"


def test_no_us_fallback_note_when_the_crosswalk_is_absent():
    """A None distribution is not an unresolved one.

    If the bundled tables are missing (a broken install, or a source tree with
    nothing built), the label falls back to NSI or its own default — so a note
    saying "using the US typical" would describe a number nobody used. Same
    None-is-not-False rule as `incorporated` and `water_system`.
    """
    from unittest import mock
    geo = {"county_fips": "47157", "county_name": "Shelby County",
           "state_fips": "47", "tract": "47157003100"}
    with mock.patch("housing_label.simulate.location.year_built_data"
                    ".year_built_distribution_for", return_value=None):
        loc = resolve_location(lat=35.13, lon=-89.99, allow_network=False, geography=geo)
    assert loc.year_built_distribution is None
    assert "year_built" not in (loc.notes or {}), (
        "claimed a US fallback when no distribution was loaded at all")


def test_us_fallback_is_noted_when_it_really_happens():
    """The note must still fire for a genuine national fallback."""
    from unittest import mock
    geo = {"county_fips": "47157", "county_name": "Shelby County",
           "state_fips": "47", "tract": "47157003100"}
    us = {"year_built": 1980, "p25": 1959, "p75": 2000, "spread": 41,
          "geo_level": "us", "resolved": False, "label": "US typical",
          "source": "US typical year built (ACS) — not this building's"}
    with mock.patch("housing_label.simulate.location.year_built_data"
                    ".year_built_distribution_for", return_value=us):
        loc = resolve_location(lat=35.13, lon=-89.99, allow_network=False, geography=geo)
    assert "US typical" in (loc.notes or {}).get("year_built", "")


def test_get_pga_prefers_true_nshm_hazard_curve():
    """Primary path: get_pga returns the TRUE 2%/50yr AND 10%/50yr read off the NSHM
    hazard curve — not a 10%/50yr derived from the 0.43 ratio."""
    import housing_label.enrich.seismic_lookup as sl
    orig = sl._nshm_hazard_pga
    sl._nshm_hazard_pga = lambda lat, lon: (0.90, 0.45)   # true both (ratio 0.5, ≠ 0.43)
    try:
        pga2, pga10, source = sl.get_pga(34.0, -118.0)
        assert pga2 == 0.90 and pga10 == 0.45
        assert "NSHM" in source
    finally:
        sl._nshm_hazard_pga = orig


def test_get_pga_ratio_fallback_when_nshm_unavailable():
    """Fallback path (non-CONUS / NSHM outage): design-maps 2%/50yr × the 0.43 ratio."""
    import housing_label.enrich.seismic_lookup as sl
    sl._usgs_pga.cache_clear()
    orig_hz, orig_usgs = sl._nshm_hazard_pga, sl._usgs_pga
    sl._nshm_hazard_pga = lambda lat, lon: None           # force the fallback
    sl._usgs_pga = lambda lat, lon: 0.80
    try:
        pga2, pga10, source = sl.get_pga(34.0, -118.0)
        assert pga2 == 0.8
        assert abs(pga10 - 0.8 * sl.PGA_10_2_RATIO) < 1e-9
        assert "ratio" in source
    finally:
        sl._nshm_hazard_pga, sl._usgs_pga = orig_hz, orig_usgs
        sl._usgs_pga.cache_clear()


def test_gm_at_rate_interpolates_and_clamps():
    """Log-log interpolation of the hazard curve: exact hits, monotonicity, clamps."""
    import housing_label.enrich.seismic_lookup as sl
    xs, ys = [0.1, 0.2, 0.4], [1e-2, 1e-3, 1e-4]   # xs ascending, ys descending
    assert abs(sl._gm_at_rate(xs, ys, 1e-3) - 0.2) < 1e-9        # exact node
    assert sl._gm_at_rate(xs, ys, 5e-4) > sl._gm_at_rate(xs, ys, 5e-3)  # rarer → stronger
    assert sl._gm_at_rate(xs, ys, 1.0) == 0.1                    # very frequent → low end
    assert sl._gm_at_rate(xs, ys, 1e-9) == 0.4                   # very rare → high end


def test_get_pga_offline_no_grid_is_none():
    """With network off and no bundled grid, get_pga returns None (caller then
    falls back), never a fabricated value."""
    import housing_label.enrich.seismic_lookup as sl
    if sl._GRID_CSV.exists():
        return  # a bundled grid is present; offline would interpolate, skip
    assert sl.get_pga(34.0, -118.0, allow_network=False) is None


def test_supplied_geography_resolves_offline_without_geocoding():
    """The Census geocode is the only network call needed to learn a point's county
    and tract, and every crosswalk keyed off them is bundled. So a caller who
    already knows the FIPS — a batch job with pre-joined geography, or a fixture
    pinning a known place — should get all of that enrichment without a network
    call, rather than choosing between a live geocode and no location signal.

    Narrower than "the resolver is network-free": structure_for_point and
    footprint_for_point still go out when allow_network is set. Those degrade to
    None on their own; the geography does not.
    """
    from unittest import mock
    geo = {"county_fips": "47157", "county_name": "Shelby County",
           "state_fips": "47", "tract": "47157003100",
           "place_label": "Memphis city", "place_geoid": "4748000",
           "incorporated": True, "in_urban_area": True}
    with mock.patch("housing_label.simulate.location._get",
                    side_effect=AssertionError("geocoder called")):
        loc = resolve_location(lat=35.13, lon=-89.99, allow_network=False,
                               geography=geo)

    assert loc.county_fips == "47157" and loc.tract == "47157003100"
    assert loc.incorporated is True and loc.in_urban_area is True
    # Everything downstream of the geocode is bundled, so it must have resolved.
    assert loc.climate_zone is not None
    assert loc.egrid_factor is not None
    assert loc.climate_projection and loc.climate_projection.get("resolved")
    assert loc.wildfire and loc.wildfire.get("resolved")
    assert "not geocoded" in (loc.notes or {}).get("geocoder", "")


def test_geography_and_address_together_are_rejected():
    """They are contradictory instructions — geography says the county/tract are
    already known, address says to geocode for them. Honouring either silently
    would drop the other, which this resolver explicitly promises not to do."""
    try:
        resolve_location(address="1600 Pennsylvania Ave NW, Washington DC",
                         lat=35.13, lon=-89.99,
                         geography={"county_fips": "47157"})
    except ValueError as exc:
        assert "not both" in str(exc)
        return
    raise AssertionError("expected ValueError")


def test_supplied_geography_still_needs_a_point():
    """The bundled lookups key off FIPS, but the parcel-level enrichers key off
    lat/lon, so a geography without coordinates would be half a location."""
    try:
        resolve_location(geography={"county_fips": "47157"})
    except ValueError as exc:
        assert "lat and lon" in str(exc)
        return
    raise AssertionError("expected ValueError")


def test_offline_without_geography_leaves_the_geography_unknown():
    """The behaviour the golden snapshot was silently relying on: no geocode means
    no county and no tract, so every location dimension goes unscored."""
    loc = resolve_location(lat=35.13, lon=-89.99, allow_network=False)
    assert loc.county_fips is None and loc.tract is None
    assert "no network" in (loc.notes or {}).get("geocoder", "")


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
