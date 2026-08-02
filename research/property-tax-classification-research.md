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

**A sixth question, added in Phase 8: does the preference actually exclude renters?** Four
Mountain states have an owner-occupied preference that a secondary source describes exactly
as a tenure split, and none of them is one — each keys on how the home is *occupied* (primary
residence against second home or short-term rental) rather than on who owns it. Ask it of
every "homestead", "primary residence" or "owner-occupied" rule before believing it.

### Worked example — Utah, and why one confident answer is not enough

Utah's 45% primary residential exemption implies a **×1.82** multiplier, which would be among
the largest in this table. A first pass against the Utah State Tax Commission's own page
returned an unambiguous answer:

> a landlord renting a home to a tenant would not qualify, since the exemption applies only
> when the owner themselves uses the property as their primary residence

That is wrong. The Utah County Assessor's explainer says the opposite, in terms:

> Apartments, condos and mobile homes **also qualify**. … **Properties inhabited by tenants
> also qualify**, if they reside in the property for 183 consecutive days or more in a
> calendar year.

The tell was that the first answer's decisive sentence was an *inference* ("meaning the owner
must personally occupy it"), while its only actual quotation covered transient use and
condominiums in rental pools — both consistent with long-term rentals qualifying. **Quotes
are evidence; the summary around them is not.** Encoding the first answer would have applied
a large correction to 1% of the population in the wrong direction, and nothing downstream
would have caught it, because a wrong multiplier still scores.

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


## South Atlantic

Eight of nine jurisdictions encoded; DC deferred (below). Two carry corrections; six were
researched and found to have no classification of rental housing.

### South Carolina — `RULE_ASSESSMENT`, 4% → 6%, ×1.50

| | |
|---|---|
| **Threshold** | 1 rental unit (tenure-based) |
| **Authority** | S.C. Code Ann. § 12-43-220(c), (e), § 12-37-220(B)(47); S.C. Const. art. X, § 1 |
| **Verified** | 2026-08-01 |

§ 12-43-220(c) gives a 4% assessment ratio to an owner-occupied **legal residence**; all
other real property is 6%. Same shape as Alabama and Mississippi — owner-occupancy is the
test, so the threshold is 1 and a rented detached house is reclassified.

**×1.50 is correct. An earlier version of this section said it under-corrects; that was
wrong, and the retraction is recorded because the wrong reading is the tempting one.**

South Carolina also exempts owner-occupied legal residences from school **operating**
millage (§ 12-37-220(B)(47)) on top of giving them the 4% ratio. Writing `m_n` for
non-school millage, `m_so` for school operating and `m_sd` for school debt:

| | ratio | pays |
|---|---|---|
| owner-occupied legal residence | 4% | `0.04 (m_n + m_sd)` |
| rental / other | 6% | `0.06 (m_n + m_so + m_sd)` |

On a **total** tax bill the rental/owner ratio therefore exceeds 1.5, which is what the old
note saw. But this model never uses the total bill. `region_context` builds
`municipal_rate = ACS_effective_rate × (1 − school_tax_share)` and `enrich_row` applies the
class multiplier to *that*, so the multiplier operates on the **non-school** rate:

```
rental non-school     0.06 · m_n
------------------ = ------------ = 1.5   exactly
owner  non-school     0.04 · m_n
```

The observed owner rate is the base for **both** legs. The exemption changes that base's
*level*, and cancels out of the *ratio*. Michigan's Principal Residence Exemption (Phase 5)
is the same structure with no class split to confuse it, and correctly carries no correction
at all — that case is what settled this one.

**The real residual is a revenue-side defect, not a classification one.** `school_tax_share`
is the school share of property tax collected across *all* property in the county, but
`ACS_effective_rate` is measured over **owner-occupied homes only** — exactly the homes the
exemption applies to. So the netting removes a school component the rate has largely already
lost, understating non-school revenue for every South Carolina parcel regardless of tenure.

That defect is **not South Carolina-specific** — Texas and Michigan share it, together with
South Carolina covering 13.2% of the US population among encoded states. It is written up
properly, with quantification, in
[infrastructure-burden-research.md](infrastructure-burden-research.md); it needs school
operating-versus-debt millage data that is not bundled, and is not fixed here.

### West Virginia — `RULE_RATE`, ×2.00

| | |
|---|---|
| **Threshold** | 1 rental unit (tenure-based) |
| **Authority** | W. Va. Const. art. X, § 1b; W. Va. Code § 11-8-6 et seq.; West Virginia Tax Division, *Property Tax Rates* |
| **Verified** | 2026-08-01 |

The **first `RULE_RATE` jurisdiction** — the first where the split is by tax rate rather
than assessment ratio. Every class is assessed at 60% of value; only the levy differs.

Class II is *"owner-occupied residential property used exclusively for residential purposes
and all farm land used for agricultural purposes by its owner or bona fide tenant"* (WV Tax
Division). Class III is everything else outside a municipality; Class IV everything else
inside. So rental housing is Class III or IV.

**Two sources initially appeared to conflict, and the resolution matters.** W. Va. Code
§ 11-8-6 gives aggregate caps of 50¢ / $1 / $1.50 / $2 for Classes I–IV, a 1:2:3:4 ratio
that reads as Class III being only 1.5× Class II. But those are *aggregate ceilings across
all levying bodies*. The per-body maximum regular levy rates the Tax Division publishes are:

| levy | Class II | Class III | Class IV |
|---|---|---|---|
| County | 28.60 | 57.20 (2.0×) | 57.20 (2.0×) |
| School | 45.90 | 91.80 (2.0×) | 91.80 (2.0×) |
| Municipal | 25.00 | 50.00 (2.0×) | 100.00 (4.0×) |

County and school are the bulk of any West Virginia bill and both are exactly 2.0×, so
**2.00** is encoded. **Under-corrects inside municipalities**, where the Class IV municipal
leg is 4×.

### Florida — `RULE_UNIFORM`, no correction

| | |
|---|---|
| **Authority** | Fla. Const. art. VII, § 4(d), (g), (h), § 6; Fla. Stat. §§ 193.155, 193.1554, 196.031 |
| **Verified** | 2026-08-01 |

Just valuation applies uniformly; there is no class for rental property.

