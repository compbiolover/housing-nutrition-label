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

import contextlib
import json
import pathlib
import sys
import tempfile

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import scripts.jurisdictions as B  # noqa: E402
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
    data["benchmark"].update({"drawn": 220, "sampled": 218,
                              "dropped": {"no_address": 2, "no_year_built": 0}})
    page = M._render({"generated": "2026-08-24", "jurisdictions": {"dc": data}})
    assert "Drawn from 220 assessor rows" in page
    assert "2 had no address on file" in page


def test_the_note_measures_against_the_benchmark_not_the_scored_rows():
    """`rows` is what this run scored; `sampled` is what reached the benchmark. A
    geocoding failure is already reported by the unscored note, so comparing
    against `rows` would count it twice AND attribute a scorer failure to the
    assessor's record-keeping."""
    data = _juris("X", "1111111111111111", rows=216)      # 2 lost to geocoding
    data["benchmark"]["drawn"] = 220
    data["benchmark"]["sampled"] = 218
    page = M._render({"generated": "2026-08-24", "jurisdictions": {"dc": data}})
    # No recorded breakdown here, so this exercises the no-cause-claimed path as
    # well as the denominator: the count must be 220 - 218, never 220 - 216.
    assert "2 could not be graded" in page, (
        "the note must describe 220 - 218, not 220 - 216")
    assert "4 could not be graded" not in page


def test_nothing_is_said_when_every_drawn_row_was_gradeable():
    """A permanent "0 could not be graded" is noise; a missing one when there were
    40 is a misrepresented sample."""
    data = _juris("X", "ffffffffffffffff", rows=218)
    data["benchmark"].update({"drawn": 218, "sampled": 218})
    assert "could not be graded" not in M._render(
        {"generated": "2026-08-24", "jurisdictions": {"dc": data}})


def test_the_dc_caveat_appears_only_when_dc_is_on_the_page():
    """The condominium exclusion is a fact about a measurement. Printing it on a
    page that carries no DC section would describe a limitation of numbers that are
    not there."""
    cook_only = M._render({"generated": "2026-08-24", "jurisdictions": {
        "cook": _juris("Cook County Assessor (Open Data)", "aaaaaaaaaaaaaaaa")}})
    assert "excludes condominiums" not in cook_only

    with_dc = M._render({"generated": "2026-08-24", "jurisdictions": {
        "dc": _juris("DC Office of Tax and Revenue (Open Data)", "bbbbbbbbbbbbbbbb")}})
    assert "excludes condominiums" in with_dc


@contextlib.contextmanager
def _isolated_lock():
    """Point the lock at a temp path for the duration of a test.

    These tests create and delete lock files. Aimed at the real one, a suite run
    during a live measurement's critical section would delete that run's guard and
    let a second merge in — a test corrupting the thing it is testing.
    """
    original = M.LOCK
    with tempfile.TemporaryDirectory() as tmp:
        M.LOCK = pathlib.Path(tmp) / "results.lock"
        try:
            yield M.LOCK
        finally:
            M.LOCK = original


def test_the_lock_is_released_and_needs_no_unix_only_import():
    """`fcntl` is Unix-only, and this module is imported by the test suite and by
    --check. The repository documents a Windows setup, so a platform-specific import
    would fail the whole file at collection time rather than at the write it guards.
    """
    assert "fcntl" not in dir(M), "a Unix-only import came back"
    with _isolated_lock() as lock:
        with M._results_lock():
            assert lock.exists()
        assert not lock.exists(), "the lock must not outlive the run that took it"


def test_a_held_lock_is_never_taken_automatically():
    """Two earlier versions tried to reclaim an old lock — unlink-if-old, then
    compare-the-contents-and-unlink. Both were time-of-check/time-of-use races:
    between deciding a lock is abandoned and removing it, its holder can release
    and a third process acquire, and the removal then frees a live lock so two
    merges run at once. That is the lost update the lock exists to prevent, so the
    window was not the problem — the takeover was.

    Now a lock that outlives the wait is reported with the command to clear it.
    This pins that it is never silently reclaimed, and that the error names the
    file so the message is actionable rather than merely correct.
    """
    original = M._LOCK_TIMEOUT_S
    M._LOCK_TIMEOUT_S = 0            # do not sit through the real wait
    try:
        with _isolated_lock() as lock:
            lock.write_text("another-process")
            raised = None
            try:
                with M._results_lock():
                    raise AssertionError("acquired a lock somebody else was holding")
            except SystemExit as exc:
                raised = exc
            assert raised is not None, "a held lock must not be taken"
            assert str(lock) in str(raised), "the error must name the file to remove"
            assert lock.exists(), "the other process's lock must survive"
    finally:
        M._LOCK_TIMEOUT_S = original


def test_a_measurement_taken_before_the_rename_is_refused_not_ignored():
    """`pin_mismatches` was named for Cook's identifier; DC's is an SSL, so the key
    is parcel-generic now. Every committed section carries the new one, so the
    fallback reader is gone — but dropping it silently would render such a section
    with NO mismatch sentence, losing the disclosure that some answers were wrong
    for the address asked about. A cleaner-looking page than the data supports is
    the failure this file exists to stop, so it refuses instead."""
    data = _juris("Cook County Assessor (Open Data)", "9999999999999999")
    data.pop("parcel_mismatches", None)
    data["pin_mismatches"] = 3
    try:
        M._readable_results({"generated": "2026-08-24", "jurisdictions": {"cook": data}},
                            "x", existed=True)
    except SystemExit as exc:
        assert "pin_mismatches" in str(exc) and "different parcel" in str(exc)
    else:
        raise AssertionError("a section using only the pre-rename key was accepted")


def test_the_current_key_renders_the_mismatch_sentence():
    """The complement: the refusal above must not be the only path — a section
    using the current key still publishes the count."""
    data = _juris("Cook County Assessor (Open Data)", "9999999999999999")
    data["parcel_mismatches"] = 3
    page = M._render({"generated": "2026-08-24", "jurisdictions": {"cook": data}})
    assert "3 landed on a different parcel" in page


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


# --- the benchmark and its metadata must describe the same file ----------------


_GRADEABLE = ("parcel_id,address,year_built,sqft,stories,construction,"
              "foundation,condition\n"
              "1,A,1990,1000,1,brick,,good\n"
              "2,B,1975,900,2,frame,,average\n")


