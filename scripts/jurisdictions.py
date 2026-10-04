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
        # condominium table carries no wall, story or condition column at all.
        # Averaging them would hide which half a number came from, and the halves
        # do not answer for the same fields.
        "scope": "condominium units only (61,329 of DC's 170,602 CAMA records)",
        # Published beneath `dc` rather than beside it. The two are disjoint halves
        # of one city's stock, and the condominium half is the narrower, more
        # specific claim — a reader looking for "Washington, DC" should find the
        # houses and then the condominiums under them, not two peers that look like
        # two cities. They stay separate measurements because they answer for
        # different fields from different tables; nesting is a statement about how
        # to read them, not a license to average them.
        "parent": "dc",
    },
    # Adapter benchmarks (scripts/benchmark_samplers): homes drawn at random from
    # each adapter's own source, the reference read through the adapter at the
    # parcel itself. `sampler` routes build_benchmark.py to that package; `basis`
    # tells the page which kind of reference a section was graded against.
    "nj": {
        "source": "NJOGIS Parcels and MOD-IV Composite of New Jersey",
        "label": "New Jersey",
        "scope": "residential (class 2) parcels in all 21 counties, drawn in "
                 "proportion to each county's housing units",
        "sampler": "adapter", "basis": "adapter", "adapter": "nj",
    },
    "la": {
        "source": "Los Angeles County Office of the Assessor (LA County eGIS parcels)",
        "label": "Los Angeles County, California",
        "scope": "parcels the roll classifies Residential, condominium units "
                 "included and typed with their unit",
        "sampler": "adapter", "basis": "adapter", "adapter": "la",
    },
    "ca": {
        "source": "Contra Costa, San Joaquin and Riverside County Assessors",
        "label": "California — Contra Costa, San Joaquin and Riverside Counties",
        "scope": "residential parcels and condominium units in the three counties, "
                 "drawn in proportion to each county's housing units",
        "sampler": "adapter", "basis": "adapter", "adapter": "ca",
    },
    "sf": {
        "source": "San Francisco Office of the Assessor-Recorder (DataSF secured roll)",
        "label": "San Francisco, California",
        "scope": "residential records (single- and multi-family uses, condominium "
                 "units included) in the latest closed secured roll",
        "sampler": "adapter", "basis": "adapter", "adapter": "sf",
    },
    "nyc": {
        "source": "NYC Department of City Planning MapPLUTO (Department of Finance)",
        "label": "New York City",
        "scope": "tax lots with at least one residential unit in all five boroughs, "
                 "drawn in proportion to each borough's housing units (a "
                 "condominium is one billing lot)",
        "sampler": "adapter", "basis": "adapter", "adapter": "nyc",
    },
    "mo": {
        "source": "Jackson County (MO) Assessment Department Parcel Viewer",
        "label": "Missouri (Jackson County)",
        "scope": "dwelling land-use records (houses, townhouses, condominium units, "
                 "duplexes to apartments) in Jackson County, the one county the "
                 "adapter serves",
        "sampler": "adapter", "basis": "adapter", "adapter": "mo",
    },
    "co": {
        "source": "Denver, Jefferson, Adams, Douglas and Boulder county assessors",
        "label": "Colorado (Denver metro)",
        "scope": "residential parcels (houses, condominium units, townhouses and "
                 "multifamily) in the five Denver-metro counties the adapter serves, "
                 "drawn in proportion to each county's housing units",
        "sampler": "adapter", "basis": "adapter", "adapter": "co",
    },
    "mn": {
        "source": "MetroGIS Regional Parcel Dataset (Metropolitan Council)",
        "label": "Minnesota (Twin Cities metro)",
        "scope": "residential parcels (houses, townhouses, condominium units, "
                 "duplexes to apartments) in the seven metro counties, drawn in "
                 "proportion to each county's housing units",
        "sampler": "adapter", "basis": "adapter", "adapter": "mn",
    },
    "tx": {
        "source": "Texas county appraisal districts (twelve counties' own services)",
        "label": "Texas (twelve largest-county appraisal districts)",
        "scope": "residential accounts (state categories A single-family and "
                 "condominium, B multifamily, M mobile homes) in the twelve counties "
                 "the adapter serves, drawn in proportion to each county's housing "
                 "units",
        "sampler": "adapter", "basis": "adapter", "adapter": "tx",
    },
    "ga": {
        "source": "Fulton, Clayton, Chatham (SAGIS) and Forsyth county parcel layers",
        "label": "Georgia — Fulton, Clayton, Chatham and Forsyth counties",
        "scope": "improved residential parcels in the four counties the adapter "
                 "answers for (19% of Georgia's homes), drawn in proportion to each "
                 "county's housing units",
        "sampler": "adapter", "basis": "adapter", "adapter": "ga",
    },
    "mi": {
        "source": "SEMCOG Building Footprints 2024",
        "label": "Southeast Michigan (SEMCOG's seven counties)",
        "scope": "live single-family, attached-condo and apartment buildings (not "
                 "parcels) in Wayne, Oakland, Macomb, Washtenaw, Livingston, St. Clair "
                 "and Monroe, drawn in proportion to each county's housing units",
        "sampler": "adapter", "basis": "adapter", "adapter": "mi",
    },
    "pdx": {
        "source": "Oregon Metro RLIS Taxlots (Public)",
        "label": "Portland metro, Oregon (Multnomah, Washington, Clackamas)",
        "scope": "residential taxlots (single-family, multi-family and rural "
                 "residential, condominium units included) in all three counties, "
                 "drawn in proportion to each county's housing units",
        "sampler": "adapter", "basis": "adapter", "adapter": "pdx",
    },
    "va": {
        "source": "Chesterfield County Open GIS Data; City of Richmond Assessor",
        "label": "Virginia — Chesterfield County and the City of Richmond",
        "scope": "residential assessment records in Chesterfield County and the City "
                 "of Richmond only, drawn in proportion to each one's housing units",
        "sampler": "adapter", "basis": "adapter", "adapter": "va",
    },
    "ut": {
        "source": "UGRC Land Information Records parcels (Utah county tax rolls)",
        "label": "Utah",
        "scope": "residential parcels with a recorded year built in the 28 counties "
                 "served, one draw per parcel, in proportion to each county's housing "
                 "units",
        "sampler": "adapter", "basis": "adapter", "adapter": "ut",
    },
    "pa": {
        "source": "Montgomery, York, Northampton and Cumberland County (PA) assessment "
                  "parcel layers",
        "label": "Pennsylvania (four counties)",
        "scope": "residential parcels with a recorded year built in Montgomery, York, "
                 "Northampton and Cumberland counties, drawn in proportion to each "
                 "county's housing units",
        "sampler": "adapter", "basis": "adapter", "adapter": "pa",
    },
    "oh": {
        "source": "Ohio county auditors' parcel layers (nine counties)",
        "label": "Ohio (nine counties)",
        "scope": "residential, agricultural and apartment parcels with a recorded "
                 "year built in the nine counties served, drawn in proportion to each "
                 "county's housing units",
        "sampler": "adapter", "basis": "adapter", "adapter": "oh",
    },
    "ind": {
        "source": "Vanderburgh County Assessor tax parcels",
        "label": "Indiana (Vanderburgh County)",
        "scope": "residential, apartment and farmhouse parcels with a recorded year "
                 "built in Vanderburgh County",
        "sampler": "adapter", "basis": "adapter", "adapter": "ind",
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
