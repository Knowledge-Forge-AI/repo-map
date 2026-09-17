"""Capture the ordinary CLI callable without executing a module entrypoint."""
from __future__ import annotations

import os
from pathlib import Path
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from repomap_kg.cli.main import main
from runner_coverage_execution import (
    prepare_child_coverage_environment as prepare_child_coverage_environment,
    scrub_coverage_environment as scrub_coverage_environment,
)


def capture_cli(
    entrypoint: Callable[[list[str]], int], *args: str,
) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = entrypoint(list(args))
    return exit_code, stdout.getvalue(), stderr.getvalue()


def run_repo_map_in_process(*args: str) -> tuple[int, str, str]:
    return capture_cli(main, *args)


REPO_ROOT = Path(__file__).resolve().parents[5]
SOURCE_ROOT = REPO_ROOT / "src" / "main" / "python"
FIXTURE_ROOT = REPO_ROOT / "src" / "test" / "fixtures"


def source_environment(
    source_root: Path, *, extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    return prepare_child_coverage_environment(
        os.environ, family="cli_module", source_root=source_root, extra_env=extra_env,
    )


def module_environment(*, extra_env: dict[str, str] | None = None) -> dict[str, str]:
    return source_environment(SOURCE_ROOT, extra_env=extra_env)


def module_process_environment(*, extra_env: dict[str, str] | None = None) -> dict[str, str]:
    return prepare_child_coverage_environment(
        os.environ, family="cli_module", source_root=SOURCE_ROOT, extra_env=extra_env,
    )


def write_text_fixture(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
