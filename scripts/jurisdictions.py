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
        # Named here, not buried: condominium units are a separate CAMA table and
        # cannot be reached from a coordinate, so they are outside what this
        # measures. 61,329 condo rows against 109,273 residential.
        "scope": "non-condominium homes only (condos are ~36% of DC's CAMA stock)",
    },
}

#: Display names, derived rather than restated — see the module docstring.
LABELS = {key: cfg["label"] for key, cfg in JURISDICTIONS.items()}
