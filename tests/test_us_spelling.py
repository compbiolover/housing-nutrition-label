#!/usr/bin/env python3
"""Every tracked text file is written in US English.

The repository drifted into British spellings ("storeys", "neighbour",
"modelled") one adapter at a time until the coverage page read "Storeys". This
fails on the common British forms so the drift cannot start again. It is a short
list of words this codebase actually used, not a spell checker: a new British
form will get past it, but the ones already fixed cannot come back.

Spans that are someone else's spelling are skipped: URLs, proper names (Centre
County, PA; Bal Harbour, FL) and identifiers owned elsewhere (OSM's
``sports_centre``, Python's ``Future.cancelled()``).

This file alone:  pytest tests/test_us_spelling.py
"""

from __future__ import annotations

import pathlib
import re
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parent.parent

_BRITISH = re.compile(
    r"(?<![A-Za-z])("
    r"storey|storeys|storeyed|colour\w*|neighbour\w*|behaviour\w*|harbour|"
    r"modell(?:ed|ing|er|ers)|labell(?:ed|ing)|travell(?:ed|ing)|cancell(?:ed|ing)|"
    r"licence|licences|centre|centres|centred|metre|metres|kilometres?|"
    r"normalis\w*|recognis\w*|summaris\w*|organis(?:e|ed|es|ing|ation|ations)|canonicalis\w*|memois\w*|"
    r"characteris(?:e|ed|es|ing|ation)|optimis(?:e|ed|es|ing|ation|ations)|serialis\w*|authoris\w*|"
    r"generalis\w*|realis(?:e|ed|es|ing)|analys(?:e|ed|ing)|"
    r"grey|greyed|judgement|whilst|amongst|ageing|artefact|catalogue|programme|"
    r"favour\w*|honour\w*|rigour|aluminium|analogue|theatre|respelt|misspelt"
    r")(?![A-Za-z])",
    re.IGNORECASE)

_THEIRS = re.compile(r"https?://\S+|sports_centre|Centre County|Bal Harbour|"
                     r"\.cancelled\(|CancelledError")

_SKIP_SUFFIXES = {".svg", ".png", ".ico", ".csv", ".json", ".lock", ".pdf", ".gz",
                  ".parquet", ".xlsx", ".zip"}


def _tracked_text_files():
    out = subprocess.run(["git", "ls-files"], cwd=_ROOT, capture_output=True,
                         text=True, check=True).stdout.split("\n")
    for name in out:
        path = _ROOT / name
        if name and path.suffix.lower() not in _SKIP_SUFFIXES and path.is_file():
            yield path


def test_no_british_spellings():
    found = []
    for path in _tracked_text_files():
        if path.name == "test_us_spelling.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in _BRITISH.finditer(_THEIRS.sub("", line)):
                found.append(f"{path.relative_to(_ROOT)}:{lineno}: {m.group(1)}")
    assert not found, "British spellings (write US English):\n" + "\n".join(found[:50])
