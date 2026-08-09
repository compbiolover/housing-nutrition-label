#!/usr/bin/env python3
"""Offline tests for bulk scoring (no network, no pytest).

Run directly:  python tests/test_batch.py
"""

import io

from housing_label import batch as B
from housing_label.simulate.dimensions import DIMENSIONS
from housing_label.simulate.house import build_label_parts, label_payload

SHELBY_TRACT = "47157003100"


def _rows(*extra, **common):
    base = {"lat": "35.15", "lon": "-89.85", "tract": SHELBY_TRACT,
            "year_built": "1995", "sqft": "1800"}
    base.update(common)
    return [dict(base, **e) for e in (extra or ({},))]


# ── The claim that justifies driving the live path ───────────────────────────
def test_batch_matches_the_live_path_exactly():
    """A parcel scored in bulk must equal the same parcel scored through the API.

    This is the whole reason bulk scoring drives build_label_parts instead of
    reviving score/all_dimensions.py: agreement by construction rather than by
    convention. The first thing a customer does is spot-check a few rows against
    GET /label, and a discrepancy there is unexplainable.
    """
    geo = {"tract": SHELBY_TRACT, "county_fips": "47157", "state_fips": "47"}
    cfg, r, label = build_label_parts(lat=35.15, lon=-89.85, allow_network=False,
                                      geography=geo, allow_non_residential=True,
                                      year_built=1995, sqft=1800)
    live = label_payload(cfg, r, label)
    rec = next(B.score_rows(_rows(), allow_network=False))

    assert rec["error"] is None, rec["error"]
    assert rec["composite_score"] == live["composite_score"]
    assert rec["building_score"] == live["construction_score"]
    assert rec["site_score"] == live["location_score"]
    for d in live["dimensions"]:
        assert rec[f"{d['key']}_score"] == d["score"], d["key"]
        assert rec[f"{d['key']}_national_grade"] == d["national_grade"], d["key"]


# ── Geography is what makes offline bulk scoring worth anything ──────────────
def test_pre_joined_tract_scores_every_dimension_with_no_network():
    rec = next(B.score_rows(_rows(), allow_network=False))
    assert rec["n_scored"] == len(DIMENSIONS) == 13, rec["n_scored"]
    for key, _ in DIMENSIONS:
        assert rec[f"{key}_score"] is not None, key


def test_without_geography_the_location_dimensions_are_honestly_unscored():
    """Not an error, and not a fabricated number — just fewer dimensions.

    The failure this guards against is the opposite: silently returning a
    five-dimension label that looks like a thirteen-dimension one.
    """
    rec = next(B.score_rows(_rows({"tract": ""}), allow_network=False))
    assert rec["error"] is None
    assert rec["n_scored"] < 13
    assert rec["resilience_score"] is not None       # construction side still works
    assert rec["air_quality_score"] is None          # needs the tract


def test_tract_alone_implies_county_and_state():
    parsed = B.parse_row({"lat": "35.15", "lon": "-89.85", "tract": SHELBY_TRACT})
    assert parsed["geography"]["county_fips"] == "47157"
    assert parsed["geography"]["state_fips"] == "47"
    # A GEOID that lost its leading zero to a spreadsheet still resolves.
    parsed = B.parse_row({"lat": "32.5", "lon": "-86.5", "tract": "1001020100"})
    assert parsed["geography"]["tract"] == "01001020100"
    assert parsed["geography"]["county_fips"] == "01001"


def test_address_and_geography_are_mutually_exclusive():
    try:
        B.parse_row({"address": "1 Main St", "tract": SHELBY_TRACT})
    except ValueError as exc:
        assert "not both" in str(exc)
    else:
        raise AssertionError("address + geography should be rejected")


# ── One bad parcel must not end a 400,000-row run ────────────────────────────
def test_bad_rows_are_recorded_not_raised():
    rows = [
        {"id": "ok", "lat": "35.15", "lon": "-89.85", "tract": SHELBY_TRACT},
        {"id": "no-position"},
        {"id": "bad-year", "lat": "35.15", "lon": "-89.85", "year_built": "nineteen"},
        {"id": "ok2", "lat": "35.15", "lon": "-89.85", "tract": SHELBY_TRACT},
    ]
    recs = list(B.score_rows(rows, allow_network=False))
    assert len(recs) == 4
    assert [r["id"] for r in recs] == ["ok", "no-position", "bad-year", "ok2"]
    assert recs[0]["error"] is None and recs[3]["error"] is None
    assert recs[1]["error"] and recs[2]["error"]
    assert "year_built" in recs[2]["error"]


