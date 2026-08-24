#!/usr/bin/env python3
"""What a county assessor adapter returns, and the vocabulary it must speak.

Why this layer exists
---------------------
Every construction attribute on the label is currently an *area typical* or a
*model*: NSI's occupancy and material are modeled from regional distributions,
and the year built is a census-tract quantile (``data/year_built.py``). None of
them is a measurement of the building on the parcel.

County assessors hold the measurements. There is no national source for them —
``research/parcel-level-data-research.md`` establishes that the best commercial
aggregate carries year built for 67% of parcels and no exterior wall, foundation
or heating at all — so the only route is per-county, and the only sane shape for
per-county work is a registry with one small adapter each.

The contract
------------
An adapter answers one question: *what does the county say is standing at this
point?* It returns an :class:`AssessorRecord` or ``None``, and it must translate
the county's own vocabulary into the label's, because a caller cannot be expected
to know that Cook County writes ``"Full"`` where this codebase writes
``"full-basement"``.

Three rules every adapter follows, and the reasons are not stylistic:

**Fail open, always.** A county portal being slow, rate-limited or reorganised
must never stop a label rendering. Every adapter swallows its own errors and
returns ``None``; the caller then falls back to what it had before, which is
exactly the behaviour that existed before any adapter did.

**Map only what is unambiguous.** Leaving a field ``None`` costs nothing — the
caller falls back to NSI or an area typical — while guessing wrong silently
scores the wrong house. So a value the county records that does not map cleanly
onto this vocabulary is dropped rather than approximated, and the adapter says
in a comment which values it drops and why.

**Nothing is bundled.** These records are queried live and cached in this
process only. See the licence note below.

Licence, and why no county data is committed
--------------------------------------------
Cook County's terms of use (``cookcountyil.gov/terms-use``) provide the data "AS
IS", disclaim every warranty, and grant no explicit right to redistribute a
dataset; the copyright clause that does appear is scoped to images and graphics.
Illinois assessment records are public records, but as
``research/parcel-level-data-research.md`` warns, assessors commonly assert
rights in the *compilation* even where the underlying facts are public.

So this package queries and caches; it never writes a county record into the
repository. That is the two-tier split open question #4 of that memo anticipated
— public-domain data bundled, licensed data cached — and it is also why the
accuracy harness fetches its ground truth on demand instead of committing it.

Adapters also drop owner names, mailing addresses and sale parties on principle,
which removes the most commonly restricted class of field from nearly every
county's terms and keeps PII out of a public repo. Cook County's characteristics
table happens to carry none of them, so here that costs nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

# The label's own vocabularies, restated here so an adapter author has one place
# to look. Sources: simulate/house.py _EDITABLE_FIELDS, enrich/structure.py
# _CONSTRUCTION / _FOUND_TYPE, score/resilience.py EXTWALL_FACTOR / COND_FACTOR.
CONSTRUCTION_VALUES = frozenset({
    "frame", "vinyl", "brick-frame", "brick", "block", "stone", "icf", "sip", "steel",
})
FOUNDATION_VALUES = frozenset({"slab", "crawl", "partial-basement", "full-basement"})
CONDITION_VALUES = frozenset({
    "unsound", "poor", "fair", "average", "good", "excellent",
})

# Fields where an adapter must map a county's own category system onto the
# label's, rather than transcribe a value the county already records in the
# label's terms. A year built and a floor area are numbers the assessor wrote
# down; a wall material and a condition grade are the adapter's reading of a
# different vocabulary, and at least one such reading is knowingly lossy (Cook's
# single "Masonry" category covers the label's brick, block and stone).
#
# The distinction is not cosmetic: it is the difference between "the county
# recorded this" and "the county recorded something we believe means this", and
# the label carries it as a lower confidence on the translated fields so the
# `observed` tag does not claim more than the source supports.
TRANSLATED = frozenset({"construction", "condition"})


@dataclass(frozen=True)
class AssessorRecord:
    """One county's record of the building at a point, in the label's vocabulary.

    Every attribute is optional: a county may publish a year built and nothing
    else, and a partial record is still strictly better than an area typical for
    the fields it does carry. ``source`` carries the attribution that has to
    travel with the value onto the label, and ``parcel_id`` is kept so a reader
    (or a bug report) can trace a value back to the county's own record.
    """

    source: str                      # human-readable, carries attribution
    data_vintage: str                # what the county says this reflects
    parcel_id: str | None = None
    year_built: int | None = None
    sqft: float | None = None
    stories: int | None = None
    construction: str | None = None
    foundation: str | None = None
    condition: str | None = None

    def fields(self) -> dict:
        """The populated construction attributes, as the autofill wants them.

        Only non-None entries, so a caller can merge without having to
        distinguish "the county says nothing" from "the county says zero".
        """
        out = {}
        for name in ("year_built", "sqft", "stories", "construction",
                     "foundation", "condition"):
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        return out

    def __post_init__(self):
        # A typo in an adapter's mapping table would otherwise reach the scorer as
        # an unknown string and be silently treated as neutral — the quiet kind of
        # wrong this codebase keeps finding. Cheap to catch at construction.
        for name, allowed in (("construction", CONSTRUCTION_VALUES),
                              ("foundation", FOUNDATION_VALUES),
                              ("condition", CONDITION_VALUES)):
            value = getattr(self, name)
            if value is not None and value not in allowed:
                raise ValueError(
                    f"{type(self).__name__}.{name}={value!r} is not in the label's "
                    f"vocabulary ({sorted(allowed)}) — an adapter must translate, "
                    f"not pass the county's own wording through")
