import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ENTRYPOINT = Path("tools/ci/check_file_lengths.py").resolve()


def write_lines(path: Path, line_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x\n" * line_count)


def initialize_repo(root: Path, *, line_count: int = 1) -> Path:
    (root / "src/main/python").mkdir(parents=True)
    (root / "src/test/unit/python").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    tracked_file = root / "src/main/python/app.py"
    write_lines(tracked_file, line_count)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "add",
            "--",
            "pyproject.toml",
            "src/main/python/app.py",
        ],
        check=True,
    )
    return tracked_file


def run_cli(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ENTRYPOINT), "--repo-root", str(root), *arguments],
        cwd=root.parent,
        check=False,
        capture_output=True,
        text=True,
    )


def run_cli_with_env(
    root: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ENTRYPOINT),
            "--repo-root",
            str(root),
            "--format",
            "json",
        ],
        cwd=root.parent,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ | environment,
    )


@pytest.mark.parametrize("arguments", [(), ("--format", "text")])
def test_ci_length0_cli_emits_text_by_default_and_explicitly(tmp_path, arguments) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    initialize_repo(root)

    completed = run_cli(root, *arguments)

    assert completed.returncode == 0
    assert completed.stdout == (
        "file-length: passed\n"
        "limits: warning >400, failure >1000\n"
        "scanned: 1 Python files\n"
        "warnings: 0\n"
        "failures: 0\n"
    )
    assert completed.stderr == ""


def test_ci_length0_cli_emits_one_json_document(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    initialize_repo(root, line_count=401)

    completed = run_cli(root, "--format", "json")
    payload = json.loads(completed.stdout)

    assert completed.returncode == 0
    assert completed.stdout.endswith("\n")
    assert payload["version"] == 1
    assert payload["profile"] == "file-length"
    assert payload["status"] == "passed_with_warnings"
    assert payload["warning_count"] == 1
    assert payload["failure_count"] == 0
    assert completed.stderr == ""


def test_ci_length0_cli_returns_one_for_policy_failure(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    initialize_repo(root, line_count=1001)

    completed = run_cli(root)

    assert completed.returncode == 1
    assert completed.stdout.startswith("file-length: failed\n")
    assert "FAILURE  1001  src/main/python/app.py\n" in completed.stdout
    assert completed.stderr == ""


@pytest.mark.parametrize(
    "arguments",
    [
        ("--format", "yaml"),
        ("--repo-root",),
        ("--unknown",),
    ],
)
def test_ci_length0_cli_rejects_malformed_invocation(tmp_path, arguments) -> None:
    completed = subprocess.run(
        [sys.executable, str(ENTRYPOINT), *arguments],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr.startswith("usage:")


def test_ci_length0_cli_rejects_missing_repository(tmp_path) -> None:
    completed = run_cli(tmp_path / "missing")

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "not a directory" in completed.stderr


def test_ci_length0_cli_rejects_non_git_repository(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "src/main/python").mkdir(parents=True)
    (root / "src/test").mkdir()
    (root / "tools").mkdir()
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    completed = run_cli(root)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "Git worktree" in completed.stderr


def test_ci_length0_cli_separates_operational_error_from_policy_failure(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    tracked_file = initialize_repo(root)
    tracked_file.unlink()

    completed = run_cli(root, "--format", "json")

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr.startswith("file-length: error:")
    assert "regular file" in completed.stderr


def test_ci_length0_cli_ignores_git_index_override(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    initialize_repo(root)
    alternate_index = tmp_path / "alternate.index"
    subprocess.run(
        ["git", "read-tree", "--empty"],
        check=True,
        env=os.environ | {"GIT_INDEX_FILE": str(alternate_index)},
    )

    completed = run_cli_with_env(root, {"GIT_INDEX_FILE": str(alternate_index)})

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["scanned_file_count"] == 1
    assert completed.stderr == ""


@pytest.mark.parametrize("variable", ["GIT_DIR", "GIT_WORK_TREE"])
def test_ci_length0_cli_ignores_git_repository_overrides(
    tmp_path,
    variable,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    initialize_repo(root)
    other = tmp_path / "other"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    override = other / ".git" if variable == "GIT_DIR" else other

    completed = run_cli_with_env(root, {variable: str(override)})

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["scanned_file_count"] == 1
    assert completed.stderr == ""


def test_ci_length0_cli_sanitizes_unresolvable_home_root(tmp_path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ENTRYPOINT),
            "--repo-root",
            "~ci-length0-user-that-does-not-exist",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == "file-length: error: unable to resolve repository root\n"
    assert "Traceback" not in completed.stderr
    assert str(ENTRYPOINT) not in completed.stderr
