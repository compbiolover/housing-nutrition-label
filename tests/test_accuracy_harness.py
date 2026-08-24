#!/usr/bin/env python3
"""The accuracy harness's arithmetic — the part that can be wrong quietly.

``scripts/measure_accuracy.py`` needs network for every row, so it cannot run in
CI and its *measurements* are taken by hand. What can and must be tested offline
is the maths that turns scored cases into published percentages, because that is
where a mistake would not announce itself: a coverage denominator that counted
rows the county never had a value for, or a grade-impact rate computed over pairs
where one side is missing, produces a number that looks entirely plausible and is
simply false — and it would be published as this project's headline accuracy
claim.

So these tests feed hand-built cases with known answers.

Run standalone: ``python tests/test_accuracy_harness.py``
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import scripts.measure_accuracy as M  # noqa: E402


def _case(truth, inferred, truth_grades, arm_grades, resolved=True):
    """One scored address, shaped as _score_arms would return it."""
    return {
        "address": "x", "truth": truth, "resolved": resolved,
        "baseline": {"inferred": inferred, "grades": arm_grades},
        "adapter": {"inferred": inferred, "grades": arm_grades},
        "truth_grades": truth_grades,
    }


def test_year_built_error_and_tolerance_bands():
    cases = [
        _case({"year_built": 1900}, {"year_built": 1900}, {}, {}),   # exact
        _case({"year_built": 1900}, {"year_built": 1904}, {}, {}),   # 4 → within 5
        _case({"year_built": 1900}, {"year_built": 1908}, {}, {}),   # 8 → within 10
        _case({"year_built": 1900}, {"year_built": 1930}, {}, {}),   # 30 → neither
    ]
    f = M._summarise(cases, "baseline")["fields"]["year_built"]
    assert f["n"] == 4 and f["coverage_pct"] == 100.0
    assert f["median_abs_error"] == 6.0          # median of 0, 4, 8, 30
    assert f["exact_pct"] == 25.0
    assert f["within_5yr_pct"] == 50.0           # 0 and 4
    assert f["within_10yr_pct"] == 75.0          # 0, 4 and 8


def test_coverage_counts_only_rows_the_county_could_grade():
    """The denominator is rows with ground truth, not rows scored.

    Counting all rows would quietly punish the label for a field the assessor
    never recorded — reporting a miss where there was no question asked.
    """
    cases = [
        _case({"year_built": 1900}, {"year_built": 1900}, {}, {}),
        _case({}, {"year_built": 1999}, {}, {}),      # county said nothing
    ]
    f = M._summarise(cases, "baseline")["fields"]["year_built"]
    assert f["n"] == 1, "a row with no ground truth is not a row we got wrong"
    assert f["coverage_pct"] == 100.0
    assert f["exact_pct"] == 100.0


def test_a_field_the_label_could_not_infer_lowers_coverage_not_accuracy():
    """Inferring nothing is a coverage failure, not a wrong answer, and the two
    must not be blended — a label that answers rarely but correctly and one that
    answers always but badly are different products."""
    cases = [
        _case({"year_built": 1900}, {"year_built": 1900}, {}, {}),
        _case({"year_built": 1950}, {"year_built": None}, {}, {}),
    ]
    f = M._summarise(cases, "baseline")["fields"]["year_built"]
    assert f["n"] == 2
    assert f["coverage_pct"] == 50.0
    assert f["exact_pct"] == 100.0, "accuracy is over what was actually answered"


def test_categorical_fields_are_scored_on_exact_match():
    cases = [
        _case({"construction": "frame"}, {"construction": "frame"}, {}, {}),
        _case({"construction": "brick"}, {"construction": "frame"}, {}, {}),
    ]
    f = M._summarise(cases, "baseline")["fields"]["construction"]
    assert f["exact_pct"] == 50.0
    assert "median_abs_error" not in f, "a wall type has no arithmetic distance"


def test_sqft_reports_relative_error():
    cases = [
        _case({"sqft": 1000.0}, {"sqft": 1100.0}, {}, {}),    # 10%
        _case({"sqft": 2000.0}, {"sqft": 1600.0}, {}, {}),    # 20%
    ]
    f = M._summarise(cases, "baseline")["fields"]["sqft"]
    assert f["median_abs_pct_error"] == 15.0


def test_grade_impact_is_the_share_that_differs_from_truth():
    cases = [
        _case({}, {}, {"durability": "B", "building_axis": "B"},
                      {"durability": "B", "building_axis": "C"}),
        _case({}, {}, {"durability": "A", "building_axis": "A"},
                      {"durability": "C", "building_axis": "A"}),
    ]
    g = M._summarise(cases, "baseline")["grade_impact"]
    assert g["durability"]["differs_pct"] == 50.0
    assert g["building_axis"]["differs_pct"] == 50.0
    assert g["durability"]["n"] == 2


def test_grade_impact_skips_pairs_with_a_missing_side():
    """An unscored dimension is not agreement, and must not be counted as one.

    Treating a None as a match would make an unscorable address look like a
    success and drag the published rate down toward zero.
    """
    cases = [
        _case({}, {}, {"durability": "B"}, {"durability": "C"}),   # a real disagreement
        _case({}, {}, {"durability": None}, {"durability": "C"}),  # nothing to compare
        _case({}, {}, {"durability": "B"}, {"durability": None}),  # nothing to compare
    ]
    g = M._summarise(cases, "baseline")["grade_impact"]["durability"]
    assert g["n"] == 1
    assert g["differs_pct"] == 100.0


def test_an_unscorable_dimension_is_not_counted_as_agreement():
    """The payload renders an unscored dimension as an em dash, not None, and it
    arrives under the same key a real letter does. Compared as a grade, two of them
    match each other — so a row nobody could score would be counted as the label
    getting it right, in the number this project publishes as its headline."""
    payload = {"dimensions": [{"key": "durability", "national_grade": "\u2014"}],
               "construction_national_grade": "\u2014"}
    assert M._grades(payload) == {"durability": None, "building_axis": None}

    cases = [_case({}, {}, {"durability": "\u2014"}, {"durability": "\u2014"})]
    cases[0]["truth_grades"] = M._grades(
        {"dimensions": [{"key": "durability", "national_grade": "\u2014"}]})
    cases[0]["baseline"]["grades"] = cases[0]["truth_grades"]
    assert M._summarise(cases, "baseline")["grade_impact"]["durability"]["n"] == 0


def test_composite_is_not_among_the_graded_dimensions():
    """It averages in eight location dimensions no construction input touches, so
    a grade-impact rate over it would be diluted by construction and read as
    better than the label actually is."""
    assert "composite" not in M.GRADED
    assert set(M.GRADED) <= {"durability", "energy", "resilience", "environmental"}


def test_an_empty_field_reports_nothing_rather_than_zero():
    """No ground truth at all must not render as 0% accuracy."""
    f = M._summarise([_case({}, {}, {}, {})], "baseline")["fields"]["year_built"]
    assert f["n"] == 0
    assert f["coverage_pct"] is None
    assert "exact_pct" not in f


def test_the_page_reports_the_numbers_it_was_given():
    """A rendering bug would publish a wrong accuracy claim as confidently as a
    right one, so the headline values are checked to actually reach the HTML."""
    results = {
        "generated": "2026-08-24",
        "benchmark": {"source": "Cook County Assessor (Open Data)",
                      "assessment_year": "2026", "fetched": "2026-08-24",
                      "rows": 7, "sha256_16": "deadbeefdeadbeef"},
        "adapter_resolved_pct": 62.5,
        "baseline": M._summarise([_case({"year_built": 1900}, {"year_built": 1930},
                                        {"durability": "B"}, {"durability": "C"})],
                                 "baseline"),
        "adapter": M._summarise([_case({"year_built": 1900}, {"year_built": 1900},
                                       {"durability": "B"}, {"durability": "B"})],
                                "adapter"),
    }
    page = M._render(results)
    assert "deadbeefdeadbeef" in page
    assert "62.5%" in page
    assert "Cook County, Illinois" in page, "the measured jurisdiction must be named"
    assert "not a national sample" in page, "the scope caveat must survive"
    assert "7 addresses sampled" in page, "the sample size must be stated"
    # The two arms must not be transposed — the whole page is a comparison, and
    # swapping the columns would invert its conclusion while looking fine.
    baseline_row = next(l for l in page.splitlines()
                        if l.startswith("<tr><td>durability</td>"))
    assert baseline_row.index("100.0%") < baseline_row.index("0.0%"), (
        "baseline (worse) must be the first grade-impact column, adapter the second")


def _juris(source, digest, rows=7):
    return {
        "benchmark": {"source": source, "assessment_year": "2026",
                      "fetched": "2026-08-24", "rows": rows, "sha256_16": digest},
        "adapter_resolved_pct": 62.5,
        "baseline": M._summarise([_case({"year_built": 1900}, {"year_built": 1930},
                                        {"durability": "B"}, {"durability": "C"})],
                                 "baseline"),
        "adapter": M._summarise([_case({"year_built": 1900}, {"year_built": 1900},
                                       {"durability": "B"}, {"durability": "B"})],
                                "adapter"),
    }


def test_every_measured_jurisdiction_gets_its_own_section():
    """Two adapters, two sets of numbers. Averaging them would invent a figure
    describing no real place, so each is rendered separately and both digests must
    survive to the page."""
    page = M._render({"generated": "2026-08-24", "jurisdictions": {
        "cook": _juris("Cook County Assessor (Open Data)", "aaaaaaaaaaaaaaaa"),
        "dc": _juris("DC Office of Tax and Revenue (Open Data)", "bbbbbbbbbbbbbbbb"),
    }})
    assert "aaaaaaaaaaaaaaaa" in page and "bbbbbbbbbbbbbbbb" in page
    assert "Cook County, Illinois" in page and "Washington, DC" in page
    assert "not comparable to each other" in page, (
        "a reader must be told the sections describe different places")


def test_the_original_single_county_results_still_render():
    """The first published run stored one county's numbers at the top level. A
    committed measurement should not need hand-editing to survive a second adapter,
    so that shape is read as the jurisdiction it in fact described."""
    flat = {"generated": "2026-08-24", **_juris("Cook County Assessor (Open Data)", "cccc")}
    assert set(M.as_jurisdictions(flat)) == {"cook"}
    assert "Cook County, Illinois" in M._render(flat)


def test_an_unrecognised_results_shape_yields_no_sections():
    """Better an empty page than a confident one built from a file this code does
    not understand."""
    assert M.as_jurisdictions({"generated": "2026-08-24"}) == {}


def test_dc_scope_is_stated_where_the_numbers_are():
    """DC's exclusion of condominiums is a third of its housing stock. It belongs
    beside the figures, not only in the caveats at the foot of the page."""
    data = _juris("DC Office of Tax and Revenue (Open Data)", "dddddddddddddddd")
    data["benchmark"]["scope"] = "non-condominium homes only"
    page = M._render({"generated": "2026-08-24", "jurisdictions": {"dc": data}})
    assert "non-condominium homes only" in page


def test_rows_the_assessor_could_not_document_are_disclosed():
    """The builder drops a row with no address or no usable year before writing the
    benchmark, so the benchmark is already smaller than the draw. Reporting only the
    survivors would quietly redefine the population as "rows the assessor documented
    well" — a flattering sample nobody chose."""
    data = _juris("DC Office of Tax and Revenue (Open Data)", "eeeeeeeeeeeeeeee", rows=218)
    data["benchmark"]["drawn"] = 220
    page = M._render({"generated": "2026-08-24", "jurisdictions": {"dc": data}})
    assert "Drawn from 220 assessor rows" in page
    assert "2 carried no address" in page


