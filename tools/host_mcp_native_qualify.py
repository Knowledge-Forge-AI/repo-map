"""Parent entrypoint for the host MCP native qualification runner and its operator kit.

Run it with the pinned checkout's ``.venv/bin/python -I -B`` (``run.sh`` does).
Only this parent process gets ``tools`` and ``src/test/support/python`` on
``sys.path`` for its fixture helpers; the MCP child is the checkout console
script, launched with a from-scratch environment that carries no import path.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PARENT_IMPORT_ROOTS = (ROOT / "tools", ROOT / "src" / "test" / "support" / "python")


def bootstrap_parent_imports() -> tuple[str, ...]:
    for root in reversed(PARENT_IMPORT_ROOTS):
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
    return tuple(str(root) for root in PARENT_IMPORT_ROOTS)


if __name__ == "__main__":
    bootstrap_parent_imports()
    from smoke.host_mcp_native import main

    raise SystemExit(main(sys.argv[1:], kit_root=ROOT))