def test_failed_rows_stay_joinable():
    """An error row with no id is nearly useless in a portfolio run — the customer
    cannot tell which of their parcels failed. Identity is captured from the raw
    row before any parsing can throw."""
    rec = next(B.score_rows([{"id": "LOAN-42", "lat": "", "lon": ""}],
                            allow_network=False))
    assert rec["error"]
    assert rec["id"] == "LOAN-42"


def test_unknown_input_columns_are_ignored():
    """A customer's export carries their own columns; requiring them to be
    stripped first would make the tool annoying for no benefit."""
    rec = next(B.score_rows(_rows({"loan_officer": "kim", "internal_code": "X7"}),
                            allow_network=False))
    assert rec["error"] is None and rec["n_scored"] == 13


# ── Portfolio-relative grades ────────────────────────────────────────────────
def test_portfolio_grades_rank_within_the_batch():
    """Percentile is the share of scored rows at or below this one, matching the
    ``rank(pct=True)`` convention the grade thresholds in score/all_dimensions.py
    were drawn for — so the columns mean the same thing in both places.

    A consequence worth stating: the worst row of a five-row book sits at the
    20th percentile, so it grades D, not F. F is the bottom 10% and is simply
    unreachable in a book that small — which is correct. An F ought to mean "in
    the worst tenth", not "last of five".
    """
    recs = [{"composite_score": s} for s in (10.0, 20.0, 30.0, 40.0, 50.0)]
    for key, _ in DIMENSIONS:
        for r in recs:
            r[f"{key}_score"] = None
    B.portfolio_grades(recs)
    pcts = [r["composite_portfolio_pct"] for r in recs]
    assert pcts == [20.0, 40.0, 60.0, 80.0, 100.0]
    assert recs[-1]["composite_portfolio_grade"] == "A"     # best in book
    assert recs[0]["composite_portfolio_grade"] == "D"      # 20th pct, not F

    # With a book big enough for a bottom tenth to exist, F appears.
    big = [{"composite_score": float(i)} for i in range(20)]
    for key, _ in DIMENSIONS:
        for r in big:
            r[f"{key}_score"] = None
    B.portfolio_grades(big)
    assert big[0]["composite_portfolio_grade"] == "F"
    assert big[-1]["composite_portfolio_grade"] == "A"


def test_unscored_rows_do_not_rank_as_the_worst():
    """A missing input must never read as a bad parcel — it is excluded from the
    ranking, not floored at zero. Ranking it last would invent a finding."""
    recs = [{"composite_score": v} for v in (50.0, None, 90.0)]
    for key, _ in DIMENSIONS:
        for r in recs:
            r[f"{key}_score"] = None
    B.portfolio_grades(recs)
    assert recs[1]["composite_portfolio_pct"] is None
    assert recs[1]["composite_portfolio_grade"] is None
    assert recs[0]["composite_portfolio_pct"] == 50.0       # 1 of 2 scored rows


def test_national_and_portfolio_grades_are_both_reported():
    """They answer different questions — 'vs US housing' and 'vs the rest of my
    book' — so they are kept as separate columns and never merged."""
    cols = B.output_fieldnames(portfolio=True)
    assert "composite_national_grade" in cols
    assert "composite_portfolio_grade" in cols
    for key, _ in DIMENSIONS:
        assert f"{key}_national_grade" in cols
        assert f"{key}_portfolio_grade" in cols


# ── CSV round trip ───────────────────────────────────────────────────────────
def test_run_batch_csv_round_trip():
    inp = io.StringIO(
        "id,lat,lon,tract,year_built\n"
        f"A,35.15,-89.85,{SHELBY_TRACT},1995\n"
        f"B,35.15,-89.85,{SHELBY_TRACT},2020\n")
    out = io.StringIO()
    summary = B.run_batch(inp, out, allow_network=False, portfolio=True)
    assert summary == {"rows": 2, "scored": 2, "failed": 0}

    import csv as _csv
    rows = list(_csv.DictReader(io.StringIO(out.getvalue())))
    assert [r["id"] for r in rows] == ["A", "B"]
    assert all(r["composite_portfolio_grade"] for r in rows)
    # The newer build should rank above the older one in its own book.
    assert float(rows[1]["composite_score"]) > float(rows[0]["composite_score"])


def test_header_only_input_is_an_empty_run_not_a_crash():
    out = io.StringIO()
    summary = B.run_batch(io.StringIO("id,lat,lon\n"), out, allow_network=False)
    assert summary == {"rows": 0, "scored": 0, "failed": 0}
    assert out.getvalue().strip().startswith("id,lat,lon,tract")


def test_missing_header_is_rejected():
    try:
        B.run_batch(io.StringIO(""), io.StringIO(), allow_network=False)
    except ValueError as exc:
        assert "header" in str(exc)
    else:
        raise AssertionError("a headerless CSV should be rejected")


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
