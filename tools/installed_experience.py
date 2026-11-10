"""Checkout-only installed-experience evidence tool (ADR 0181).

    python3 tools/installed_experience.py plan
    python3 tools/installed_experience.py check <bundle-dir> --candidate-source-sha256 HEX64
    python3 tools/installed_experience.py show <bundle-dir> --candidate-source-sha256 HEX64 [--json]

Run directly from a checkout, the entry point puts this checkout's
``src/main/python`` and ``tools`` first on ``sys.path`` so an installed
``common_lore_index`` is never imported in their place. This is not an
installed command, console script, CLI option or MCP surface, and no product
module imports it. ``check`` re-decodes every member with the bounded reader,
recomputes the index and verdict, and binds the hosted report's
``candidate_identity.source_sha256``.
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
    from installed_experience_cli_views import run

    return run(argv)


if __name__ == "__main__":
    bootstrap_source_path()
    raise SystemExit(main())
