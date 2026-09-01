#!/usr/bin/env python3
"""Tests for the parcel-level solar yield lookup.

``scripts/build_solar.py`` queries PVGIS ONCE per county — at that county's
gazetteer internal point — and ``solar_yield_county.csv`` serves that single number
to every parcel in the county. It was never a county average, and PVGIS is natively
a point API, so the precision was available all along and discarded at build time.

What these tests defend is mostly COMMENSURABILITY. The score comes from
breakpoints derived from the national distribution of county yields; a point value
obtained under different assumptions than the table would be scored on a curve
built for a quantity it is not. So the query and the response parse have exactly one
definition, and these tests pin that.

Runs without network (the PVGIS call is stubbed). This file alone: ``pytest tests/test_point_solar.py``.
"""

from __future__ import annotations

import pathlib
from unittest import mock

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich import solar_point as sp
from housing_label.data import solar as solar_data
from housing_label.simulate.location import Location
from housing_label.simulate.house import build_label_parts

# Monroe County TN — the bundled county figure this parcel would otherwise inherit.
COUNTY = "47123"


def _payload(e_y: float, h_i: float = 1700.0) -> dict:
    """A PVGIS PVcalc response, trimmed to the fields that are read."""
    return {"outputs": {"totals": {"fixed": {"E_y": e_y, "H(i)_y": h_i}}}}


