"""Subprocess integration tests for host-side pgvector admission before sandbox dispatch."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
RUN_TESTS = REPO_ROOT / "tools" / "run_tests.py"
for extra_path in (
    REPO_ROOT,
    REPO_ROOT / "tools",
    REPO_ROOT / "src" / "main" / "python",
    REPO_ROOT / "src" / "test" / "support" / "python",
):
    if str(extra_path) not in sys.path:
        sys.path.insert(0, str(extra_path))

from repomap_test_support.test_scratch import ENV_RUN_ROOT, ENV_SCRATCH_ROOT
from runner_coverage_execution import prepare_child_coverage_environment
from test_sandbox_contract import ENV_ACTIVE, ENV_TOKEN, IMAGE_TAG


def _make_sentinel_docker(bin_dir: Path, sentinel_file: Path) -> None:
    docker_script = bin_dir / "docker"
    docker_script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{sentinel_file}"\n'
        "exit 99\n",
        encoding="utf-8",
    )
    docker_script.chmod(docker_script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _host_subprocess_env(bin_dir: Path, scratch_root: Path) -> dict[str, str]:
    env = prepare_child_coverage_environment(base_env=os.environ, family="unmeasured")
    for sandbox_var in (
        ENV_ACTIVE,
        ENV_TOKEN,
        ENV_RUN_ROOT,
        "REPOMAP_UNIT_PURITY_GUARD",
    ):
        env.pop(sandbox_var, None)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env[ENV_SCRATCH_ROOT] = str(scratch_root)
    return env


@pytest.mark.parametrize(
    ("argv", "expected_stderr"),
    [
        (
            ["--suite", "int", "--no-coverage", "--pg-test-profile", "pgvector"],
            "canonical pgvector profile requires scoped test selector(s) after '--'",
        ),
        (
            ["--suite", "int", "--no-coverage", "--pg-test-profile", "pgvector", "--"],
            "canonical pgvector profile requires scoped test selector(s) after '--'",
        ),
        (
            [
                "--suite",
                "int",
                "--no-coverage",
                "--pg-test-profile",
                "pgvector",
                "--",
                "-m",
                "requires_pgvector",
                "src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py",
            ],
            "canonical marker selection is closed; forwarded -m/--markexpr is refused",
        ),
        (
            [
                "--suite",
                "int",
                "--no-coverage",
                "--pg-test-profile",
                "pgvector",
                "--",
                "--markexpr=requires_pgvector",
                "src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py",
            ],
            "canonical marker selection is closed; forwarded -m/--markexpr is refused",
        ),
        (
            [
                "--suite",
                "int",
                "--no-coverage",
                "--pg-test-profile",
                "pgvector",
                "--",
                "src/test/unit/python/tools/pgvector_profile.unit.test.py",
            ],
            "outside selected suite root(s): src/test/int/python",
        ),
    ],
)
def test_subprocess_host_admission_rejects_invalid_pgvector_before_docker_dispatch(
    tmp_path: Path,
    argv: list[str],
    expected_stderr: str,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sentinel = tmp_path / "docker-invoked.log"
    _make_sentinel_docker(bin_dir, sentinel)
    env = _host_subprocess_env(bin_dir, tmp_path / "scratch")

    result = subprocess.run(
        [sys.executable, str(RUN_TESTS), *argv],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 2
    assert expected_stderr in result.stderr
    assert not sentinel.exists(), "Docker must not be invoked when host pgvector admission fails"
    assert not (tmp_path / "scratch").exists()


@pytest.mark.parametrize(
    "forwarded",
    [
        ["-k", "candidate"],
        ["src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py"],
    ],
)
def test_subprocess_host_admission_allows_valid_pgvector_selectors_to_reach_dispatch(
    tmp_path: Path,
    forwarded: list[str],
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sentinel = tmp_path / "docker-invoked.log"
    _make_sentinel_docker(bin_dir, sentinel)
    env = _host_subprocess_env(bin_dir, tmp_path / "scratch")

    result = subprocess.run(
        [
            sys.executable,
            str(RUN_TESTS),
            "--suite",
            "int",
            "--no-coverage",
            "--pg-test-profile",
            "pgvector",
            "--",
            *forwarded,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert sentinel.exists(), "Valid pgvector selector must pass host admission and reach sandbox dispatch"
    assert IMAGE_TAG in sentinel.read_text(encoding="utf-8")
    assert result.returncode == 2
    assert "ERROR: integration sandbox failed:" in result.stderr
    assert not (tmp_path / "scratch").exists()
    assert "canonical pgvector profile requires scoped test selector(s)" not in result.stderr
    assert "canonical marker selection is closed" not in result.stderr
    assert "outside selected suite root(s)" not in result.stderr
