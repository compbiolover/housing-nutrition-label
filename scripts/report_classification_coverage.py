#!/usr/bin/env python3
"""Report property-tax classification coverage, by Census division.

Prints which of the 51 scorable jurisdictions have a researched classification rule, what
correction each applies, and how much of the US population sits behind a researched rule.
A status tool, not a build script: it writes nothing and downloads nothing, reading only
``data/assessment.py`` and the bundled county crosswalk for population weights.

Use it to see where the regional rollout stands
(``research/property-tax-classification-rollout.md``) and to spot rules whose primary
source has not been re-read in a long time.

Run:  python scripts/report_classification_coverage.py
"""

from __future__ import annotations

import csv
import datetime
import pathlib
from collections import defaultdict

from housing_label.data.assessment import (
    BASIS_DWELLING_UNITS, CLASSIFICATION_RULES, LAW_AS_OF, RULE_UNIFORM,
)
from housing_label.data.states import (
    CENSUS_DIVISION, SCORED_JURISDICTIONS, usps_for_fips,
)

_DATA = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"

# The order the rollout plan works through the divisions.
DIVISION_ORDER = [
    "East South Central", "South Atlantic", "West South Central", "Middle Atlantic",
    "East North Central", "New England", "West North Central", "Mountain", "Pacific",
]


def population_by_state() -> dict[str, float]:
    """USPS → population, summed from the bundled gov-finance county crosswalk."""
    pop: dict[str, float] = defaultdict(float)
    path = _DATA / "govfinance_county.csv"
    if not path.exists():
        return pop
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            geoid = str(row.get("geoid", "")).strip().zfill(5)
            if geoid == "00000":
                continue
            usps = usps_for_fips(geoid)
            try:
                n = float(row.get("pop") or 0)
            except ValueError:
                continue
            if usps and n > 0:
                pop[usps] += n
    return pop


def _threshold_phrase(rule) -> str:
    """e.g. "at 2+ rental units".

    Always printed alongside a multiplier, because the threshold is half the rule: a bare
    "x1.81" reads as a blanket surcharge on all housing in the jurisdiction, when New York
    City's applies only from 11 dwelling units up and Tennessee's from 2 rental units up.
    The basis matters too — dwelling units are a physical test, rental units a tenure one.
    """
    n = rule.rental_unit_threshold or 1
    noun = "dwelling unit" if rule.threshold_basis == BASIS_DWELLING_UNITS else "rental unit"
    return f"at {n}+ {noun}{'' if n == 1 else 's'}"


def describe_effect(rule) -> str:
    """One line saying what this rule actually does, thresholds included."""
    if rule.rule_type == RULE_UNIFORM:
        return "no correction — researched, no classification of rental housing"
    if rule.local_option and not rule.sub_state:
        # A real classification that reaches rental housing but is set per municipality in
        # a state whose counties are not governmental units (RI, CT). Falling through to
        # the multiplier below would print "x1.00", which reads as "researched, no effect"
        # — the opposite of the truth, and the reason this branch exists.
        return "no correction — classification is municipal, not resolvable by county"
    if rule.sub_state:
        # A local-option container corrects only through its sub-rules; its own multiplier
        # is 1.0, and printing that would read as "researched, no effect" — the opposite of
        # the truth for a New York City parcel.
        subs = list(rule.sub_state.values())
        mults = sorted({s.multiplier() for s in subs})
        span = (f"x{mults[0]:.2f}" if len(mults) == 1
                else f"x{mults[0]:.2f}-{mults[-1]:.2f}")
        phrases = {_threshold_phrase(s) for s in subs}
        where = f"in {len(rule.sub_state)} counties only"
        if len(phrases) == 1:
            return f"{span} {phrases.pop()}, {where}"
        return f"{span} (thresholds vary by county), {where}"
    return f"x{rule.multiplier():.2f} {_threshold_phrase(rule)}"


def main() -> int:
    pop = population_by_state()
    today = datetime.date.today()
    total_pop = sum(pop.get(s, 0.0) for s in SCORED_JURISDICTIONS)
    covered_pop = 0.0
    n_researched = 0

    print(f"Property-tax classification coverage  (table as of {LAW_AS_OF})")
    print(f"{len(SCORED_JURISDICTIONS)} scorable jurisdictions: 50 states + DC. "
          "Puerto Rico and the four small territories are excluded — they carry no "
          "Census of Governments rows, so the dimension cannot score them.\n")

    by_division: dict[str, list[str]] = defaultdict(list)
    for usps in SCORED_JURISDICTIONS:
        by_division[CENSUS_DIVISION[usps]].append(usps)

    for division in DIVISION_ORDER:
        members = sorted(by_division.get(division, []))
        done = [s for s in members if s in CLASSIFICATION_RULES]
        print(f"── {division}  ({len(done)}/{len(members)} researched)")
        for usps in members:
            rule = CLASSIFICATION_RULES.get(usps)
            if rule is None:
                print(f"     {usps}   not researched")
                continue
            n_researched += 1
            covered_pop += pop.get(usps, 0.0)
            age = (today - datetime.date.fromisoformat(rule.verified)).days
            flag = "  [local option]" if rule.local_option else ""
            print(f"     {usps}   {rule.rule_type:16} "
                  f"verified {rule.verified} ({age}d ago){flag}")
            print(f"          {describe_effect(rule)}")
            print(f"          {rule.authority}")
        print()

    share = (covered_pop / total_pop * 100) if total_pop else 0.0
    print(f"Researched: {n_researched}/{len(SCORED_JURISDICTIONS)} jurisdictions, "
          f"{share:.1f}% of US population.")
    print("An unresearched jurisdiction applies NO correction, so rental housing there "
          "is scored as if it were taxed like an owner-occupied home.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
