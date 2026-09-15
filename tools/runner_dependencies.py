#!/usr/bin/env python3
"""Import the optional test dependencies tools/run_tests.py needs."""

from __future__ import annotations

import importlib.util


def import_pytest():
    try:
        import pytest
    except ImportError as error:
        raise RuntimeError(
            "pytest is required for tools/run_tests.py; install the test extra "
            "with: python3 -m pip install -e '.[test]'"
        ) from error
    return pytest


def import_xdist():
    if importlib.util.find_spec("xdist") is None:
        raise RuntimeError(
            "pytest-xdist is required for --jobs auto/N; install the test "
            "extra with: python3 -m pip install -e '.[test]'"
        )
    return True


def import_coverage():
    try:
        import coverage
    except ImportError as error:
        raise RuntimeError(
            "coverage.py is required for tools/run_tests.py coverage gates; "
            "install the test extra with: python3 -m pip install -e '.[test]'"
        ) from error
    return coverage
