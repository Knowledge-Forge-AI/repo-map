"""Pinned checker identity and incomplete-output contracts."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tomllib
from typing import Any

import pytest

from ci.python_quality_mypy import (
    QualityProfileError,
    _canonical_import_identity,
    _check_mypy,
)
from ci.retained_python_ratchets import EXPECTED_MYPY_CONFIG
from ci.python_quality_profiles import check_paths


_EXPECTED_MYPY_TOML = """[tool.mypy]
python_version = "3.12"
check_untyped_defs = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_unreachable = true
strict_equality = true
show_error_codes = true
"""


def test_external_absolute_alias_has_profile_error(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    owner = root / "owner.py"
    owner.write_text("value: int = 1\n", encoding="utf-8")
    alias = tmp_path / "alias.py"
    alias.symlink_to(owner)
    result = check_paths((str(alias),), root, raise_on_error=False)
    assert result["status"] == "failed"
    assert result["tool_failure"] == "QualityProfileError"
    assert result["failure_category"] == "input"
    assert result["completed_checks"] == []
    assert "alias" in result["message"]


@pytest.mark.parametrize("directory", [False, True])
def test_root_symlink_alias_is_refused(tmp_path: Path, directory: bool) -> None:
    product = tmp_path / "src/main/python"
    product.mkdir(parents=True)
    (product / "owner.py").write_text("value: int = 1\n", encoding="utf-8")
    tooling = tmp_path / "tools"
    if directory:
        tooling.symlink_to(product, target_is_directory=True)
    else:
        tooling.mkdir()
        (tooling / "owner.py").symlink_to(product / "owner.py")
    result = check_paths(("tools/owner.py",), tmp_path, raise_on_error=False)
    assert result["status"] == "failed"
    assert result["classification"] == "tool-failure"
    assert result["failure_category"] == "input"
    assert result["completed_checks"] == []
    assert "alias" in result["message"]


def test_qualified_system_tool_is_the_same_direct_and_imported_module(tmp_path: Path) -> None:
    package = tmp_path / "tools" / "system"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "config.py").write_text('value: int = "bad"\n', encoding="utf-8")
    (tmp_path / "tools" / "runner.py").write_text(
        "from tools.system.config import value\nresult: int = value\n", encoding="utf-8",
    )
    targets = ("tools/runner.py", "tools/system/config.py", "tools/system/__init__.py")
    result = check_paths(targets, tmp_path)
    assert result["analyzed_paths"] == list(targets)
    assert result["status"] == "failed"
    findings = result["mypy"]["findings"]
    assert any(item["path"] == "tools/system/config.py" and item["code"] == "assignment"
               for item in findings)


@pytest.mark.parametrize("stdout", ["", "unexpected partial output\n"])
def test_success_status_without_source_attestation_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str,
) -> None:
    (tmp_path / "owner.py").write_text("value: int = 1\n", encoding="utf-8")

    def incomplete(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(subprocess, "run", incomplete)
    with pytest.raises(QualityProfileError):
        _check_mypy(("owner.py",), tmp_path)


def test_attested_wrong_file_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "owner.py").write_text("value: int = 1\n", encoding="utf-8")

    def wrong_source(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "", "LOG: Parsing other.py (owner)\n")

    monkeypatch.setattr(subprocess, "run", wrong_source)
    with pytest.raises(QualityProfileError, match="attestation"):
        _check_mypy(("owner.py",), tmp_path)


@pytest.mark.parametrize("external", [False, True])
def test_dependency_alias_cannot_transfer_finding_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, external: bool,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "owner.py").write_text("value = 1\n")
    (root / "product.py").write_text("value = 1\n")
    alias = (tmp_path if external else root) / "alias.py"
    alias.symlink_to(root / "product.py")
    reported_path = str(alias) if external else "alias.py"

    def output(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 1, f"{reported_path}:1: error: bad type  [assignment]\n",
            "LOG: Parsing owner.py (owner)\n",
        )

    monkeypatch.setattr(subprocess, "run", output)
    with pytest.raises(QualityProfileError, match="alias"):
        _check_mypy(("owner.py",), root)


def test_duplicate_dependency_findings_across_batches_are_retained_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = ("one-batch/owner.py", "two-batch/owner.py")
    for path in targets:
        target = tmp_path / path
        target.parent.mkdir()
        target.write_text("value = 1\n")
    calls = []

    def output(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command, 1, "dependency.py:1: error: bad type  [assignment]\n",
            f"LOG: Parsing {command[-1]} (owner)\n",
        )

    monkeypatch.setattr(subprocess, "run", output)
    status, findings = _check_mypy(targets, tmp_path)
    assert len(calls) == 2
    assert status == "failed"
    assert len(findings) == 1
    assert findings[0]["path"] == "dependency.py"
    assert findings[0]["dependency"] is True


def test_real_mypy_uses_exact_repository_config_and_pinned_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_EXPECTED_MYPY_TOML, encoding="utf-8")
    configured = tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"]["mypy"]
    assert configured == EXPECTED_MYPY_CONFIG
    repo_root = Path(__file__).resolve().parents[6]
    repository_config = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert repository_config["tool"]["mypy"] == configured

    (tmp_path / "owner.py").write_text("value: int = 1\n", encoding="utf-8")
    real_run = subprocess.run
    mypy_commands: list[list[str]] = []

    def capture_mypy(command: list[str], *args: Any, **kwargs: Any) -> Any:
        if len(command) >= 3 and command[1:3] == ["-m", "mypy"]:
            mypy_commands.append(command)
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", capture_mypy)
    result = check_paths(("owner.py",), tmp_path)

    assert result["status"] == "passed"
    assert result["analyzed_paths"] == ["owner.py"]
    assert len(mypy_commands) == 1
    command = mypy_commands[0]
    config_index = command.index("--config-file")
    assert command[config_index + 1] == str(pyproject)
    assert "--python-version=3.12" not in command
    assert "--check-untyped-defs" in command

    (tmp_path / "owner.py").write_text('value: int = "bad"\n', encoding="utf-8")
    findings = check_paths(("owner.py",), tmp_path)
    assert findings["status"] == "failed"
    assert any(item["path"] == "owner.py" and item["code"] == "assignment"
               for item in findings["mypy"]["findings"])
    assert len(mypy_commands) == 2
    pyproject.write_text(_EXPECTED_MYPY_TOML.replace("strict_equality = true", "strict_equality = false"),
                         encoding="utf-8")
    with pytest.raises(QualityProfileError, match="mypy configuration changed"):
        check_paths(("owner.py",), tmp_path)
    assert len(mypy_commands) == 2, "Configuration drift must fail before mypy runs"


def test_real_mypy_splits_same_canonical_identity_and_attests_all_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "invalid-one" / "common.py"
    second = tmp_path / "invalid.two" / "common.py"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text('value: int = "known type error"\n', encoding="utf-8")
    second.write_text("value: int = 1\n", encoding="utf-8")
    paths = ("invalid-one/common.py", "invalid.two/common.py")

    assert _canonical_import_identity(paths[0], tmp_path) == "common"
    assert _canonical_import_identity(paths[1], tmp_path) == "common"
    real_run = subprocess.run
    mypy_commands: list[list[str]] = []

    def capture_mypy(command: list[str], *args: Any, **kwargs: Any) -> Any:
        if len(command) >= 3 and command[1:3] == ["-m", "mypy"]:
            mypy_commands.append(command)
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", capture_mypy)
    result = check_paths(paths, tmp_path)

    assert result["status"] == "failed"
    assert result["analyzed_paths"] == list(paths)
    assert result["requested_identities"] == {path: "common" for path in paths}
    assert len(mypy_commands) == 2
    observed_targets = {
        Path(command[-1]).resolve().relative_to(tmp_path).as_posix()
        for command in mypy_commands
    }
    assert observed_targets == set(paths)
    findings = result["mypy"]["findings"]
    assert any(
        finding["path"] == paths[0]
        and (finding["code"] == "assignment" or "Incompatible" in finding["message"])
        for finding in findings
    )
