#!/usr/bin/env python3
"""Keep the README's code-derived regions in sync with the scoring engine.

The roadmap and dimension list in the README kept drifting from the code — the
board still said "9-dimension scoring pipeline" long after four more dimensions
shipped. This script regenerates the *factual* parts that can be derived from
code (the scored-dimension roster and its count) so they can never silently go
stale, while the qualitative roadmap columns stay human-curated.

Single source of truth: ``housing_label.simulate.dimensions.DIMENSIONS`` — the
exact list the scoring engine iterates — plus the ``CONSTRUCTION_DRIVEN`` /
``LOCATION_DRIVEN`` sets. Add a dimension there and this block updates in
lockstep (and CI fails until the committed README matches).

Managed region (everything between the markers is overwritten)::

    <!-- BEGIN AUTOGEN:dimensions ... -->
    ... generated table ...
    <!-- END AUTOGEN:dimensions -->

Usage::

    python scripts/sync_readme.py --write     # rewrite the managed region in place
    python scripts/sync_readme.py --check      # exit 1 if the README is out of date (CI)

With neither flag it prints the generated block to stdout (a dry run).
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.simulate.dimensions import (  # noqa: E402
    DIMENSIONS, CONSTRUCTION_DRIVEN, LOCATION_DRIVEN)

README = _ROOT / "README.md"

_BEGIN = ("<!-- BEGIN AUTOGEN:dimensions (managed by scripts/sync_readme.py — "
          "edits here are overwritten; run `python scripts/sync_readme.py --write`) -->")
_END = "<!-- END AUTOGEN:dimensions -->"

# Regex that matches the whole managed region including its markers, so --write
# can replace it wholesale. Non-greedy body; DOTALL so it spans lines.
_REGION_RE = re.compile(
    re.escape(_BEGIN) + r".*?" + re.escape(_END), re.DOTALL)

# Written-out cardinals for the count sentence, so the prose reads naturally for
# any plausible dimension count (falls back to the digits for counts past the
# table's end — only ~20+ dimensions, which we'd rephrase by hand anyway).
_CARDINALS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen",
    17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
}


def _driver(key: str) -> str:
    """How a dimension is driven — the same construction/location split the label
    and the House Simulator docs describe. Resilience is in neither set: it blends
    the build (EAL modifiers) with the location's hazard exposure."""
    if key in CONSTRUCTION_DRIVEN:
        return "Construction"
    if key in LOCATION_DRIVEN:
        return "Location"
    return "Construction + location"


def _cardinal(n: int) -> str:
    return _CARDINALS.get(n, str(n))


def generate_block() -> str:
    """Render the managed region (markers included) from the code's dimension list."""
    n = len(DIMENSIONS)
    lines = [
        _BEGIN,
        f"The engine scores **{_cardinal(n)} dimensions** "
        "(0–100, higher is better) plus a rolled-up composite. This roster is "
        "generated from the code, so it never drifts from what actually ships:",
        "",
        "| # | Dimension | Driven by |",
        "|---|---|---|",
    ]
    for i, (key, label) in enumerate(DIMENSIONS, 1):
        lines.append(f"| {i} | {label} | {_driver(key)} |")
    lines.append(_END)
    return "\n".join(lines)


def _apply(text: str, block: str) -> str:
    if not _REGION_RE.search(text):
        raise SystemExit(
            "sync_readme: markers not found in README.md. Add this region where "
            "the generated dimension roster should live:\n\n" + block + "\n")
    return _REGION_RE.sub(lambda _m: block, text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true",
                   help="Rewrite the managed region in README.md in place.")
    g.add_argument("--check", action="store_true",
                   help="Exit non-zero if README.md is out of sync (for CI).")
    args = ap.parse_args()

    block = generate_block()

    if not README.exists():
        print(f"sync_readme: {README} not found", file=sys.stderr)
        return 2
    text = README.read_text(encoding="utf-8")
    updated = _apply(text, block)

    if args.check:
        if updated != text:
            print("README.md is out of sync with the code's dimension list.\n"
                  "Run: python scripts/sync_readme.py --write", file=sys.stderr)
            return 1
        print("README.md dimension roster is in sync.")
        return 0

    if args.write:
        if updated != text:
            README.write_text(updated, encoding="utf-8")
            print("README.md updated.")
        else:
            print("README.md already in sync.")
        return 0

    # Dry run: just print the generated block.
    print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
