#!/usr/bin/env python3
"""Validate every canonical Liquibase changelog without a live database."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
CHANGELOGS = (
    "src/main/resources/rdbms/changelog.yaml",
    "src/main/resources/coordinator-rdbms/changelog.yaml",
)


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory(prefix="repomap-liquibase-") as temporary:
        for changelog in CHANGELOGS:
            completed = subprocess.run(
                [
                    "liquibase",
                    "--url=offline:postgresql",
                    f"--search-path={ROOT}",
                    f"--changelog-file={changelog}",
                    "validate",
                ],
                cwd=temporary,
                check=False,
            )
            if completed.returncode != 0:
                failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