**Found and deliberately rejected:** the homestead exemption (§ 196.031) and — more
significantly — the split assessment-increase caps. Homestead property is capped at 3%
annual growth (art. VII, § 4(d)); non-homestead residential of nine units or fewer at 10%
(§ 4(g)); all other non-homestead at 10% (§ 4(h)). Over a long holding period this opens a
very large owner/rental gap.

It is still not a classification. The gap depends on how long the owner has held the
property and on how far assessed value has drifted from market value, so two identical
adjacent houses can carry very different effective rates purely by purchase date. A constant
class multiplier cannot represent that, and would misstate it in both directions. See the
roadmap item on cap-driven divergence.

### Georgia — `RULE_UNIFORM`, no correction

| | |
|---|---|
| **Authority** | Ga. Code Ann. § 48-5-7(a), § 48-5-44, § 48-5-44.2; Ga. Const. art. VII, § I, ¶ III |
| **Verified** | 2026-08-01 |

§ 48-5-7(a) assesses all taxable tangible property at **40%** of fair market value. Every
enumerated exception is use-based — agricultural, rehabilitated historic, conservation,
timberland — and none distinguishes owner-occupied from rental. The constitution limits
classes for property taxation to tangible and intangible personal property, leaving no room
for a rental-real-property class.

**Found and rejected:** the § 48-5-44 homestead exemption and the § 48-5-44.2 statewide
floating homestead exemption (effective 2025), which caps a homestead's taxable base value
to inflation. Rental property gets no equivalent.

### Maryland — `RULE_UNIFORM`, no correction

| | |
|---|---|
| **Authority** | Md. Code, Tax-Prop. §§ 8-101, 8-103(c), 6-302(b), 9-105 |
| **Verified** | 2026-08-01 |

§ 6-302(b)(1) requires *"a single county property tax rate for all real property subject to
county property tax"*, and the § 8-101 real-property subdivisions are use-based (farm,
woodland, planned development, railroad, utility, conservation) with no tenure subclass.
The authorized special-rate subclasses cover operating property, vacant-and-unfit property,
and certain commercial-industrial financing districts — none defined by tenure.

**Found and rejected:** the § 9-105 Homestead Property Tax Credit, which caps assessment
growth for a homeowner's principal residence only. A credit, not a class.

### North Carolina — `RULE_UNIFORM`, no correction

| | |
|---|---|
| **Authority** | N.C. Gen. Stat. § 105-283, § 105-277; N.C. Const. art. V, § 2(2) |
| **Verified** | 2026-08-01 |

§ 105-283 appraises all property at true value in money, with no tenure distinction, and the
only § 105-277 classes are solar heating/cooling systems and private water company property.

North Carolina also **forecloses the local-option question outright**, which no other state
in this phase does: N.C. Const. art. V, § 2(2) provides that *"Only the General Assembly
shall have the power to classify property for taxation, which power shall be exercised only
on a State-wide basis and shall not be delegated."* A county could not adopt a rental class
even if it wanted to.

### Virginia — `RULE_UNIFORM`, no correction

| | |
|---|---|
| **Authority** | Va. Const. art. X, § 1; Va. Code § 58.1-3201, § 58.1-3221.3 |
| **Verified** | 2026-08-01 |

Uniform assessment at 100% of fair market value.

**This one looked like a local-option case and is not.** Virginia does permit locality-level
real-property classification in several statutes, but the only one with real rate
consequences — § 58.1-3221.3, the commercial and industrial class funding transportation in
Northern Virginia and Hampton Roads — *expressly excludes* rental housing: *"all residential
uses and all multifamily residential uses, including but not limited to single family
residential units, cooperatives, condominiums, townhouses, apartments, or homes in a
subdivision when leased on a unit by unit basis."* A locality levying that extra rate cannot
reach an apartment building. Uniform, not local option.

### Delaware — `RULE_UNIFORM`, no correction

| | |
|---|---|
| **Authority** | Del. Code tit. 9, § 8306 (as amended by HB 62, 2023); tit. 9, ch. 83 |
| **Verified** | 2026-08-01 |

No state property tax; counties assess at fair market value as of the county base year, now
on a five-year reassessment cycle following the 2020 school-funding litigation that forced a
statewide reassessment (completed 2024–25). Title 9 ch. 83 differentiates improved from
unimproved land and grants agricultural use-value, but has no tenure classification. The
senior school property tax credit is age-gated, not a general owner-occupied preference.

### District of Columbia — deferred, unverified

DC restructured its property classes for tax year 2025, introducing a Class 1A / Class 1B
split. Sources conflict on where a multifamily rental building lands: one reading keeps
residential improved property in **Class 1A** regardless of unit count, another pushes
anything above Class 1B's two-unit limit into the **Class 2** commercial catch-all. Those
give very different multipliers.

Under the sourcing standard an unresolved jurisdiction is **left unencoded rather than
guessed**, so DC applies no correction and is recorded here as explicitly outstanding.
`tests/test_assessment.py` asserts that DC is the *only* South Atlantic jurisdiction
missing, so the deferral cannot quietly become an oversight. At 0.21% of the US population
the cost of deferring is small.


---

## West South Central

All four jurisdictions encoded, and **none carries a correction** — the first division to
finish that way. Every owner/rental gap in it runs through an exemption, credit or
assessment cap, which the exclusion rule above keeps out of the table.

### Louisiana — `RULE_UNIFORM` (a predicted correction that dissolved)

| | |
|---|---|
| **Authority** | La. Const. art. VII, § 18(A), (B), § 20; La. Admin. Code tit. 61, § V-101 |
| **Verified** | 2026-08-01 |

The rollout memo typed Louisiana as a correcting state, on the strength of a real 10%/15%
split noticed during design spot-checking. **Reading the primary source overturns that.**

Art. VII, § 18(B) sets five classes:

| classification | percentage |
|---|---|
| Land | 10% |
| Improvements for residential purposes | 10% |
| Electric cooperative properties, excluding land | 15% |
| Public service properties, excluding land | 25% |
| Other property | 15% |

The split is genuine, but it turns on **use**, not tenure. There is no owner-occupancy or
unit-count qualifier anywhere in the provision, and an apartment building is an improvement
used for residential purposes — so it sits in the 10% class beside a detached house. The
Tax Commission's own rule, LAC 61:V-101, reproduces the same five classes and adds no tenure
test.