def _benchmark(tmp, text=_GRADEABLE):
    """A benchmark with the columns the scorer grades on. A header-only stand-in
    is refused now, and rightly: a file with nothing to grade against publishes
    zero observed rows while the grade-impact rate is computed from a default."""
    path = pathlib.Path(tmp) / "benchmark-x.csv"
    path.write_text(text)
    import hashlib
    return path, hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _meta(juris="dc", **over):
    """Metadata a real build would write, so a test overrides only what it tests.

    Each new provenance guard broke a handful of hand-built fixtures that were
    missing a field they never meant to be about. A complete default keeps a test
    failing for its own reason.
    """
    out = {"jurisdiction": juris, "rows": 2,
           "source": B.JURISDICTIONS[juris]["source"],
           "scope": B.JURISDICTIONS[juris]["scope"]}
    out.update(over)
    return {k: v for k, v in out.items() if v is not _OMIT}


def _sect(key="dc", **over):
    """A results section complete enough for the renderer to read."""
    bench = {"jurisdiction": key, "rows": 2, "assessment_year": "2026",
             "fetched": "2026-01-01", "sampled": 2,
             "source": B.JURISDICTIONS[key]["source"],
             "scope": B.JURISDICTIONS[key]["scope"]}
    bench.update(over.pop("benchmark", {}))
    out = {"benchmark": {k: v for k, v in bench.items() if v is not _OMIT},
           "baseline": {}, "adapter": {}, "adapter_resolved_pct": 90.0,
           "rows": 2, "unscored": 0}
    out.update(over)
    return {k: v for k, v in out.items() if v is not _OMIT}


class _Omit:
    def __repr__(self):
        return "<omit>"


_OMIT = _Omit()


def test_a_benchmark_matching_its_metadata_is_accepted():
    with tempfile.TemporaryDirectory() as tmp:
        path, digest = _benchmark(tmp)
        got = M._verify_benchmark(path, _meta(sha256_16=digest), "dc")
        assert got == path.read_bytes(), (
            "the validated bytes are what the caller parses; returning anything "
            "else reopens the window this check exists to close")


def test_a_benchmark_that_is_not_the_one_its_metadata_describes_is_refused():
    """The interrupted-build case. The builder renames a finished file into place,
    so the pair should never disagree — but if it does, scoring it would publish a
    partial sample under the previous run's row count and digest, which is a
    fabricated measurement that looks entirely ordinary."""
    with tempfile.TemporaryDirectory() as tmp:
        path, _ = _benchmark(tmp)
        try:
            M._verify_benchmark(path, _meta(sha256_16="deadbeefdeadbeef"), "dc")
        except SystemExit as exc:
            assert "does not match" in str(exc)
        else:
            raise AssertionError("a mismatched benchmark was accepted for scoring")


def test_a_hand_edited_row_count_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        path, digest = _benchmark(tmp)
        try:
            M._verify_benchmark(path, _meta(sha256_16=digest, rows=99), "dc")
        except SystemExit as exc:
            assert "99" in str(exc)
        else:
            raise AssertionError("a benchmark with the wrong row count was accepted")


def test_a_benchmark_with_no_recorded_digest_still_runs():
    """The pre-split cache predates the field. Refusing it would invent a problem
    rather than catch one."""
    with tempfile.TemporaryDirectory() as tmp:
        path, _ = _benchmark(tmp)
        M._verify_benchmark(path, _meta("cook", rows=_OMIT, jurisdiction=_OMIT,
                                        scope=_OMIT), "cook", legacy=True)


def test_a_benchmark_stamped_for_another_jurisdiction_is_refused():
    """Copying benchmark-cook.* to benchmark-dc.* passes the digest — the file
    really is the one its metadata describes — and would publish Cook addresses
    under DC's name. The metadata said `cook` the whole time; nobody read it."""
    with tempfile.TemporaryDirectory() as tmp:
        path, digest = _benchmark(tmp)
        try:
            M._verify_benchmark(path, _meta("cook", sha256_16=digest), "dc")
        except SystemExit as exc:
            assert "cook" in str(exc) and "dc" in str(exc)
        else:
            raise AssertionError(
                "one jurisdiction's benchmark was accepted under another's name")


def test_the_row_count_is_checked_even_with_no_digest_recorded():
    """The count used to hang off the digest check, so a pre-split cache — which
    records `rows` and no digest — was not validated at all."""
    with tempfile.TemporaryDirectory() as tmp:
        path, _ = _benchmark(tmp)
        try:
            M._verify_benchmark(path, _meta("cook", rows=99, jurisdiction=_OMIT,
                                        scope=_OMIT), "cook", legacy=True)
        except SystemExit as exc:
            assert "99" in str(exc)
        else:
            raise AssertionError("a wrong row count passed when no digest was set")


def test_a_section_renders_without_a_recorded_digest():
    """`m['sha256_16']` was indexed directly, so a digest-less benchmark raised
    KeyError during render — AFTER results.json had already been overwritten. A
    crash that leaves the published state half-updated is the worst ordering, so
    this renders the real committed section with the digest taken away rather than
    a hand-built stand-in that might not have the shape the renderer expects."""
    import copy
    results = json.loads(M.RESULTS.read_text())
    key, data = next(iter(M.as_jurisdictions(results).items()))
    data = copy.deepcopy(data)
    data["benchmark"].pop("sha256_16", None)
    assert "unrecorded" in M._section(key, data)


def test_the_drop_disclosure_reports_recorded_reasons_not_deduced_ones():
    """Four review rounds found this sentence naming a cause it could not know —
    each fix reworded a guess derived from `drawn - sampled`. The builder is the
    only place that knows why a row was dropped, so it records it now."""
    note = M._ungradeable_note({"drawn": 220, "sampled": 215,
                                "dropped": {"no_address": 2, "no_year_built": 3}})
    assert "2 had no address on file" in note and "3 had no usable year built" in note


def test_a_reason_with_no_rows_is_not_listed():
    note = M._ungradeable_note({"drawn": 220, "sampled": 218,
                                "dropped": {"no_address": 2, "no_year_built": 0}})
    assert "no address on file" in note and "year built" not in note


def test_metadata_without_a_breakdown_claims_no_cause():
    """Benchmarks built before the field exists must not have a cause invented for
    them — that is the mistake this whole change is undoing."""
    note = M._ungradeable_note({"drawn": 220, "sampled": 218})
    assert "could not be graded" in note
    assert "no address" not in note and "year built" not in note


