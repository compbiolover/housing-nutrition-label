#!/usr/bin/env python3
"""Offline tests for bulk scoring (no network, no pytest).

Run directly:  python tests/test_batch.py
"""

import io

from housing_label import batch as B
from housing_label.data import year_built as year_built_data
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


def test_ranking_matches_the_bisect_definition_including_ties():
    """The O(1) lookup table must agree with a straight bisect_right, which is the
    definition the grade thresholds were drawn for. Ties are the interesting case:
    every row in a run takes the count at the END of the run, so identical scores
    always get identical grades."""
    import bisect
    import random
    random.seed(7)
    # Deliberately few distinct values, so ties are common.
    scores = [random.choice([None] + [float(v) for v in range(15)]) for _ in range(300)]
    recs = [{"composite_score": s} for s in scores]
    for key, _ in DIMENSIONS:
        for r in recs:
            r[f"{key}_score"] = None
    B.portfolio_grades(recs)

    vals = sorted(s for s in scores if s is not None)
    n = len(vals)
    for r, s in zip(recs, scores):
        expected = None if s is None else round(bisect.bisect_right(vals, s) / n * 100, 1)
        assert r["composite_portfolio_pct"] == expected, s


def test_geography_without_coordinates_is_refused():
    """Pairing a caller's tract with the Shelby default point would return a
    Location that is internally incoherent — and say nothing about it."""
    from housing_label.simulate.house import build_label_parts
    try:
        build_label_parts(geography={"tract": SHELBY_TRACT}, allow_network=False)
    except ValueError as exc:
        assert "requires lat and lon" in str(exc)
    else:
        raise AssertionError("geography without lat/lon should be refused")


def test_unknown_house_field_is_refused_by_name():
    """The silent-drop this whole path was blocked on: an unrecognised kwarg used
    to vanish into **fields and score a subtly different parcel."""
    from housing_label.simulate.house import build_label_parts
    try:
        build_label_parts(lat=35.15, lon=-89.85, allow_network=False, year_bult=1995)
    except TypeError as exc:
        assert "year_bult" in str(exc)
    else:
        raise AssertionError("an unknown house field should be refused")


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
    # Subset rather than equality: the summary grows keys over time, and a test
    # that breaks on every addition teaches people to update it without reading.
    assert summary["rows"] == 2 and summary["scored"] == 2 and summary["failed"] == 0

    import csv as _csv
    rows = list(_csv.DictReader(io.StringIO(out.getvalue())))
    assert [r["id"] for r in rows] == ["A", "B"]
    assert all(r["composite_portfolio_grade"] for r in rows)
    # The newer build should rank above the older one in its own book.
    assert float(rows[1]["composite_score"]) > float(rows[0]["composite_score"])


def test_header_only_input_is_an_empty_run_not_a_crash():
    out = io.StringIO()
    summary = B.run_batch(io.StringIO("id,lat,lon\n"), out, allow_network=False)
    assert summary["rows"] == 0 and summary["scored"] == 0 and summary["failed"] == 0
    assert out.getvalue().strip().startswith("id,lat,lon,tract")


def test_missing_header_is_rejected():
    try:
        B.run_batch(io.StringIO(""), io.StringIO(), allow_network=False)
    except ValueError as exc:
        assert "header" in str(exc)
    else:
        raise AssertionError("a headerless CSV should be rejected")


# ── Concurrency ──────────────────────────────────────────────────────────────
def test_jobs_does_not_change_the_output():
    """--jobs must be invisible in the result — same rows, same order, same values.

    Order is the trap: yielding each row as its future completes would reorder the
    stream against the input, so a customer joining the output back to their book
    by position would attach every score to the wrong parcel. Nothing would look
    wrong; every row is a real score of a real parcel.
    """
    rows = [dict(_rows()[0], id=f"P{i}", year_built=str(1900 + i * 3))
            for i in range(50)]
    serial = list(B.score_rows(rows, allow_network=False, jobs=1))
    threaded = list(B.score_rows(rows, allow_network=False, jobs=4))
    assert [r["id"] for r in threaded] == [r["id"] for r in serial]
    assert threaded == serial


def test_jobs_window_boundary_keeps_order():
    """The pool submits in windows of jobs*8, so a run that does not divide evenly
    into windows exercises the trailing partial batch — the place an off-by-one
    would drop or duplicate rows."""
    for n in (1, 8, 16, 17, 33):
        rows = [dict(_rows()[0], id=f"P{i}") for i in range(n)]
        recs = list(B.score_rows(rows, allow_network=False, jobs=2))
        assert [r["id"] for r in recs] == [f"P{i}" for i in range(n)], n


