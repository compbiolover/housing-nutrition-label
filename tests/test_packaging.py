#!/usr/bin/env python3
"""The distribution actually contains every package in the source tree.

Why this exists
---------------
``pyproject.toml`` lists packages explicitly rather than autodiscovering them, so
a new subpackage is included in a wheel only if someone remembers to add it. Tests
never catch the omission: CI installs the project editable, which imports straight
from ``src/`` and finds the package whether or not it is declared. The failure
appears only for someone who installs a built wheel, as an ImportError at runtime.

That is exactly what happened when ``housing_label.enrich.assessor`` was added, so
the invariant is pinned here rather than left to memory.

Run standalone: ``python tests/test_packaging.py``
"""

from __future__ import annotations

import pathlib
import sys
import tomllib

from setuptools import find_packages

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_every_source_package_is_declared_for_distribution():
    cfg = tomllib.loads((_ROOT / "pyproject.toml").read_text())
    declared = set(cfg["tool"]["setuptools"]["packages"])
    found = set(find_packages(where=str(_ROOT / "src")))
    missing = sorted(found - declared)
    assert not missing, (
        f"{missing} exist under src/ but are not in pyproject's package list, so a "
        f"wheel would omit them and importing them would fail for anyone who did "
        f"not install editable. Add them to [tool.setuptools] packages.")


def _run_all() -> int:
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
