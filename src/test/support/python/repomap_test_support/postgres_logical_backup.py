"""Portable plain-format PostgreSQL backup helpers for integration tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Sequence

from repomap_kg.storage import run_psql
from repomap_test_support.postgres_harness import postgres_bin_dir


def dump_plain_database(
    postgres: Any,
    psql_args: Sequence[str],
    backup_path: Path,
) -> None:
    """Write a plain logical dump portable across supported test servers."""

    subprocess.run(
        [
            str(postgres_bin_dir() / "pg_dump"),
            *psql_args,
            "--format=plain",
            "--file",
            str(backup_path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    portable = "\n".join(
        line
        for line in backup_path.read_text(encoding="utf-8").splitlines()
        if line != "SET transaction_timeout = 0;"
    )
    backup_path.write_text(portable + "\n", encoding="utf-8")


def restore_plain_database(
    postgres: Any,
    psql_args: Sequence[str],
    backup_path: Path,
) -> None:
    """Restore one portable plain logical dump into an empty test database."""

    run_psql(
        [
            postgres.psql_command,
            *psql_args,
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input_text=backup_path.read_text(encoding="utf-8"),
    )
