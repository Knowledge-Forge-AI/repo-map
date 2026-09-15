"""Deterministic mixed Python/Go repository fixture for system testing."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.system.config import SystemTestError


def materialize_fixture_repository(target_dir: Path) -> Path:
    """Create a minimal, public-safe mixed Python and Go git repository."""
    target_dir = Path(target_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    calc_py = target_dir / "calc.py"
    calc_py.write_text(
        '"""Calculation module."""\n\n'
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n\n"
        "def multiply(a: int, b: int) -> int:\n"
        "    return a * b\n",
        encoding="utf-8",
    )

    main_py = target_dir / "main.py"
    main_py.write_text(
        '"""Main entrypoint."""\n\n'
        "from calc import add, multiply\n\n"
        "def compute_total() -> int:\n"
        "    return add(10, multiply(2, 5))\n",
        encoding="utf-8",
    )

    helper_go = target_dir / "helper.go"
    helper_go.write_text(
        "package main\n\n"
        "func Greet(name string) string {\n"
        '    return "Hello, " + name\n'
        "}\n",
        encoding="utf-8",
    )

    # Initialize as git repository
    commands = [
        ["git", "init"],
        ["git", "config", "user.name", "System Test Runner"],
        ["git", "config", "user.email", "system-test@repomap.local"],
        ["git", "add", "."],
        ["git", "commit", "-m", "Initial system test fixture repository"],
    ]
    for cmd in commands:
        result = subprocess.run(
            cmd,
            cwd=target_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SystemTestError(
                f"git fixture setup failed ({' '.join(cmd)}): {result.stderr.strip()}"
            )

    return target_dir