**Found and rejected.** Where Louisiana *does* separate owner from renter is the art. VII,
§ 20 homestead exemption — $7,500 of assessed value, $75,000 of market value, owner-occupied
only. Those same Tax Commission rules apply it exactly as an exemption rather than a class:
on an income-producing property the owner-occupied part is exempt and the rented part is
not, and a rented half of a double house does not qualify at all. The special assessment level is
age-, disability- and income-gated. Both fall squarely under the exclusion rule.

**Residual uncertainty, recorded not hidden.** Louisiana assessors colloquially describe
apartment buildings as "commercial", and no case or AG opinion squarely construing
"improvements for residential purposes" as applied to apartments was found. The
constitutional text offers no tenure hook for the contrary reading, and `RULE_UNIFORM` is
the under-correcting choice, so the text and the governing principle point the same way.
`tests/test_assessment.py::test_louisiana_split_roll_is_use_based_not_tenure_based` pins
the finding so it cannot quietly regress to the remembered ×1.50.

### Texas — `RULE_UNIFORM`

| | |
|---|---|
| **Authority** | Tex. Const. art. VIII, § 1(a), (b); Tex. Tax Code § 11.13, § 23.23, § 23.231 |
| **Verified** | 2026-08-01 |

Art. VIII, § 1(a) is the flat command that "taxation shall be equal and uniform", and § 1(b)
taxes all real property in proportion to its value. Texas has no property classes at all.

**Found and rejected:** the § 11.13 residence-homestead exemption, the § 23.23 10% homestead
appraisal cap, and the § 23.231 20% circuit-breaker limitation on non-homestead real
property valued at $5M or less.

That last one is the most instructive item in this division. It caps growth on
**non-homestead** property, so it *narrows* the owner/rental gap where Florida's caps widen
it. A regime whose caps do not all push the same direction cannot be represented by a fixed
class multiplier at all — which is the case for the roadmap item rather than a `notes` line.

### Oklahoma — `RULE_UNIFORM`

| | |
|---|---|
| **Authority** | Okla. Const. art. X, § 8(A)(2), (B), § 8B, § 8C |
| **Verified** | 2026-08-01 |

§ 8(A)(2) assesses real property at between 11% and 13.5% of fair cash value. Critically,
§ 8(B) fixes **one** such percentage per county for real property — so Oklahoma's use
categories (agricultural, residential, commercial/industrial) drive *valuation*, not the
ratio, and none of them turns on tenure.

**Found and rejected:** the § 8B annual valuation caps — 3% for homestead and agricultural
against 5% for everything else — and the § 8C senior valuation freeze, which is age- and
income-gated.

### Arkansas — `RULE_UNIFORM`

| | |
|---|---|
| **Authority** | Ark. Const. art. 16, § 5, amend. 79; Ark. Code Ann. § 26-26-303 |
| **Verified** | 2026-08-01 |

Art. 16, § 5 requires taxation "equal and uniform throughout the State", and § 26-26-303
assesses all real property at 20% of appraised value with no tenure class.

**Found and rejected:** the amendment 79 homestead property tax credit ($500, rising to $600
for 2026 bills) and its split assessed-value caps — 5% a year for a homestead against 10%
for all other real property. Same shape as Florida.

---

## Middle Atlantic

Three of three encoded. New York is the hardest jurisdiction in the country and the first
to use `local_option`, `sub_state`, `BASIS_DWELLING_UNITS` and `RULE_EFFECTIVE` — four
pieces of schema that had existed unused since Phase 0. New Jersey and Pennsylvania are
constitutionally uniform.

### New York — `RULE_EFFECTIVE`, ×1.81, New York City only

| | |
|---|---|
| **Threshold** | 11 dwelling units (not rental units, and not tenure) |
| **Scope** | The five boroughs — 36005, 36047, 36061, 36081, 36085 |
| **Authority** | N.Y. Real Prop. Tax Law § 1801, § 1802, § 1805, § 1903; NYC Advisory Commission on Property Tax Reform, *Preliminary Report* (2020), Figure 2 and Table 15 |
| **Verified** | 2026-08-01 |

**Two regimes, only one resolvable.** RPTL art. 18 gives *special assessing units* —
assessing units of 1,000,000 or more, meaning New York City and Nassau County — a four-class
system. § 1802 puts "all one, two and three family residential real property" in class one
and "all other residential real property" in class two, so a rental building of four or more
units is class two. Separately, RPTL art. 19 § 1903 lets any other *approved assessing unit*
split a homestead from a non-homestead class, but only by local law, only after a
revaluation, and one assessing unit at a time. A county contains many assessing units that
may each choose differently, so art. 19 **cannot be resolved at the county granularity this
table keys on**. Towns that adopted it are under-corrected, which is the safe direction.

**The naive statutory multiplier is 4.70× and would be wrong by a factor of 2.6.** Class one
is assessed at 6% of value and taxed at 19.843%; class two at 45% and 12.439% (FY2026).
Multiply through and class two looks like it pays 4.70× what class one pays.

The City's own commission explains why that is an artifact. DOF's published class two
"market value" is an income-capitalization figure that runs well below sales-based value, so
an effective tax rate computed on DOF values overstates the disparity — the report says
prior studies using DOF values "considerably overstated" it, and notes the widely cited
Furman Center estimate of "almost five times" shrinks "dramatically" once a common
denominator is used. Recomputed on sales-based market values (FY2019 median ETR per $100):

| property type | median ETR |
|---|---|
| Class 1 (1–3 family) | $0.85 |
| Class 2 condos | $0.63 |
| Class 2 co-ops | $0.88 |
| Class 2 small rentals (≤10 units) | $0.75 |
| **Class 2 large rentals (11+ units)** | **$1.54** |
| Class 4 non-utilities | $1.29 |

This model's denominator is an ACS self-reported market value — the sales-based concept, not
DOF's — so **$1.54 / $0.85 = 1.81×** is the figure that matches. The Lincoln Institute
50-state study puts the same rental-to-homestead ratio at 2.55×; 1.81 is the
under-correcting choice of the two.

**The 11-unit threshold is statutory, not tuned.** RPTL § 1805(2) shields class two parcels
with fewer than 11 residential units behind the same kind of growth cap class one gets (8% a
year, 30% over five). The ETR table shows that shield working: small rentals pay **$0.75**,
*less* than the $0.85 a 1–3 family home pays. Correcting a 10-unit building would invent a
penalty the City's own data says is absent.

