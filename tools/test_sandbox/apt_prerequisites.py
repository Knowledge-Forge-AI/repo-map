#!/usr/bin/env python3
"""Compatibility CLI for ``tools/native_apt_prerequisites.py`` (ADR 0089 D5/D6).

The canonical module holds the whole implementation; image recipes stage and
hash its bytes, never this wrapper. This path keeps the existing command line.
"""

from __future__ import annotations

from pathlib import Path
import sys

if __package__ in (None, ""):
    tools_root = Path(__file__).resolve().parents[1]
    if str(tools_root) not in sys.path:
        sys.path.insert(0, str(tools_root))

from native_apt_prerequisites import main

if __name__ == "__main__":
    raise SystemExit(main())
