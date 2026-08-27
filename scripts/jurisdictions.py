#!/usr/bin/env python3
"""The jurisdictions the accuracy harness knows about — one registry, two scripts.

``build_benchmark.py`` draws a sample from an assessor and ``measure_accuracy.py``
scores it, and both have to agree on which jurisdictions exist and what each one
is called. They kept that list twice, so adding a third adapter to one of them
would have made the other reject `--jurisdiction` outright or publish a section
headed by its bare key. Neither failure announces itself at the point the mistake
is made — the build succeeds and the measurement is the thing that comes out
wrong.

`scope` is the honest description of what the sample covers, and it is published
verbatim beside the numbers. DC's is not a footnote: a figure drawn from 64% of
the city's stock must not read as "DC".
"""

from __future__ import annotations

JURISDICTIONS = {
    "cook": {
        "source": "Cook County Assessor (Open Data)",
        "label": "Cook County, Illinois",
        "scope": "all residential improvement records",
    },
    "dc": {
        "source": "DC Office of Tax and Revenue (Open Data)",
        "label": "Washington, DC",
        # Named here, not buried. The sample is drawn from the residential CAMA
        # table, so condominium units — a separate table, 61,329 rows against
        # 109,273 residential — are outside it. That is a statement about the
        # benchmark, not about the adapter: the adapter does serve DC condos, by
        # address rather than by coordinate. Until the sample covers them, the
        # published DC figures describe the non-condominium path only, which
        # errs toward understating coverage rather than overstating it.
        "scope": "non-condominium homes only (condos are ~36% of DC's CAMA stock)",
    },
    "dc-condo": {
        "source": "DC Office of Tax and Revenue (Open Data)",
        "label": "Washington, DC — condominiums",
        # The other two thirds of the sentence above. Kept a separate jurisdiction
        # rather than folded into `dc` because the two are not one population
        # measured twice: they come from different CAMA tables, are reached by
        # different lookups (address-and-unit versus point-in-polygon), and the
        # condominium table carries no wall, storey or condition column at all.
        # Averaging them would hide which half a number came from, and the halves
        # do not answer for the same fields.
        "scope": "condominium units only (61,329 of DC's 170,602 CAMA records)",
        # Published beneath `dc` rather than beside it. The two are disjoint halves
        # of one city's stock, and the condominium half is the narrower, more
        # specific claim — a reader looking for "Washington, DC" should find the
        # houses and then the condominiums under them, not two peers that look like
        # two cities. They stay separate measurements because they answer for
        # different fields from different tables; nesting is a statement about how
        # to read them, not a licence to average them.
        "parent": "dc",
    },
}


def ordered() -> list[str]:
    """Registry keys, parents before their own children.

    The page used to emit sections in plain sorted order, which put "dc-condo"
    directly after "dc" by luck of the alphabet. Luck is not an ordering: a
    jurisdiction named "dc-b..." would have landed between a parent and its child
    and split the section in half.
    """
    tops = sorted(k for k, v in JURISDICTIONS.items() if not v.get("parent"))
    out = []
    for key in tops:
        out.append(key)
        out.extend(sorted(k for k, v in JURISDICTIONS.items()
                          if v.get("parent") == key))
    # Anything whose parent is not itself registered would vanish from the page
    # entirely — a measured jurisdiction silently unpublished.
    orphans = sorted(set(JURISDICTIONS) - set(out))
    if orphans:
        raise SystemExit(
            f"{', '.join(orphans)} name a parent that is not registered, so they "
            f"would be measured and never published.")
    return out

#: Display names, derived rather than restated — see the module docstring.
LABELS = {key: cfg["label"] for key, cfg in JURISDICTIONS.items()}