# ── Resume ───────────────────────────────────────────────────────────────────
def _resume_input(n=20):
    lines = ["id,lat,lon,tract,year_built"]
    for i in range(n):
        lines.append(f"P{i},35.15,-89.85,{SHELBY_TRACT},{1900 + i * 5}")
    return "\n".join(lines) + "\n"


def test_resume_produces_the_same_file_as_an_uninterrupted_run():
    """The property that makes --resume safe to reach for: byte-for-byte identical.

    Anything less and a resumed 400,000-row job is a different artifact from the
    one it was meant to complete, which is unusable for the reconciliation that is
    the whole point of running it.
    """
    import tempfile
    from pathlib import Path

    src = _resume_input()
    whole = io.StringIO()
    B.run_batch(io.StringIO(src), whole, allow_network=False)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.csv"
        # A run that died after 7 rows.
        head = io.StringIO()
        B.run_batch(io.StringIO("\n".join(src.split("\n")[:8]) + "\n"), head,
                    allow_network=False)
        path.write_text(head.getvalue(), newline="")

        offset = B.resume_offset(path)
        assert offset == 7
        with path.open("a", newline="") as f:
            summary = B.run_batch(io.StringIO(src), f, allow_network=False,
                                  resume_from=offset)
        assert summary["rows"] == 13 and summary["resumed_from"] == 7
        # newline="" on both sides: csv writes \r\n, and letting the reader
        # translate it would compare something neither run produced.
        with path.open(newline="") as f:
            assert f.read() == whole.getvalue()


def test_resume_on_a_first_run_is_a_no_op():
    """A resumable job should be launched the same way every time, including the
    first — so a missing output file is 0 rows, not an error."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        assert B.resume_offset(Path(tmp) / "nope.csv") == 0
        empty = Path(tmp) / "empty.csv"
        empty.write_text("")
        assert B.resume_offset(empty) == 0


def test_resume_refuses_an_output_written_with_different_columns():
    """The silent corruption this guards: --portfolio-grades flipped between runs
    adds 28 columns, and appending anyway would line the CSV up while making every
    appended cell mean something different from the ones above it."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.csv"
        out = io.StringIO()
        B.run_batch(io.StringIO(_resume_input(3)), out, allow_network=False,
                    portfolio=True)
        path.write_text(out.getvalue(), newline="")

        assert B.resume_offset(path, portfolio=True) == 3
        try:
            B.resume_offset(path, portfolio=False)
        except ValueError as exc:
            assert "different columns" in str(exc)
        else:
            raise AssertionError("a mismatched header should be refused")


def test_resume_skips_by_position_not_by_id():
    """Real exports repeat ids — the same property on two loans is routine — so a
    skip keyed on them would drop the wrong rows."""
    src = ("id,lat,lon,tract\n"
           + "".join(f"DUP,35.15,-89.85,{SHELBY_TRACT}\n" for _ in range(5)))
    out = io.StringIO()
    summary = B.run_batch(io.StringIO(src), out, allow_network=False, resume_from=3)
    assert summary["rows"] == 2
    # And no header, because the file being appended to already has one.
    assert not out.getvalue().startswith("id,lat")


# ── Defaulted-input provenance ───────────────────────────────────────────────
def test_a_row_with_no_building_attributes_says_so():
    """The finding this whole column exists for: an attribute-free row is scored as a
    generic wood-frame slab 2,000 sqft house in flood zone X — and n_scored still
    reads 13/13. Nothing in the output distinguished that from a measured grade."""
    rec = next(B.score_rows([{"lat": "35.15", "lon": "-89.85", "tract": SHELBY_TRACT}],
                            allow_network=False))
    assert rec["error"] is None and rec["n_scored"] == 13
    assert rec["building_source"] == "defaulted"
    defaulted = rec["defaulted_inputs"].split(",")
    # year_built is still ASSUMED even though it is now the tract's ACS median
    # rather than a flat default: an area typical is not a fact about this house,
    # and the column exists to say so.
    assert "year_built" in defaulted
    # Offline every parcel in the country defaults to zone X (minimal) — the best
    # of the three — so a book of coastal AE properties would otherwise read as
    # though none of them were in a floodplain.
    assert "flood_zone" in defaulted


def test_the_defaulted_year_built_is_the_tracts_own_median():
    """The assumed vintage is this tract's, not a national stand-in.

    Pinned because the bundled ACS crosswalk resolves offline, so the batch path
    gets it for free — and the failure mode if that ever regresses is silent: the
    row would still score, still say "defaulted", and just quietly describe a
    different house.
    """
    dist = year_built_data.year_built_distribution_for(SHELBY_TRACT)
    assert dist is not None and dist["geo_level"] == "tract"

    # The batch record reports scores, not inputs, so read the same payload batch
    # scores from (batch.py drives build_label_parts / label_payload directly).
    parsed = B.parse_row({"lat": "35.15", "lon": "-89.85", "tract": SHELBY_TRACT})
    cfg, r, label = build_label_parts(lat=parsed["lat"], lon=parsed["lon"],
                                      geography=parsed["geography"],
                                      allow_network=False, **parsed["fields"])
    yb = label_payload(cfg, r, label)["building"]["year_built"]
    assert yb["value"] == dist["year_built"]
    assert yb["status"] == "assumed", "an area typical must never read as measured"
    assert "not this building" in yb["source"]
    assert yb["typical_range"] == [dist["p25"], dist["p75"]]


