"""Transitional ``python -m repomap_kg.server.mcp`` stdio launch shim (ADR 0123).

Only the launch path is kept; MCP tool implementations are not re-exported.
"""

from __future__ import annotations

import sys

LEGACY_MCP_NOTICE = (
    "warning: legacy-module: repomap_kg.server.mcp is deprecated and remains only through v0.1.x; "
    "use common_lore_index.server.mcp"
)


def main() -> int:
    print(LEGACY_MCP_NOTICE, file=sys.stderr)
    from common_lore_index.server.mcp import main as canonical_main

    return canonical_main()


if __name__ == "__main__":
    raise SystemExit(main())