def test_no_gap_says_nothing():
    assert M._ungradeable_note({"drawn": 218, "sampled": 218}) == ""


def test_an_unstamped_per_jurisdiction_benchmark_is_refused():
    """A missing stamp has to be refused as firmly as a wrong one. Checking only
    for a CONFLICTING jurisdiction catches the careful mistake and misses the
    careless one: a legacy Cook benchmark copied to benchmark-dc.* carries no stamp
    at all, matches its own digest, and would publish Cook as DC."""
    with tempfile.TemporaryDirectory() as tmp:
        path, digest = _benchmark(tmp)
        try:
            M._verify_benchmark(path, _meta(sha256_16=digest, jurisdiction=_OMIT), "dc")
        except SystemExit as exc:
            assert "no jurisdiction recorded" in str(exc)
        else:
            raise AssertionError(
                "an unstamped benchmark was accepted under a jurisdiction's name")


def test_only_the_legacy_path_may_go_unstamped():
    """The pre-split file is the one that legitimately predates the field, and it
    described Cook. Nothing else gets the exemption."""
    with tempfile.TemporaryDirectory() as tmp:
        path, digest = _benchmark(tmp)
        M._verify_benchmark(path, _meta("cook", sha256_16=digest, jurisdiction=_OMIT,
                                        scope=_OMIT), "cook", legacy=True)
        try:
            M._verify_benchmark(path, _meta("cook", sha256_16=digest,
                                        jurisdiction="dc", scope=_OMIT),
                            "cook", legacy=True)
        except SystemExit:
            pass
        else:
            raise AssertionError(
                "legacy must excuse a MISSING stamp, never a contradicting one")


def test_an_unreadable_results_shape_is_not_treated_as_an_empty_store():
    """"Merge, never replace" has to hold against a file this code does not
    recognise — precisely when it is least safe to assume there is nothing to
    preserve. as_jurisdictions returns {} for an unknown shape, and continuing
    would delete every other jurisdiction's measurement to fix a schema mistake."""
    assert M.as_jurisdictions({"something": "else"}) == {}, (
        "if this ever returns sections for an unknown shape, the guard that "
        "depends on it being empty needs revisiting")
    try:
        M._readable_results({"something": "else"}, "this merge", existed=True)
    except SystemExit as exc:
        assert "no jurisdiction sections" in str(exc)
    else:
        raise AssertionError(
            "a results file with no readable sections was accepted for merging")


def test_a_per_jurisdiction_benchmark_must_carry_a_digest():
    """Without a digest AND without `rows`, nothing checks the file's content at
    all: a benchmark correctly labelled `dc` could hold any bytes and still be
    published as DC. The no-digest exemption belongs to the pre-split file only —
    I granted it to the stamp and not the digest in the same edit."""
    with tempfile.TemporaryDirectory() as tmp:
        path, _ = _benchmark(tmp)
        try:
            M._verify_benchmark(path, _meta(sha256_16=_OMIT, rows=_OMIT), "dc")
        except SystemExit as exc:
            assert "sha256_16" in str(exc)
        else:
            raise AssertionError(
                "a benchmark whose contents nothing verifies was accepted")


def test_the_legacy_path_may_still_lack_a_digest():
    with tempfile.TemporaryDirectory() as tmp:
        path, _ = _benchmark(tmp)
        M._verify_benchmark(path, _meta("cook", rows=_OMIT, jurisdiction=_OMIT,
                                        scope=_OMIT), "cook", legacy=True)


def test_the_gate_reads_the_results_and_page_together():
    """They are renamed into place one after the other, so an unlocked read can
    catch the instant between and report the page as stale when it is merely being
    replaced — a spurious CI failure."""
    src = pathlib.Path(M.__file__).read_text()
    check = src[src.index("    if args.check:"):src.index("    juris = args.jurisdiction")]
    assert "with _results_lock():" in check, (
        "the check must read both files inside the same lock the writers hold")


def test_the_published_sample_size_is_verified_against_the_file():
    """`sampled` is what the page states as the population and uses as the drop
    disclosure's denominator. Checking only `rows` left the number the reader
    actually sees unverified."""
    with tempfile.TemporaryDirectory() as tmp:
        path, digest = _benchmark(tmp)               # two rows
        try:
            M._verify_benchmark(path, _meta(sha256_16=digest, sampled=218), "dc")
        except SystemExit as exc:
            assert "sampled" in str(exc) and "218" in str(exc)
        else:
            raise AssertionError("a false published sample size was accepted")


def test_render_only_refuses_an_unreadable_results_file():
    """The merge grew this guard a commit before --render-only did. Both are
    destructive with the same empty answer: the merge writes this run alone over
    the file, the render publishes an empty page over the real one."""
    try:
        M._readable_results({"something": "else"}, "the rendered page", existed=True)
    except SystemExit as exc:
        assert "no jurisdiction sections" in str(exc)
    else:
        raise AssertionError("an unreadable results file was accepted for render")
    # And the empty case is still a legitimate fresh start.
    assert M._readable_results({}, "x", existed=False) == {}


def test_an_existing_but_falsy_results_file_is_not_a_fresh_start():
    """`{}`, `[]`, `0`, `false` are all files that EXIST and say something this
    code cannot read. Testing truthiness let every one through as a fresh store —
    the same absent/unreadable conflation, one level up. `0` and `false` were
    worse than accepted: they raised TypeError inside as_jurisdictions, an
    unhandled crash where a stated refusal belongs."""
    for value in ({}, [], 0, False, "text"):
        try:
            M._readable_results(value, "x", existed=True)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"an existing results file holding {value!r} was "
                                 f"treated as nothing worth preserving")
    assert M._readable_results({}, "x", existed=False) == {}, (
        "a genuinely missing file is still a fresh start")


def test_a_render_failure_replaces_neither_file():
    """The page was written second, straight from _render() in the argument list,
    so anything that made rendering raise left results.json already replaced and
    the page still describing the previous run — the two disagreeing, with the CI
    gate comparing exactly those two."""
    with tempfile.TemporaryDirectory() as tmp:
        results_p = pathlib.Path(tmp) / "results.json"
        page_p = pathlib.Path(tmp) / "accuracy.html"
        results_p.write_text('{"before": true}')
        page_p.write_text("<p>before</p>")
        orig = (M.RESULTS, M.PAGE, M._render)
        M.RESULTS, M.PAGE = results_p, page_p

        def boom(_results):
            raise KeyError("benchmark")

        M._render = boom
        try:
            M._publish({"after": True})
        except KeyError:
            pass
        else:
            raise AssertionError("a failing render reported success")
        finally:
            M.RESULTS, M.PAGE, M._render = orig
        assert results_p.read_text() == '{"before": true}', (
            "results.json was replaced even though the page could not be built")
        assert page_p.read_text() == "<p>before</p>"


