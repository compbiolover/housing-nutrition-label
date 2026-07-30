"""Property-tax **classification** — the assessment ratio a parcel is taxed on.

Most states assess all housing at one ratio, so the appraised value and the
effective tax rate are enough to estimate a parcel's tax bill. A minority use a
*split roll*: they put rental housing above some unit count into the commercial
class and assess it at a higher fraction of value. Where that happens, applying a
single-family assessment ratio to an apartment building understates its property-tax
revenue — and therefore understates its Infrastructure Burden fiscal ratio.

Tennessee (the pilot state) is one of those states, and the rule is constitutional
rather than merely statutory.

Tennessee
---------
**Tenn. Const. art. II, § 28** sets residential assessment at 25% of value,
"provided that residential property containing two (2) or more rental units is
hereby defined as industrial and commercial property." That is codified at
**Tenn. Code Ann. § 67-5-501(11)**, which defines residential property as "all real
property that is used, or held for use, for dwelling purposes and that contains not
more than one (1) rental unit," and states that property "that contains two (2) or
more rental units, is defined and shall be classified as 'industrial and commercial
property'" (see also § 67-5-501(4)). **Tenn. Code Ann. § 67-5-801** sets the rates:
residential 25%, industrial and commercial 40%.

The operative count is **rental units, not dwelling units**. Tennessee AG Opinion
No. 25-016 (Aug. 25, 2025), "Classification of Residential Property," applies it:
a single-family home rented long-term stays residential (one rental unit), and an
owner-occupied duplex stays residential (the owner's half is not a rental unit).
The same opinion notes there is no bright-line physical test — in *Spring Hill,
L.P. v. State Board of Equalization*, No. M2001-02683-COA-R3-CV, 2003 WL 23099679,
at *17–*18 (Tenn. Ct. App. Dec. 31, 2003), 44 detached single-family homes on
separate lots were classified industrial and commercial because they were one
commonly owned and managed rental development.

So a 157-unit rental apartment building in Memphis is assessed at 40%, not 25% —
1.6x the revenue the model previously credited it. A 157-unit *condominium* building
is not: each unit is its own parcel containing at most one rental unit.

Scope and honesty about it
--------------------------
Only Tennessee is encoded here, because only Tennessee has been researched to
primary sources for this repo. Every other state returns ``None`` — "no
classification adjustment known" — and the caller keeps whatever ratio it already
used. That is a real coverage gap, not a claim that other states lack split rolls;
several do, with different thresholds and different ratios. Extending this table
means reading each state's constitution or code, one at a time, and it should not be
guessed at from a secondary source.

The national (non-Shelby) path has a related and *unfixed* limitation: it uses an
ACS-derived effective tax rate built from **owner-occupied** homes (B25103 median
taxes paid ÷ B25077 median value), so in any split-roll state that rate understates
what a rental apartment building actually pays. Applying the Tennessee uplift there
would double-count, so ``classified_assess_ratio`` is applied only where the
underlying rate is a statutory ratio rather than an observed owner-occupied
effective rate. See ``enrich/region_context.py``.
"""

from __future__ import annotations

# Tenn. Code Ann. § 67-5-801 assessment rates.
TN_RESIDENTIAL_ASSESS_RATIO = 0.25
TN_COMMERCIAL_ASSESS_RATIO = 0.40

# Tenn. Const. art. II, § 28 / Tenn. Code Ann. § 67-5-501(11): two or more rental
# units on a parcel puts it in the industrial-and-commercial class.
TN_COMMERCIAL_RENTAL_UNIT_THRESHOLD = 2

# States with a researched split-roll rule for multi-unit rental housing.
# state USPS code → (threshold in rental units, residential ratio, commercial ratio)
SPLIT_ROLL_STATES = {
    "TN": (TN_COMMERCIAL_RENTAL_UNIT_THRESHOLD,
           TN_RESIDENTIAL_ASSESS_RATIO,
           TN_COMMERCIAL_ASSESS_RATIO),
}

# Default tenure assumption for a multi-unit building when the caller doesn't say.
# ACS 2024 5-yr table B25032 (tenure by units in structure, US): 86.1% of units in
# 2+ unit structures are renter-occupied, rising to 87.9% in 5+ unit structures. So
# treating a multi-unit building as rental is right for ~6 of every 7 of them; a
# condominium or owner-occupied duplex is the documented exception and callers can
# say so explicitly.
MULTIUNIT_RENTAL_DEFAULT = True


def rental_unit_count(units: int, *, owner_occupied: bool | None = None) -> int:
    """Rental units on a parcel — the count that drives classification.

    ``units`` is the number of dwelling units on the parcel. ``owner_occupied``
    says whether the owner lives in one of them; ``None`` means "unknown", which
    resolves to the ACS-backed default (a multi-unit building is rental; a single
    home is owner-occupied). One unit is subtracted when the owner occupies one,
    which is what makes an owner-occupied duplex residential under AG Op. 25-016.
    """
    units = max(int(units or 1), 1)
    if owner_occupied is None:
        owner_occupied = not (units > 1 and MULTIUNIT_RENTAL_DEFAULT)
    return max(units - 1, 0) if owner_occupied else units


def commercial_assess_ratio(state: str | None, units: int, *,
                            owner_occupied: bool | None = None) -> float | None:
    """The commercial assessment ratio, if this parcel is classified commercial.

    Returns ``None`` in every other case — no researched rule for the state, or the
    parcel stays residential — and the caller keeps the ratio it would otherwise
    have used. Returning ``None`` rather than the residential ratio is deliberate:
    it makes this a strictly *additive* correction that can only move parcels the
    statute actually reclassifies. A caller that supplies its own assessment basis
    (the national path passes ``assess_ratio=1.0`` against an effective tax rate)
    is never silently overridden for ordinary housing.

    ``state`` is a USPS code ("TN"); matching is case-insensitive.
    """
    rule = SPLIT_ROLL_STATES.get((state or "").strip().upper())
    if rule is None:
        return None
    threshold, _residential, commercial = rule
    rentals = rental_unit_count(units, owner_occupied=owner_occupied)
    return commercial if rentals >= threshold else None
