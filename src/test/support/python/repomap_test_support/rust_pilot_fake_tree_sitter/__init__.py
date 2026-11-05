"""Stdlib stand-ins for ``tree_sitter`` and ``tree_sitter_rust`` (T1 only).

The ``tree_sitter`` and ``tree_sitter_rust`` subpackages here exist so that the
real guest helper, setup writer, readback and runtime probe can run as host
subprocesses against explicit, non-native packages. The fake grammar is a
small bracket scanner, not Tree-sitter: results from it are fake-protocol
evidence and never native component evidence.

Source directives (test-only): ``//@fake:sleep`` stalls the parse,
``//@fake:noise`` writes stray bytes to stdout and ``//@fake:abort`` aborts.
"""

from __future__ import annotations

from pathlib import Path


def site_directory() -> Path:
    """Directory to place first on the guest module path instead of the sealed site."""

    return Path(__file__).resolve().parent