def test_named_reasons_are_used_only_when_they_explain_the_whole_gap():
    """The builder asserts the reasons account for every drawn parcel, but this
    reads metadata it did not write — an older file with one reason recorded, or a
    newer builder with a reason this code does not know. A partial list rendered
    as a complete one is the under-reporting the drop accounting exists to end."""
    complete = M._ungradeable_note({"drawn": 220, "sampled": 215,
                                    "dropped": {"no_address": 2, "no_year_built": 3}})
    assert "2 had no address on file" in complete

    partial = M._ungradeable_note({"drawn": 220, "sampled": 215,
                                   "dropped": {"no_address": 2}})
    assert "5 could not be graded" in partial, partial
    assert "no address on file" not in partial, (
        "naming 2 of a 5-row gap implies the other 3 away")


def test_jurisdiction_is_rejected_in_the_modes_that_ignore_it():
    """--check --jurisdiction dc read exactly the same committed results as
    --check, and reported success as though it had checked something narrower."""
    src = pathlib.Path(M.__file__).read_text()
    assert '"--jurisdiction", choices=sorted(LABELS), default=None' in src, (
        "the default must be None so the guard can tell 'not supplied' from "
        "'supplied as the default'")
    assert '("--jurisdiction", args.jurisdiction is not None)' in src, (
        "--jurisdiction must join the scoring flags rejected by the no-score modes")


def test_a_non_dict_jurisdictions_map_is_refused_not_crashed():
    """The ROOT type was checked and the map inside it was not, so
    {"jurisdictions": null} reached dict(None) and raised TypeError — the
    unhandled crash this guard exists to replace, one level in from where the
    check was put."""
    for bad in (None, [], "text", 3):
        try:
            M._readable_results({"jurisdictions": bad}, "x", existed=True)
        except SystemExit as exc:
            assert "not an object" in str(exc), (bad, str(exc))
        except (TypeError, ValueError) as exc:
            raise AssertionError(
                f"jurisdictions={bad!r} crashed with {type(exc).__name__} instead "
                f"of a stated refusal")
        else:
            raise AssertionError(f"jurisdictions={bad!r} was accepted")


def test_a_failed_page_write_rolls_the_results_back():
    """Rendering first only covers exceptions from _render. If the page write or
    rename fails — a full disk, a permissions change — the new results would sit
    beside the old page, which is the inconsistency the ordering exists to
    prevent, reached a different way."""
    with tempfile.TemporaryDirectory() as tmp:
        results_p = pathlib.Path(tmp) / "results.json"
        # The target is a NON-EMPTY DIRECTORY, so staging succeeds and the PAGE
        # RENAME is what fails — which is the only path that reaches the rollback.
        # A missing parent fails inside `_staged` before either rename, so this
        # test would have passed with the rollback deleted. Exactly the mistake I
        # already fixed in the temp-leak test and left standing here.
        page_p = pathlib.Path(tmp) / "accuracy.html"
        page_p.mkdir()
        (page_p / "occupant").write_text("x")
        results_p.write_text('{"before": true}')
        orig = (M.RESULTS, M.PAGE, M._render)
        M.RESULTS, M.PAGE = results_p, page_p
        M._render = lambda _r: "<p>new</p>"
        try:
            M._publish({"after": True})
        except OSError:
            pass
        else:
            raise AssertionError("a failed page write reported success")
        finally:
            M.RESULTS, M.PAGE, M._render = orig
        assert results_p.read_text() == '{"before": true}', (
            "the results rename was not rolled back after the page rename failed")
        assert not list(pathlib.Path(tmp).glob("*.tmp")), "temp files left behind"


def test_the_check_applies_the_same_readability_guard_as_the_writers():
    """{"jurisdictions": {}} paired with the matching empty page PASSED the gate,
    while both writers refuse that state as destructive. The gate's one job is
    agreeing with the writers about what is publishable."""
    try:
        M._readable_results({"jurisdictions": {}}, "this check", existed=True)
    except SystemExit:
        pass
    else:
        raise AssertionError("an empty jurisdictions map was accepted")
    src = pathlib.Path(M.__file__).read_text()
    check = src[src.index("    if args.check:"):src.index("    juris = args.jurisdiction")]
    assert "_readable_results(" in check, (
        "the check must refuse what the writers refuse, or it certifies a state "
        "neither of them would produce")


def test_the_dc_basement_caveat_needs_a_dc_section():
    """It lived in the static caveat list, so a Cook-only page told readers what DC
    does not record without showing them any DC."""
    assert M._dc_foundation_caveat({"dc": {}}) != ""
    assert M._dc_foundation_caveat({"cook": {}}) == ""


def test_a_parcel_absent_from_the_layer_is_not_an_undocumented_address():
    """Two different facts were folded into one reason, so the page said "had no
    address on file" about a parcel whose record was simply not there — a claim
    about the assessor's documentation the build has no evidence for."""
    note = M._ungradeable_note({"drawn": 10, "sampled": 7,
                                "dropped": {"no_parcel_record": 2, "no_address": 1}})
    assert "2 were not in the parcel layer" in note, note
    assert "1 had no address on file" in note, note


def test_a_drop_reason_this_page_cannot_name_forces_the_generic_sentence():
    """The completeness test summed EVERY integer in `dropped` while the sentence
    rendered only the reasons this module knows. The map is written by a script
    that changes independently of this one, so a reason added there could make the
    total balance while the sentence named a subset — under-reporting produced by
    the check written to prevent under-reporting.

    It stays impossible only because the rendered set and the summed set are now
    the same object, so this pins that they are."""
    note = M._ungradeable_note({"drawn": 10, "sampled": 5,
                                "dropped": {"no_address": 2, "no_parcel_id": 3}})
    assert "5 could not be graded" in note, note
    assert "had no address" not in note, (
        "naming 2 of a 5-row gap implies the unknown 3 away")

    # A reason the page CAN name, accounting for the whole gap, still reads out.
    named = M._ungradeable_note({"drawn": 10, "sampled": 5,
                                 "dropped": {"no_address": 2, "no_year_built": 3}})
    assert "2 had no address on file" in named and "3 had no usable year" in named


