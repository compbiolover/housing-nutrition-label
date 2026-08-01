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
    CLASSIFICATION_RULES, LAW_AS_OF, RULE_UNIFORM, classification_for,
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
            info = classification_for(usps, 8, owner_occupied=False)
            mult = info["multiplier"]
            if rule.rule_type == RULE_UNIFORM:
                effect = "no correction"
            elif rule.sub_state:
                # A local-option container corrects only through its sub-rules, so its own
                # multiplier is 1.0 and printing that would read as "researched, no
                # effect" — the opposite of the truth for a New York City parcel.
                subs = sorted({s.multiplier() for s in rule.sub_state.values()})
                effect = "x" + "/".join(f"{m:.2f}" for m in subs)
                effect += f" in {len(rule.sub_state)} cos"
            else:
                effect = f"x{mult:.2f}"
            age = (today - datetime.date.fromisoformat(rule.verified)).days
            flag = "  [local option]" if rule.local_option else ""
            print(f"     {usps}   {rule.rule_type:16} {effect:22} "
                  f"verified {rule.verified} ({age}d ago){flag}")
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
