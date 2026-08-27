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
uses it — and what it infers is compared against what that jurisdiction's assessor
recorded.

Three arms, and the third is the point
--------------------------------------
* ``baseline`` — adapters off. NSI's structure record plus the tract's ACS
  year-built distribution: what every label outside an adapter's area gets.
* ``adapter`` — adapters on. The assessor's observed record where it resolves.
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

Each jurisdiction is measured separately and its results merge into the published
page, so running one never replaces another's numbers.

Run:  python scripts/build_benchmark.py --jurisdiction dc --rows 200 --seed 20260827
      ASSESSOR_ADAPTERS=1 python scripts/measure_accuracy.py --jurisdiction dc
      python scripts/measure_accuracy.py --check
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import dataclasses
import html
import json
import logging
import math
import os
import pathlib
import statistics
import sys
import tempfile
import time
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
# The display names, derived from the registry build_benchmark.py draws from,
# so a third adapter cannot be accepted by one script and unknown to the other.
from scripts.jurisdictions import JURISDICTIONS, LABELS, ordered  # noqa: E402
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
LOCK = CACHE_DIR / "results.lock"
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


def _parcel_key(raw) -> str:
    """A parcel identifier in a form two jurisdictions can both be compared in.

    Cook's PIN is a 14-digit number that loses leading zeros in some exports, so it
    is zero-padded — the county's own guidance. DC's SSL is `square + suffix + lot`
    with interior spaces and is not a number at all, so padding it would be
    meaningless; only the digit case is padded, and whitespace is collapsed so a
    difference in column formatting cannot read as a different parcel.
    """
    text = " ".join(str(raw or "").split()).upper()
    return text.zfill(14) if text.isdigit() else text


def _parcel_matches(loc, row: dict) -> bool:
    """Whether the adapter resolved the same parcel the benchmark row describes."""
    record = getattr(loc, "assessor", None)
    if record is None:
        return False
    got = _parcel_key(getattr(record, "parcel_id", ""))
    # `pin` is the column the first benchmark used, before a second jurisdiction
    # made the name wrong; an older cached file still reads.
    want = _parcel_key(row.get("parcel_id") or row.get("pin"))
    return bool(got) and got == want


#: Jurisdictions whose ground-truth floor area is already per dwelling unit.
#: Cook's `char_bldg_sf` and DC's residential `GBA` are the whole building's, so
#: on a multi-unit parcel they are a different quantity from the label's sqft and
#: are dropped below. DC's condominium `LIVING_GBA` is the unit's own area — the
#: one field the condominium table gets righter than the residential one — and
#: dropping it there discards the measurement instead of protecting it.
PER_UNIT_AREA = frozenset({"dc-condo"})


def _score_arms(row: dict, juris: str) -> dict | None:
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
    #
    # ...which is exactly why it is conditional. A condominium record's
    # LIVING_GBA is ALREADY per unit, and the adapter deliberately keeps it. NSI
    # calls a condo building multifamily, as it should, so applying this rule
    # there discarded the truth for 188 of 211 units while the adapter went on
    # reporting one — the two sides of the comparison holding different rules,
    # which is the thing the paragraph above claims cannot happen. It measured
    # sqft on the 23 rows NSI happened to misclassify, and called that the
    # condominium floor-area accuracy.
    if juris not in PER_UNIT_AREA and getattr(loc, "structure_type", None) == "multifamily":
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
        "parcel_mismatch": (loc.assessor is not None
                            and not _parcel_matches(loc, row)),
        "baseline": {"inferred": {f: cfg_off.get(f) for f in FIELDS},
                     "grades": _grades(pay_off)},
        "adapter": {"inferred": {f: cfg_on.get(f) for f in FIELDS},
                    "grades": _grades(pay_on)},
        "truth_grades": _grades(pay_truth),
    }


def _wilson(hits: int, n: int, z: float = 1.959963985) -> list[float] | None:
    """A 95% Wilson interval for a proportion, in percentage points.

    Wilson rather than the textbook normal interval: at the rates these adapters
    reach — DC condominiums answer for about 97% — the normal interval runs past
    100%, and an accuracy page that prints an upper bound of 101% has discredited
    itself before anyone reads the number.

    This covers the SAMPLING half of the uncertainty only: how much the rate could
    move because these particular rows were drawn rather than others. It assumes
    each row is an independent draw, which the random sampler now makes true. It
    says nothing about the run-to-run half — see `_spread`.
    """
    if n <= 0:
        return None
    p, z2 = hits / n, z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = (z / (1 + z2 / n)) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return [round(100 * max(0.0, centre - half), 1), round(100 * min(1.0, centre + half), 1)]


def _spread(values: list[float]) -> dict | None:
    """What repeated scorings of the SAME rows actually did.

    The other half of the uncertainty, and the half no formula produces. Every
    upstream failure in this pipeline fails open — a timeout is indistinguishable
    from a county with no record — so a portal having a bad minute removes rows
    from the numerator and nothing says so. Scoring one benchmark twice moved the
    Cook rate five points, which is far more than an independent per-request
    failure rate could produce, so the misses arrive in bursts rather than one
    roll per row. Bursts do not shrink when the sample grows, which is exactly why
    this is measured by repetition instead of derived from n.
    """
    if not values:
        return None
    lo, hi = min(values), max(values)
    return {"runs": len(values), "min": round(lo, 1), "max": round(hi, 1),
            "spread": round(hi - lo, 1),
            "median": round(statistics.median(values), 1)}


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
    n = results.get("parcel_mismatches") or 0
    if not n:
        return ""
    return (f", of which {n} landed on a different parcel than the benchmark row "
            f"&mdash; those answers are wrong for the address asked about, and are "
            f"scored as the error they are rather than set aside")


#: Drop reasons this page can state, and the wording for each. The note is only
#: allowed to name reasons when THESE account for the whole gap, so a reason added
#: to the builder later forces the generic sentence rather than being silently
#: excluded from a total that still appears to balance.
#:
#: "were not in the parcel layer" is deliberately weaker than "had no address on
#: file": the layer held no record at all, so what the assessor documents about
#: those parcels was never observed by this build.
_DROP_REASONS = {
    "no_parcel_record": "{} were not in the parcel layer",
    "no_address": "{} had no address on file",
    "no_year_built": "{} had no usable year built",
}

#: The counters are shared; what they MEAN is not. Cook and DC's residential path
#: place a row by looking for its parcel polygon, so `no_parcel_record` really is
#: "not in the parcel layer". The condominium path never asks the parcel layer
#: anything — a unit's SSL is not in it — and places a row through the District's
#: unit index instead, where the same counter means "no active condominium unit
#: row". Printing the parcel wording there states a fact about the District's map
#: that this build has no evidence for, which is the failure this whole note
#: exists to avoid, arriving through the one field that looked jurisdiction-free.
_DROP_WORDING = {
    "dc-condo": {
        "no_parcel_record": "{} had no active unit record to place them",
        "no_address": "{} had a unit record carrying no address or unit number",
    },
}


