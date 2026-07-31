# Property-tax classification — per-jurisdiction research record

The authority behind every entry in `src/housing_label/data/assessment.py`. One row per
jurisdiction, added as each is researched. The rollout sequence and design rationale live
in [property-tax-classification-rollout.md](property-tax-classification-rollout.md).

Run `python scripts/report_classification_coverage.py` for live coverage.

---

## Method

**Index, then primary.** The Lincoln Institute's *Significant Features of the Property Tax*
classification database is used to find *which* states classify. Every encoded number is
then verified against that state's own constitution, code, or Department of Revenue
publication. Lincoln is the search index, never the cited authority. Where index and
primary source disagree, the state is left **unencoded** rather than guessed.

Five questions per jurisdiction, in order:

1. More than one assessment ratio, or more than one rate, for *real* property?
2. What distinguishes the classes — dwelling-unit count, rental-unit count,
   owner-occupancy, or use?
3. Is the residential class defined by owner-occupancy (threshold 1 rental unit) or by unit
   count (threshold 2+)?
4. Uniform statewide, or local option?
5. Does the differential attach to the **assessment ratio**, the **rate**, or an
   **exemption/credit**?

## What is deliberately excluded

**Exemptions, credits, and assessment caps are not classification**, even where they open a
large owner-occupied/rental gap. Florida's Save Our Homes, Texas's homestead cap,
California's Proposition 13, and Louisiana's homestead exemption all fall here.

The reason is the same one that makes the multiplier valid in the first place. The revenue
side of the national path is an ACS effective rate measured over **owner-occupied** homes,
so it already embeds the exemption those homes receive. A rental property differs by the
*absence* of that exemption — which is value-dependent and generally larger than a constant
multiplier, not a fixed ratio between two statutory classes. Encoding one as the other
would over-correct.

So a state where an exemption was found and rejected still gets a record, typed
`RULE_UNIFORM`, with `notes` saying what was found. That is how "researched, no correction"
is distinguished from "not researched" — silence would conflate them.

## Governing principle: when in doubt, under-correct

Unresearched states, local-option states whose geography cannot be resolved, and
single-family homes of unknown tenure all resolve to no correction. An under-corrected
rental building looks like the model's previous behavior; an over-corrected one invents tax
revenue that no assessor would ever bill.

---

## Encoded jurisdictions

### Tennessee — `RULE_ASSESSMENT`, 25% → 40%, ×1.60

| | |
|---|---|
| **Threshold** | 2 **rental** units |
| **Authority** | Tenn. Const. art. II, § 28; Tenn. Code Ann. § 67-5-501(11), (4); § 67-5-801 |
| **Construed by** | Tenn. Att'y Gen. Op. No. 25-016 (Aug. 25, 2025); *Spring Hill, L.P. v. State Bd. of Equalization*, No. M2001-02683-COA-R3-CV, 2003 WL 23099679 (Tenn. Ct. App. Dec. 31, 2003) |
| **Verified** | 2026-07-31 |

Tennessee's rule is **constitutional**, not merely statutory. Art. II, § 28 assesses
residential property at 25% of value, "provided that residential property containing two
(2) or more rental units is hereby defined as industrial and commercial property." That is
codified at § 67-5-501(11), which defines residential property as "all real property that
is used, or held for use, for dwelling purposes and that contains not more than one (1)
rental unit," with a parallel statement in § 67-5-501(4). Section 67-5-801 sets the rates:
residential 25%, industrial and commercial 40%.

The operative count is **rental units, not dwelling units**. AG Op. 25-016 works the edges:
a single-family home rented long-term stays residential, and so does an owner-occupied
duplex, because each contains only one rental unit. The same opinion notes there is no
bright-line physical test — *Spring Hill* classified 44 detached homes on separate lots as
industrial and commercial because they were one commonly owned and managed rental
development, expressly rejecting the argument that "the determinative factor is whether the
residences are physically conjoined."

**Consequence.** A Memphis apartment building generates 1.6× the property tax a flat
residential ratio credits it. A condominium building of the same size does not: each unit
is its own parcel containing at most one rental unit, which is what
`separately_parceled=True` expresses.

---

## Not yet researched

The other 50 jurisdictions. Each applies **no correction**, so rental housing in them is
currently scored as though taxed like an owner-occupied home. Spot-checking during the
rollout design already indicates that at least Alabama, South Carolina, Mississippi and
Louisiana have real split rolls, so this gap understates rental housing materially in the
Southeast — but none is encoded until its primary source has been read.
