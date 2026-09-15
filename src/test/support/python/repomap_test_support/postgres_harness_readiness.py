"""Readiness checks and Postgres binary resolution helpers."""

from __future__ import annotations

import shutil
import subprocess
import time
import unittest
from pathlib import Path
from typing import Callable

from repomap_test_support.postgres_container_config import (
    DEFAULT_TEST_POSTGRES_RUNTIME,
    SubprocessRunner,
    bounded_text,
)


def postgres_config_path(option: str) -> Path | None:
    pg_config = shutil.which("pg_config")
    if pg_config is None:
        return None
    result = subprocess.run(
        [pg_config, option],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if not value:
        return None
    return Path(value).resolve()


def postgres_bin_dir() -> Path:
    from repomap_test_support import postgres_harness as owner

    bindir = owner.postgres_config_path("--bindir")
    if bindir is not None:
        return bindir
    initdb = Path(shutil.which("initdb") or "initdb").resolve()
    return initdb.parent


def postgres_share_dir() -> Path:
    from repomap_test_support import postgres_harness as owner

    share = owner.postgres_config_path("--sharedir")
    if share is None:
        share = owner.postgres_bin_dir().parent / "share" / "postgresql"
    if not (share / "postgres.bki").exists():
        raise unittest.SkipTest(f"missing Postgres share directory: {share}")
    return share


def require_postgres_runtime_or_skip(
    runtime: str = DEFAULT_TEST_POSTGRES_RUNTIME,
) -> None:
    if shutil.which(runtime) is None:
        raise unittest.SkipTest(
            f"missing container runtime {runtime!r} for temporary Postgres tests"
        )


def poll_container_readiness(
    runner: SubprocessRunner,
    *,
    runtime: str,
    container_name: str,
    user: str,
    database: str,
    timeout_seconds: float,
    sleeper: Callable[[float], None] = time.sleep,
    logs_provider: Callable[[], str] | None = None,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        result = runner(
            [
                runtime,
                "exec",
                container_name,
                "pg_isready",
                "-h",
                "127.0.0.1",
                "-p",
                "5432",
                "-U",
                user,
                "-d",
                database,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return
        last_error = (result.stderr or result.stdout or "").strip()
        sleeper(0.25)
    logs = logs_provider() if logs_provider is not None else ""
    detail = bounded_text(last_error or logs)
    raise RuntimeError(
        "temporary Postgres container did not become ready"
        + (f": {detail}" if detail else "")
    )