def _drop_reasons(juris: str | None) -> dict[str, str]:
    """The wording for this jurisdiction, over exactly the shared set of reasons.

    Built from `_DROP_REASONS`' keys rather than merged into them, so an override
    cannot add a reason. The printed set and the summed set have to stay the same
    or the total can balance while the sentence names a subset — see the comment
    on `named` below, which is the same trap from the other direction.
    """
    over = _DROP_WORDING.get(juris or "", {})
    return {k: over.get(k, v) for k, v in _DROP_REASONS.items()}


def _ungradeable_note(m: dict) -> str:
    """Say how many drawn rows never reached the benchmark, and stay silent at zero.

    The builder drops a row the assessor gave no address or no usable year for, so
    the benchmark is already smaller than the draw. Reporting only the survivors
    would quietly redefine the population as "rows the assessor documented well".
    """
    # Against `sampled` — what reached the benchmark — NOT `rows`, which is what
    # this run managed to score. Rows lost to geocoding are already reported by
    # _unscored_note; counting them here too would double-report them AND blame
    # the assessor for a failure that happened in the scorer.
    drawn, sampled = m.get("drawn"), m.get("sampled")
    if not drawn or not sampled or drawn <= sampled:
        return ""
    # The builder records why each row was dropped. Where it did, say so; where it
    # did not — metadata written before the field existed — describe the gap
    # without claiming a cause, rather than asserting the likeliest one. Four
    # review rounds found this sentence naming a cause it could not know.
    d = m.get("dropped") or {}
    gap = drawn - sampled
    # Summed over exactly the reasons that will be PRINTED, not over the map. The
    # first version added up every integer in `dropped`, so a builder adding a
    # reason this code does not render — the map is written by a script that
    # changes independently of this one — could make the total match while the
    # sentence named a subset. That is under-reporting produced by the check
    # written to prevent under-reporting, and it stays impossible only if the
    # rendered set and the summed set are the same object.
    reasons = _drop_reasons(m.get("jurisdiction"))
    parts = [tmpl.format(n) for key, tmpl in reasons.items() if (n := d.get(key))]
    named = sum(n for key in reasons if isinstance(n := d.get(key), int))
    if parts and named == gap:
        return f" Drawn from {drawn} assessor rows; {', '.join(parts)}."
    return (f" Drawn from {drawn} assessor rows; {gap} could not be graded from "
            f"the assessor's own record.")


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


def as_jurisdictions(results: dict) -> dict:
    """The per-jurisdiction map, upgrading the original single-county shape.

    The first published run predates a second adapter and stored one county's
    numbers at the top level. Rather than require a hand-edit of a committed
    measurement, that shape is read as `{"cook": ...}` — the jurisdiction it in
    fact described.
    """
    if "jurisdictions" in results:
        return results["jurisdictions"]
    keys = ("benchmark", "baseline", "adapter")
    if all(k in results for k in keys):
        return {"cook": {k: v for k, v in results.items() if k != "generated"}}
    return {}


def _dc_foundation_caveat(juris: dict) -> str:
    """The basement note, only where a DC section is actually present.

    It was in the static caveat list, so a Cook-only page — the legacy shape, or a
    first run of a new jurisdiction — told readers what DC does not record without
    showing them any DC. `_dc_caveat` next to it was already conditional; this is
    the same fact stated in two places, one of them gated and one not.
    """
    if "dc" not in juris:
        return ""
    return ("<li><strong>DC records no basement type</strong>, so foundation is "
            "never observed there and its row stays at the baseline. That is a gap "
            "in the source, not a failure of the lookup.</li>")


def _dc_caveat(juris: dict) -> str:
    """DC's condominium exclusion — emitted only when DC is actually on the page.

    Rendering it unconditionally would tell a reader of a Cook-only page about a
    limitation of a measurement that page does not contain.
    """
    if "dc" not in juris:
        return ""
    return """<li><strong>Washington, DC excludes condominiums</strong>, which are
about 36% of its assessor's residential stock (61,329 condo records against 109,273
others). DC keeps them in a separate table keyed by unit, and a unit-level
identifier does not appear in the parcel geometry at all &mdash; so no coordinate
can pick one unit out of a building. The DC figures therefore describe non-condo
homes, and the adapter returns nothing for a condo rather than guessing.</li>"""


def _draw_sentence(m: dict) -> str:
    """How the rows were chosen, when the builder recorded it.

    Silent rather than "unrecorded" when it did not. A benchmark built before the
    sampler took a seed genuinely has nothing to say here, and printing the word
    twice in one sentence reads as a rendering fault rather than as a fact about
    the file.
    """
    method, seed = m.get("draw_method"), m.get("seed")
    if not method or seed is None:
        return ""
    return f"Drawn {html.escape(str(method))}, seed {html.escape(str(seed))} &middot; "


def _confidence_sentence(data: dict) -> str:
    """How far the headline rate could move, from both causes, or "" if unmeasured.

    Two intervals, never merged into one. They answer different questions and a
    reader who is told only their sum cannot tell which one to attack: a wide
    sampling interval is fixed by drawing more rows, a wide run-to-run range is
    fixed upstream and not by any amount of sampling.
    """
    parts = []
    ci = data.get("resolved_ci95")
    if ci:
        parts.append(f"95% confidence interval {ci[0]}&ndash;{ci[1]}% for the draw")
    runs = data.get("resolved_runs")
    # Whether the range was PRINTED, not whether the field exists. Keying the tail
    # on the field alone explained a "second range" that a one-run section never
    # showed — the sentence describing the evidence outliving the evidence, which
    # is the failure mode this page keeps producing in new places.
    showed_range = bool(runs and runs.get("runs", 0) > 1)
    if showed_range:
        parts.append(
            f"and {runs['min']}&ndash;{runs['max']}% observed across "
            f"{runs['runs']} scorings of these same rows")
    if not parts:
        return ""
    tail = (" The second range is not sampling error: it is the same addresses "
            "scored again. Every upstream failure here fails open, so a portal "
            "having a bad minute is indistinguishable from a county with no "
            "record, and it removes rows from the numerator silently."
            if showed_range else "")
    return f" {', '.join(parts)}.{tail}"


