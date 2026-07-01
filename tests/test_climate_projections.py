#!/usr/bin/env python3
"""Offline tests for the climate-projection lookup (no network, no pytest).

Run directly:  python tests/test_climate_projections.py
"""

import csv
import gzip
import statistics

from housing_label.data import climate_projections as cp
from housing_label.score.all_dimensions import score_climate
import pandas as pd


def _read_tract_csv() -> list[dict]:
    """The bundled tract crosswalk rows (gzip or plain)."""
    path = cp._TRACT_CSV_GZ if cp._TRACT_CSV_GZ.exists() else cp._TRACT_CSV
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as f:
        return list(csv.DictReader(f))


def test_resolved_county_has_bands_and_drivers():
    d = cp.climate_projection_for_county("47157")   # Shelby County, TN
    assert d["resolved"] is True
    assert d["geo_level"] == "county"
    assert "Shelby" in d["label"]
    # A concrete 0–100 headline (low band) plus a low/high band.
    assert 0 <= d["score"] <= 100
    assert d["score"] == d["score_low"]
    # Higher emissions → more hazard → never a higher score than the low band.
    assert d["score_high"] <= d["score_low"]
    # Four hazard legs and six raw drivers, each with hist/low/high.
    assert set(d["hazards"]) == {"heat", "precip", "drought", "fire"}
    assert set(d["drivers"]) >= {"heat_days95", "heat_days100", "drought_consecdd", "fire_fwi"}
    assert set(d["drivers"]["heat_days95"]) == {"hist", "low", "high"}
    # ClimRR is a single RCP8.5 pathway, so the fire leg has no low/high spread.
    assert d["hazards"]["fire"]["low"] == d["hazards"]["fire"]["high"]


def test_hotter_county_scores_below_milder_county():
    # Memphis (hot, many >95°F days) should score worse than Boston (mild).
    memphis = cp.climate_projection_for_county("47157")["score"]
    boston = cp.climate_projection_for_county("25025")["score"]
    assert memphis < boston


def test_fire_leg_lower_in_fire_prone_west():
    # The ClimRR Fire Weather Index leg must make a fire-prone desert county score
    # far worse on fire than a humid eastern one. San Bernardino, CA (desert SW)
    # vs. Shelby County, TN (humid Memphis).
    sb = cp.climate_projection_for_county("06071")["hazards"]["fire"]["low"]
    memphis = cp.climate_projection_for_county("47157")["hazards"]["fire"]["low"]
    assert sb is not None and memphis is not None
    assert sb < memphis          # higher FWI → lower fire sub-score
    assert sb <= 5               # extreme fire weather → near-zero
    # The fire metric scorer is non-increasing as projected FWI rises.
    scores = [cp._metric_score("fire_fwi", x) for x in (0, 10, 20, 40, 80)]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 100 and scores[-1] == 0


def test_fire_leg_bundled_for_conus():
    # Every CONUS county carries the fire leg; the ClimRR grid excludes HI/PR, and
    # a county missing the fire columns still scores from the remaining legs
    # (skipped, not nulled).
    rows = list(csv.DictReader(cp._CSV.open()))
    with_fire = [r for r in rows if r.get("fire_fwi_low", "") != ""]
    assert len(with_fire) > 3000, "fire leg should be bundled for ~all CONUS counties"
    # A synthetic row with the fire metric absent still yields a composite from the
    # other three legs (graceful-optional leg).
    conus = next(r for r in with_fire if r["geoid"] == "47157")
    stripped = {k: v for k, v in conus.items() if not k.startswith("fire_")}
    assert cp._band_score(stripped, "low") is not None


def test_unmapped_and_none_fall_back_to_national_average():
    nat_low, nat_high = cp._national_average()
    for fips in ("99999", None):
        d = cp.climate_projection_for_county(fips)
        assert d["resolved"] is False
        assert d["geo_level"] == "us"
        assert d["label"] == cp.US_AVG_LABEL
        assert d["score"] == nat_low
        assert d["score_high"] == nat_high
        assert d["hazards"] == {} and d["drivers"] == {}


def test_tract_crosswalk_bundled():
    # The sub-county LOCA2 tract crosswalk is bundled (sampled from the ~6 km grid).
    assert cp._TRACT_CSV_GZ.exists() or cp._TRACT_CSV.exists()
    assert len(cp._tract_table()) > 70000


