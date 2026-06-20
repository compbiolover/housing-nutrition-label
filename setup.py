"""Compatibility shim.

All package metadata lives in ``pyproject.toml`` (the authoritative source).
This file exists only so legacy tooling that still calls ``python setup.py`` /
``pip`` without PEP 517 support continues to work.
"""

from setuptools import setup

setup()