def test_nothing_is_said_when_every_drawn_row_was_gradeable():
    """A permanent "0 could not be graded" is noise; a missing one when there were
    40 is a misrepresented sample."""
    data = _juris("X", "ffffffffffffffff", rows=218)
    data["benchmark"]["drawn"] = 218
    assert "could not be graded" not in M._render(
        {"generated": "2026-08-24", "jurisdictions": {"dc": data}})


def test_the_page_states_the_sampled_count_not_the_scored_one():
    """`rows` is the scored subset and `sampled` is the population. The method
    sentence says "N addresses sampled", so it must use the latter — quoting the
    scored count there would let a batch of failed geocodes shrink the stated
    sample while the page still read as though nothing had been dropped."""
    results = {
        "generated": "2026-08-24",
        "benchmark": {"source": "Cook County Assessor (Open Data)",
                      "assessment_year": "2026", "fetched": "2026-08-24",
                      "sampled": 220, "rows": 200, "sha256_16": "deadbeefdeadbeef"},
        "unscored": 20,
        "adapter_resolved_pct": 62.5,
        "baseline": M._summarise([_case({}, {}, {}, {})], "baseline"),
        "adapter": M._summarise([_case({}, {}, {}, {})], "adapter"),
    }
    page = M._render(results)
    assert "220 addresses sampled" in page
    assert "20 sampled addresses could not be" in page, (
        "the excluded rows must be disclosed, not just netted out of the count")


def test_an_older_result_without_a_sampled_count_still_renders():
    """`sampled` was added after the first published run, so the renderer must not
    hard-fail on a results file that predates it."""
    results = {
        "generated": "2026-08-24",
        "benchmark": {"source": "Cook County Assessor (Open Data)",
                      "assessment_year": "2026", "fetched": "2026-08-24",
                      "rows": 200, "sha256_16": "deadbeefdeadbeef"},
        "adapter_resolved_pct": 62.5,
        "baseline": M._summarise([_case({}, {}, {}, {})], "baseline"),
        "adapter": M._summarise([_case({}, {}, {}, {})], "adapter"),
    }
    assert "200 addresses sampled" in M._render(results)


def _run_all() -> int:
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