def test_every_rendered_drop_reason_is_one_the_summation_counts():
    """The guarantee is structural, not a coincidence to be maintained by hand."""
    for key in M._DROP_REASONS:
        gap_note = M._ungradeable_note({"drawn": 9, "sampled": 2,
                                        "dropped": {key: 7}})
        assert "could not be graded" not in gap_note, (
            f"{key} is rendered but was not counted toward completeness")


def test_a_failed_rename_leaves_no_temp_file_behind():
    """`_staged` returns a live file, so a failing `replace` propagates and leaves
    `<name>.<random>.tmp` behind. The cleanup existed in `_publish` and not in the
    helper beside it."""
    with tempfile.TemporaryDirectory() as tmp:
        # The target is a NON-EMPTY DIRECTORY, so staging succeeds and the rename
        # is what fails. A missing parent would fail inside `_staged` instead,
        # before any temp exists — which is what my first version of this test did,
        # so it passed against the unfixed code and proved nothing.
        target = pathlib.Path(tmp) / "out.txt"
        target.mkdir()
        (target / "occupant").write_text("x")
        try:
            M._write_atomic(target, "x")
        except OSError:
            pass
        else:
            raise AssertionError("a failed rename reported success")
        assert not list(pathlib.Path(tmp).glob("*.tmp")), (
            f"temp file left behind: {list(pathlib.Path(tmp).glob('*.tmp'))}")


def test_a_failed_lock_acquisition_does_not_leave_the_lock_behind():
    """Between the exclusive create and the try/finally that releases it, the lock
    EXISTS and nothing is registered to remove it. A write or close that raised in
    between left the file behind, turning a transient filesystem error into a
    permanent outage for every later measurement — recoverable only by hand, which
    is exactly what the no-automatic-takeover decision makes expensive."""
    import os as _os
    with _isolated_lock() as lock:
        real_write = _os.write

        def boom(fd, data):
            raise OSError("disk full")

        _os.write = boom
        try:
            with M._results_lock():
                raise AssertionError("acquisition reported success")
        except OSError:
            pass
        finally:
            _os.write = real_write
        assert not lock.exists(), (
            "the lock this process created outlived the failure that created it")

    # And the ordinary path still acquires and releases.
    with _isolated_lock() as lock:
        with M._results_lock():
            assert lock.exists()
        assert not lock.exists()


def test_a_results_file_naming_an_unregistered_jurisdiction_is_refused():
    """The registry decides what may be published. A typo or a section left by a
    newer copy of these scripts was carried through the merge and rendered under
    its bare key, and --check would then certify a page claiming a jurisdiction no
    adapter is registered for."""
    try:
        M._readable_results({"jurisdictions": {"dcx": _sect("dc")}},
                            "this merge", existed=True)
    except SystemExit as exc:
        assert "dcx" in str(exc)
    else:
        raise AssertionError("an unregistered jurisdiction section was accepted")
    # A registered one still passes.
    assert set(M._readable_results({"jurisdictions": {"cook": _sect("cook")}},
                                   "x", existed=True)) == {"cook"}


def test_a_section_must_agree_with_the_key_it_sits_under():
    """Checking only that the KEY is registered left the fabrication one move
    away: put the DC section under "cook" and the page prints DC's numbers beneath
    Cook's heading, with Cook's source line, and --check certifies it. The stamp
    that would catch it was already in the file — the same oversight as the
    benchmark's stamp going unread for the first half of this change."""
    try:
        M._readable_results({"jurisdictions": {"cook": _sect(
            "cook", benchmark={"jurisdiction": "dc"})}}, "x", existed=True)
    except SystemExit as exc:
        assert "'dc'" in str(exc) and "cook" in str(exc)
    else:
        raise AssertionError("a section was published under another's heading")

    # Unstamped is allowed for cook alone: the pre-split measurement predates the
    # field and is genuinely Cook's.
    assert set(M._readable_results({"jurisdictions": {"cook": _sect("cook")}},
                                   "x", existed=True)) == {"cook"}
    try:
        M._readable_results({"jurisdictions": {"dc": _sect(
            "dc", benchmark={"jurisdiction": _OMIT})}}, "x", existed=True)
    except SystemExit as exc:
        assert "no jurisdiction" in str(exc)
    else:
        raise AssertionError("an unstamped non-legacy section was accepted")


def test_the_committed_results_still_pass_every_readability_guard():
    """The guards are only worth having if the real file satisfies them; a guard
    that would reject the committed measurement is a broken guard, not a strict
    one."""
    results = json.loads(M.RESULTS.read_text())
    readable = set(M._readable_results(results, "x", existed=True))
    # Every section in the file must survive the guards, and every section must be
    # a jurisdiction the registry knows. Naming the pair that existed when this was
    # written made adding a third jurisdiction fail a test about readability — the
    # same hardcoded-roster shape the sampler tests were just moved off.
    assert readable == set(results["jurisdictions"])
    assert readable <= set(M.JURISDICTIONS), (
        f"results hold {sorted(readable - set(M.JURISDICTIONS))}, which the "
        f"registry does not name")
    assert readable, "the committed measurement has no readable sections"


_FULL_HEADER = ("parcel_id,address,year_built,sqft,stories,construction,"
                "foundation,condition\n1,A,1990,1000,1,brick,,good\n")


def _graded(tmp, text=_FULL_HEADER):
    import hashlib
    path = pathlib.Path(tmp) / "benchmark-dc.csv"
    path.write_text(text)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def test_a_benchmark_with_no_truth_columns_cannot_be_scored():
    """The digest proves the file is the one its metadata describes and says
    nothing about whether it can be scored. A CSV holding only parcel_id,address
    passed every check, and _score_arms then ran with NO truth fields — zero
    observed rows published for every field while the grade-impact rate was
    computed against a synthetic default label instead of the assessor's record.
    A measurement of nothing, rendered as a measurement."""
    with tempfile.TemporaryDirectory() as tmp:
        path, digest = _graded(tmp, "parcel_id,address\n1,A\n")
        try:
            M._verify_benchmark(path, _meta(sha256_16=digest, rows=1), "dc")
        except SystemExit as exc:
            assert "year_built" in str(exc)
        else:
            raise AssertionError("a benchmark with nothing to grade was accepted")