def _section(key: str, data: dict, *, depth: int = 0) -> str:
    """One jurisdiction's numbers.

    `depth` nests a jurisdiction under its parent — DC's condominiums are a
    narrower claim inside DC, not a second city — by shifting every heading down
    one level rather than by rendering a different template. One template means the
    two cannot drift apart, which matters more here than the markup does.
    """
    h_top, h_sub = f"h{2 + depth}", f"h{3 + depth}"
    m = data["benchmark"]
    rows_f, rows_g = [], []
    for f in FIELDS:
        b, a = data["baseline"]["fields"][f], data["adapter"]["fields"][f]
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
        b, a = data["baseline"]["grade_impact"][k], data["adapter"]["grade_impact"][k]
        bv = "—" if b["differs_pct"] is None else f"{b['differs_pct']}%"
        av = "—" if a["differs_pct"] is None else f"{a['differs_pct']}%"
        rows_g.append(f"<tr><td>{html.escape(k)}</td><td>{bv}</td><td>{av}</td>"
                      f"<td>{b['n']}</td></tr>")

    scope = m.get("scope")
    scope_html = (f" Scope: {html.escape(scope)}." if scope else "")
    return f"""
<{h_top} id="{html.escape(key)}">{html.escape(LABELS.get(key, key))}</{h_top}>

<p><strong>Method.</strong> {m.get('sampled', m['rows'])} addresses sampled across
{html.escape(m['source'])} (assessment year {html.escape(str(m['assessment_year']))},
fetched {html.escape(m['fetched'])}){_unscored_note(data)}.{scope_html}{_ungradeable_note(m)} Each is scored
from the address alone, with no construction details supplied, and compared against
that jurisdiction's own assessor record.</p>

<{h_sub}>Field accuracy</{h_sub}>
<div class="table-scroll"><table class="data-table"><thead><tr>
<th>Field</th><th>Coverage<br>baseline</th><th>Coverage<br>w/ assessor</th>
<th>Exact<br>baseline</th><th>Exact<br>w/ assessor</th>
<th>Median error<br>baseline</th><th>Median error<br>w/ assessor</th><th>Truth rows</th>
</tr></thead><tbody>
{chr(10).join(rows_f)}
</tbody></table></div>

<p><strong>Year built, by tolerance.</strong> The single field the rest of the
construction profile leans on hardest, so the near-misses are worth seeing rather
than collapsing into one median: {_tolerance_sentence(data)}</p>

<{h_sub}>Does the reader see a different grade?</{h_sub}>
<div class="table-scroll"><table class="data-table"><thead><tr>
<th>Dimension</th><th>Baseline</th><th>With assessor</th><th>n</th>
</tr></thead><tbody>
{chr(10).join(rows_g)}
</tbody></table></div>

<p style="opacity:0.75;font-size:0.85rem;">Assessor lookups resolved for
{data['adapter_resolved_pct']}% of the sample{_mismatch_note(data)}.{_confidence_sentence(data)}
{_draw_sentence(m)}Benchmark digest
{html.escape(m.get('sha256_16') or 'unrecorded')}.</p>
"""


def _render(results: dict) -> str:
    juris = as_jurisdictions(results)
    sections = "\n".join(
        _section(k, juris[k], depth=1 if JURISDICTIONS.get(k, {}).get("parent") else 0)
        for k in ordered() if k in juris)
    measured = ", ".join(LABELS.get(k, k) for k in sorted(juris))

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
often that inference matches what the assessing authority recorded for the same
building &mdash; the only check that asks whether the output describes the world
rather than whether the code does what it says.</p>

<p><strong>How to read it.</strong> <em>Baseline</em> is what the label infers
everywhere: a modelled structure record plus the census tract's year-built
distribution. <em>With assessor</em> adds an observed record from the assessing
authority where one resolves. The number that matters is the last table in each section — a year-built
error that moves no letter is not a defect anyone can see; one that crosses a
code-era boundary is.</p>

<p>Measured so far: {html.escape(measured)}. Each adapter is measured against its
own assessor, and the sections are not comparable to each other &mdash; different
housing stock, different record-keeping, different sample.</p>
{sections}
<h2>What this does and does not establish</h2>
<ul>
<li><strong>These are the jurisdictions with an adapter, not a national sample.</strong>
Each figure describes one place's housing stock and record-keeping.
Nothing here supports a claim about anywhere else, and the two sections should not
be averaged into one.</li>
{_dc_caveat(juris)}
<li>The assessor's own record is treated as truth. It can be stale or wrong; it is
the best available reference, not a survey.</li>
<li>Addresses where the assessor lookup does not resolve fall back to the
baseline, so the &ldquo;with assessor&rdquo; column includes them. It is the
end-to-end number a visitor would experience, not the adapter's accuracy on the
rows it answers.</li>
<li>The benchmarks are fetched on demand and not committed: neither source grants
an explicit right to redistribute a dataset. Re-running months later samples a
refreshed roll, so each section's digest and date are recorded to make that
visible.</li>
<li><strong>The categorical fields are a weaker test than the numeric ones.</strong>
Wall material, foundation and condition are translated out of the assessor's
vocabulary into the label's by the same table on both sides of the comparison, so
their &ldquo;exact&rdquo; rates in the assessor column largely measure whether the
right parcel was found &mdash; not whether the translation is right. One entry is
knowingly lossy in each source: Cook's single <em>Masonry</em> category and DC's
<em>Brick/Stone</em> are both read as brick, the label's brick/block/stone
distinction being finer than either. Year built and floor area carry no such
circularity; they are numbers, compared as numbers.</li>
<li><strong>Rows are not graded on every field.</strong> The
<em>Truth rows</em> column is each field's own denominator, and it is not always the
full sample. Floor area is the clearest case: an assessor records the whole
building's area while the label's figure is per dwelling unit, so on a multi-unit
parcel the two are different quantities and the row is excluded rather than scored
as a miss. A rate is over the rows in that column, not over every address
sampled.</li>
<li><strong>Condition is close to a constant.</strong> Most sampled parcels carry
one dominant grade in each source, so a high agreement rate on that row reflects the
distribution of the source far more than the label's skill, and should not be read
as one.</li>
{_dc_foundation_caveat(juris)}
<li><strong>The reference profile is not wholly observed.</strong> Where the
assessor records nothing for a field, the truth arm falls back to the same modelled
inputs the other two arms use, so a grade attributed to &ldquo;true
attributes&rdquo; is built from the assessor's facts <em>plus</em> those
fallbacks. It is the best
available reference, and on the rows with an incomplete record it understates the
distance between the arms rather than overstating it.</li>
</ul>

<p style="opacity:0.75;font-size:0.85rem;margin-top:2rem;border-top:1px solid #cbd5e1;
padding-top:0.9rem;">{html.escape(DISCLAIMER)}</p>