class _Resp:
    def __init__(self, payload=None, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


# ── Commensurability with the bundled table ──────────────────────────────────
def test_the_build_script_imports_the_query_rather_than_restating_it():
    """One definition, so the county table and the point lookup cannot drift into
    asking PVGIS different questions and being scored on the same curve."""
    import scripts.build_solar as build_solar
    assert build_solar.PVGIS_PARAMS is sp.PVGIS_PARAMS
    assert build_solar.PVGIS_URL is sp.PVGIS_URL
    assert build_solar.parse_pvgis is sp.parse_pvgis


def test_the_query_pins_every_assumption_the_curve_depends_on():
    """peakpower=1 is what makes E_y a specific yield at all; the rest are the
    modelling choices the bundled quantiles were computed under."""
    assert sp.PVGIS_PARAMS["peakpower"] == "1"
    assert sp.PVGIS_PARAMS["loss"] == "14"
    assert sp.PVGIS_PARAMS["mountingplace"] == "building"
    assert sp.PVGIS_PARAMS["raddatabase"] == "PVGIS-NSRDB"
    assert sp.PVGIS_PARAMS["optimalinclination"] == "1"
    assert sp.PVGIS_PARAMS["aspect"] == "0"


def test_a_point_and_a_county_yield_score_identically():
    """Same number in, same score out — the point path must not re-implement the
    curve, or the two resolutions would disagree about the same yield."""
    for y in (485.2, 1041.3, 1368.0, 1500.7, 1850.9):
        assert (solar_data.reading_for_yield(y, 1700.0, "point")["score"]
                == solar_data.reading_for_yield(y, 1700.0, "county")["score"])


def test_the_parse_rounds_the_way_the_csv_stores_it():
    """So a point lookup and a county lookup of the same coordinates agree to the
    last digit rather than differing by a rounding step."""
    assert sp.parse_pvgis(_payload(1234.5678, 1700.4321)) == (1234.6, 1700.4)


# ── The lookup ───────────────────────────────────────────────────────────────
def test_off_network_returns_none():
    sp._yield_at.cache_clear()
    assert sp.solar_yield_near(35.5, -84.4, allow_network=False) is None


def test_outside_coverage_is_a_definitive_answer_not_a_failure():
    """PVGIS answers 400 outside its radiation database (far-north Alaska). That is
    a permanent property of the location, so it must not be retried and must not
    raise — the caller simply keeps the county figure."""
    sp._yield_at.cache_clear()
    g = mock.Mock(return_value=_Resp(status=400))
    with mock.patch.object(sp.utils, "http_session", return_value=mock.Mock(get=g)):
        assert sp.solar_yield_near(71.29, -156.79) is None
        assert g.call_count == 1, "a 400 must not be retried"


def test_an_outage_raises_rather_than_returning_none():
    """None means "no point-level answer exists here" and is indistinguishable to
    the caller from outside-coverage. An outage is a different fact and the label
    says so, so it cannot be flattened into the same return value."""
    sp._yield_at.cache_clear()
    with mock.patch.object(sp.utils, "http_session",
                           return_value=mock.Mock(get=mock.Mock(side_effect=RuntimeError("down")))), \
         mock.patch.object(sp.utils, "retry_wait"):
        try:
            sp.solar_yield_near(35.5, -84.4)
        except sp.SolarDataUnavailable:
            return
    raise AssertionError("expected SolarDataUnavailable")


def test_a_successful_lookup_reports_the_yield_and_its_provenance():
    sp._yield_at.cache_clear()
    with mock.patch.object(sp.utils, "http_session",
                           return_value=mock.Mock(get=mock.Mock(
                               return_value=_Resp(_payload(1502.3, 1899.1))))):
        got = sp.solar_yield_near(35.5, -84.4)
    assert got["yield_kwh_kwp"] == 1502.3
    assert got["irradiation"] == 1899.1
    assert "parcel" in got["source"]


# ── The refinement end to end ────────────────────────────────────────────────
def _loc():
    return Location(lat=35.5282, lon=-84.4230, state_fips="47", county_fips=COUNTY,
                    county_name="Monroe", tract="47123925302", place_label="Monroe",
                    in_urban_area=False, climate_zone="4A", egrid_subregion=None,
                    egrid_factor=None, climate_projection=None, wildfire=None,
                    structure_type="single_family", num_units=1, notes=None)


def _solar(point_result):
    """Score with the PVGIS point lookup stubbed to a result (or an exception).

    Built with allow_network=False so nothing ELSE in the pipeline reaches out —
    the flood, seismic and road-noise enrichers all query live services, and a
    solar test that depends on FEMA and USGS being up is not a solar test. The stub
    replaces the lookup wholesale, so the flag it would have been passed is moot.
    """
    target = "housing_label.enrich.solar_point.solar_yield_near"
    kw = ({"side_effect": point_result} if isinstance(point_result, Exception)
          else {"return_value": point_result})
    with mock.patch(target, **kw):
        _cfg, _r, lbl = build_label_parts(location=_loc(), allow_network=False,
                                          value=250_000)
    dim = next(d for d in lbl["dimensions"] if d["key"] == "solar")
    return dim["score"], lbl["location_notes"].get("solar", "")


def _county_score():
    return solar_data.solar_for_county(COUNTY)["score"]


def test_a_point_yield_replaces_the_county_centroid_figure():
    sunny = {"yield_kwh_kwp": 1800.0, "irradiation": 2100.0, "source": "test"}
    score, note = _solar(sunny)
    assert score == solar_data.reading_for_yield(1800.0, 2100.0, "point")["score"]
    assert score != _county_score()
    assert "at this parcel" in note


def test_the_refinement_moves_in_BOTH_directions():
    """Unlike the noise refinement this is not a credit and has no fail-safe
    direction: it is the same query without the coarsening, so a parcel that is
    genuinely dimmer than its county's centroid must score LOWER."""
    dim = {"yield_kwh_kwp": 1100.0, "irradiation": 1300.0, "source": "test"}
    bright = {"yield_kwh_kwp": 1800.0, "irradiation": 2100.0, "source": "test"}
    assert _solar(dim)[0] < _county_score() < _solar(bright)[0]


def test_no_point_answer_keeps_the_county_figure_silently():
    """Off-network and outside-coverage are not degradations worth a caveat — the
    county figure is exactly what the label showed before this existed."""
    score, note = _solar(None)
    assert score == _county_score()
    assert "unavailable" not in note


def test_an_outage_keeps_the_county_figure_and_says_so():
    """The score is unchanged, but serving a county centroid's yield under a
    parcel-level label without mentioning it is the failure mode being avoided."""
    score, note = _solar(sp.SolarDataUnavailable("down"))
    assert score == _county_score()
    assert "unavailable" in note.lower()


def test_off_network_runs_never_reach_for_the_network():
    """The batch path and --no-network runs must not acquire a live dependency.

    Patching the shared session rather than one module's requests.get makes this
    stricter than it was: ANY fetcher reaching for the network fails it, not just
    the solar one."""
    with mock.patch.object(sp.utils, "http_session",
                           side_effect=AssertionError("network!")):
        _cfg, _r, lbl = build_label_parts(location=_loc(), allow_network=False,
                                          value=250_000)
    dim = next(d for d in lbl["dimensions"] if d["key"] == "solar")
    assert dim["score"] == _county_score()


def test_the_note_keeps_the_percentile_claim_honest():
    """The curve is built from COUNTY quantiles. Scoring a point against it is
    valid, but the sentence it produces has to stay true."""
    _score, note = _solar({"yield_kwh_kwp": 1800.0, "irradiation": 2100.0,
                           "source": "test"})
    assert "US counties" in note


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("point-solar tests passed")