def test_provenance_is_checked_against_the_registry_not_only_itself():
    """The stamp is metadata and the digest covers only the CSV bytes, so copying
    Cook's pair and editing one word makes a valid-looking DC benchmark. The
    source line the page prints has to agree with the registry too."""
    with tempfile.TemporaryDirectory() as tmp:
        path, digest = _graded(tmp)
        try:
            M._verify_benchmark(path, _meta(sha256_16=digest, rows=1,
                                          source="Cook County Assessor (Open Data)"),
                                "dc")
        except SystemExit as exc:
            assert "jurisdictions.py" in str(exc)
        else:
            raise AssertionError("a DC benchmark citing Cook's assessor passed")
        M._verify_benchmark(path, _meta(sha256_16=digest, rows=1), "dc")


def test_a_section_citing_the_wrong_assessor_is_refused():
    """The page prints the source line beneath the heading, so a section stamped
    `dc` carrying Cook's source renders a DC result attributed to Cook."""
    bad = {"jurisdictions": {"dc": _sect(
        "dc", benchmark={"source": "Cook County Assessor (Open Data)"})}}
    try:
        M._readable_results(bad, "x", existed=True)
    except SystemExit as exc:
        assert "source" in str(exc) and "Cook County Assessor" in str(exc)
    else:
        raise AssertionError("a section attributed to the wrong assessor passed")


def test_a_section_that_is_not_an_object_is_refused_either_way():
    """`{"cook": []}` is falsy, so `data or {}` read it as an empty section and
    accepted it; a truthy non-mapping reached .get() and raised AttributeError."""
    for value in ([], "x", 3, None):
        try:
            M._readable_results({"jurisdictions": {"dc": value}}, "x", existed=True)
        except SystemExit:
            pass
        except AttributeError:
            raise AssertionError(f"section {value!r} crashed instead of refusing")
        else:
            raise AssertionError(f"section {value!r} was accepted")


def test_the_legacy_benchmark_on_disk_is_still_scorable():
    """The pre-split builder wrote `pin`, and `_parcel_matches` still reads it —
    the legacy branch exists to keep that file usable. Requiring `parcel_id`
    unconditionally refused the one benchmark that branch is FOR, so the
    documented compatibility lasted exactly as long as it took to add a schema
    check without looking at the file it had to accept."""
    legacy_header = ("pin,address,lat,lon,year_built,sqft,stories,construction,"
                     "foundation,condition\n1,A,0,0,1990,1000,1,brick,,good\n")
    with tempfile.TemporaryDirectory() as tmp:
        path, digest = _benchmark(tmp, legacy_header)
        M._verify_benchmark(path, _meta("cook", sha256_16=digest, rows=1,
                                        jurisdiction=_OMIT, scope=_OMIT),
                            "cook", legacy=True)
    # ...and `pin` is NOT an acceptable identifier for a jurisdiction-specific
    # file, which the current builder always writes as `parcel_id`.
    with tempfile.TemporaryDirectory() as tmp:
        path, digest = _benchmark(tmp, legacy_header)
        try:
            M._verify_benchmark(path, _meta(sha256_16=digest, rows=1), "dc")
        except SystemExit as exc:
            assert "parcel_id" in str(exc)
        else:
            raise AssertionError("a jurisdiction file with no parcel_id passed")


def test_a_section_with_no_provenance_at_all_is_refused():
    for section in ({}, {"benchmark": {}}, {"benchmark": {"source": ""}}):
        try:
            M._readable_results({"jurisdictions": {"cook": section}}, "x",
                                existed=True)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"{section!r} was published with no attribution")


def test_a_benchmark_block_that_is_not_an_object_is_refused():
    """Typed the section and not the thing inside it — a `benchmark` of "corrupt"
    raised AttributeError from the very .get() meant to read its provenance."""
    for bad in ("corrupt", [], 7):
        try:
            M._readable_results({"jurisdictions": {"dc": {"benchmark": bad}}},
                                "x", existed=True)
        except SystemExit:
            pass
        except AttributeError:
            raise AssertionError(f"benchmark={bad!r} crashed instead of refusing")
        else:
            raise AssertionError(f"benchmark={bad!r} was accepted")


def test_the_scope_sentence_is_checked_against_the_registry():
    """`scope` is printed verbatim as the sentence limiting DC's numbers to
    non-condominium homes — 64% of the city's stock. Editing it to claim all homes
    leaves the CSV, its digest and every other field untouched, so a figure drawn
    from two thirds of DC publishes as DC. The fabrication this whole change is
    about, through the one provenance field nothing read."""
    with tempfile.TemporaryDirectory() as tmp:
        path, digest = _benchmark(tmp)
        base = {"jurisdiction": "dc", "sha256_16": digest, "rows": 2,
                "source": B.JURISDICTIONS["dc"]["source"]}
        M._verify_benchmark(path, {**base, "scope": B.JURISDICTIONS["dc"]["scope"]},
                            "dc")
        try:
            M._verify_benchmark(path, {**base, "scope": "all homes"}, "dc")
        except SystemExit as exc:
            assert "scope" in str(exc)
        else:
            raise AssertionError("a widened scope claim was accepted")

    results = json.loads(M.RESULTS.read_text())
    import copy
    widened = copy.deepcopy(results)
    widened["jurisdictions"]["dc"]["benchmark"]["scope"] = "all homes"
    try:
        M._readable_results(widened, "x", existed=True)
    except SystemExit as exc:
        assert "scope" in str(exc)
    else:
        raise AssertionError("a widened scope claim was published")


def test_a_truncated_section_refuses_rather_than_crashing_the_renderer():
    """A benchmark block and nothing else passed every guard and then raised
    KeyError from _section — --check and --render-only crashing where this
    function promises a stated refusal."""
    section = {"benchmark": {"jurisdiction": "dc",
                             "source": B.JURISDICTIONS["dc"]["source"],
                             "scope": B.JURISDICTIONS["dc"]["scope"]}}
    try:
        M._readable_results({"jurisdictions": {"dc": section}}, "x", existed=True)
    except SystemExit as exc:
        assert "baseline" in str(exc) or "benchmark.rows" in str(exc)
    except KeyError:
        raise AssertionError("a truncated section crashed instead of refusing")
    else:
        raise AssertionError("a section the page cannot render was accepted")


