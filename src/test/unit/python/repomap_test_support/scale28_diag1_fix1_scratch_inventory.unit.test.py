"""SCALE28-FIX12-DIAG1-FIX1: no behavior-bearing test may bypass the owner.

A behaviour-bearing hardcode is one that *allocates* somewhere outside the
centralized authority — ``TemporaryDirectory(dir=...)``, ``mkdtemp(dir=...)``,
``NamedTemporaryFile(dir=...)``. Synthetic path strings, negative tests, and
redaction fixtures legitimately mention ``/private/tmp`` without creating
anything there, so this regression targets allocation, not the substring.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
SEARCH_ROOTS = ("src/test", "tools")

ALLOCATION_WITH_DIR = re.compile(
    r"(?:TemporaryDirectory|mkdtemp|NamedTemporaryFile|mkstemp)\s*\("
    r"[^)]*\bdir\s*=\s*[\"'](/private/tmp|/tmp)[\"']",
)



def _python_files():
    for root in SEARCH_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            yield path.relative_to(REPO_ROOT).as_posix(), path


def test_no_behavior_bearing_test_allocates_outside_the_scratch_owner():
    offenders = []
    for relative, path in _python_files():
        text = path.read_text(encoding="utf-8")
        for match in ALLOCATION_WITH_DIR.finditer(text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{relative}:{line}")

    assert offenders == [], (
        "these sites allocate outside the centralized test scratch owner; "
        "use repomap_test_support.test_scratch.short_test_directory: "
        + ", ".join(offenders)
    )
