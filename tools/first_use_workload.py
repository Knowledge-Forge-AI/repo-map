"""Checkout-only first-use workload evidence tool (ADR 0180).

    python3 tools/first_use_workload.py plan [--source-parent HEX40]
    python3 tools/first_use_workload.py check --bundle DIR
    python3 tools/first_use_workload.py show --bundle DIR [--json]

Run directly from a checkout, the entry point puts this checkout's
``src/main/python`` first on ``sys.path`` so an installed, older
``common_lore_index`` is never imported in its place. This is not an installed
command, console script, CLI option or MCP surface, and no product module may
import it.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_SOURCE = REPO_ROOT / "src" / "main" / "python"
TOOLS_ROOT = REPO_ROOT / "tools"


def bootstrap_source_path(path: list[str] | None = None) -> list[str]:
    """Place this checkout's product and tool roots first, without duplicates."""
    entries = sys.path if path is None else path
    for root in (str(TOOLS_ROOT), str(PRODUCT_SOURCE)):
        while root in entries:
            entries.remove(root)
        entries.insert(0, root)
    return entries


def main(argv: Sequence[str] | None = None) -> int:
    from first_use_workload_cli_views import run

    return run(argv)


if __name__ == "__main__":
    bootstrap_source_path()
    raise SystemExit(main())
