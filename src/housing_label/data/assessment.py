"""Property-tax **classification** — the assessment ratio a parcel is taxed on.

Most states assess all housing at one ratio, so appraised value and the effective tax rate
are enough to estimate a parcel's bill. A minority use a *split roll*: they put rental
housing into a higher-taxed class. Where that happens, applying a single-family basis to an
apartment building understates its property-tax revenue — and therefore understates its
Infrastructure Burden fiscal ratio.

Two mechanisms, one correction
------------------------------
A state can split the roll two ways, and they are economically equivalent:

* ``RULE_ASSESSMENT`` — one class is assessed at a higher *fraction of value* (Tennessee
  25% vs 40%; South Carolina 4% vs 6%).
* ``RULE_RATE`` — assessment is uniform but the *millage* differs by class (DC, Rhode
  Island, New York City).

Both reduce to a **multiplier** on what an owner-occupied home pays, which is what the two
scoring paths need:

* The **statutory path** (the Shelby pilot) applies a real assessment ratio against a real
  millage, so it needs the absolute commercial ratio — ``classified_assess_ratio``.
* The **national path** applies an ACS *observed effective rate* (B25103 median taxes ÷
  B25077 median value) computed over **owner-occupied** homes. That rate already embeds
  whatever class owner-occupied homes fall in, so an absolute ratio would double-count.
  It needs the ratio *between* the classes — ``classification_multiplier``.

The multiplier is well-founded on that path for an exact reason: **its denominator must
match the baseline embedded in the observed rate.** In Tennessee owner-occupied homes are
the 25% class; in South Carolina the 4% legal-residence class; in DC Class 1. In every
classifying state the ACS owner-occupied baseline *is* the residential denominator.

What is deliberately NOT encoded
--------------------------------
**Exemptions, credits, and assessment caps are excluded**, even where they produce a large
owner-occupied/rental gap. Florida's Save Our Homes, Texas's homestead cap, California's
Proposition 13 and Louisiana's homestead exemption all fall here. The reasoning is the same
one that makes the multiplier valid: the ACS observed rate already embeds the exemption for
owner-occupied homes, so the rental baseline differs by its *absence* — a correction that is
value-dependent and generally larger than a constant multiplier, not a class ratio. Encoding
one as the other would over-correct. Only a rule assigning rental or non-owner-occupied
property to a distinct statutory class with a distinct ratio or rate is encoded here; a
state where one was found and rejected carries a ``RULE_UNIFORM`` record whose ``notes``
say so, which is how "researched, no correction" is told apart from "not researched".

Tennessee (the pilot)
---------------------
**Tenn. Const. art. II, § 28** sets residential assessment at 25% of value, "provided that
residential property containing two (2) or more rental units is hereby defined as
industrial and commercial property." Codified at **Tenn. Code Ann. § 67-5-501(11)**, which
defines residential property as "all real property that is used, or held for use, for
dwelling purposes and that contains not more than one (1) rental unit" (see also
§ 67-5-501(4)). **Tenn. Code Ann. § 67-5-801** sets the rates: residential 25%, industrial
and commercial 40%.

The operative count is **rental units, not dwelling units**. Tennessee AG Opinion No.
25-016 (Aug. 25, 2025) applies it: a single-family home rented long-term stays residential
(one rental unit), and so does an owner-occupied duplex (the owner's half is not a rental
unit). There is no bright-line physical test — in *Spring Hill, L.P. v. State Board of
Equalization*, No. M2001-02683-COA-R3-CV, 2003 WL 23099679, at *17–*18 (Tenn. Ct. App.
Dec. 31, 2003), 44 detached homes on separate lots were classified industrial and
commercial because they were one commonly owned and managed rental development.

So a 157-unit rental building in Memphis is assessed at 40%, not 25% — 1.6x the revenue a
flat residential ratio credits it. A 157-unit *condominium* is not: each unit is its own
parcel containing at most one rental unit (see ``separately_parceled``).

Coverage
--------
Twenty-four of 51 scorable jurisdictions are encoded: all of East South Central, West South
Central, Middle Atlantic and East North Central, and all of South Atlantic except the
District of Columbia, which is deferred as unverified.

Six carry a correction — AL and WV at 2.0x, New York City at 1.81x, TN at 1.6x, MS and SC
at 1.5x. The other eighteen were researched and found to have no classification of rental
housing, and are recorded as ``RULE_UNIFORM`` rather than left absent: both produce a 1.0
multiplier at the point of use, so only the record distinguishes "researched, no
correction" from "not researched". Louisiana and Ohio are the instructive ones — both have
a real class split, but it keys on *use* rather than tenure, so an apartment building sits
in the same class as a detached house.

New York is the only ``local_option`` state resolved so far, and the only one whose
correction comes from a published effective-rate study rather than statutory legs — see
``RULE_EFFECTIVE`` and the NY notes, where the naive statutory reading over-corrects by
2.6x.

The remaining 27 jurisdictions return no correction. That is a real coverage gap, not a
claim that they lack split rolls — several do, with different thresholds and ratios. The
rollout plan is ``research/property-tax-classification-rollout.md`` and the per-jurisdiction
authority record is ``research/property-tax-classification-research.md``; extending the
table means reading each state's constitution or code, one at a time, and must not be
guessed from a secondary source. ``scripts/report_classification_coverage.py`` prints live
coverage by Census division.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from housing_label.data.states import SCORED_JURISDICTIONS

# Date the encoded rules were last checked against their primary sources, in aggregate.
# Per-record ``verified`` gives the per-state granularity; this is the table-level vintage,
# playing the same role as ``DATA_VINTAGE`` in the crosswalk loaders.
LAW_AS_OF = "2026-08-01"

# ── Rule types ────────────────────────────────────────────────────────────────
RULE_ASSESSMENT = "assessment_ratio"   # classes differ by fraction of value assessed
RULE_RATE = "tax_rate"                 # uniform assessment, classes differ by millage
RULE_EFFECTIVE = "effective_rate"      # both differ; a published ETR study is the datum
RULE_UNIFORM = "uniform"               # researched; no classification of rental housing

# What the reclassification threshold counts. Tennessee counts RENTAL units; New York City's
# Class 1 vs Class 2 counts DWELLING units (1-3 family vs 4+), so the distinction has to be
# in the schema from the start rather than retrofitted after states are encoded.
BASIS_RENTAL_UNITS = "rental_units"
BASIS_DWELLING_UNITS = "dwelling_units"

# A split roll that more than triples the tax is not a real rule, it is a research error —
# the widest genuine split found so far is Cook County's 10% vs 25%. Mirrors the clamp
# convention of ``data/govfinance.MULT_FLOOR/CEIL`` and ``data/propertytax.RATE_FLOOR/CEIL``.
CLASSIFICATION_MULT_CEIL = 3.0

# Tenn. Code Ann. § 67-5-801 assessment rates.
TN_RESIDENTIAL_ASSESS_RATIO = 0.25
TN_COMMERCIAL_ASSESS_RATIO = 0.40
# Tenn. Const. art. II, § 28 / Tenn. Code Ann. § 67-5-501(11).
TN_COMMERCIAL_RENTAL_UNIT_THRESHOLD = 2

# Default tenure assumption for a multi-unit building when the caller doesn't say.
# ACS 2024 5-yr table B25032 (tenure by units in structure, US): 86.1% of units in 2+ unit
# structures are renter-occupied, rising to 87.9% in 5+ unit structures — so treating a
# multi-unit building as rental is right for roughly six of every seven. The mirror image
# holds for detached homes: 14.0% are renter-occupied, so defaulting a single home to
# owner-occupied is right ~86% of the time. A condominium or owner-occupied duplex is the
# documented exception and callers can say so explicitly.
MULTIUNIT_RENTAL_DEFAULT = True


@dataclass(frozen=True)
class ClassificationRule:
    """How one jurisdiction classifies rental housing for property tax.

    ``residential``/``commercial`` are assessment ratios when ``rule_type`` is
    ``RULE_ASSESSMENT`` and class tax rates when it is ``RULE_RATE``; either way the
    correction is their quotient. ``effective_multiplier`` overrides that quotient for
    jurisdictions where the published effective differential is the primary datum — in New
    York City the class ratios and the class rates move in opposite directions, so deriving
    the multiplier from either leg alone is wrong.

    ``local_option`` marks a state whose classification is set below the state level. Those
    yield no correction unless ``sub_state`` carries an entry for the parcel's county,
    because a statewide average is wrong nearly everywhere: many of Massachusetts's 351
    municipalities set no shift at all while Boston sets a large one.
    """

    usps: str
    rule_type: str
    authority: str                        # primary-source citation
    verified: str                         # ISO date the citation was read
    threshold_basis: str | None = None
    rental_unit_threshold: int | None = None
    residential: float | None = None
    commercial: float | None = None
    effective_multiplier: float | None = None
    local_option: bool = False
    sub_state: dict[str, "ClassificationRule"] = field(default_factory=dict)
    notes: str = ""

    def multiplier(self) -> float:
        """Ratio of the non-residential class to the residential class, clamped."""
        if self.rule_type == RULE_UNIFORM:
            return 1.0
        if self.effective_multiplier is not None:
            raw = self.effective_multiplier
        elif self.residential and self.commercial:
            raw = self.commercial / self.residential
        else:
            return 1.0
        # Rounded because the legs are decimal statutory percentages whose quotient is
        # not always exact in binary — Mississippi's 0.15/0.10 lands on
        # 1.4999999999999998. Six places is far finer than any real statute distinguishes
        # and keeps the multiplier comparable to the literal a test or a reader expects.
        return round(min(max(raw, 1.0), CLASSIFICATION_MULT_CEIL), 6)


CLASSIFICATION_RULES: dict[str, ClassificationRule] = {
    "TN": ClassificationRule(
        usps="TN",
        rule_type=RULE_ASSESSMENT,
        threshold_basis=BASIS_RENTAL_UNITS,
        rental_unit_threshold=TN_COMMERCIAL_RENTAL_UNIT_THRESHOLD,
        residential=TN_RESIDENTIAL_ASSESS_RATIO,
        commercial=TN_COMMERCIAL_ASSESS_RATIO,
        authority=("Tenn. Const. art. II, § 28; Tenn. Code Ann. § 67-5-501(11), (4); "
                   "§ 67-5-801; Tenn. Att'y Gen. Op. No. 25-016 (Aug. 25, 2025)"),
        verified="2026-07-31",
        notes=("Counts RENTAL units, not dwelling units: a rented single-family home and an "
               "owner-occupied duplex both stay residential. Spring Hill, L.P. v. State Bd. "
               "of Equalization, 2003 WL 23099679, at *17-*18, holds there is no "
               "bright-line physical test."),
    ),
    # ── East South Central ────────────────────────────────────────────────────
    "AL": ClassificationRule(
        usps="AL",
        rule_type=RULE_ASSESSMENT,
        threshold_basis=BASIS_RENTAL_UNITS,
        # Class III requires single-family AND owner-occupied, so ANY rental housing
        # falls to Class II — an apartment building and a rented detached house alike.
        # Threshold 1, unlike Tennessee's 2.
        rental_unit_threshold=1,
        residential=0.10,
        commercial=0.20,
        authority=("Ala. Const. amend. 373 (recompiled as Ala. Const. of 2022, art. XI, "
                   "§ 217); Ala. Code § 40-8-1"),
        verified="2026-07-31",
        notes=("Class III (10%) is 'all agricultural, forest, and single-family, "
               "owner-occupied residential property ... and historic buildings and "
               "sites'; Class II (20%) is 'all property not otherwise classified'. "
               "Verified against the Alabama Department of Revenue's published class "
               "table. UNDER-CORRECTS: Alabama also grants a homestead exemption on "
               "Class III, which depresses the observed owner-occupied rate further, so "
               "the true gap exceeds 2.0x. Safe direction."),
    ),
    "MS": ClassificationRule(
        usps="MS",
        rule_type=RULE_ASSESSMENT,
        threshold_basis=BASIS_RENTAL_UNITS,
        rental_unit_threshold=1,
        residential=0.10,
        commercial=0.15,
        authority="Miss. Const. art. 4, § 112; Miss. Code Ann. § 27-35-4",
        verified="2026-07-31",
        notes=("Class I (10%) is 'single-family, owner-occupied, residential real "
               "property'; Class II (15%) is 'all other real property, except for real "
               "property included in Class I or IV'. Same single-family-AND-owner-"
               "occupied test as Alabama, so the same threshold of 1. UNDER-CORRECTS "
               "for the same homestead-exemption reason."),
    ),
    "KY": ClassificationRule(
        usps="KY",
        rule_type=RULE_UNIFORM,
        authority="Ky. Const. § 172; Ky. Rev. Stat. § 132.020",
        verified="2026-07-31",
        notes=("No classification of real property. Ky. Const. § 172 requires all "
               "property be assessed at fair cash value, which the General Assembly has "
               "confirmed means 100%, and the KRS 132.020 state real property rate does "
               "not distinguish residential from commercial; local district rates apply "
               "uniformly within a district. FOUND AND REJECTED: the Ky. Const. § 170 "
               "homestead exemption for owners 65+ or totally disabled — an exemption "
               "keyed to owner characteristics rather than a property class, so it falls "
               "under the documented exclusion rule."),
    ),
    # ── South Atlantic ────────────────────────────────────────────────────────
    "SC": ClassificationRule(
        usps="SC",
        rule_type=RULE_ASSESSMENT,
        threshold_basis=BASIS_RENTAL_UNITS,
        rental_unit_threshold=1,
        residential=0.04,
        commercial=0.06,
        authority=("S.C. Code Ann. § 12-43-220(c), (e), § 12-37-220(B)(47); "
                   "S.C. Const. art. X, § 1"),
        verified="2026-08-01",
        notes=("§ 12-43-220(c) gives a 4% ratio to an owner-occupied legal residence; all "
               "other real property is 6%. Tenure-based like Alabama and Mississippi, so "
               "threshold 1. 1.50 IS THE RIGHT FIGURE, and an earlier note here claiming "
               "it under-corrects was wrong — recorded because the wrong reading is the "
               "tempting one. South Carolina also exempts owner-occupied legal residences "
               "from school OPERATING millage, so on a TOTAL tax bill a rental really does "
               "pay more than 1.5x an owner. But this dimension nets school taxes out of "
               "both sides and applies the multiplier to the NON-SCHOOL rate, where the "
               "ratio is 0.06/0.04 = 1.5 exactly: the observed owner rate is the base for "
               "both legs, so the exemption changes that base's LEVEL and cancels out of "
               "the RATIO. Michigan's Principal Residence Exemption is the same shape and "
               "correctly yields no correction at all. THE REAL RESIDUAL IS ELSEWHERE: "
               "region_context nets a county-wide school_tax_share off an owner-occupied "
               "ACS rate that has already lost its school operating component, which "
               "over-removes and understates non-school revenue for every South Carolina "
               "parcel, owner and rental alike. That is a revenue-model issue, not a "
               "classification one, and is logged in "
               "research/infrastructure-burden-research.md."),
    ),
    "WV": ClassificationRule(
        usps="WV",
        rule_type=RULE_RATE,
        threshold_basis=BASIS_RENTAL_UNITS,
        rental_unit_threshold=1,
        # Class II vs Class III/IV maximum regular levy rates, county leg (cents per
        # $100). The ratio is what matters, not the absolute cents — school is 45.90 vs
        # 91.80, the same 2.0x. All classes are assessed at 60% of value, so the rate is
        # the ONLY thing that differs. This is the first RULE_RATE jurisdiction.
        residential=0.2860,
        commercial=0.5720,
        authority=("W. Va. Const. art. X, § 1b; W. Va. Code § 11-8-6 et seq.; West "
                   "Virginia Tax Division, Property Tax Rates (maximum regular levy "
                   "rates by class)"),
        verified="2026-08-01",
        notes=("Class II is 'owner-occupied residential property used exclusively for "
               "residential purposes and all farm land used for agricultural purposes by "
               "its owner or bona fide tenant'; Class III is everything else outside a "
               "municipality and Class IV everything else inside. W. Va. Code § 11-8-6's "
               "aggregate caps (50c/$1/$1.50/$2) look like 1.5x for Class III, but those "
               "are ceilings across ALL levying bodies; the per-body maximum rates are "
               "2.0x for both county (28.60 -> 57.20) and school (45.90 -> 91.80), which "
               "are the bulk of any bill. UNDER-CORRECTS inside municipalities, where the "
               "Class IV municipal leg is 4x rather than 2x."),
    ),
    "FL": ClassificationRule(
        usps="FL",
        rule_type=RULE_UNIFORM,
        authority=("Fla. Const. art. VII, § 4(d), (g), (h), § 6; Fla. Stat. §§ 193.155, "
                   "193.1554, 196.031"),
        verified="2026-08-01",
        notes=("Just valuation applies uniformly; there is no class for rental property. "
               "FOUND AND REJECTED: the homestead exemption (§ 196.031) and the split "
               "assessment-increase caps — 3% for homestead (art. VII, § 4(d)) versus 10% "
               "for non-homestead (§ 4(g) for residential of nine units or fewer, § 4(h) "
               "for everything else). Those produce a large and growing owner/rental gap, "
               "but it is keyed to time in ownership and is value-dependent rather than a "
               "fixed class ratio, so a constant multiplier would misstate it. Logged as "
               "a roadmap item, not encoded here."),
    ),
    "GA": ClassificationRule(
        usps="GA",
        rule_type=RULE_UNIFORM,
        authority="Ga. Code Ann. § 48-5-7(a), § 48-5-44, § 48-5-44.2; Ga. Const. art. VII, § I, ¶ III",
        verified="2026-08-01",
        notes=("§ 48-5-7(a) assesses all taxable tangible property at 40% of fair market "
               "value. Every enumerated exception is use-based (agricultural, historic, "
               "conservation, timberland); none distinguishes owner-occupied from rental, "
               "and the constitution leaves no room for a rental-real-property class. "
               "FOUND AND REJECTED: the § 48-5-44 homestead exemption and the § 48-5-44.2 "
               "statewide floating homestead exemption."),
    ),
    "MD": ClassificationRule(
        usps="MD",
        rule_type=RULE_UNIFORM,
        authority="Md. Code, Tax-Prop. §§ 8-101, 8-103(c), 6-302(b), 9-105",
        verified="2026-08-01",
        notes=("§ 6-302(b)(1) requires 'a single county property tax rate for all real "
               "property subject to county property tax', and the § 8-101 subclasses are "
               "use-based with no tenure subclass. FOUND AND REJECTED: the § 9-105 "
               "Homestead Property Tax Credit, which caps assessment growth for a "
               "homeowner's principal residence only — a credit, not a class."),
    ),
    "NC": ClassificationRule(
        usps="NC",
        rule_type=RULE_UNIFORM,
        authority="N.C. Gen. Stat. § 105-283, § 105-277; N.C. Const. art. V, § 2(2)",
        verified="2026-08-01",
        notes=("§ 105-283 appraises all property at true value in money with no tenure "
               "distinction, and the only § 105-277 classes are solar systems and private "
               "water company property. N.C. Const. art. V, § 2(2) forecloses a local "
               "option outright: 'Only the General Assembly shall have the power to "
               "classify property for taxation, which power shall be exercised only on a "
               "State-wide basis and shall not be delegated.' The elderly/disabled "
               "exclusions are age- and income-gated, not a general owner-occupied "
               "preference."),
    ),
    "VA": ClassificationRule(
        usps="VA",
        rule_type=RULE_UNIFORM,
        authority="Va. Const. art. X, § 1; Va. Code § 58.1-3201, § 58.1-3221.3",
        verified="2026-08-01",
        notes=("Uniform assessment at 100% of fair market value. Virginia DOES permit "
               "some locality-level real-property classification, which made this look "
               "like a local-option case — but § 58.1-3221.3, the only one with rate "
               "consequences, EXPRESSLY EXCLUDES rental housing: 'all residential uses "
               "and all multifamily residential uses, including ... apartments, or homes "
               "in a subdivision when leased on a unit by unit basis'. So a locality "
               "levying the extra commercial/industrial transportation rate cannot apply "
               "it to apartments. Uniform, not local option."),
    ),
    "DE": ClassificationRule(
        usps="DE",
        rule_type=RULE_UNIFORM,
        authority="Del. Code tit. 9, § 8306 (as amended by HB 62, 2023); tit. 9, ch. 83",
        verified="2026-08-01",
        notes=("No state property tax; counties assess at fair market value as of the "
               "county base year, now on a five-year reassessment cycle after the 2020 "
               "school-funding litigation. Title 9 ch. 83 differentiates improved from "
               "unimproved land and grants agricultural use-value, but has no tenure "
               "classification. The senior school property tax credit is age-gated, not a "
               "general owner-occupied preference."),
    ),
    # ── West South Central ────────────────────────────────────────────────────
    #
    # All four are uniform, including Louisiana — see its notes. This is the first
    # division that adds no correction at all.
    "LA": ClassificationRule(
        usps="LA",
        rule_type=RULE_UNIFORM,
        authority="La. Const. art. VII, § 18(A), (B), § 20; La. Admin. Code tit. 61, § V-101",
        verified="2026-08-01",
        notes=("Art. VII, § 18(B) does split 10% from 15%, and the rollout memo predicted "
               "that made Louisiana a correcting state. It does not. The five classes are "
               "land 10%, IMPROVEMENTS FOR RESIDENTIAL PURPOSES 10%, electric cooperative "
               "15%, public service 25%, other property 15% — a USE test carrying no "
               "tenure or unit-count qualifier, so an apartment building is an improvement "
               "used for residential purposes and sits in the 10% class beside a detached "
               "house. The Tax Commission's own rule at LAC 61:V-101 reproduces the same "
               "five classes and adds no tenure test. FOUND AND REJECTED: the art. VII, "
               "§ 20 homestead exemption ($7,500 of assessed value, $75,000 of market "
               "value, owner-occupied only) — which is where those Tax Commission rules "
               "DO separate owner from renter, exempting the owner-occupied part of an "
               "income-producing property but not the rented part — and the special "
               "assessment level, which is age-, disability- and "
               "income-gated. CAVEAT: Louisiana assessors colloquially call apartment "
               "buildings 'commercial', and no case or AG opinion squarely construing "
               "'improvements for residential purposes' as to apartments was found. The "
               "text has no tenure hook for the other reading, and uniform is the "
               "under-correcting choice, so text and the governing principle agree."),
    ),
    "TX": ClassificationRule(
        usps="TX",
        rule_type=RULE_UNIFORM,
        authority="Tex. Const. art. VIII, § 1(a), (b); Tex. Tax Code § 11.13, § 23.23, § 23.231",
        verified="2026-08-01",
        notes=("Art. VIII, § 1(a) is the flat command that 'taxation shall be equal and "
               "uniform', and § 1(b) taxes all real property in proportion to its value. "
               "Texas has no property classes at all. FOUND AND REJECTED: the § 11.13 "
               "residence-homestead exemption, the § 23.23 10% homestead appraisal cap, "
               "and the § 23.231 20% circuit-breaker limitation on non-homestead real "
               "property valued at $5M or less. The last of those NARROWS the owner/rental "
               "gap rather than widening it, which is exactly why a fixed class multiplier "
               "cannot represent this regime. Logged as a roadmap item, not encoded."),
    ),
    "OK": ClassificationRule(
        usps="OK",
        rule_type=RULE_UNIFORM,
        authority="Okla. Const. art. X, § 8(A)(2), (B), § 8B, § 8C",
        verified="2026-08-01",
        notes=("§ 8(A)(2) assesses real property at 11%-13.5% of fair cash value, and "
               "§ 8(B) fixes ONE such percentage per county for real property, so the "
               "art. X use categories (agricultural, residential, commercial/industrial) "
               "drive valuation rather than the ratio, and none of them turns on tenure. "
               "FOUND AND REJECTED: the § 8B annual valuation caps, 3% for homestead and "
               "agricultural against 5% for everything else, and the § 8C senior "
               "valuation freeze, which is age- and income-gated."),
    ),
    "AR": ClassificationRule(
        usps="AR",
        rule_type=RULE_UNIFORM,
        authority="Ark. Const. art. 16, § 5, amend. 79; Ark. Code Ann. § 26-26-303",
        verified="2026-08-01",
        notes=("Art. 16, § 5 requires taxation 'equal and uniform throughout the State', "
               "and § 26-26-303 assesses all real property at 20% of appraised value with "
               "no tenure class. FOUND AND REJECTED: the amendment 79 homestead property "
               "tax credit ($500, rising to $600 for 2026 bills) and its split "
               "assessed-value caps, 5% a year for a homestead against 10% for all other "
               "real property. Same shape as Florida — a real owner/rental gap driven by "
               "a cap rather than a class ratio."),
    ),
    # ── Middle Atlantic ───────────────────────────────────────────────────────
    "NY": ClassificationRule(
        usps="NY",
        rule_type=RULE_EFFECTIVE,
        local_option=True,
        sub_state=dict.fromkeys(
            # The five boroughs. New York City is the only assessing unit whose class
            # system this table can resolve; see the notes for why the rest of the state
            # cannot be resolved at county granularity.
            ("36005", "36047", "36061", "36081", "36085"),
            ClassificationRule(
                usps="NY",
                rule_type=RULE_EFFECTIVE,
                threshold_basis=BASIS_DWELLING_UNITS,
                # RPTL § 1805(2) shields class two parcels with FEWER THAN 11 residential
                # units behind the same kind of growth cap class one gets (8%/yr, 30% over
                # five years). The city's own ETR study shows that shield working: small
                # rentals pay LESS than houses. So 11 is not a chosen breakpoint, it is
                # the statutory line where the correction actually begins.
                rental_unit_threshold=11,
                effective_multiplier=1.54 / 0.85,
                authority=("N.Y. Real Prop. Tax Law § 1802 (class definitions), § 1805 "
                           "(assessment caps); NYC Advisory Commission on Property Tax "
                           "Reform, Preliminary Report (2020), Figure 2 and Table 15"),
                verified="2026-08-01",
                notes=("Class one is 1-3 family residential; class two is all other "
                       "residential, so a rental building of four or more units is class "
                       "two. The NAIVE statutory multiplier is 4.70x — class one is "
                       "assessed at 6% of value and taxed at 19.843%, class two at 45% "
                       "and 12.439% (FY2026) — and encoding that would OVER-CORRECT by "
                       "roughly 2.6x. The city's own commission explains why: DOF's "
                       "published class two 'market value' is an income-capitalization "
                       "figure well below sales-based value, so ETRs computed on DOF "
                       "values 'considerably overstated the disparity'. Recomputed on a "
                       "common sales-based denominator (FY2019 median ETR per $100): "
                       "class one 1-3 family $0.85, class two small rentals $0.75, class "
                       "two large rentals $1.54, condos $0.63, coops $0.88. This model's "
                       "denominator is an ACS self-reported market value, which is the "
                       "sales-based concept, so $1.54/$0.85 = 1.81x is the matching "
                       "figure. The Lincoln Institute 50-state study puts the same ratio "
                       "at 2.55x; 1.81 is the under-correcting choice of the two. "
                       "UNDER-CORRECTS in Manhattan, where 1-3 family homes pay a $0.41 "
                       "median ETR against $1.02 on Staten Island."),
            ),
        ),
        authority=("N.Y. Real Prop. Tax Law § 1801 (special assessing units), § 1802; "
                   "§ 1903 (homestead/non-homestead, other assessing units)"),
        verified="2026-08-01",
        notes=("New York classifies BELOW the state level, in two separate regimes, which "
               "is why this is local_option with only New York City resolved. (1) RPTL "
               "art. 18 gives special assessing units — assessing units of 1,000,000 or "
               "more, meaning New York City and Nassau County — a four-class system. (2) "
               "RPTL art. 19 § 1903 lets any other approved assessing unit split a "
               "homestead from a non-homestead class, but only by local law, only after a "
               "revaluation, and one assessing unit at a time. A county contains many "
               "assessing units that may each choose differently, so art. 19 is NOT "
               "resolvable at the county granularity this table keys on, and towns that "
               "adopted it are under-corrected. NASSAU COUNTY (36059) IS DEFERRED: it is "
               "a special assessing unit under the same class definitions, but its "
               "assessment ratios and class rates differ from the city's and no "
               "sales-based ETR study comparable to the NYC commission's was found, so "
               "its multiplier would be a guess."),
    ),
    "NJ": ClassificationRule(
        usps="NJ",
        rule_type=RULE_UNIFORM,
        authority="N.J. Const. art. VIII, § 1, ¶ 1(a); N.J.S.A. 54:4-2.25, 54:4-23",
        verified="2026-08-01",
        notes=("¶ 1(a) requires assessment 'by uniform rules' and that all real property "
               "be assessed 'according to the same standard of value', which § 54:4-2.25 "
               "fixes as true value. The sole constitutional exception is agricultural "
               "and horticultural land, not tenure. Apartments are valued by income "
               "capitalization, but that is an appraisal METHOD reaching the same "
               "standard of value, not a separate class. FOUND AND REJECTED: the ANCHOR "
               "benefit and the senior freeze, both rebates paid outside the assessment."),
    ),
    "PA": ClassificationRule(
        usps="PA",
        rule_type=RULE_UNIFORM,
        authority=("Pa. Const. art. VIII, § 1; Valley Forge Towers Apartments N, LP v. "
                   "Upper Merion Area Sch. Dist., 163 A.3d 962 (Pa. 2017); 53 Pa. Stat. "
                   "§ 8583 (homestead exclusion)"),
        verified="2026-08-01",
        notes=("The Uniformity Clause forecloses classification of real property, and "
               "Valley Forge Towers is squarely about rental housing: a school district "
               "appealed only apartment-complex assessments and not single-family homes, "
               "and the Supreme Court held that unconstitutional because 'all property in "
               "a taxing district is a single class' and sub-classifications may not be "
               "treated disparately. Pennsylvania therefore cannot enact the kind of rule "
               "this table encodes. FOUND AND REJECTED: the Act 1 homestead/farmstead "
               "exclusion, which is an exclusion from assessed value for owner-occupied "
               "homes rather than a class."),
    ),
    # ── East North Central ────────────────────────────────────────────────────
    #
    # All five uniform. Two of them looked like corrections until the primary source was
    # read: Illinois (Cook's ordinance) and Ohio (the HB 920 class split).
    "IL": ClassificationRule(
        usps="IL",
        rule_type=RULE_UNIFORM,
        authority=("35 ILCS 200/9-145; Cook County Assessor, Definitions for the "
                   "Classifications of Real Property (class-code schedule)"),
        verified="2026-08-01",
        notes=("The rollout memo predicted Illinois as the second local_option case, on "
               "Cook County's classification ordinance. IT IS NOT. Cook's own class-code "
               "schedule groups major classes 1, 2 and 3 together under the heading "
               "'RESIDENTIAL ASSESSMENT CLASSES (10% level of assessment)' — class 2 is "
               "houses, condos and buildings of six units or fewer, class 3 is rental "
               "apartment buildings of seven or more units, and BOTH are 10%. The split "
               "that matters in Cook is residential against commercial (class 5A, 25%), "
               "and rental housing sits on the residential side of it. Class 3 was higher "
               "historically and was reduced by ordinance in stages to 10% by 2011, so an "
               "older secondary source shows a differential that no longer exists. The "
               "Assessor's three-year equalization study puts the REALISED levels at 9.15% "
               "for class 2 against 7.89% for class 3, so in practice Cook apartments are "
               "assessed below houses and even the observed gap runs the wrong way for a "
               "correction. Outside Cook, 35 ILCS 200/9-145 is a uniform 33-1/3%."),
    ),
    "OH": ClassificationRule(
        usps="OH",
        rule_type=RULE_UNIFORM,
        authority=("Ohio Const. art. XII, § 2a; Ohio Rev. Code § 5713.03, § 5713.041, "
                   "§ 319.301, § 323.152"),
        verified="2026-08-01",
        notes=("Ohio does have a real two-class system — art. XII, § 2a permits separate "
               "HB 920 tax-reduction factors for class I and class II — but § 5713.041 "
               "draws the line by USE, not tenure: 'Lands and improvements thereon used "
               "for residential or agricultural purposes shall be classified as "
               "residential/agricultural real property, and all other lands and "
               "improvements thereon shall be classified as nonresidential/agricultural.' "
               "An apartment building is used for residential purposes, so it is class I "
               "alongside a detached house. Same shape as Louisiana. Assessment is a "
               "uniform 35% of true value. FOUND AND REJECTED: the § 323.152 2.5% "
               "owner-occupancy credit and the homestead exemption, both credits."),
    ),
    "MI": ClassificationRule(
        usps="MI",
        rule_type=RULE_UNIFORM,
        authority="Mich. Const. art. IX, §§ 3, 31; Mich. Comp. Laws § 211.7cc, § 211.34d",
        verified="2026-08-01",
        notes=("Uniform assessment at 50% of true cash value, with no tenure class. "
               "FOUND AND REJECTED, and the most interesting rejection in the table: the "
               "§ 211.7cc Principal Residence Exemption relieves an owner-occupied "
               "principal residence of up to 18 mills, and multi-family and rental "
               "property do not qualify — a large, genuinely tenure-based differential. "
               "It still warrants no correction here, for a sharper reason than the "
               "general exclusion rule: those 18 mills are a SCHOOL OPERATING levy, and "
               "this dimension nets school taxes out of BOTH sides (non-school cost model, "
               "school_tax_share on the revenue side). The gap is real but sits outside "
               "what the fiscal ratio measures. This case RESOLVED an open question against "
               "South Carolina, whose note used to claim that an owner-occupied exemption "
               "from school operating millage made its 1.50x under-correct. It does not: "
               "the exemption moves the level of the observed owner rate, which is the "
               "base for both legs, so it cancels out of the ratio. Michigan is the clean "
               "case because it has no class split at all to confuse the issue. What both "
               "states DO share is a genuine revenue-model problem — a county-wide "
               "school_tax_share netted off an owner-occupied rate that has already lost "
               "its school component — logged in "
               "research/infrastructure-burden-research.md."),
    ),
    "IN": ClassificationRule(
        usps="IN",
        rule_type=RULE_UNIFORM,
        authority="Ind. Const. art. 10, § 1(f); Ind. Code § 6-1.1-20.6",
        verified="2026-08-01",
        notes=("FOUND AND REJECTED: the constitutional circuit-breaker caps — 1% of gross "
               "assessed value for an owner-occupied homestead, 2% for other residential "
               "and agricultural, 3% for commercial. These bind hard (statewide credits "
               "exceeded $1.2 billion in 2025), so this is the least comfortable uniform "
               "record in the table. STRUCTURALLY DIFFERENT from Florida's and Texas's "
               "caps, which limit the GROWTH of assessed value and so depend on holding "
               "period and appreciation. Indiana caps tax as a share of CURRENT assessed "
               "value, by class, with no time dependence: where the local gross rate "
               "exceeds 2% the owner/rental ratio is exactly 2.0, where it is under 1% it "
               "is exactly 1.0, and in between it is the gross rate over 1%. That makes "
               "Indiana the most tractable member of the cap roadmap item, not a Save Our "
               "Homes lookalike. It is unencodable today only for want of county GROSS "
               "rates: the bundled ACS effective_tax_rate is the owner-occupied rate, "
               "already capped, so the gross rate cannot be recovered from it."),
    ),
    "WI": ClassificationRule(
        usps="WI",
        rule_type=RULE_UNIFORM,
        authority="Wis. Const. art. VIII, § 1; Wis. Stat. § 70.32",
        verified="2026-08-01",
        notes=("The uniformity clause forecloses classification of real property as "
               "firmly as Pennsylvania's does: for direct taxation under the rule of "
               "uniformity there can be but one constitutional class, and the burden must "
               "be borne as nearly as practicable by all property according to value. "
               "§ 70.32 assesses real property at full value with no tenure distinction. "
               "FOUND AND REJECTED: the lottery and gaming credit, available only for an "
               "owner-occupied primary residence."),
    ),
    # DC is deliberately NOT encoded. It restructured its classes for tax year 2025 (a
    # new Class 1A / 1B split), and sources conflict on where a multifamily rental
    # building lands: one reading keeps residential improved property in Class 1A
    # regardless of unit count, another pushes anything above Class 1B's two-unit limit
    # into the Class 2 commercial catch-all. Those give very different multipliers, so
    # under the sourcing standard DC stays unencoded rather than guessed. See
    # research/property-tax-classification-research.md.
}


def rule_for(state: str | None) -> ClassificationRule | None:
    """The rule for a USPS code, or ``None`` if the state has not been researched."""
    return CLASSIFICATION_RULES.get((state or "").strip().upper())


def rental_unit_count(units: int, *, owner_occupied: bool | None = None,
                      separately_parceled: bool | None = None) -> int:
    """Rental units on a parcel — the count that drives classification.

    ``units`` is the number of dwelling units on the parcel. ``owner_occupied`` says whether
    the owner lives in one of them; ``None`` means unknown, which resolves to the ACS-backed
    default (a multi-unit building is rental, a single home is owner-occupied). One unit is
    subtracted when the owner occupies one, which is what keeps an owner-occupied duplex
    residential under AG Op. 25-016.

    ``separately_parceled=True`` means each unit is its own tax parcel — a condominium — so
    no parcel holds more than one rental unit however large the building is. The unit count
    reaching this module comes from a *structure* record (NSI), which cannot tell a condo
    tower from a rental tower, so this is the caller's way of saying which it is.
    """
    units = max(int(units or 1), 1)
    if separately_parceled:
        units = 1
    if owner_occupied is None:
        owner_occupied = not (units > 1 and MULTIUNIT_RENTAL_DEFAULT)
    return max(units - 1, 0) if owner_occupied else units


def _reclassified(rule: ClassificationRule | None, units: int, *,
                  owner_occupied: bool | None = None,
                  separately_parceled: bool | None = None,
                  county_fips: str | None = None) -> ClassificationRule | None:
    """The rule to apply if this parcel is reclassified, else ``None``.

    Resolves local-option states through ``sub_state`` first: a state whose classification
    is set below the state level yields nothing unless the parcel's county carries its own
    entry.
    """
    if rule is None or rule.rule_type == RULE_UNIFORM:
        return None
    if rule.local_option:
        key = str(county_fips).strip().zfill(5) if county_fips else None
        rule = rule.sub_state.get(key) if key else None
        if rule is None:
            return None
    threshold = rule.rental_unit_threshold
    if not threshold:
        return None
    if rule.threshold_basis == BASIS_DWELLING_UNITS:
        count = 1 if separately_parceled else max(int(units or 1), 1)
    else:
        count = rental_unit_count(units, owner_occupied=owner_occupied,
                                  separately_parceled=separately_parceled)
    return rule if count >= threshold else None


def classified_assess_ratio(state: str | None, units: int, *,
                            owner_occupied: bool | None = None,
                            separately_parceled: bool | None = None,
                            county_fips: str | None = None) -> float | None:
    """The commercial assessment ratio, if this parcel is classified commercial.

    For the **statutory** path only — a caller applying a real assessment ratio against a
    real millage. Returns ``None`` in every other case: no researched rule, a ``RULE_RATE``
    state (where the ratio does not differ, only the millage does), or a parcel that stays
    residential. Returning ``None`` rather than the residential ratio is deliberate — it
    makes this a strictly *additive* correction that can only move parcels the statute
    actually reclassifies, so a caller supplying its own assessment basis is never silently
    overridden for ordinary housing.
    """
    rule = _reclassified(rule_for(state), units, owner_occupied=owner_occupied,
                         separately_parceled=separately_parceled, county_fips=county_fips)
    if rule is None or rule.rule_type != RULE_ASSESSMENT:
        return None
    return rule.commercial


def classification_multiplier(state: str | None, units: int, *,
                              owner_occupied: bool | None = None,
                              separately_parceled: bool | None = None,
                              county_fips: str | None = None) -> float:
    """How much more this parcel pays than an owner-occupied home of the same value.

    For the **national** path — a caller applying an ACS observed effective rate, which is
    computed over owner-occupied homes and therefore already carries the residential class
    in its denominator. Returns exactly ``1.0`` unless the parcel is reclassified, so an
    unresearched state, a uniform state, an unresolved local-option state, and ordinary
    housing all leave the rate untouched.
    """
    rule = _reclassified(rule_for(state), units, owner_occupied=owner_occupied,
                         separately_parceled=separately_parceled, county_fips=county_fips)
    return 1.0 if rule is None else rule.multiplier()


def classification_for(state: str | None, units: int, *,
                       owner_occupied: bool | None = None,
                       separately_parceled: bool | None = None,
                       county_fips: str | None = None) -> dict:
    """Reporting view of the classification decision — always a dict, never ``None``.

    The two computational accessors above return ``None``/``1.0`` because absence *is* the
    signal there; this one honors the always-return-a-dict convention the crosswalk loaders
    use, and carries the provenance a label or a coverage report needs.
    """
    rule = rule_for(state)
    applied = _reclassified(rule, units, owner_occupied=owner_occupied,
                            separately_parceled=separately_parceled, county_fips=county_fips)
    researched = rule is not None
    return {
        "state": (state or "").strip().upper() or None,
        "rule_type": rule.rule_type if researched else None,
        "researched": researched,
        "applied": applied is not None,
        "multiplier": applied.multiplier() if applied is not None else 1.0,
        "assess_ratio": (applied.commercial
                         if applied is not None and applied.rule_type == RULE_ASSESSMENT
                         else None),
        "authority": applied.authority if applied is not None else (
            rule.authority if researched else None),
        "verified": rule.verified if researched else None,
        "local_option": bool(rule.local_option) if researched else False,
        "label": (f"{rule.usps} {rule.rule_type}" if researched
                  else "no researched classification rule"),
    }


def unresearched_jurisdictions() -> list[str]:
    """Scored jurisdictions with no classification record yet, sorted."""
    return sorted(SCORED_JURISDICTIONS - set(CLASSIFICATION_RULES))


def active_basis() -> tuple[str, ...]:
    """Fingerprint of the jurisdictions currently carrying a correction, e.g.
    ``("TN:1.60",)``.

    ``score/all_dimensions.INFRA_XS_BASIS`` records this as of the last recalibration, and
    a test asserts the two match — so adding a state without re-anchoring the national
    breakpoints fails CI instead of silently mis-scoring every parcel in the country.
    A sorted tuple rather than a hash, so the diff is legible as a changelog.

    Sub-state rules are walked too, keyed ``USPS/county_fips``. A local-option state's
    container carries no legs of its own, so counting only top-level rules would let New
    York City enter the reference distribution while the fingerprint stayed unchanged —
    exactly the silent mis-scoring this guard exists to prevent.
    """
    entries = []
    for usps, rule in CLASSIFICATION_RULES.items():
        if rule.rule_type != RULE_UNIFORM and rule.multiplier() > 1.0:
            entries.append(f"{usps}:{rule.multiplier():.2f}")
        for county_fips, sub in rule.sub_state.items():
            if sub.rule_type != RULE_UNIFORM and sub.multiplier() > 1.0:
                entries.append(f"{usps}/{county_fips}:{sub.multiplier():.2f}")
    return tuple(sorted(entries))
