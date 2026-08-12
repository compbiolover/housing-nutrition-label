"""The one wording of the label's disclaimer, for every surface that shows it.

A score printed beside somebody's house reads as a verdict on that house. It is
not one: it is what the model expects of a home *like* this one, at this
location, from public data nobody visited the property to collect. That gap is
the whole reason this module exists, and the reason the notice travels *with*
the label rather than living on a Terms page nobody opens — the badge lands on
third-party sites, the payload lands in third-party code, and the CSV lands in
somebody's underwriting spreadsheet, all of them far from anything we control.

So the text lives here, once, and every renderer reads it from here:

* ``simulate.house.label_payload`` puts ``DISCLAIMER`` on the JSON, which the
  CLI's ``--json``, the HTTP API, and ``docs/label-core.js`` all consume;
* ``print_label`` prints it under the terminal card;
* ``badge.py`` draws a short notice onto the SVG, ends the accessible name on
  ``DISCLAIMER_SHORT``, and carries the full text in the image's ``<desc>``.

``docs/label-core.js`` keeps a fallback copy for payloads that predate the field
(a cached response, an older self-hosted API); ``tests/test_disclaimer.py``
fails if that copy drifts from this one, because two disclaimers that disagree
are worse than either alone.

No em dashes or other non-ASCII: this string is rendered into SVG, HTML, JSON,
and a fixed-width terminal box, and one of those will always be the surface
where a clever character breaks.
"""

from __future__ import annotations

# The full notice. Deliberately says what the label *is* before what it isn't:
# "not advice" alone tells a reader nothing about how much weight the number can
# carry, and the answer ("a model, not a look at your house") is the useful part.
DISCLAIMER = (
    "Informational purposes only. This label is a modeled estimate built from "
    "public data. It is not an inspection, appraisal, survey, or insurance "
    "quote, and it is not legal, financial, insurance, engineering, or real "
    "estate advice. It describes what the model expects of a home like this "
    "one at this location; it cannot tell you the condition, safety, value, or "
    "insurability of any particular property. Verify anything you would act on "
    "with a qualified professional. Provided as is, without warranty."
)

# For surfaces with one line and no room to argue: the compact badge, a footer,
# a status line. Keeps both halves of the full notice (it is a model; it is not
# advice) because dropping either one is what makes fine print misleading.
DISCLAIMER_SHORT = (
    "Modeled estimate, for information only. Not advice, not an inspection or "
    "appraisal."
)
