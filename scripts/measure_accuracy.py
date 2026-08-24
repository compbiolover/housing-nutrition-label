#!/usr/bin/env python3
"""Measure how often the label describes the house that is actually there.

The question this answers
-------------------------
Every buyer segment in ``research/monetization-research.md`` opens with "how
accurate is it", and until now the answer was a paragraph of prose. The repo's
900+ tests all assert that the code does what it says; none of them asks whether
the output matches the world. This does.

For each benchmark address (``scripts/build_benchmark.py``) the scorer is pointed
at the address with **no construction attributes supplied** — the way a visitor
uses it — and what it infers is compared against what the county recorded.

Three arms, and the third is the point
--------------------------------------
* ``baseline`` — adapters off. NSI's structure record plus the tract's ACS
  year-built distribution: what every label outside an adapter county gets.
* ``adapter`` — adapters on. The county's observed record where it resolves.
* ``truth`` — the ground truth supplied explicitly. Not an accuracy arm; it is
  the reference the other two are graded against, because the number that
  matters is not "how many years out is the year built" but *does the reader see
  a different letter*.

The two arms share one location resolve. Everything expensive — the geocode, NSI,
the flood zone — happens once per address, and the arms differ only in whether
``location.assessor`` is present. That also makes the comparison exact: the arms
cannot diverge for any reason except the thing under test.

The headline metric
-------------------
**Grade-impact rate**: the share of addresses where an arm shows a different
letter than the truth does, per dimension and for the Building axis. Field-level
error (years, square feet) is reported too, but a 6-year year-built error that
moves no grade is not a defect a reader can see, and a 3-year one that crosses a
code-era boundary is.

Network, and why this is not a unit test
----------------------------------------
Every row geocodes and hits NSI, so this cannot run in CI. It follows the
``build_*.py`` contract instead: run manually, commit the results, and let CI
verify the published page still matches the committed run (``--check``).

Run:  python scripts/build_benchmark.py --rows 200
      ASSESSOR_ADAPTERS=1 python scripts/measure_accuracy.py
      python scripts/measure_accuracy.py --check
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import html
import json
import logging
import pathlib
import statistics
import sys
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger("measure_accuracy")

_ROOT = pathlib.Path(__file__).resolve().parents[1]
# Both entries are needed and neither is the cwd: `src` for the package, the repo
# root for `scripts.build_icons` below. Relying on the cwd instead would work when
# run from the repo root and fail anywhere else, which is the kind of breakage
# that only shows up in somebody else's shell.
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.legal import DISCLAIMER  # noqa: E402
# The brand navy, read from the constant the favicons are actually drawn from
# rather than copied as a literal — test_icons already pins that constant against
# the CSS variable, so importing it puts this page inside the same guard instead
# of beside it.
from scripts.build_icons import PALETTE as _ICON_PALETTE  # noqa: E402

_THEME_NAVY = _ICON_PALETTE["tile"]

CACHE_DIR = _ROOT / ".accuracy_cache"
BENCHMARK = CACHE_DIR / "benchmark.csv"
META = CACHE_DIR / "benchmark.meta.json"
RESULTS = _ROOT / "research" / "accuracy" / "results.json"
PAGE = _ROOT / "docs" / "accuracy.html"

NUMERIC = ("year_built", "sqft", "stories")
CATEGORICAL = ("construction", "foundation", "condition")
FIELDS = NUMERIC + CATEGORICAL

# The dimensions a construction attribute can actually move, plus the axis that
# aggregates them. Composite is deliberately excluded: it averages in eight
# location dimensions that no construction input touches, so a grade-impact rate
# computed on it would be diluted by design and read as better than it is.
GRADED = ("durability", "energy", "resilience", "environmental")
AXIS = "construction_national_grade"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# What the payload puts in a grade field when the dimension could not be scored
# (dimensions.py). It is a rendering character, not a grade, and it reaches this
# module through the same key a real letter does — so it is normalised to None
# here, once, rather than at each comparison. Left alone, two unscorable rows
# would compare EQUAL and be counted as the label agreeing with the truth, which
# inflates the headline accuracy with rows that were never scored at all.
_UNSCORED = "\u2014"


def _grade(v):
    return None if v in (None, "", _UNSCORED) else v


def _grades(payload: dict) -> dict:
    out = {d["key"]: _grade(d.get("national_grade"))
           for d in payload.get("dimensions", []) if d.get("key") in GRADED}
    out["building_axis"] = _grade(payload.get(AXIS))
    return out


def _pin_matches(loc, row: dict) -> bool:
    """Whether the adapter resolved the same parcel the benchmark row describes."""
    record = getattr(loc, "assessor", None)
    if record is None:
        return False
    got = str(getattr(record, "parcel_id", "") or "").strip().zfill(14)
    want = str(row.get("pin") or "").strip().zfill(14)
    return bool(got) and got == want


def _score_arms(row: dict) -> dict | None:
    """Score one benchmark address three ways off a single location resolve."""
    from housing_label.simulate.house import build_label_parts, label_payload
    from housing_label.simulate.location import resolve_location

    try:
        loc = resolve_location(address=row["address"], allow_network=True)
    except Exception as exc:  # noqa: BLE001
        log.debug("  %s: location failed (%s)", row["address"], exc)
        return None
    if loc is None or not loc.tract:
        return None

    # The arms differ in exactly one attribute of one object.
    loc_off = dataclasses.replace(loc, assessor=None)

    truth_fields = {}
    for f in FIELDS:
        v = row.get(f)
        if v not in (None, ""):
            truth_fields[f] = _num(v) if f in NUMERIC else v
    for f in ("year_built", "stories"):
        if f in truth_fields:
            truth_fields[f] = int(truth_fields[f])

    # The county's floor area is the whole building's; the label's sqft is per
    # dwelling unit. On a multi-unit parcel they are different quantities, so
    # comparing them would score a basis mismatch as an accuracy failure — and
    # feeding the building total in as truth would inflate the reference profile
    # exactly as it would inflate a real label. The adapter drops the field for
    # the same reason (see _autofill_construction_from_nsi); truth follows it, so
    # both sides of the comparison hold the same rule.
    if getattr(loc, "structure_type", None) == "multifamily":
        truth_fields.pop("sqft", None)

    def run(location, **fields):
        cfg, r, label = build_label_parts(location=location, allow_network=True,
                                          allow_non_residential=True, **fields)
        return cfg, label_payload(cfg, r, label)

    try:
        cfg_off, pay_off = run(loc_off)
        cfg_on, pay_on = run(loc)
        _cfg_t, pay_truth = run(loc_off, **truth_fields)
    except Exception as exc:  # noqa: BLE001
        log.debug("  %s: scoring failed (%s)", row["address"], exc)
        return None

    return {
        "address": row["address"],
        "truth": truth_fields,
        # `resolved` is whether the adapter answered at all, because that is what a
        # visitor experiences: they type this address, the lookup runs, and either
        # a county record reaches the label or it does not.
        #
        # A wrong-parcel answer is NOT excluded. An earlier revision marked a PIN
        # disagreement unresolved while still scoring the adapter arm from the
        # record it found — hiding the mismatch from coverage while letting its
        # wrong values degrade accuracy, which is the least honest of the
        # available choices. Whichever parcel the lookup landed on, its values are
        # what the visitor is shown for THIS address, so they belong in the
        # accuracy rates. The mismatch is a distinct defect from a bad field
        # mapping, so it is counted and published beside them rather than folded
        # in silently.
        "resolved": loc.assessor is not None,
        "pin_mismatch": (loc.assessor is not None and not _pin_matches(loc, row)),
        "baseline": {"inferred": {f: cfg_off.get(f) for f in FIELDS},
                     "grades": _grades(pay_off)},
        "adapter": {"inferred": {f: cfg_on.get(f) for f in FIELDS},
                    "grades": _grades(pay_on)},
        "truth_grades": _grades(pay_truth),
    }


def _summarise(cases: list[dict], arm: str) -> dict:
    """Field error and grade impact for one arm."""
    out: dict = {"fields": {}, "grade_impact": {}}

    for f in FIELDS:
        pairs = [(c["truth"][f], c[arm]["inferred"].get(f)) for c in cases
                 if f in c["truth"]]
        got = [(t, g) for t, g in pairs if g is not None]
        entry = {"n": len(pairs), "coverage_pct": round(100 * len(got) / len(pairs), 1)
                 if pairs else None}
        if got and f in NUMERIC:
            errs = [abs(float(g) - float(t)) for t, g in got]
            entry["median_abs_error"] = round(statistics.median(errs), 1)
            entry["exact_pct"] = round(100 * sum(e == 0 for e in errs) / len(errs), 1)
            if f == "year_built":
                for tol in (5, 10):
                    entry[f"within_{tol}yr_pct"] = round(
                        100 * sum(e <= tol for e in errs) / len(errs), 1)
            if f == "sqft":
                rel = [abs(float(g) - float(t)) / float(t) for t, g in got if float(t)]
                entry["median_abs_pct_error"] = round(100 * statistics.median(rel), 1) if rel else None
        elif got:
            entry["exact_pct"] = round(100 * sum(g == t for t, g in got) / len(got), 1)
        out["fields"][f] = entry

    for key in list(GRADED) + ["building_axis"]:
        pairs = [(c["truth_grades"].get(key), c[arm]["grades"].get(key)) for c in cases]
        pairs = [(t, g) for t, g in pairs if t is not None and g is not None]
        out["grade_impact"][key] = {
            "n": len(pairs),
            "differs_pct": round(100 * sum(t != g for t, g in pairs) / len(pairs), 1)
            if pairs else None,
        }
    return out


def _tolerance_sentence(results: dict) -> str:
    """The ±5 / ±10-year bands, which _summarise computes and the tables above do
    not show. They were quoted as a headline result while appearing nowhere on the
    page a reader was pointed at, which is the kind of gap that makes a published
    number unverifiable."""
    b = results["baseline"]["fields"]["year_built"]
    a = results["adapter"]["fields"]["year_built"]
    def pct(e, k):
        v = e.get(k)
        return "&mdash;" if v is None else f"{v}%"
    return (f"within &plusmn;5 years {pct(b,'within_5yr_pct')} of the time at "
            f"baseline and {pct(a,'within_5yr_pct')} with the assessor; within "
            f"&plusmn;10 years {pct(b,'within_10yr_pct')} and "
            f"{pct(a,'within_10yr_pct')}.")


def _mismatch_note(results: dict) -> str:
    """Disclose lookups that found a parcel, but not the right one.

    Folding these into the accuracy rate would publish a matching failure as an
    accuracy failure. They are a distinct defect, so they are counted unresolved
    and named here instead of disappearing.
    """
    n = results.get("pin_mismatches") or 0
    if not n:
        return ""
    return (f", of which {n} landed on a different parcel than the benchmark row "
            f"&mdash; those answers are wrong for the address asked about, and are "
            f"scored as the error they are rather than set aside")


def _unscored_note(results: dict) -> str:
    """Say so when rows were sampled but could not be scored, and stay silent when
    none were — a permanent "0 could not be scored" is noise, a missing one when
    there were 40 is a misrepresented sample size."""
    n = results.get("unscored") or 0
    if not n:
        return ""
    return (f"; a further {n} sampled address{'es' if n != 1 else ''} could not be "
            f"geocoded or scored and {'are' if n != 1 else 'is'} excluded from every "
            f"rate below")


def _render(results: dict) -> str:
    m = results["benchmark"]
    rows_f, rows_g = [], []
    for f in FIELDS:
        b, a = results["baseline"]["fields"][f], results["adapter"]["fields"][f]
        def cell(e, k, suffix=""):
            v = e.get(k)
            return "—" if v is None else f"{v}{suffix}"
        rows_f.append(
            f"<tr><td>{html.escape(f)}</td>"
            f"<td>{cell(b,'coverage_pct','%')}</td><td>{cell(a,'coverage_pct','%')}</td>"
            f"<td>{cell(b,'exact_pct','%')}</td><td>{cell(a,'exact_pct','%')}</td>"
            f"<td>{cell(b,'median_abs_error')}</td><td>{cell(a,'median_abs_error')}</td>"
            f"<td>{b.get('n', 0)}</td></tr>")
    for k in list(GRADED) + ["building_axis"]:
        b, a = results["baseline"]["grade_impact"][k], results["adapter"]["grade_impact"][k]
        bv = "—" if b["differs_pct"] is None else f"{b['differs_pct']}%"
        av = "—" if a["differs_pct"] is None else f"{a['differs_pct']}%"
        rows_g.append(f"<tr><td>{html.escape(k)}</td><td>{bv}</td><td>{av}</td>"
                      f"<td>{b['n']}</td></tr>")

    # The site-wide head block and the disclaimer are not decoration: two tests
    # (test_icons, test_disclaimer) assert that EVERY page under docs/ carries
    # them, and a generated page is not exempt from a rule about what a reader
    # sees. Both are taken from the same sources the hand-written pages use, so a
    # palette or wording change reaches this page too.
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Accuracy &mdash; Housing Nutrition Label</title>
<link rel="icon" href="favicon.svg" type="image/svg+xml" sizes="any">
<link rel="icon" href="favicon.ico" type="image/x-icon" sizes="any">
<link rel="apple-touch-icon" href="apple-touch-icon.png" sizes="180x180">
<meta name="theme-color" content="{html.escape(_THEME_NAVY)}">
<link rel="stylesheet" href="style.css"><link rel="stylesheet" href="label-core.css">
</head><body>
<!-- GENERATED by scripts/measure_accuracy.py — do not edit by hand. -->
<a href="#main" class="skip-link">Skip to content</a>
<nav>
  <a href="index.html" class="logo">Housing<span>Label</span>.dev</a>
  <button class="hamburger" aria-label="Menu">&#9776;</button>
  <ul>
    <li><a href="index.html">Overview</a></li>
    <li><a href="methodology.html">Methodology</a></li>
    <li><a href="examples.html">Examples</a></li>
    <li><a href="label.html">Label</a></li>
    <li><a href="setup.html">Setup</a></li>
    <li><a href="reference.html">Reference</a></li>
    <li><a href="https://github.com/compbiolover/housing-nutrition-label">GitHub</a></li>
  </ul>
</nav>
<main id="main" style="max-width:56rem;margin:0 auto;padding:1.5rem;">
<h1>How accurate is the label?</h1>

<p>Every score on this site is inferred from public data. This page measures how
often that inference matches what a county assessor recorded for the same
building &mdash; the only check that asks whether the output describes the world
rather than whether the code does what it says.</p>

<p><strong>Method.</strong> {m.get('sampled', m['rows'])} addresses sampled across
{html.escape(m['source'])} (assessment year {html.escape(str(m['assessment_year']))},
fetched {html.escape(m['fetched'])}){_unscored_note(results)}. Each is scored from
the address alone, with no construction details supplied, and compared against the
county's record. The benchmark itself is not redistributed; see the note at the
foot of this page.</p>

<h2>Field accuracy</h2>
<p><em>Baseline</em> is what the label infers everywhere: a modelled structure
record plus the census tract's year-built distribution. <em>With assessor</em> adds
an observed county record where one resolves.</p>
<div class="table-scroll"><table class="data-table"><thead><tr>
<th>Field</th><th>Coverage<br>baseline</th><th>Coverage<br>w/ assessor</th>
<th>Exact<br>baseline</th><th>Exact<br>w/ assessor</th>
<th>Median error<br>baseline</th><th>Median error<br>w/ assessor</th><th>Graded on</th>
</tr></thead><tbody>
{chr(10).join(rows_f)}
</tbody></table></div>

<p><strong>Year built, by tolerance.</strong> The single field the rest of the
construction profile leans on hardest, so the near-misses are worth seeing rather
than collapsing into one median: {_tolerance_sentence(results)}</p>

<h2>Does the reader see a different grade?</h2>
<p>The number that matters. A year-built error that moves no letter is not a
defect anyone can see; one that crosses a code-era boundary is. Share of
addresses whose letter differs from the one the true attributes produce:</p>
<div class="table-scroll"><table class="data-table"><thead><tr>
<th>Dimension</th><th>Baseline</th><th>With assessor</th><th>n</th>
</tr></thead><tbody>
{chr(10).join(rows_g)}
</tbody></table></div>

<h2>What this does and does not establish</h2>
<ul>
<li>The sample is <strong>Cook County, Illinois only</strong>, because it is the
only county with both an adapter and free published ground truth. It is a real
measurement of one county's housing stock, not a national accuracy figure, and it
should not be read as one.</li>
<li>The county's own record is treated as truth. It can be stale or wrong; it is
the best available reference, not a survey.</li>
<li>Addresses where the assessor lookup does not resolve fall back to the
baseline, so the &ldquo;with assessor&rdquo; column includes them. It is the
end-to-end number a visitor would experience, not the adapter's accuracy on the
rows it answers.</li>
<li>The benchmark is fetched on demand and not committed: Cook County grants no
explicit right to redistribute a dataset. Re-running months later samples a
refreshed roll, so the digest and date above are recorded to make that visible.</li>
<li><strong>The categorical fields are a weaker test than the numeric ones.</strong>
Wall material, foundation and condition are translated out of the county's
vocabulary into the label's by the same table on both sides of the comparison, so
their &ldquo;exact&rdquo; rates in the assessor column largely measure whether the
right parcel was found &mdash; not whether the translation is right. One entry is
knowingly lossy: the county's single <em>Masonry</em> category is read as brick,
the label's brick/block/stone distinction being finer than the source. Year built
and floor area carry no such circularity; they are numbers, compared as numbers.</li>
<li><strong>Rows are not graded on every field.</strong> The
<em>Graded on</em> column is each field's own denominator, and it is not always the
full sample. Floor area is the clearest case: the county records the whole
building's area while the label's figure is per dwelling unit, so on a multi-unit
parcel the two are different quantities and the row is excluded rather than scored
as a miss. A rate is over the rows in that column, not over every address
sampled.</li>
<li><strong>Condition is close to a constant here.</strong> All but a handful of
sampled parcels carry the county's <em>Average</em> grade, so a high agreement rate
on that row reflects the distribution of the source far more than the label's
skill, and should not be read as one.</li>
<li><strong>The reference profile is not wholly observed.</strong> Where the county
records nothing for a field, the truth arm falls back to the same modelled inputs
the other two arms use, so a grade attributed to &ldquo;true attributes&rdquo; is
built from the county's facts <em>plus</em> those fallbacks. It is the best
available reference, and on the rows with an incomplete record it understates the
distance between the arms rather than overstating it.</li>
</ul>

<p style="opacity:0.75;font-size:0.85rem;margin-top:2rem;border-top:1px solid #cbd5e1;
padding-top:0.9rem;">{html.escape(DISCLAIMER)}</p>

<p style="opacity:0.75;font-size:0.85rem;">Assessor lookups resolved for
{results['adapter_resolved_pct']}% of the sample{_mismatch_note(results)} &middot; benchmark digest
{html.escape(m['sha256_16'])} &middot; generated {html.escape(results['generated'])}.
Regenerate with <code>python scripts/measure_accuracy.py</code>.</p>
</main>
<script src="nav.js"></script>
</body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="verify the published page matches the committed results")
    ap.add_argument("--limit", type=int, default=None, help="score only the first N rows")
    ap.add_argument("--render-only", action="store_true",
                    help="rebuild the page from the committed results, no scoring")
    args = ap.parse_args()

    if args.render_only:
        # For a copy or layout edit: the measurements are the expensive part and
        # they have not changed, so re-scoring 200 addresses to restyle a table
        # would be both slow and a small lie about when they were taken.
        if not RESULTS.exists():
            raise SystemExit(f"{RESULTS} missing — nothing to render")
        PAGE.write_text(_render(json.loads(RESULTS.read_text())))
        log.info("Rendered %s from the committed measurements.", PAGE)
        return 0

    if args.check:
        if not RESULTS.exists():
            log.error("%s is missing — run the harness and commit its output.", RESULTS)
            return 1
        results = json.loads(RESULTS.read_text())
        if not PAGE.exists() or PAGE.read_text() != _render(results):
            log.error("%s is out of date. Regenerate: python scripts/measure_accuracy.py "
                      "--render-only", PAGE)
            return 1
        log.info("accuracy page is in sync with the committed measurements.")
        return 0

    if not BENCHMARK.exists():
        raise SystemExit(f"{BENCHMARK} missing — run scripts/build_benchmark.py first")
    # Fail closed, not open. With no adapter enabled both arms resolve identically
    # and the run would overwrite the published results with a comparison of the
    # baseline against itself — a non-measurement that renders as a real one, and
    # the headline claim of the whole project. Asking the gate itself also catches
    # ASSESSOR_ADAPTERS=0, which a presence check reads as enabled and enabled()
    # reads as off.
    from housing_label.enrich.assessor import enabled as _adapters_enabled
    if not _adapters_enabled():
        raise SystemExit(
            "ASSESSOR_ADAPTERS is not enabled, so the adapter arm would equal the "
            "baseline. Refusing to publish a measurement of nothing — set "
            "ASSESSOR_ADAPTERS=1 to run, or --render-only to rebuild the page from "
            "the committed results.")

    rows = list(csv.DictReader(BENCHMARK.open()))
    if args.limit is not None:
        # `if args.limit` would read 0 as "no limit" and quietly score the whole
        # benchmark — the opposite of what was asked, and expensive to discover.
        if args.limit < 1:
            raise SystemExit(f"--limit must be at least 1 (got {args.limit})")
        rows = rows[:args.limit]
    meta = json.loads(META.read_text()) if META.exists() else {}

    cases = []
    for i, row in enumerate(rows, 1):
        case = _score_arms(row)
        if case is not None:
            cases.append(case)
        if i % 10 == 0 or i == len(rows):
            log.info("scored %d/%d (%d usable)", i, len(rows), len(cases))
    if not cases:
        raise SystemExit("no address scored — refusing to publish an empty measurement")

    resolved = sum(1 for c in cases if c["resolved"])
    mismatched = sum(1 for c in cases if c.get("pin_mismatch"))
    results = {
        "generated": date.today().isoformat(),
        # Both counts, deliberately. Every rate below is over the rows that could be
        # scored, and silently republishing that as the sample size would let a
        # network outage or a batch of hard addresses quietly narrow the population
        # while the page still read as the full sample.
        "benchmark": {**meta, "sampled": len(rows), "rows": len(cases)},
        "unscored": len(rows) - len(cases),
        # Over the sampled population, not the scored subset. Dividing by
        # `cases` would drop every address that failed to geocode out of the
        # denominator, so the failures this metric should expose could only ever
        # raise it. It is published as end-to-end coverage, so it is measured
        # that way.
        "adapter_resolved_pct": round(100 * resolved / len(rows), 1),
        "pin_mismatches": mismatched,
        "baseline": _summarise(cases, "baseline"),
        "adapter": _summarise(cases, "adapter"),
    }

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=2) + "\n")
    PAGE.write_text(_render(results))

    log.info("Scored %d addresses; assessor answered for %d (%.1f%%); "
             "%d of those landed on a different parcel (scored as error).",
             len(cases), resolved, results["adapter_resolved_pct"], mismatched)
    for f in FIELDS:
        b = results["baseline"]["fields"][f]
        a = results["adapter"]["fields"][f]
        log.info("  %-13s exact %5s%% → %5s%%   median err %6s → %6s",
                 f, b.get("exact_pct"), a.get("exact_pct"),
                 b.get("median_abs_error"), a.get("median_abs_error"))
    log.info("  grade differs from truth:")
    for k in list(GRADED) + ["building_axis"]:
        log.info("    %-14s %5s%% → %5s%%", k,
                 results["baseline"]["grade_impact"][k]["differs_pct"],
                 results["adapter"]["grade_impact"][k]["differs_pct"])
    log.info("Wrote %s and %s.", RESULTS, PAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