<p style="opacity:0.75;font-size:0.85rem;">Generated
{html.escape(results['generated'])}. Regenerate with
<code>python scripts/measure_accuracy.py --jurisdiction &lt;name&gt;</code>; each
run replaces only its own section.</p>
</main>
<script src="nav.js"></script>
</body></html>
"""


_LOCK_TIMEOUT_S = 60


@contextlib.contextmanager
def _results_lock():
    """Serialise the results read-modify-write across concurrent runs.

    An exclusive-create lockfile rather than `fcntl.flock`: this module is imported
    by the test suite and by `--check`, and the repository documents a Windows
    setup, where a Unix-only import would fail the whole file at collection time.
    `O_CREAT | O_EXCL` is atomic on every platform Python runs on and needs no
    platform branch.

    There is deliberately NO automatic takeover of an old lock. Two earlier
    attempts — unlink-if-old, then compare-the-contents-and-unlink — were both
    time-of-check/time-of-use races: between deciding a lock is abandoned and
    removing it, its holder can release and a third process acquire, and the
    removal then frees a live lock so two merges run at once. That is the exact
    lost update this exists to prevent, so shrinking the window is not good enough.

    Doing it correctly needs a lease with a heartbeat, or a platform lock
    primitive. Neither is worth carrying for a script run by hand a few times a
    week whose critical section is a file read, a dict splice and two renames —
    milliseconds. (The 45-minute measurement runs OUTSIDE this lock; only its
    result is written inside.) So a lock that outlives the wait is reported with
    the command to clear it, and a human decides. A stuck build that says exactly
    what to do beats a silent double-write.
    """
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pass
        else:
            # From here the lock EXISTS, and the try/finally that releases it is
            # not installed until this function yields. A write or close that
            # raised in between left the file behind, turning a transient
            # filesystem error into a permanent outage for every later
            # measurement — recoverable only by hand, which is exactly what the
            # no-automatic-takeover decision makes expensive.
            try:
                try:
                    os.write(fd, f"{os.getpid()}".encode())
                finally:
                    os.close(fd)
            except BaseException:
                LOCK.unlink(missing_ok=True)     # only ever this process's own
                raise
            break
        if time.monotonic() >= deadline:
            held = ""
            with contextlib.suppress(OSError):
                held = LOCK.read_text()
            raise SystemExit(
                f"another run holds {LOCK}"
                f"{f' (pid {held})' if held else ''}; waited {_LOCK_TIMEOUT_S}s.\n"
                f"If no measurement is running, that lock is left over from "
                f"a killed one. Delete that file and re-run:\n"
                f"    rm {LOCK}\n"
                f"    del {LOCK}      (Windows)")
        time.sleep(0.5)
    try:
        yield
    finally:
        # Safe as a plain unlink: nothing takes this lock away from its holder, so
        # the file here is always the one acquired above.
        LOCK.unlink(missing_ok=True)


def _readable_results(previous, where: str, *, existed: bool) -> dict:
    """The jurisdiction sections of a results file, or the end of the run.

    `as_jurisdictions` answers {} for a shape it does not recognise, and BOTH
    writers then do something destructive with that answer: the merge writes this
    run's section alone over whatever the file held, and --render-only publishes an
    empty accuracy page over the real one. An unreadable file is exactly when it is
    least safe to assume there is nothing worth keeping.

    One function because the two paths kept diverging: the merge grew this guard a
    commit before --render-only did, which is the same one-branch-and-not-its-
    neighbour mistake that produced half the findings on this change.

    `existed` rather than truthiness. A file holding `{}`, `[]`, `0` or `false` is
    a file that exists and says something this code cannot read — testing
    `if previous` let every one of those through as a fresh store, which is the
    same "absent" and "unreadable" conflation, one level up. A non-dict is refused
    before it reaches `as_jurisdictions`, which used to raise TypeError on it: an
    unhandled crash where a stated refusal belongs.
    """
    if existed and isinstance(previous, dict) and "jurisdictions" in previous \
            and not isinstance(previous["jurisdictions"], dict):
        # The root type was checked and the map inside it was not, so
        # {"jurisdictions": null} reached dict(None) and raised TypeError — the
        # unhandled crash this function exists to replace with a stated refusal,
        # one level in from where I put the guard.
        raise SystemExit(
            f"{RESULTS.name} has a 'jurisdictions' key holding "
            f"{type(previous['jurisdictions']).__name__}, not an object, so "
            f"{where} cannot read it — and writing would destroy it. Inspect it "
            f"(or move it aside) and re-run.")
    if existed and not isinstance(previous, dict):
        raise SystemExit(
            f"{RESULTS.name} holds {type(previous).__name__}, not an object, so "
            f"{where} cannot read it — and writing would destroy it. Inspect it "
            f"(or move it aside) and re-run.")
    juris_map = dict(as_jurisdictions(previous or {}))
    if existed and not juris_map:
        raise SystemExit(
            f"{RESULTS.name} exists but no jurisdiction sections could be read "
            f"from it, so {where} would destroy whatever it holds. Inspect it "
            f"(or move it aside) and re-run.")
    # The registry decides what may be published. A typo, or a section left by a
    # newer copy of these scripts, was carried through the merge and rendered under
    # its bare key — and --check would then certify a page claiming a jurisdiction
    # no adapter is registered for. This page states measured accuracy per
    # jurisdiction; a heading nothing can produce is a claim nothing backs.
    unknown = sorted(set(juris_map) - set(LABELS))
    if unknown:
        raise SystemExit(
            f"{RESULTS.name} holds {', '.join(repr(u) for u in unknown)}, which "
            f"scripts/jurisdictions.py does not register. {where} would carry a "
            f"measurement forward under a name nothing can produce. Add the "
            f"jurisdiction, or move the file aside.")
    # And each section must agree with the key it sits under. Checking only that
    # the KEY is registered leaves the fabrication one move away: put the DC
    # section under "cook" and the page prints DC's numbers beneath Cook's
    # heading, with Cook's source line, and --check certifies it. The stamp that
    # would have caught it was already in the file — the same oversight as the
    # benchmark's stamp going unread for the whole first half of this change.
    #
    # Unstamped is allowed for `cook` alone: the pre-split measurement predates
    # the field and is genuinely Cook's. Anywhere else it is a section whose
    # provenance nothing records.
    for key, data in juris_map.items():
        if not isinstance(data, dict):
            # `{"cook": []}` is falsy, so `data or {}` read it as an empty section
            # and accepted it; a truthy non-mapping reached .get() and raised
            # AttributeError. Both are the unreadable file this guard exists to
            # refuse, arriving one level further in.
            raise SystemExit(
                f"{RESULTS.name} has a section keyed {key!r} holding "
                f"{type(data).__name__}, not an object. {where} cannot read it. "
                f"Inspect it (or move it aside) and re-run.")
        bench = data.get("benchmark")
        if bench is not None and not isinstance(bench, dict):
            # Typed the section and not the thing inside it — a `benchmark` of
            # "corrupt" raised AttributeError from the very .get() meant to read
            # its provenance. One level deeper than the guard I wrote last round.
            raise SystemExit(
                f"{RESULTS.name}'s {key!r} section has a benchmark holding "
                f"{type(bench).__name__}, not an object. {where} cannot read its "
                f"provenance. Inspect it (or move it aside) and re-run.")
        if not bench:
            # `_section` reads data["benchmark"] for the source, the assessment
            # year and the sample size it prints. A section without one has no
            # provenance to publish, and saying that is clearer than reporting its
            # source as None.
            raise SystemExit(
                f"{RESULTS.name}'s {key!r} section has no benchmark block, so it "
                f"records no provenance at all. {where} would publish a "
                f"measurement nothing accounts for. Inspect it (or move it "
                f"aside) and re-run.")
        # The pre-rename key is refused rather than ignored. Dropping its reader
        # without this would have been the quiet kind of removal: a section
        # carrying only `pin_mismatches` would render with no mismatch sentence at
        # all, silently losing a disclosure that says some answers were wrong for
        # the address asked about. Refusing names the problem; ignoring it
        # publishes a cleaner-looking page than the data supports.
        if "pin_mismatches" in data and "parcel_mismatches" not in data:
            raise SystemExit(
                f"{RESULTS.name}'s {key!r} section records mismatches under "
                f"'pin_mismatches', which is no longer read. Rendering it would "
                f"drop the sentence saying how many answers landed on a different "
                f"parcel. Re-measure that jurisdiction with "
                f"scripts/measure_accuracy.py --jurisdiction {key}.")
        # Both provenance fields the page prints verbatim. `scope` is the sentence
        # limiting DC's numbers to non-condominium homes; edited to claim all
        # homes it publishes a figure drawn from 64% of the city as the city.
        # Equality, not merely non-conflict: `""` passed the old condition and
        # rendered with no attribution at all, on a page whose whole claim is that
        # each number came from a named record of a stated population.
        for field in ("source", "scope"):
            recorded, want = bench.get(field), JURISDICTIONS.get(key, {}).get(field)
            # The pre-split Cook measurement predates `scope`; nothing else may
            # omit either field.
            if not want or (key == "cook" and field == "scope" and not recorded):
                continue
            if recorded != want:
                raise SystemExit(
                    f"{RESULTS.name}'s {key!r} section records {field} "
                    f"{recorded!r}, but scripts/jurisdictions.py says {key!r} is "
                    f"{want!r}. {where} would publish a measurement described "
                    f"wrongly.")
        # The keys _section indexes directly. Without this a truncated section —
        # a benchmark block and nothing else — passed every guard here and then
        # raised KeyError from the renderer: --check and --render-only crashing
        # where this function promises a stated refusal.
        needed = [k for k in ("baseline", "adapter", "adapter_resolved_pct")
                  if k not in data]
        needed += [f"benchmark.{k}" for k in ("rows", "assessment_year", "fetched")
                   if k not in bench]
        if needed:
            raise SystemExit(
                f"{RESULTS.name}'s {key!r} section is missing "
                f"{', '.join(sorted(set(needed)))}, which the page reads directly. "
                f"{where} would fail while rendering. Inspect it (or move it "
                f"aside) and re-run.")
        stamped = bench.get("jurisdiction")
        if stamped == key or (stamped is None and key == "cook"):
            continue
        was = f"{stamped!r}" if stamped else "no jurisdiction"
        raise SystemExit(
            f"{RESULTS.name} has a section keyed {key!r} whose benchmark records "
            f"{was}. {where} would publish one jurisdiction's measurement under "
            f"another's heading. Inspect it (or move it aside) and re-run.")
    return juris_map


def _verify_benchmark(path: pathlib.Path, meta: dict, juris: str,
                      legacy: bool = False) -> bytes:
    """The benchmark's bytes, once they are proven to be the ones it claims to be.

    Returns the snapshot it validated, and the caller parses THAT rather than
    reopening the file. Hashing one read and parsing another leaves a window in
    which a concurrent build can rename a new CSV into place: this run would then
    score the new sample while reporting the old metadata's row count and digest —
    the very mispairing the check exists to prevent, produced by the check itself.

    Three things have to hold, and none makes the others redundant:

    * **Jurisdiction.** The metadata records which assessor the draw came from, and
      until now nobody read it. Copying `benchmark-cook.*` to `benchmark-dc.*`
      passes the digest — the file really is the one its metadata describes — and
      publishes Cook addresses under `jurisdictions["dc"]`. The evidence was
      already in the file; this reads it. It must MATCH, not merely not-conflict:
      `legacy` marks the one pre-split file that predates the field, and every
      other benchmark has to name its jurisdiction outright.
    * **Digest.** Catches an interrupted build: a partial CSV beside the previous
      run's metadata. Required outside the legacy path, because without it and
      without `rows` nothing checks the file's CONTENT at all — a correctly
      labelled benchmark could hold any bytes and still be published.
    * **Row count.** Checked independently of the digest, not as a follow-on. A
      pre-split cache records `rows` but no digest, and skipping the count there
      would leave that file unvalidated altogether.

    A measurement published under the wrong provenance is indistinguishable from a
    real one downstream, so each of these fails the run rather than warning.
    """
    payload = path.read_bytes()
    stamped = meta.get("jurisdiction")
    if stamped != juris and not (legacy and not stamped):
        # A MISSING stamp is refused as firmly as a wrong one, everywhere except
        # the one file that legitimately predates the field. Accepting "unstamped"
        # would leave the hole open in its easiest form: a legacy Cook benchmark
        # copied to benchmark-dc.* carries no stamp at all, matches its own digest,
        # and publishes Cook as DC. Checking only for a wrong stamp catches the
        # careful mistake and misses the careless one.
        was = f"metadata for {stamped!r}" if stamped else "no jurisdiction recorded"
        raise SystemExit(
            f"{path.name} carries {was}, not {juris!r}. Scoring it would publish "
            f"one jurisdiction's addresses under another's name. Rebuild with "
            f"scripts/build_benchmark.py --jurisdiction {juris}.")
    # The stamp is metadata and the digest covers only the CSV bytes, so copying
    # Cook's pair and editing one word makes a valid-looking DC benchmark. The
    # source line the page prints is checked against the registry, which a forger
    # would then also have to edit — and doing that publishes Cook's source under
    # DC's heading, which the results guard refuses.
    # `scope` is checked beside `source`, and it is the more dangerous of the two.
    # The page prints it verbatim as the sentence limiting DC's numbers to
    # non-condominium homes — 64% of the city's stock. Editing it to claim all
    # homes leaves the CSV, its digest and every other field untouched, so a
    # figure drawn from two thirds of DC publishes as DC. That is the fabrication
    # this whole change is about, reached through the one field nothing read.
    for field in ("source", "scope"):
        recorded = meta.get(field)
        expected = JURISDICTIONS.get(juris, {}).get(field)
        # Absent is allowed only on the pre-split file, which predates `scope`
        # entirely; present-and-different never is.
        if expected and recorded != expected and not (legacy and not recorded):
            raise SystemExit(
                f"{path.stem}.meta.json records {field} {recorded!r}, but "
                f"scripts/jurisdictions.py says {juris!r} is {expected!r}. "
                f"Rebuild with scripts/build_benchmark.py --jurisdiction {juris}.")
    want = meta.get("sha256_16")
    if not want and not legacy:
        # Same exemption as the stamp above, and I granted it to one and not the
        # other in the same edit. Without a digest AND without `rows`, nothing
        # about the file's CONTENT is checked at all — a benchmark correctly
        # labelled `dc` can hold any bytes whatsoever and still be scored and
        # published as DC. Only the pre-split file may lack this.
        raise SystemExit(
            f"{path.stem}.meta.json records no sha256_16, so nothing would verify "
            f"that {path.name} is the sample it describes. Rebuild with "
            f"scripts/build_benchmark.py --jurisdiction {juris}.")
    if want:
        got = hashlib.sha256(payload).hexdigest()[:16]
        if got != want:
            raise SystemExit(
                f"{path.name} does not match {path.stem}.meta.json: the metadata "
                f"describes digest {want}, the file on disk is {got}. That pairing "
                f"means an interrupted or edited build, and scoring it would "
                f"publish one sample under another's provenance. Rebuild it with "
                f"scripts/build_benchmark.py.")
    # The digest proves the file is the one its metadata describes; it says nothing
    # about whether that file can be scored. A CSV holding only `parcel_id,address`
    # passes every check above, and `_score_arms` then runs with NO truth fields —
    # publishing zero observed rows for every field while the grade-impact rate is
    # computed against a synthetic default label instead of the assessor's record.
    # A measurement of nothing, rendered as a measurement.
    header = next(csv.reader(io.StringIO(payload.decode())), [])
    # The pre-split builder wrote `pin`, and `_parcel_matches` still reads it —
    # this path exists to keep that file scorable. Requiring `parcel_id`
    # unconditionally refused the one benchmark the legacy branch is FOR, so the
    # compatibility the code documents lasted exactly as long as it took me to add
    # a schema check without looking at the file it had to accept.
    identifier = ("parcel_id", "pin") if legacy else ("parcel_id",)
    absent = [f for f in FIELDS if f not in header]
    if "address" not in header:
        absent.insert(0, "address")
    if not any(i in header for i in identifier):
        absent.insert(0, " or ".join(identifier))
    if absent:
        raise SystemExit(
            f"{path.name} has no {', '.join(absent)} column(s), so there is "
            f"nothing to grade against. Rebuild with scripts/build_benchmark.py "
            f"--jurisdiction {juris}.")
    # Headers prove the columns exist; they say nothing about what is in them. A
    # blank `year_built` yields a case with no assessor truth at all, and a
    # non-numeric one reaches int(_num(...)) in _score_arms and aborts a run
    # mid-flight. Both are the same defect as the missing column, one layer in:
    # a digest-valid CSV that cannot produce the measurement it is scored for.
    gradeable = 0
    for i, row in enumerate(csv.DictReader(io.StringIO(payload.decode())), 1):
        year = (row.get("year_built") or "").strip()
        if not year:
            continue
        try:
            value = int(float(year))
        except ValueError:
            raise SystemExit(
                f"{path.name} row {i} has year_built {year!r}, which is not a "
                f"number. Scoring would abort part-way through. Rebuild it.")
        if not 1600 <= value <= 2100:
            raise SystemExit(
                f"{path.name} row {i} has year_built {value}, outside any "
                f"plausible range. Rebuild it.")
        gradeable += 1
    if not gradeable:
        raise SystemExit(
            f"{path.name} has a year_built column but no row carries a usable "
            f"value, so every grade would be computed against a default rather "
            f"than the assessor's record. Rebuild it.")

    # `sampled` is checked beside `rows` because main() publishes it as the
    # population and uses it as the denominator of the drop disclosure. Verifying
    # only `rows` left the number the page actually states unverified.
    have = None
    for field in ("rows", "sampled"):
        claimed = meta.get(field)
        if claimed is None:
            continue
        if have is None:
            have = sum(1 for _ in csv.DictReader(io.StringIO(payload.decode())))
        if have != claimed:
            raise SystemExit(
                f"{path.name} holds {have} rows; its metadata claims {claimed} "
                f"for {field!r}. Rebuild it with scripts/build_benchmark.py.")
    return payload


def _publish(results: dict) -> None:
    """Replace the results file and the page, or replace neither — in this process.

    Worth stating the limit rather than implying more. Two renames cannot be one
    atomic step, so a KILL between them (SIGKILL, power loss) still leaves new
    results beside the old page. That state is not silent: `--check` compares
    exactly those two files, fails, and names `--render-only` as the repair, which
    rebuilds the page from the results now on disk. A generation or manifest scheme
    would close the window properly, and does not earn its keep for a script run by
    hand whose exposure is the microseconds between two renames and whose failure
    is loudly detected by the gate that already runs on every commit.

    The page used to be written second, straight from `_render(results)` in the
    argument list. Anything that made rendering raise — a section carried over
    from the file just read that this code cannot render — therefore left
    results.json already replaced and the page still describing the previous run.
    The two would disagree, and the CI gate compares exactly those two.

    Rendering first turns that into a failure that changes nothing. It is a
    function rather than two ordered lines because the ordering IS the guarantee,
    and a guarantee that lives in the order of two statements is one edit from
    being lost silently.
    """
    page = _render(results)                     # may raise; nothing written yet
    payload = json.dumps(results, indent=2) + "\n"

    # Two files cannot be renamed in one atomic step, so the aim is to make the
    # window as small as the filesystem allows and to leave nothing behind if it
    # is missed. Both temps are written FIRST — a full disk or a permissions
    # problem fails there, before anything published has changed — and only then
    # are the renames issued back to back. If the second still fails, the first is
    # rolled back from the copy taken beforehand, so the pair stays consistent
    # rather than leaving new results beside the old page.
    before = RESULTS.read_bytes() if RESULTS.exists() else None
    staged: list[pathlib.Path] = []
    try:
        # Both staged before either rename, and inside the cleanup — staging the
        # page can itself fail (a missing directory, a full disk), and the first
        # temp was orphaned when it did. Found by the test written for the rename
        # failure, which is the point of testing the failure rather than the path.
        results_tmp = _staged(RESULTS, payload.encode())
        staged.append(results_tmp)
        page_tmp = _staged(PAGE, page.encode())
        staged.append(page_tmp)

        results_tmp.replace(RESULTS)
        staged.remove(results_tmp)
        try:
            page_tmp.replace(PAGE)
            staged.remove(page_tmp)
        except BaseException:
            if before is None:
                RESULTS.unlink(missing_ok=True)
            else:
                back = _staged(RESULTS, before)
                try:
                    back.replace(RESULTS)
                finally:
                    back.unlink(missing_ok=True)
            raise
    finally:
        for tmp in staged:
            tmp.unlink(missing_ok=True)


def _staged(path: pathlib.Path, data: bytes) -> pathlib.Path:
    """Write `data` to a fresh temp file beside `path`, ready to be renamed onto it.

    Unique, not merely temporary: a fixed `<name>.tmp` is one path shared by every
    concurrent writer, so two interleave into it or one renames it away while the
    other is filling it. Same directory, because a rename is only atomic within a
    filesystem.
    """
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    tmp = pathlib.Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def _write_atomic(path: pathlib.Path, text: str) -> None:
    """Write via a temporary file and rename, so no reader sees a partial file.

    The rename is wrapped because `_staged` has already created a live file by the
    time it returns: a failing `replace` — a permissions change, an open target on
    Windows — otherwise propagates and leaves `<name>.<random>.tmp` behind. The
    cleanup existed in `_publish` and not in the helper beside it, which is the
    same one-branch-and-not-its-neighbour pattern as most findings on this change.
    """
    tmp = _staged(path, text.encode())
    try:
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="verify the published page matches the committed results")
    ap.add_argument("--limit", type=int, default=None,
                    help="score only the first N rows (requires --dry-run)")
    ap.add_argument("--dry-run", action="store_true",
                    help="score and report without writing results or the page")
    ap.add_argument("--render-only", action="store_true",
                    help="rebuild the page from the committed results, no scoring")
    # Default None, not "cook", so the guard below can tell "not supplied" from
    # "supplied as the default". Without that distinction --jurisdiction joins the
    # accepted-and-ignored list: --check --jurisdiction dc reads exactly the same
    # committed results as --check, and reports success as though it had checked
    # something narrower.
    ap.add_argument("--replicates", type=int, default=1, metavar="N",
                    help="score the benchmark N times and publish the observed "
                         "range as well as the point estimate (default 1)")
    ap.add_argument("--jurisdiction", choices=sorted(LABELS), default=None,
                    help="which benchmark to score (default cook)")
    args = ap.parse_args()

    # Stated as one rule rather than a condition per pair, because fixing the pairs
    # one at a time is how --check --limit survived the round that fixed
    # --render-only --limit. Two modes score nothing, and each is dispatched before
    # the scoring flags are even validated; two flags only modify scoring. Any
    # combination across that line is a flag accepted and ignored, which is worse
    # than one rejected — the caller believes it took effect. Two no-score modes
    # together contradict each other outright: --check VERIFIES the page against
    # the results, --render-only OVERWRITES it, so the gate would pass by
    # rewriting what it was asked to inspect.
    no_score = [n for n, on in (("--check", args.check),
                                ("--render-only", args.render_only)) if on]
    if args.replicates < 1:
        # The same rule --rows already carries in the builder, applied to its
        # neighbour here, and applied before anything is read or scored. Zero
        # replicates scored nothing and then indexed the empty list for a median
        # run: an IndexError traceback where this script otherwise states its
        # refusals. A guard on one argument and not the one beside it is how most
        # of the findings on this branch got in.
        raise SystemExit(f"--replicates must be at least 1 (got {args.replicates})")
    scoring = [n for n, on in (("--dry-run", args.dry_run),
                               ("--limit", args.limit is not None),
                               # A scoring flag like the rest: --check --replicates 3
                               # would otherwise be accepted and silently ignored,
                               # which is the failure the whole block exists for and
                               # which the new flag walked straight past.
                               ("--replicates", args.replicates != 1),
                               ("--jurisdiction", args.jurisdiction is not None)) if on]
    if len(no_score) > 1:
        raise SystemExit(
            "--check verifies the published page against the committed results and "
            "--render-only overwrites that page, so together the check would pass "
            "by rewriting what it was asked to inspect. Use one.")
    if no_score and scoring:
        raise SystemExit(
            f"{no_score[0]} scores nothing, so {' and '.join(scoring)} would be "
            f"accepted and ignored. Drop {no_score[0]} to score, or drop "
            f"{' and '.join(scoring)}.")

    if args.render_only:
        # For a copy or layout edit: the measurements are the expensive part and
        # they have not changed, so re-scoring 200 addresses to restyle a table
        # would be both slow and a small lie about when they were taken.
        if not RESULTS.exists():
            raise SystemExit(f"{RESULTS} missing — nothing to render")
        # Under the same lock and the same atomic write as a real run. Reading the
        # results and writing the page is the identical critical section; unlocked,
        # a render started before a measurement finishes would publish a page built
        # from the old results over the one that run just wrote, leaving the two
        # files disagreeing — and the CI gate compares exactly those two.
        with _results_lock():
            previous = json.loads(RESULTS.read_text())
            _readable_results(previous, "the rendered page", existed=True)
            _write_atomic(PAGE, _render(previous))
        log.info("Rendered %s from the committed measurements.", PAGE)
        return 0

    if args.check:
        if not RESULTS.exists():
            log.error("%s is missing — run the harness and commit its output.", RESULTS)
            return 1
        # Under the same lock as the writers. The two files are renamed into place
        # one after the other, so an unlocked read can catch the instant between
        # them and pair new results with the old page — a spurious failure of the
        # CI gate, reported as the page being out of date when it is merely being
        # replaced. Reading them together is the same critical section as writing
        # them together.
        with _results_lock():
            results = json.loads(RESULTS.read_text())
            # The same guard the merge and the render apply. Without it
            # {"jurisdictions": {}} paired with the matching empty page PASSES the
            # gate, while both writers correctly refuse that state as destructive —
            # so the one job of the gate, agreeing with the writers about what is
            # publishable, was the job it did not do.
            _readable_results(results, "this check", existed=True)
            page = PAGE.read_text() if PAGE.exists() else None
        if page is None or page != _render(results):
            log.error("%s is out of date. Regenerate: python scripts/measure_accuracy.py "
                      "--render-only", PAGE)
            return 1
        log.info("accuracy page is in sync with the committed measurements.")
        return 0

    juris = args.jurisdiction or "cook"
    benchmark = CACHE_DIR / f"benchmark-{juris}.csv"
    meta_file = CACHE_DIR / f"benchmark-{juris}.meta.json"
    legacy = False
    if not benchmark.exists() and juris == "cook":
        # The pre-split path held Cook's benchmark and nothing else, so it is a
        # valid fallback for Cook alone. Applying it to any other jurisdiction
        # would score Cook addresses and publish them under that jurisdiction's
        # name — a fabricated measurement that would look entirely ordinary.
        benchmark, meta_file = BENCHMARK, META
        legacy = True
    if not benchmark.exists():
        raise SystemExit(f"{benchmark} missing — run scripts/build_benchmark.py "
                         f"--jurisdiction {juris} first")
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

    if not meta_file.exists():
        # A benchmark with no metadata has no provenance, and a measurement whose
        # provenance is unknown is the one thing this page must not publish. It is
        # also reachable: a build interrupted between the CSV rename and the
        # metadata rename leaves exactly this. The named path is already refused by
        # the jurisdiction stamp; this covers the legacy one, which is exempt from
        # that check and would otherwise be scored and then crash the renderer
        # AFTER results.json had been replaced.
        raise SystemExit(
            f"{meta_file.name} is missing, so {benchmark.name} has no recorded "
            f"provenance — an interrupted build leaves exactly this. Rebuild with "
            f"scripts/build_benchmark.py --jurisdiction {juris}.")
    meta = json.loads(meta_file.read_text())
    payload = _verify_benchmark(benchmark, meta, juris, legacy=legacy)
    # Checked before scoring, not discovered during render: the page is written
    # AFTER results.json, so a field missing here would abort a 45-minute run with
    # the published state already half-replaced.
    for field in ("source", "assessment_year", "fetched", "rows"):
        if not meta.get(field):
            raise SystemExit(
                f"{meta_file.name} has no {field!r}, which the published page "
                f"states for every measurement. Rebuild the benchmark.")
    rows = list(csv.DictReader(io.StringIO(payload.decode())))
    if args.limit is not None:
        # `if args.limit` would read 0 as "no limit" and quietly score the whole
        # benchmark — the opposite of what was asked, and expensive to discover.
        if args.limit < 1:
            raise SystemExit(f"--limit must be at least 1 (got {args.limit})")
        # --limit is a smoke test, and a smoke test must not become the published
        # measurement. Without this, scoring one row republishes the section with
        # one case while the benchmark metadata still says the full sample size —
        # a partial run wearing a complete run's numbers. (Done accidentally
        # during development; the committed results had to be restored from git.)
        if not args.dry_run:
            raise SystemExit(
                "--limit produces a partial measurement, which must not replace a "
                "published one. Add --dry-run to score a few rows and print the "
                "result without writing.")
        rows = rows[:args.limit]

    def score_once(label: str) -> list[dict]:
        out = []
        for i, row in enumerate(rows, 1):
            case = _score_arms(row, juris)
            if case is not None:
                out.append(case)
            if i % 10 == 0 or i == len(rows):
                log.info("%sscored %d/%d (%d usable)", label, i, len(rows), len(out))
        if not out:
            raise SystemExit(
                "no address scored — refusing to publish an empty measurement")
        return out

    # Replicates score the SAME rows again, which is the point: holding the draw
    # fixed separates run-to-run noise from sampling noise. A fresh draw each time
    # would confound the two and neither could be reported on its own.
    replicates = []
    for r in range(args.replicates):
        tag = f"[run {r + 1}/{args.replicates}] " if args.replicates > 1 else ""
        got = score_once(tag)
        pct = round(100 * sum(1 for c in got if c["resolved"]) / len(rows), 1)
        log.info("%sassessor answered for %.1f%%", tag, pct)
        replicates.append((pct, got))

    # The detailed tables come from ONE run — the median by resolution rate — and
    # the page says so. Averaging field-level rates across repeated scorings of the
    # same rows would present a number no single run produced, and pooling them
    # would count each row once per replicate and shrink every interval by a factor
    # the sample never earned.
    replicates.sort(key=lambda t: t[0])
    resolved_pcts = [pct for pct, _ in replicates]
    cases = replicates[len(replicates) // 2][1]

    resolved = sum(1 for c in cases if c["resolved"])
    mismatched = sum(1 for c in cases if c.get("parcel_mismatch"))
    measured = {
        # Three counts, and they mean different things:
        #   drawn    what the builder asked the assessor for
        #   sampled  what reached the benchmark (drawn, minus rows with no address
        #            or no usable year — the builder drops those before writing)
        #   rows     what this run could actually score
        # `sampled` takes the benchmark's own count where the meta records one,
        # NOT the length of the CSV as read: with --limit, or after the builder
        # dropped rows, the CSV is already the smaller number and reporting it as
        # the sample would quietly redefine the population as whatever survived.
        "benchmark": {**meta,
                      "sampled": meta.get("sampled", meta.get("rows", len(rows))),
                      "rows": len(cases)},
        "unscored": len(rows) - len(cases),
        # Over the sampled population, not the scored subset. Dividing by
        # `cases` would drop every address that failed to geocode out of the
        # denominator, so the failures this metric should expose could only ever
        # raise it. It is published as end-to-end coverage, so it is measured
        # that way.
        "adapter_resolved_pct": round(100 * resolved / len(rows), 1),
        # The sampling half: how far the rate could move because these rows were
        # drawn rather than others. Valid only because the draw is random — see
        # `_draw_offsets` in the builder.
        "resolved_ci95": _wilson(resolved, len(rows)),
        # The run-to-run half, present only when it was actually measured. A
        # single run cannot report a spread, and inventing one from the interval
        # above would dress the sampling half up as the whole.
        "resolved_runs": _spread(resolved_pcts) if len(resolved_pcts) > 1 else None,
        # Named for the parcel, not for Cook's PIN: DC's identifier is an SSL and
        # a Cook-specific key in a cross-jurisdiction schema misleads whoever reads
        # it next. The `pin_mismatches` fallback that let a pre-rename measurement
        # keep rendering is gone: every committed section now carries this key, so
        # the fallback could only have served a file that no longer exists — and a
        # reader that silently accepts two names for one field is how a section
        # gets published under a schema nothing checks.
        "parcel_mismatches": mismatched,
        "baseline": _summarise(cases, "baseline"),
        "adapter": _summarise(cases, "adapter"),
    }

    # Merge, never replace. Each jurisdiction is a separate expensive run, and
    # writing the file wholesale would silently delete the other's numbers while
    # the page still claimed to report both.
    #
    # The read-modify-write is held under a lock, and the write is a rename onto
    # the target. The lock covers only this splice, not the scoring above: two runs
    # finishing together would otherwise both read the same prior file and the
    # second would drop the first's brand-new section — the RESULT of a 45-minute
    # measurement lost silently, with a page that still looks complete. An
    # interrupted write would be worse: a truncated results file is the one input
    # the CI gate trusts.
    if args.dry_run:
        log.info("Dry run — results and page NOT written.")
        _log_summary(measured, juris)
        return 0

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with _results_lock():
        existed = RESULTS.exists()
        previous = json.loads(RESULTS.read_text()) if existed else {}
        juris_map = _readable_results(previous, "this merge", existed=existed)
        juris_map[juris] = measured
        results = {"generated": date.today().isoformat(), "jurisdictions": juris_map}
        _publish(results)

    _log_summary(measured, juris)
    log.info("Wrote %s and %s.", RESULTS, PAGE)
    return 0


def _log_summary(measured: dict, juris: str) -> None:
    log.info("[%s] scored %d addresses; assessor answered for %.1f%%; "
             "%d landed on a different parcel (scored as error).",
             juris, measured["benchmark"]["rows"],
             measured["adapter_resolved_pct"], measured["parcel_mismatches"])
    for f in FIELDS:
        b = measured["baseline"]["fields"][f]
        a = measured["adapter"]["fields"][f]
        log.info("  %-13s exact %5s%% → %5s%%   median err %6s → %6s",
                 f, b.get("exact_pct"), a.get("exact_pct"),
                 b.get("median_abs_error"), a.get("median_abs_error"))
    log.info("  grade differs from truth:")
    for k in list(GRADED) + ["building_axis"]:
        log.info("    %-14s %5s%% → %5s%%", k,
                 measured["baseline"]["grade_impact"][k]["differs_pct"],
                 measured["adapter"]["grade_impact"][k]["differs_pct"])


if __name__ == "__main__":
    sys.exit(main())
