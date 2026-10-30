"""Installed command entry points for CLOE (ADR 0123).

Each command names its brand explicitly; nothing is inferred from ``argv[0]``.
All three delegate, at call time, to the one canonical ``common_lore_index.cli``
``main``, so importing this module loads no CLI implementation or driver.
"""

from __future__ import annotations

import sys

CLOE_PROG = "cloe"
LONG_PROG = "common-lore-index"
LEGACY_PROG = "repomap-kg"
LEGACY_COMMAND_NOTICE = (
    "warning: legacy-command: repomap-kg is deprecated and remains only through v0.1.x; use cloe"
)


def _canonical_main(argv: list[str] | None, prog: str) -> int:
    from common_lore_index import cli

    return cli.main(argv, prog=prog)


def cloe_main(argv: list[str] | None = None) -> int:
    return _canonical_main(argv, CLOE_PROG)


def long_main(argv: list[str] | None = None) -> int:
    return _canonical_main(argv, LONG_PROG)


def legacy_main(argv: list[str] | None = None) -> int:
    print(LEGACY_COMMAND_NOTICE, file=sys.stderr)
    return _canonical_main(argv, LEGACY_PROG)