def test_a_benchmark_whose_rows_carry_no_usable_year_is_refused():
    """Headers prove the columns exist and say nothing about what is in them. A
    blank year yields a case with no assessor truth; a non-numeric one aborts
    _score_arms part-way through a run."""
    header = ("parcel_id,address,year_built,sqft,stories,construction,"
              "foundation,condition\n")
    for body, why in ((f"{header}1,A,,1,1,brick,,good\n", "every year blank"),
                      (f"{header}1,A,oops,1,1,brick,,good\n", "non-numeric"),
                      (f"{header}1,A,3999,1,1,brick,,good\n", "implausible")):
        with tempfile.TemporaryDirectory() as tmp:
            path, digest = _benchmark(tmp, body)
            try:
                M._verify_benchmark(path, {
                    "jurisdiction": "dc", "sha256_16": digest, "rows": 1,
                    "source": B.JURISDICTIONS["dc"]["source"],
                    "scope": B.JURISDICTIONS["dc"]["scope"]}, "dc")
            except SystemExit:
                pass
            else:
                raise AssertionError(f"{why}: an unscorable benchmark passed")


def test_every_real_benchmark_on_disk_still_verifies():
    """The guards are only worth having if the real files satisfy them. This
    caught a shape check that rejected the committed measurement, and a schema
    check that rejected the legacy benchmark the legacy branch exists for."""
    cache = pathlib.Path(M.CACHE_DIR)
    for csv_path in sorted(cache.glob("benchmark*.csv")):
        meta_path = csv_path.with_suffix(".meta.json")
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        legacy = csv_path.name == "benchmark.csv"
        juris = meta.get("jurisdiction") or "cook"
        M._verify_benchmark(csv_path, meta, juris, legacy=legacy)


def test_a_drop_reason_is_worded_for_the_join_that_produced_it():
    """`no_parcel_record` counts different things in different jurisdictions. The
    condominium path never asks the parcel layer anything — a unit's SSL is not in
    it — so "were not in the parcel layer" states a fact about the District's map
    that the build has no evidence for."""
    m = {"jurisdiction": "dc-condo", "drawn": 220, "sampled": 212,
         "dropped": {"no_parcel_record": 8, "no_address": 0, "no_year_built": 0}}
    note = M._ungradeable_note(m)
    assert "parcel layer" not in note, note
    assert "unit record" in note, note
    # The parcel-based jurisdictions keep the parcel wording, which is true there.
    for juris in ("cook", "dc"):
        assert "parcel layer" in M._ungradeable_note(dict(m, jurisdiction=juris))


def test_wording_overrides_cannot_change_which_reasons_are_counted():
    """The printed set and the summed set must stay identical, or the total can
    balance while the sentence names a subset. An override adds wording, never a
    reason — so it is built over the shared keys rather than merged into them."""
    for juris in list(M._DROP_WORDING) + ["cook", "dc", None, "made-up"]:
        assert set(M._drop_reasons(juris)) == set(M._DROP_REASONS), juris


def test_every_registered_jurisdiction_gets_wording_that_names_its_own_join():
    """A jurisdiction whose placement is not a parcel lookup must not inherit the
    parcel sentence by default. This fails when a fourth is registered with a
    different join and no wording, which is the moment to write one."""
    parcel_placed = {"cook", "dc"}
    for juris in M.JURISDICTIONS:
        if juris in parcel_placed:
            continue
        assert juris in M._DROP_WORDING, (
            f"{juris} is registered but has no drop-reason wording, so its rows "
            f"would be reported as missing from a parcel layer its join never "
            f"consults")


# --- what the published interval is allowed to claim --------------------------------


def test_the_interval_never_runs_past_a_hundred_percent():
    """DC condominiums answer for about 97%. The textbook normal interval puts the
    upper bound past 100 there, and a page printing 101% accuracy has discredited
    itself before the number is read. Wilson stays inside the range a proportion
    can occupy."""
    lo, hi = M._wilson(205, 211)
    assert 0 <= lo <= hi <= 100, (lo, hi)
    assert M._wilson(200, 200)[1] <= 100


def test_a_bigger_sample_narrows_the_interval():
    """The whole reason n was computed rather than guessed."""
    narrow = M._wilson(732, 1000)
    wide = M._wilson(73, 100)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_an_empty_sample_has_no_interval_rather_than_a_wrong_one():
    assert M._wilson(0, 0) is None


def test_the_interval_brackets_the_rate_it_describes():
    for hits, n in ((73, 100), (205, 211), (1, 50), (49, 50)):
        lo, hi = M._wilson(hits, n)
        assert lo <= 100 * hits / n <= hi, (hits, n, lo, hi)


def test_a_single_run_reports_no_spread_at_all():
    """One scoring cannot say how much scoring varies. Reporting the sampling
    interval as though it covered run-to-run noise too would dress half the
    uncertainty up as the whole — and it is the half that does NOT shrink when the
    sample grows, so the dressing would point a reader at the wrong repair."""
    assert M._spread([]) is None
    one = M._spread([73.2])
    assert one["runs"] == 1 and one["spread"] == 0.0


def test_the_spread_reports_what_repeated_scorings_actually_did():
    got = M._spread([68.2, 73.2, 70.1])
    assert got["min"] == 68.2 and got["max"] == 73.2
    assert got["spread"] == 5.0
    assert got["median"] == 70.1


def test_the_two_uncertainties_are_reported_separately():
    """A reader told only their sum cannot tell which to attack: a wide sampling
    interval is fixed by drawing more rows, a wide run-to-run range is fixed
    upstream and by no amount of sampling."""
    sentence = M._confidence_sentence(
        {"resolved_ci95": [67.9, 77.8], "resolved_runs": M._spread([68.2, 73.2])})
    assert "67.9" in sentence and "77.8" in sentence
    assert "68.2" in sentence and "73.2" in sentence
    assert "not sampling error" in sentence


def test_no_confidence_sentence_when_nothing_was_measured():
    assert M._confidence_sentence({}) == ""


def test_the_explanation_does_not_outlive_the_range_it_explains():
    """The tail explaining "the second range" was keyed on the field existing
    rather than on the range being printed, so a section holding a single run
    rendered a sentence explaining a range the reader could not see. A sentence
    describing evidence that is not there is the same defect as a number without
    provenance, one layer out."""
    one = M._confidence_sentence(
        {"resolved_ci95": [67.9, 77.8], "resolved_runs": M._spread([73.2])})
    assert "67.9" in one
    assert "second range" not in one, one
    many = M._confidence_sentence(
        {"resolved_ci95": [67.9, 77.8], "resolved_runs": M._spread([68.2, 73.2])})
    assert "second range" in many


