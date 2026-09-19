"""CLI helpers shared by RepoMap tests."""

from __future__ import annotations

import runpy
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from repomap_kg.cli.main import main
from repomap_test_support.cli_in_process import capture_cli
from repomap_test_support.cli_in_process import source_environment
from repomap_test_support.cli_in_process import write_text_fixture as write_text_fixture


REPO_ROOT = Path(__file__).resolve().parents[5]
SOURCE_ROOT = REPO_ROOT / "src" / "main" / "python"
FIXTURE_ROOT = REPO_ROOT / "src" / "test" / "fixtures"


def module_environment(*, extra_env: dict[str, str] | None = None) -> dict[str, str]:
    return source_environment(SOURCE_ROOT, extra_env=extra_env)


def run_cli_module(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "repomap_kg", *args],
        check=False,
        cwd=REPO_ROOT,
        env=module_environment(),
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def run_repo_map_in_process(*args: str) -> tuple[int, str, str]:
    return capture_cli(main, *args)


def run_module_entrypoint(*args: str) -> tuple[int, str, str]:
    original_argv = sys.argv[:]
    stdout = StringIO()
    stderr = StringIO()

    try:
        sys.argv = ["repomap-kg", *args]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                runpy.run_module("repomap_kg", run_name="__main__")
            except SystemExit as caught:
                code = caught.code if isinstance(caught.code, int) else 1
            else:
                raise AssertionError("repomap_kg module entrypoint did not exit")
    finally:
        sys.argv = original_argv

    return code, stdout.getvalue(), stderr.getvalue()
# v0.0.2 dynamic target re-attestation.