**Condominiums.** Elsewhere a separately-parceled condo escapes correction because each
parcel holds at most one rental unit. In New York City the statute says the opposite — condos
are class two regardless of unit count. The outcome is still correct, by a different route:
class two condos pay $0.63 against $0.85 for houses, so no correction is right anyway.

**Under-corrects in Manhattan.** Median ETR for 1–3 family homes ranges from $0.41 in
Manhattan to $1.02 on Staten Island, and a single citywide multiplier cannot express that.
Manhattan's owner-occupied ACS baseline is also mostly co-ops and condos, which are already
class two — so the multiplier's denominator is less clean there than the borough-blind figure
implies.

**Nassau County (36059) is deferred.** It is a special assessing unit under the same class
definitions, but its assessment ratios and class rates differ from the city's, and no
sales-based ETR study comparable to the commission's was found. Its multiplier would be a
guess. `tests/test_assessment.py` asserts Nassau is absent from `sub_state` and named in the
notes, so the deferral cannot become an oversight.

### New Jersey — `RULE_UNIFORM`

| | |
|---|---|
| **Authority** | N.J. Const. art. VIII, § 1, ¶ 1(a); N.J.S.A. 54:4-2.25, 54:4-23 |
| **Verified** | 2026-08-01 |

¶ 1(a) requires assessment "by uniform rules" and that all real property be assessed
"according to the same standard of value", which § 54:4-2.25 fixes as true value. The sole
constitutional exception is agricultural and horticultural land, not tenure. Apartments are
valued by income capitalization, but that is an appraisal *method* reaching the same standard
of value, not a separate class.

**Found and rejected:** the ANCHOR benefit and the senior freeze, both rebates paid outside
the assessment entirely.

### Pennsylvania — `RULE_UNIFORM`

| | |
|---|---|
| **Authority** | Pa. Const. art. VIII, § 1; *Valley Forge Towers Apartments N, LP v. Upper Merion Area Sch. Dist.*, 163 A.3d 962 (Pa. 2017); 53 Pa. Stat. § 8583 |
| **Verified** | 2026-08-01 |

The Uniformity Clause forecloses classification of real property, and *Valley Forge Towers*
is squarely about rental housing: a school district appealed only apartment-complex
assessments while leaving single-family homes alone, and the Supreme Court held that
unconstitutional because "all property in a taxing district is a single class, and, as a
consequence, the Uniformity Clause does not permit the government, including taxing
authorities, to treat different properties sub-classifications in a disparate manner."
Pennsylvania could not enact the kind of rule this table encodes even if it wanted to.

**Found and rejected:** the Act 1 homestead/farmstead exclusion — an exclusion from assessed
value for owner-occupied homes, not a class.

---

## East North Central

All five encoded, none carrying a correction. The value of the phase is in what was
rejected: **two states whose real class splits key on use rather than tenure**, one whose
large owner/rental gap lives entirely inside a levy this dimension already excludes, and one
cap regime that is structurally unlike Florida's.

### Illinois — `RULE_UNIFORM` (the second predicted correction to dissolve)

| | |
|---|---|
| **Authority** | 35 ILCS 200/9-145; Cook County Assessor, *Definitions for the Classifications of Real Property* |
| **Verified** | 2026-08-01 |

The rollout memo typed Illinois as the second `local_option` case, expecting Cook County's
classification ordinance to split houses from apartments. **It does not.** Cook's own
class-code schedule groups its major classes under one heading:

> **II. RESIDENTIAL ASSESSMENT CLASSES (10% level of assessment)** — Major Class 1 Vacant,
> Major Class 2 Residential, Major Class 3 Multi-Family