def test_the_sampler_docstrings_describe_the_draw_the_page_publishes():
    """The page prints "drawn uniform random offsets without replacement" beside
    every rate. A sampler whose own docstring says "evenly-spaced" contradicts a
    published claim about how the number was made."""
    import scripts.build_benchmark as B
    for fn in (B._cama_sample, B._dc_sample, B._dc_condo_sample):
        doc = (fn.__doc__ or "").lower()
        assert "evenly" not in doc, f"{fn.__name__}: {doc!r}"
        assert "random" in doc, f"{fn.__name__}: {doc!r}"


def test_a_nested_jurisdiction_renders_under_its_parent_not_beside_it():
    """DC's condominiums are a narrower claim inside DC, not a second city. The
    heading level is the statement; two <h2>s would read as two places."""
    parent = _juris("DC Office of Tax and Revenue (Open Data)", "1234    5678")
    parent["benchmark"]["scope"] = M.JURISDICTIONS["dc"]["scope"]
    child = _juris("DC Office of Tax and Revenue (Open Data)", "2528    2029")
    child["benchmark"]["scope"] = M.JURISDICTIONS["dc-condo"]["scope"]
    page = M._render({"generated": "2026-08-27",
                      "jurisdictions": {"dc": parent, "dc-condo": child}})
    assert '<h2 id="dc">' in page
    assert '<h3 id="dc-condo">' in page
    assert '<h2 id="dc-condo">' not in page
    # ...and the child must come after its parent, not before it by alphabet.
    assert page.index('id="dc"') < page.index('id="dc-condo"')


def test_the_publication_order_puts_every_parent_before_its_children():
    from scripts.jurisdictions import JURISDICTIONS as J, ordered
    order = ordered()
    assert set(order) == set(J), (sorted(order), sorted(J))
    for key, cfg in J.items():
        parent = cfg.get("parent")
        if parent:
            assert order.index(parent) < order.index(key), key
            assert parent in J, f"{key} names an unregistered parent {parent!r}"


def test_a_replicate_count_below_one_is_refused_not_crashed_on():
    """Zero replicates scored nothing and then indexed the empty list for a median
    run — an IndexError where this script otherwise states its refusals."""
    for bad in (0, -1, -3):
        argv = sys.argv
        sys.argv = ["measure_accuracy.py", "--replicates", str(bad), "--dry-run"]
        try:
            M.main()
        except SystemExit as exc:
            assert "--replicates must be at least 1" in str(exc), (bad, str(exc))
        except IndexError:  # pragma: no cover - the defect this pins
            raise AssertionError(f"--replicates {bad} crashed instead of refusing")
        else:
            raise AssertionError(f"--replicates {bad} was accepted")
        finally:
            sys.argv = argv


def test_every_scoring_flag_is_refused_beside_a_mode_that_scores_nothing():
    """--check and --render-only score nothing, so a scoring flag beside either is
    accepted and silently ignored — the caller believes it took effect. The rule
    predates --replicates, and --replicates walked straight past it."""
    for mode in ("--check", "--render-only"):
        argv = sys.argv
        sys.argv = ["measure_accuracy.py", mode, "--replicates", "3"]
        try:
            M.main()
        except SystemExit as exc:
            assert "--replicates" in str(exc) and "ignored" in str(exc), str(exc)
        else:
            raise AssertionError(f"{mode} --replicates 3 was accepted")
        finally:
            sys.argv = argv


def test_the_documented_invocations_carry_every_required_argument():
    """Both module docstrings print a Run: line to copy. The builder now requires a
    seed, so a line without one fails at argparse for anyone following it."""
    import scripts.build_benchmark as B
    for mod in (B, M):
        for line in (mod.__doc__ or "").splitlines():
            if "build_benchmark.py" in line and "python" in line:
                assert "--seed" in line, f"{mod.__name__}: {line.strip()!r}"


def test_the_cache_walk_reaches_the_caches_that_make_requests():
    """Replicates are only measurements if each one actually makes its requests.
    The adapters and the geocoder memoise, so the second scoring of a row answers
    from memory: the DC condominium benchmark took half an hour on the first run
    and thirty-eight seconds on the second. A cache replay cannot fail the way a
    live request can, so a range across such runs describes the cache — and reads
    as reassuring stability, which is the worst way to be wrong about the number
    this page exists to qualify."""
    from housing_label.enrich.assessor import cook_il, dc
    from housing_label.simulate import location as L

    caches = (dc._lookup_cached, cook_il._lookup_cached, L._geocode_address_cached)
    for c in caches:
        c.cache_clear()
    # Populate without network: lru_cache stores whatever the call returns, and a
    # refusal is a perfectly good cache entry — which is the point, a cached miss
    # replays as a miss.
    dc._lookup_cached(0.0, 0.0, None)
    cook_il._lookup_cached(0.0, 0.0, None)
    assert any(c.cache_info().currsize for c in caches), "nothing cached to clear"

    assert M._clear_caches() > 0
    for c in caches:
        assert c.cache_info().currsize == 0, c


def test_replicates_that_plainly_replayed_a_cache_are_refused():
    """The check of last resort behind the cache walk, and independent of it: it
    needs no knowledge of where the caches are, so it still fires if a future one
    escapes the walk. These are the real numbers from the run that exposed the
    bug — half an hour, then thirty-eight seconds, then two."""
    try:
        M._refuse_cache_replay([1800.0, 38.0, 2.0])
    except SystemExit as exc:
        assert "did not repeat the work" in str(exc)
    else:
        raise AssertionError("a cache replay was accepted as a replicate")


def test_honestly_varying_runtimes_are_not_refused():
    """Portal latency moves real runs around. A threshold tight enough to catch
    every replay would refuse honest runs on a slow afternoon — the failure this
    exists for was three orders of magnitude, not a factor of two."""
    M._refuse_cache_replay([1800.0, 2400.0, 2100.0])
    M._refuse_cache_replay([600.0, 900.0])
    M._refuse_cache_replay([1800.0])      # one run cannot be a replay of anything
    M._refuse_cache_replay([])


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