def test_tract_resolves_at_tract():
    # A tract present in the bundled crosswalk resolves at tract resolution.
    rows = _read_tract_csv()
    geoid = next(r["geoid"] for r in rows if r["geoid"].startswith("47157"))  # Shelby, TN
    d = cp.climate_projection_for_tract(geoid)
    assert d["resolved"] is True and d["geo_level"] == "tract"
    assert 0 <= d["score"] <= 100 and d["score_high"] <= d["score_low"]
    # A tract id that lost its leading zero (read as a number) is padded to 11
    # before lookup, so it still resolves (tract or parent county) — never US.
    al = cp.climate_projection_for_tract("1001020100")     # 10 digits → "01001020100"
    assert al["resolved"] is True and al["geo_level"] in ("tract", "county")


def test_tract_in_unmapped_county_and_none_fall_back_to_us():
    nat_low, _ = cp._national_average()
    for tract in ("99999000100", None):
        d = cp.climate_projection_for_tract(tract)
        assert d["resolved"] is False
        assert d["geo_level"] == "us"
        assert d["score"] == nat_low


def test_score_monotonic_in_projected_heat():
    # The metric scorer must be non-increasing as projected hazard rises.
    xs = [0, 10, 30, 60, 100, 200]
    scores = [cp._metric_score("heat_days95", x) for x in xs]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 100 and scores[-1] == 0


def test_crosswalk_integrity():
    rows = list(csv.DictReader(cp._CSV.open()))
    assert len(rows) >= 3000, "expected ~3100+ counties"
    geoids = [r["geoid"] for r in rows]
    assert len(geoids) == len(set(geoids)), "duplicate county FIPS"
    for r in rows:
        assert len(r["geoid"]) == 5 and r["geoid"].isdigit()
        assert r["geo_level"] == "county"
    # Tract crosswalk: unique 11-digit geoids, all tagged geo_level=tract.
    trows = _read_tract_csv()
    assert len(trows) >= 70000, "expected ~85k tracts"
    tgeoids = [r["geoid"] for r in trows]
    assert len(tgeoids) == len(set(tgeoids)), "duplicate tract GEOID"
    for r in trows:
        assert len(r["geoid"]) == 11 and r["geoid"].isdigit()
        assert r["geo_level"] == "tract"


def test_intra_county_tract_variation_exists():
    # The whole point of the LOCA2 build: tracts within a large, diverse county
    # genuinely differ — the inverse of CMRA's tract layer (which broadcast the
    # county value, zero spread). San Bernardino, CA (06071) spans coast→desert.
    trows = _read_tract_csv()
    sb = [float(r["heat_days95_low"]) for r in trows
          if r["geoid"].startswith("06071") and r["heat_days95_low"]]
    assert len(sb) > 50
    assert max(sb) - min(sb) > 1.0


def test_county_is_mean_of_its_tracts():
    # Build invariant: a county value is the mean of its tracts' samples.
    cfips = "06071"
    trows = _read_tract_csv()
    tract_vals = [float(r["heat_days95_low"]) for r in trows
                  if r["geoid"].startswith(cfips) and r["heat_days95_low"]]
    county_row = next(r for r in csv.DictReader(cp._CSV.open()) if r["geoid"] == cfips)
    assert abs(float(county_row["heat_days95_low"]) - statistics.mean(tract_vals)) < 0.5


def test_pipeline_scorer_maps_counties():
    # No county column → single-county pilot default (Shelby).
    out = score_climate(pd.DataFrame({"x": [1, 2]}))
    assert out.tolist() == [cp.climate_projection_for_county("47157")["score"]] * 2
    # With a county column → per-row mapping incl. national-average fallback.
    out = score_climate(pd.DataFrame({"county_fips": ["47157", "06037", "99999"]}))
    assert out.tolist() == [
        cp.climate_projection_for_county("47157")["score"],
        cp.climate_projection_for_county("06037")["score"],
        cp.climate_projection_for_county(None)["score"],
    ]


def test_pipeline_scorer_maps_tracts():
    # A tract column takes precedence and resolves tract→county→US.
    out = score_climate(pd.DataFrame({"tract": ["47157000100", "06037000100", "99999000100"]}))
    assert out.tolist() == [
        cp.climate_projection_for_tract("47157000100")["score"],
        cp.climate_projection_for_tract("06037000100")["score"],
        cp.climate_projection_for_tract("99999000100")["score"],
    ]


def test_pipeline_scorer_handles_numeric_geoid_columns():
    # A numeric county column with a NaN forces float dtype, so GEOIDs stringify
    # as "47157.0" — must still resolve to the county, not the US fallback.
    out = score_climate(pd.DataFrame({"county_fips": [47157, None]}))
    assert out.iloc[0] == cp.climate_projection_for_county("47157")["score"]
    assert out.iloc[1] == cp.climate_projection_for_county(None)["score"]
    # Same for a numeric 11-digit tract column.
    out = score_climate(pd.DataFrame({"tract": [47157000100, None]}))
    assert out.iloc[0] == cp.climate_projection_for_tract("47157000100")["score"]


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