def test_a_fully_specified_row_reads_supplied():
    rec = next(B.score_rows(_rows({"construction": "frame", "foundation": "crawl",
                                   "condition": "fair", "flood_zone": "AE"}),
                            allow_network=False))
    assert rec["error"] is None
    assert rec["building_source"] == "supplied"
    assert rec["defaulted_inputs"] == ""


def test_a_partly_specified_row_names_the_missing_fields():
    """Three states, not two: 'partial' is the common case in real books, and
    lumping it with either extreme would misdescribe most of a run."""
    rec = next(B.score_rows(_rows(), allow_network=False))     # year_built + sqft
    assert rec["building_source"] == "partial"
    missing = set(rec["defaulted_inputs"].split(","))
    assert "year_built" not in missing and "sqft" not in missing
    assert {"construction", "foundation", "condition", "flood_zone"} <= missing


def test_defaults_still_move_the_building_grade():
    """States the size of the remaining error, so the warning is not taken as
    pedantry — while no longer overstating it.

    This assertion used to demand a 40-point gap, which held only because an
    attribute-free row was scored as a 2024 new build in a 1950s neighbourhood. Now
    that the assumed vintage follows the tract, most of that gap was never about the
    missing *attributes* at all — it was one bad default. What is left (condition,
    construction, foundation) is real and still worth a grade step, so the warning
    stands on a smaller, truer number.
    """
    # Same tract, same flood zone, so the ONLY difference is whether the building
    # attributes were supplied.
    blank = next(B.score_rows([{"lat": "35.15", "lon": "-89.85",
                                "tract": SHELBY_TRACT, "flood_zone": "AE"}],
                              allow_network=False))
    real = next(B.score_rows(_rows({"year_built": "1948", "condition": "poor",
                                    "construction": "frame", "foundation": "crawl",
                                    "flood_zone": "AE"}),
                             allow_network=False))
    assert blank["building_source"] == "defaulted"
    assert real["building_source"] == "supplied"
    assert blank["building_score"] - real["building_score"] > 10
    # The Site half barely moves — 0.4 of a point here, and only because Air
    # Quality reads the foundation for radon exposure. That asymmetry is why the
    # provenance is reported for the building half specifically instead of the
    # whole row being discarded: Site-only scoring is a legitimate product for a
    # customer who holds no building data.
    assert abs(blank["site_score"] - real["site_score"]) < 1.0


def test_a_defaulted_grade_follows_the_neighbourhoods_vintage():
    """The improvement, pinned: the default is no longer a flat optimistic constant.

    Two Shelby County tracts, identical rows, nothing supplied. The 1950s tract has
    to grade far below the 2010s one — if this ever collapses to a single number
    again, every book of older housing silently reads as new construction, which is
    the bias the provenance columns were added to expose.
    """
    def _blank(tract):
        return next(B.score_rows([{"lat": "35.15", "lon": "-89.85", "tract": tract}],
                                 allow_network=False))

    old_tract, new_tract = "47157003100", "47157021545"   # ACS medians 1950 and 2012
    a, b = _blank(old_tract), _blank(new_tract)
    assert a["building_source"] == b["building_source"] == "defaulted"
    assert b["building_score"] - a["building_score"] > 40, (
        f"defaulted grades barely differ between a 1950s and a 2010s tract "
        f"({a['building_score']} vs {b['building_score']}) — the assumed vintage "
        f"is not tracking the neighbourhood")


def test_the_run_summary_counts_defaulted_and_partial_separately():
    """Merging the two would overstate the milder one — a partial row's Building
    grade does describe this house, just less precisely — and overstating a caveat
    is the same defect as omitting one."""
    out = io.StringIO()
    src = ("id,lat,lon,tract,year_built,construction,foundation,condition,sqft,"
           "flood_zone\n"
           f"bare,35.15,-89.85,{SHELBY_TRACT},,,,,,\n"
           f"some,35.15,-89.85,{SHELBY_TRACT},1948,,,,1400,\n"
           f"full,35.15,-89.85,{SHELBY_TRACT},1948,frame,crawl,poor,1400,AE\n")
    summary = B.run_batch(io.StringIO(src), out, allow_network=False)
    assert summary["scored"] == 3
    assert summary["defaulted_building"] == 1
    assert summary["partial_building"] == 1


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