Class 2 is houses, condos, co-ops and buildings of six units or fewer; class 3 is rental
apartment buildings of seven or more units (3-13, 3-91 "apartment building over three
stories, seven or more units", 3-99 "rental condominium"). **Both are assessed at 10%.** The
split that matters in Cook is residential against commercial — class 5A at 25% — and rental
housing sits on the residential side of it.

Class 3 *was* higher historically and was reduced by ordinance in stages, reaching 10% in
2011, so an older secondary source shows a differential that no longer exists. This is
exactly the trap the "index, then primary" rule exists to catch.

The Assessor's three-year equalization study makes it stronger: the **realised** levels are
9.15% for class 2 against 7.89% for class 3, so in practice Cook apartments are assessed
*below* houses and even the observed gap runs the wrong way for a correction.

Outside Cook, 35 ILCS 200/9-145 is a uniform 33⅓%. So Illinois is `RULE_UNIFORM` and
explicitly **not** `local_option` — asserted by test, because a `local_option` record with an
empty `sub_state` would also yield 1.0 and the two must not be confusable.

### Ohio — `RULE_UNIFORM` (a real class split, keyed on use)

| | |
|---|---|
| **Authority** | Ohio Const. art. XII, § 2a; Ohio Rev. Code § 5713.03, § 5713.041, § 319.301, § 323.152 |
| **Verified** | 2026-08-01 |

Ohio genuinely has two classes — art. XII, § 2a permits separate HB 920 tax-reduction
factors for class I and class II. But § 5713.041 draws the line by **use**:

> Lands and improvements thereon used for residential or agricultural purposes shall be
> classified as residential/agricultural real property, and all other lands and improvements
> thereon shall be classified as nonresidential/agricultural real property.

An apartment building is used for residential purposes, so it is class I alongside a
detached house. **Same shape as Louisiana** — and the second time a two-class state has
turned out to owe no correction for the same reason, which is why the two are now asserted
together.

Assessment is a uniform 35% of true value. **Found and rejected:** the § 323.152 2.5%
owner-occupancy credit and the homestead exemption.

### Michigan — `RULE_UNIFORM` (a real gap, in a levy already excluded)

| | |
|---|---|
| **Authority** | Mich. Const. art. IX, §§ 3, 31; MCL § 211.7cc, § 211.34d |
| **Verified** | 2026-08-01 |

Uniform assessment at 50% of true cash value, no tenure class.

The rejection here is the most interesting in the table. The § 211.7cc **Principal Residence
Exemption** relieves an owner-occupied principal residence of up to **18 mills**, and
multi-family and rental property do not qualify. That is a large, genuinely tenure-based
differential — bigger than several multipliers this table does encode.

It still warrants no correction, for a sharper reason than the general exclusion rule: those
18 mills are a **school operating** levy, and this dimension nets school taxes out of *both*
sides — the cost model is non-school and the revenue side applies `school_tax_share`. The gap
is real but sits outside what the fiscal ratio measures.

**This settled the open South Carolina question.** Phase 2 recorded SC's owner-occupied
exemption from school operating millage as making ×1.50 *under*-correct. Michigan is the
same structure with no class split to confuse it, and the answer there is plainly no
correction at all — which forced the South Carolina reading to be worked through properly. It
does not survive: the exemption moves the *level* of the observed owner rate, which is the
base for both legs of the ratio, so it cancels. **×1.50 was right all along**, and the
section above now carries the algebra and the retraction.

Both states do share a genuine defect, but on the revenue side rather than in
classification: a county-wide `school_tax_share` netted off an owner-occupied rate that has
already lost its school component. Texas has it too. See
[infrastructure-burden-research.md](infrastructure-burden-research.md).

### Indiana — `RULE_UNIFORM` (the tractable cap case)

| | |
|---|---|
| **Authority** | Ind. Const. art. 10, § 1(f); Ind. Code § 6-1.1-20.6 |
| **Verified** | 2026-08-01 |

**Found and rejected:** the constitutional circuit-breaker caps — 1% of gross assessed value
for an owner-occupied homestead, 2% for other residential and agricultural, 3% for
commercial. They bind hard; statewide credits exceeded **$1.2 billion in 2025**.

This is the least comfortable uniform record in the table, and the notes say so. Indiana is
**structurally different** from Florida and Texas: those cap the *growth* of assessed value,
so their gap depends on holding period and appreciation. Indiana caps tax as a share of
*current* assessed value, by class, with no time dependence at all — where the local gross
rate exceeds 2% the owner/rental ratio is exactly 2.0, where it is under 1% it is exactly
1.0, and in between it is the gross rate over 1%.

That makes Indiana the **most tractable member of the cap roadmap item**, not a Save Our
Homes lookalike. It is unencodable today only for want of county **gross** rates: the bundled
ACS `effective_tax_rate` is the owner-occupied rate, already capped, so the gross rate cannot
be recovered from it once the cap binds.

### Wisconsin — `RULE_UNIFORM`

| | |
|---|---|
| **Authority** | Wis. Const. art. VIII, § 1; Wis. Stat. § 70.32 |
| **Verified** | 2026-08-01 |

The uniformity clause forecloses classification of real property as firmly as Pennsylvania's
does: for direct taxation under the rule of uniformity **there can be but one constitutional
class**, and the burden must be borne as nearly as practicable by all property according to
value. § 70.32 assesses real property at full value with no tenure distinction.

**Found and rejected:** the lottery and gaming credit, available only for an owner-occupied
primary residence.

---

## New England

Six of six encoded, none carrying a correction. The smallest division by population and the
most legally varied: it contains the sharpest test of the school-levy rule, a predicted
local-option case that turned out unable to reach apartments, and the first two records for a
state of knowledge the table had not needed before.

### Vermont — `RULE_UNIFORM` (the hardest "no" in the table)

| | |
|---|---|
| **Authority** | 32 V.S.A. § 5401(7), (10), § 5402; Vt. Const. ch. II, § 66 |
| **Verified** | 2026-08-01 |

§ 5402 imposes a **statewide education property tax at different rates on homestead and
nonhomestead property** — roughly $1.00 spending-adjusted against $1.59, about **1.6×**.
Statutory, statewide, tenure-based, no local option. On its face it is the cleanest
`RULE_RATE` candidate in the country, and anyone reading the statute alone would encode it.

It owes no correction, for exactly the reason Michigan's Principal Residence Exemption does
not: the split sits entirely inside an **education** levy, and this dimension nets school
taxes out of both the cost and the revenue side. That is the rule established when South
Carolina's note was retracted; Vermont is where it is hardest to accept.

**The instructive contrast is next door.** New Hampshire also levies a statewide education
property tax, and its Supreme Court upheld it in 2025 precisely because it is administered
"equal in valuation and **uniform in rate** throughout the state". Same instrument, opposite
answers, and the difference is exactly the thing this table encodes.

**Under-corrects, and the reason is worth stating.** Since Act 60/68 Vermont's education tax
is not a supplement to the municipal property tax — it *is* most of the bill. And 96% of
Vermont's population sits on the **national-average** school share (0.4092) rather than a
measured one, because Vermont funds schools through town-dependent systems carrying no
separate Census of Governments levy. So the model nets away ~41% of a bill that is far more
than 41% education, and the remainder still carries the differential.

Encoding ×1.59 would double-count against whatever the 41% netting *does* remove, and would
become an outright over-correction the moment the school share is fixed. The defect is on the
revenue side; see [infrastructure-burden-research.md](infrastructure-burden-research.md).

### Massachusetts — `RULE_UNIFORM` (a shift that cannot reach apartments)

| | |
|---|---|
| **Authority** | M.G.L. ch. 40, § 56; ch. 59, § 2A, § 38; Mass. Const. pt. 2, ch. 1, § 1, art. 4 |
| **Verified** | 2026-08-01 |

The rollout memo called Massachusetts "the canonical local-option case", and ch. 40, § 56
does let a municipality adopt a residential factor shifting burden toward commercial,
industrial and personal property. **But the shift cannot reach rental housing.** Massachusetts
assessors classify all real property as residential, open space, commercial or industrial, and
*residential includes all property containing one or more units for human habitation* — large
apartment buildings among them. The shift moves burden between residential and commercial;
apartments are on the residential side of it.

Same shape as Virginia in Phase 2, and recorded the same way: `local_option` explicitly
`False`, so the record says *the option does not reach rental housing* rather than *not yet
resolved*.

### Rhode Island and Connecticut — real, and not resolvable

| | RI | CT |
|---|---|---|
| **Authority** | R.I. Gen. Laws § 44-5-11.8, § 44-5-11.18 | Conn. Gen. Stat. § 12-62a, § 12-62n, § 12-62r |
| **Verified** | 2026-08-01 | 2026-08-01 |

Both classify rental housing, and this table cannot resolve either.

**Rhode Island** § 44-5-11.8 puts residential real estate of *no more than five dwelling
units* in class 1 — so a six-unit building falls to class 2 (commercial and industrial)
unless the city provides otherwise. Providence has its own regime under § 44-5-11.18, with
class 1A (fewer than six units), 1B (six to ten) and 1C (more than ten) and rate caps
relative to 1A.

**Connecticut** § 12-62a fixes a uniform 70% assessment ratio statewide, which alone would
make it uniform. But § 12-62n is a **municipal option** to set separate assessment rates, and
it names **"apartment property"** as a category distinct from "residential property" — so
unlike the Massachusetts shift, this one does reach rental housing.

In both the choice is made **per municipality** — Rhode Island's 39 cities and towns,
Connecticut's 169 — and neither state's counties are governmental units: Rhode Island's five
counties have no government, and Connecticut abolished county government in 1960. No county
FIPS can carry the rule, exactly as with New York's art. 19 assessing units.

That is a third state of knowledge:

| state of knowledge | recorded as |
|---|---|
| researched, no classification | `RULE_UNIFORM` |
| researched, classification resolved | a typed rule, or `local_option` + `sub_state` (NYC) |
| **researched, classification real but not resolvable by county** | **`local_option` + empty `sub_state`** |

All three yield a 1.0 multiplier, so only the record tells them apart — the same argument
that makes `RULE_UNIFORM` worth having at all. `RULE_UNIFORM` would be a false claim here: it
asserts there is no classification to find.

Both **under-correct** in every municipality that taxes larger rental buildings commercially.

### Maine and New Hampshire — `RULE_UNIFORM`

**Maine** (Me. Const. art. IX, § 8; 36 M.R.S. § 701-A, § 681): all taxes on real estate must
be "apportioned and assessed equally according to the just value thereof", with exceptions
only for classified farm, open space, forest land and working waterfront — all use-based, none
turning on tenure. **Found and rejected:** the § 681 homestead exemption.

**New Hampshire** (N.H. Const. pt. II, art. 5; RSA 75:1, RSA 76:3): art. 5 permits only
"proportional and reasonable" assessments and rates, and RSA 75:1 appraises at full and true
value with no tenure class. Its statewide education property tax is uniform in rate — see the
Vermont contrast above.

---

## West North Central

Seven of seven encoded, and **two carry corrections** — the first new ones since New York
City in Phase 4. The rollout memo predicted one (Minnesota); North Dakota was missed, and
turned up only because its classification lives in a definitions section the valuation
statute never cites.

### Minnesota — `RULE_ASSESSMENT`, ×1.25, four **rental** units

| | |
|---|---|
| **Authority** | Minn. Stat. § 273.13 subd. 22, subd. 25 |
| **Verified** | 2026-08-01 |

Minnesota assigns a **class rate** to each class; market value × class rate gives tax
capacity, which the local rate is applied to. A class rate therefore does exactly the job of
an assessment ratio.

| class | property | rate |
|---|---|---|
| 1a | residential **homestead** | 1.00% to $500,000, 1.25% above |
| 4bb | non-homestead residential, **1–3 units** | same as 1a |
| **4a** | residential, **4+ units, held for rent** (30+ days) | **1.25% flat** |

**Tenure alone never reclassifies.** A rented single-family home or triplex is class 4bb,
which carries 1a's rates exactly — so the threshold is 4, not the 1 used by Alabama,
Mississippi and South Carolina. And it counts **rental** units, because 4a requires the units
be held for rent: Minnesota assessors split an owner-occupied fourplex between 1a and 4a,
which a single-class model cannot express, so counting rental units leaves it unreclassified.
The under-correcting side of that edge.

**The multiplier is exact, not a bound.** Class 1a's tiering above $500,000 would make the
ratio value-dependent — except no Minnesota county has a median owner-occupied value that
reaches the tier (highest is Carver at $453,600; the median of county medians is $231,900).
The ACS rate is computed at the county median, so the 1a rate against which the multiplier
applies is a flat 1.00% statewide. A test asserts this against the bundled crosswalk, since a
future data refresh could break it.

### North Dakota — `RULE_ASSESSMENT`, ×1.11, four **dwelling** units

| | |
|---|---|
| **Authority** | N.D.C.C. § 57-02-01(5), (14), § 57-02-27 |
| **Verified** | 2026-08-01 |

§ 57-02-27 values residential property at 9% of assessed value and commercial at 10% — but
it does **not define either class**, which is why a reader stopping at the valuation statute
concludes North Dakota is uniform. The definitions are in § 57-02-01:

> Residential property is all or any portion of property used by an individual or a group of
> individuals as a dwelling … **It does not include structures which accommodate four or more
> separate family units**

and § 57-02-01(5) sweeps those into commercial: "any tract of land with four or more separate
family units … is classified commercial."

So the test is **purely physical** — four or more family units the structure accommodates,
with no tenure element at all. The basis is dwelling units, not rental units.

### The pair — same number, different basis

Minnesota and North Dakota both reclassify at **four**, and disagree about the same building:

| parcel | MN | ND |
|---|---|---|
| rented triplex | 1a rates (no correction) | residential (no correction) |
| fully rented fourplex | **×1.25** | **×1.11** |
| **owner-occupied fourplex** | no correction (3 rental units) | **×1.11** (4 family units) |
| 157-unit condo, separately parceled | no correction | no correction |

That divergence is the clearest illustration in the table of why `threshold_basis` exists as
a schema field rather than an assumption.

### South Dakota — the third school-levy rejection

| | |
|---|---|
| **Authority** | SDCL § 10-13-39, § 10-13-40; S.D. Const. art. XI, § 2 |
| **Verified** | 2026-08-01 |

§ 10-13-39's owner-occupied single-family classification cuts the **school general fund**
levy roughly in half for a principal residence, and § 10-13-40 spreads the full levy against
all district property not so classified. A large, genuinely tenure-based differential —
confined to a school levy, which this dimension nets out of both sides.

**This is now a category, not a coincidence.** Michigan's Principal Residence Exemption
(Phase 5), Vermont's homestead/nonhomestead education rate (Phase 6) and South Dakota all
reach "no correction" by the same route, and `tests/test_assessment.py` asserts each names
the school levy as its reason. A reader meeting the fourth should find the pattern written
down rather than re-derive it.

### Iowa, Missouri, Kansas, Nebraska

**Iowa** (Iowa Code § 441.21; 2013 Iowa Acts ch. 123; 2021 Iowa Acts ch. 177) had a separate
**multiresidential** class covering apartments, created in 2013, phased toward the
residential rollback, and **eliminated effective January 1, 2022** with those properties
recategorized as residential. Apartments now take the same rollback as houses. The Cook
County trap again: a source written before 2022 shows a differential that no longer exists.

**Missouri** (Mo. Const. art. X, § 4(b); § 137.016, § 137.115) subclasses residential at 19%,
agricultural 12%, commercial 32% — but § 137.016 defines residential by **use**: "all real
property improved by a structure which is used or intended to be used for residential living
by human occupants", with no tenure or unit-count qualifier, and the State Tax Commission
subclasses condominiums and apartments as residential.

**Kansas** (Kan. Const. art. 11, § 1(a)) is the clearest wording of the use-based pattern
found anywhere — the constitution names rental housing *into* the residential class: "real
property used for residential purposes **including multi-family residential real property**"
at 11.5%, against 25% commercial. No inference needed.

**Nebraska** (Neb. Const. art. VIII, § 1; § 77-201) requires taxes "levied by valuation
uniformly and proportionately upon all real property", with agricultural and horticultural
land the only permitted class. A use exception, not a tenure one.

---

## Mountain

Eight of eight encoded, **none carrying a correction** — and for one division-wide reason
rather than eight separate ones.

### The division's finding: these reforms target second homes, not landlords

Four Mountain states have a headline owner-occupied preference. **Not one excludes long-term
rental housing.** Every split turns on how the home is *occupied* — primary residence against
second home or short-term rental — rather than on who owns it. That is a coherent policy
story: these are amenity and resort states whose political target is the non-resident owner,
not the landlord.

| state | looks like | actually |
|---|---|---|
| **UT** | 45% exemption for "primary residence" → ×1.82 | Covers tenants: "Properties inhabited by tenants also qualify, if they reside in the property for 183 consecutive days or more." Apartments and condos named. What loses it is transient use and rental pools. |
| **MT** | 2025 HB 231 "homestead rate" | Covers principal residences **and long-term rentals**, the latter defined to include a unit of a multiple-unit dwelling. The higher rate hits second homes and short-term rentals. |
| **CO** | 2025 owner-occupied primary residence subclass | HB24B-1001 sets one **6.25%** rate for *all* residential on local levies. The rate varies by **levy type** (6.25% local, 7.05% school), not occupancy; the subclass carries senior/veteran exemptions. |
| **AZ** | Legal class 3 vs class 4 (leased/rented) | A genuine tenure split — but **both assessed at 10%**. The only difference is a 40% rebate on *school district* tax, capped at $600. |

### Arizona — the fourth school-levy rejection

| | |
|---|---|
| **Authority** | A.R.S. § 42-12003, § 42-12004, § 42-15003, § 42-15004; § 15-972 |
| **Verified** | 2026-08-01 |

The rollout memo predicted Arizona as this division's real correction, and its classes *do*
split owner-occupied from rented. They simply carry the same assessment ratio. The money is
in the homeowner rebate — the state pays 40% of the primary **school** district tax on class
3, capped at $600 — and this dimension nets school taxes out of both the cost and the revenue
side.

That joins Michigan (Phase 5), Vermont (Phase 6) and South Dakota (Phase 7). Four states,
four phases, one route to "no correction", asserted by a shared test.

### Wyoming — the one that does narrow to ownership

| | |
|---|---|
| **Authority** | Wyo. Const. art. 15, § 11 (amended 2024); Wyo. Stat. § 39-13-103; 2025 Wyo. Sess. Laws ch. 106 (SF 69) |
| **Verified** | 2026-08-01 |

Amendment A (2024) made residential real property a fourth constitutional class and
**authorized** an owner-occupied primary residence subclass. What the 2025 legislature
enacted is SF 69 — an **exemption**, not a class rate: 25% of the first $1,000,000 of fair
market value. It applied to **all** residential structures for FY2026 and narrows to
**owner-occupied only from FY2027**.

**Found and rejected on two grounds.** It is an exemption, and it is value-capped — 25% relief
on a $400,000 home, but proportionally less above $1M — so the gap is value-dependent in the
Idaho and Florida shape rather than a fixed class ratio.

**Flagged for re-examination**, uniquely in this division: it is the one Mountain preference
that genuinely narrows to ownership, and if Wyoming ever restates it as a class rate it
becomes encodable. A test asserts the record says so.

### Nevada, Idaho, New Mexico — cap and exemption cases

**Nevada** (NRS § 361.225, § 361.4723, § 361.4724) assesses everything at 35% of taxable
value. Its partial abatement caps the annual tax increase at **3% for an owner's primary
residence against up to 8%** for everything else — a growth cap, so the gap depends on
holding period and appreciation. Florida's shape.

**Idaho** (Idaho Code § 63-602G) grants the lesser of $125,000 or 50% of market value, and
unlike Utah's it *is* genuinely owner-occupied only. But it is **value-capped**: 50% relief on
a $250,000 home, 25% on a $500,000 one. Value-dependent, so excluded.

**New Mexico** (N.M. Const. art. VIII, § 1; § 7-37-3, § 7-36-21.2) requires taxes "equal and
uniform upon subjects of taxation of the same class" at no more than 33⅓%. § 7-36-21.2 limits
annual increases in residential valuation and may apply the limit by owner-occupancy — a
valuation growth cap, the Nevada shape.

---

## Pacific

Four of five encoded, none carrying a correction — and one deferral that is unlike any other
in this memo. **This division closes the rollout at 49 of 51, 99.4% of the population.**

### California — `RULE_UNIFORM`

| | |
|---|---|
| **Authority** | Cal. Const. art. XIII, § 1, § 3(k); art. XIII A, § 1, § 2, § 2.1 |
| **Verified** | 2026-08-01 |

The classification question is settled by one sentence. Art. XIII, § 1(a): "All property is
taxable and **shall be assessed at the same percentage of fair market value**." One
percentage, and art. XIII A, § 1 caps the ad valorem rate at **1%** for everyone, so there is
no legislative classification power left to exercise.

**Found and rejected: the homeowners' exemption.** Art. XIII, § 3(k) exempts **$7,000** of
full value on an owner-occupied principal residence. A fixed dollar exemption — the Kentucky
shape — and against a modern California assessment it is negligible.

**Found and rejected: Proposition 13.** Art. XIII A, § 2 freezes a base year value with 2%
annual growth and reassesses on change of ownership. This produces a very large owner/rental
gap in practice, but it runs on **holding period**, not on class, so the exclusion rule keeps
it out. California is the **largest member of the cap-driven divergence roadmap item** at
11.96% of the population on its own.

**Worth recording: California's cap is the one that is *not* tenure-neutral.** Proposition 19
(art. XIII A, § 2.1) narrowed the parent-child exclusion so an inherited home keeps its base
year value only if it "continues as the family home of the transferee". An inherited rental is
therefore reassessed and an inherited primary residence is not — a genuine tenure key, sitting
inside a transfer-and-cap mechanism rather than a class ratio. Documented, not encoded, and it
sharpens the roadmap item: the cap states are not all alike, and California's cap works
against rental housing specifically.

### Oregon — `RULE_UNIFORM`

| | |
|---|---|
| **Authority** | Or. Const. art. I, § 32; art. IX, § 1; art. XI, § 11, § 11b; ORS 308.149, 308.153, 308.156; OAR 150-308-0170 |
| **Verified** | 2026-08-01 |

Taxation uniform on the same class of subjects. Three things were checked and rejected.

**Measure 50** (art. XI, § 11) sets a maximum assessed value that may not grow more than **3%**
a year. A growth cap — Florida's shape.

**Measure 5** (art. XI, § 11b) limits taxes to $5 per $1,000 for one category and $10 per
$1,000 for the other. Those categories look like a classification and are not one: they are
defined by **the purpose the tax funds** — the public school system against government
operations other than the public school system — not by property type. This is the Vermont
finding in a different constitution, and it lands the same way.

**The changed property ratio** (ORS 308.153, 308.156) is the subtle one. Newly added value is
placed at the same assessed-to-market ratio as similar existing property, and "similar" is
resolved by the ORS 308.149 **property class**, which OAR 150-308-0170 takes from the
Department of Revenue's classification. That classification keys on **use**, in the Louisiana
and Ohio pattern — and the ratio *equalises* new value rather than preferring anyone, and only
at the moment value is added. Nothing in Oregon keys on tenure.

### Washington — `RULE_UNIFORM`

| | |
|---|---|
| **Authority** | Wash. Const. art. VII, § 1, § 2; RCW 84.40.030 |
| **Verified** | 2026-08-01 |

The most explicit uniform text in the table. Art. VII, § 1 provides that "**all real estate
shall constitute one class**" and that taxes "shall be uniform upon the same class of
property", with RCW 84.40.030 valuing all property at 100% of true and fair value. One class
admits no split, so there is nothing to reject.

### Alaska — `RULE_UNIFORM`

| | |
|---|---|
| **Authority** | Alaska Stat. § 29.45.030, § 29.45.050, § 29.45.110 |
| **Verified** | 2026-08-01 |

Section 29.45.110 assesses all property at full and true value, with no class ratios.

**Found and rejected: the § 29.45.050 optional exemptions**, which a municipality may adopt by
ordinance or voter approval. They are dollar-capped and gated on senior, disabled-veteran or
residence status rather than tenure. Note this is *not* a Rhode Island or Connecticut case:
there the municipal rule reaches rental housing as a class and simply cannot be resolved to a
county; here there is no such rule to resolve, so `local_option` would overstate what was
found.

### Hawaii — deferred, and for a new reason

| | |
|---|---|
| **Authority** | Haw. Rev. Stat. § 246A-2; Honolulu ROH ch. 8 and the four counties' FY26 rate resolutions |
| **Verified** | 2026-08-01 — researched, deliberately not encoded |

Hawaii is the only jurisdiction in this memo left out because the correction is **too large to
trust**, rather than too ambiguous to resolve.

Everything that usually blocks encoding is absent. Section 246A-2 transferred the property tax
power to the counties, and unlike Rhode Island and Connecticut **the four counties *are* the
taxing units**, so a county FIPS resolves the rule cleanly through `sub_state`. The split is
genuinely tenure-based: Honolulu's Residential A, Kaua'i's Non-Owner-Occupied, and the Maui
and Hawai'i County Apartment classes all separate an owner's principal residence from rented
housing.

What stops it is the size. Modelled on the FY26 rate schedules at a large apartment building:

| county | apartment / non-owner class | owner-occupied | implied |
|---|---|---|---|
| Kaua'i (Non-Owner-Occupied) | $9.21 per $1,000 eff. | $2.59 | **×3.56** |
| Honolulu (Residential A) | $11.21 per $1,000 eff. | $3.50 | **×3.20** |
| Maui (Apartment, flat) | $3.50 per $1,000 | $1.65 | ×2.12 |
| Hawai'i County (Apartment) | $11.70 per $1,000 eff. | $5.95 | ×1.97 |

**Two of the four breach `CLASSIFICATION_MULT_CEIL` (3.0)**, the tripwire this table carries
precisely so that a research error announces itself instead of scoring. And Honolulu's
Residential A is a **two-tier bracket above $1,000,000**, so the "effective rate" in that
table is a modelling choice about building value, not a statutory ratio — the Florida shape
wearing a rate schedule.

Either the multipliers are right, in which case Hawaii deserves the largest correction in the
table and should be built on a proper bracket model rather than a single assumed value; or
they are wrong, in which case the ceiling caught it. **Neither reading supports encoding it
now.** Under "when in doubt, under-correct", Hawaii stays out — at 0.44% of the population,
that is a cheap way to be wrong. The rationale lives in a comment in `assessment.py` and is
asserted by `test_hawaii_deferral_records_why_it_is_not_encoded`, so a future reader who wants
to encode it hits the reasoning first.

---

## The two deferrals

The rollout is **complete**: all nine Census divisions have been read, 49 of 51 jurisdictions
are encoded, and the two that are not are **deferrals with stated reasons**, not gaps in the
reading. Both apply **no correction**, so rental housing in them is scored as though taxed
like an owner-occupied home.

| | why it is out | is that conservative? |
|---|---|---|
| **District of Columbia** (0.21%) | Sources conflict on where a multifamily rental lands after the tax-year-2025 Class 1A/1B restructuring. The candidate readings give very different multipliers. | Unknown direction — genuinely ambiguous. |
| **Hawaii** (0.44%) | Two of four county multipliers breach the correction ceiling and Honolulu's is a value-tiered bracket rather than a class ratio. | **No — known to understate.** Hawaii does classify rental housing, and heavily. |

Together they hold **0.65%** of the US population.

Two sub-state deferrals are outstanding inside otherwise complete divisions: DC, and Nassau
County within New York. Rhode Island and Connecticut are **not** deferrals — they are
researched and recorded as unresolvable, which is a different thing again: three states of
knowledge, all distinguishable in the table.
