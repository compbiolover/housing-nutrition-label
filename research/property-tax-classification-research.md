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

### Alabama — `RULE_ASSESSMENT`, 10% → 20%, ×2.00

| | |
|---|---|
| **Threshold** | 1 rental unit (tenure-based) |
| **Authority** | Ala. Const. amend. 373 (recompiled as Ala. Const. of 2022, art. XI, § 217); Ala. Code § 40-8-1 |
| **Confirmed against** | Alabama Department of Revenue, *Property (Ad Valorem) Tax*, which publishes the class definitions verbatim |
| **Verified** | 2026-07-31 |

Class III (10%) is *"all agricultural, forest, and **single-family, owner-occupied**
residential property, including owner-occupied residential manufactured homes located on
land owned by the manufactured homeowner, and historic buildings and sites."* Class II
(20%) is the catch-all: *"all property not otherwise classified."*

Because Class III requires single-family **and** owner-occupied, **any** rental housing
falls to Class II — an apartment building and a rented detached house alike. That is a
different rule shape from Tennessee's, which counts rental units and leaves a rented
single-family home residential. At ×2.00 this is the largest multiplier in the rollout.

**Under-corrects.** Alabama also grants a homestead exemption on Class III property, which
depresses the observed owner-occupied effective rate further, so the true owner/rental gap
exceeds 2.00×. Under-correcting is the safe direction, per the governing principle above.

### Mississippi — `RULE_ASSESSMENT`, 10% → 15%, ×1.50

| | |
|---|---|
| **Threshold** | 1 rental unit (tenure-based) |
| **Authority** | Miss. Const. art. 4, § 112; Miss. Code Ann. § 27-35-4 |
| **Verified** | 2026-07-31 |

Class I (10%) is *"single-family, owner-occupied, residential real property."* Class II
(15%) is *"all other real property, except for real property included in Class I or IV."*

Structurally identical to Alabama — the same single-family-**and**-owner-occupied test, so
the same threshold of 1 — at a narrower spread. **Under-corrects** for the same
homestead-exemption reason.

### Kentucky — `RULE_UNIFORM`, no correction

| | |
|---|---|
| **Authority** | Ky. Const. § 172; Ky. Rev. Stat. § 132.020 |
| **Verified** | 2026-07-31 |

Ky. Const. § 172 requires that all property not exempted be assessed at its fair cash
value, and the General Assembly has confirmed this means 100%. The KRS 132.020 state real
property rate does not distinguish residential from commercial real property, and local
district rates apply uniformly within a district. No classification of rental housing
exists to encode.

**Found and deliberately rejected:** the homestead exemption at Ky. Const. § 170, for
owners aged 65+ or totally disabled. It is keyed to owner characteristics rather than to a
property class, so it falls under the exclusion rule above. Recording it is what makes
Kentucky *researched with no correction* rather than *not yet researched* — a distinction
that is invisible at the point of use, since both produce a 1.0 multiplier.

## Why Alabama and Mississippi need a threshold of 1

`rental_unit_count` already produces the right answer for a tenure-based rule with no code
change. The full matrix, which `tests/test_assessment.py` pins:

| parcel | rental units | AL / MS (≥1) | TN (≥2) |
|---|---|---|---|
| single-family, owner-occupied | 0 | no | no |
| single-family, **unknown tenure** | 0 (defaults to owner) | **no** | no |
| single-family, stated rental | 1 | **yes** | no |
| duplex, owner-occupied | 1 | **yes** | no |
| duplex, rented or unknown | 2 | yes | yes |
| condominium unit (separately parceled) | ≤1 | no | no |

Two rows carry the weight. **Unknown-tenure single-family stays uncorrected**, so Alabama
and Mississippi reach a detached house only when the caller explicitly says it is a rental
— the conservative default the rollout committed to.

**Owner-occupied duplex diverges by design.** Alabama and Mississippi test single-family
*and* owner-occupied, so a duplex fails on the first prong whoever lives in it. Tennessee
counts rental units instead, and an owner-occupied duplex holds only one, so it stays
residential there. Same parcel, opposite answers, both correct.


---

## Not yet researched

The remaining 47 jurisdictions. Each applies **no correction**, so rental housing in them
is currently scored as though taxed like an owner-occupied home.

East South Central is complete (KY, TN, MS, AL), which `tests/test_assessment.py` asserts
rather than claims. Spot-checking during the rollout design indicates South Carolina (4% vs
6%) and Louisiana (10% vs 15%) have real split rolls too — they land in South Atlantic and
West South Central respectively, and neither is encoded until its primary source has been
read.
