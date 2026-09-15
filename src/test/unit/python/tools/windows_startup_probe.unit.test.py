from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

import run_windows_async15_tests as probe

REPO_ROOT = Path(__file__).resolve().parents[5]
TOOL_PATH = REPO_ROOT / "tools" / "run_windows_async15_tests.py"


def _definition(**overrides):
    values = {
        "task_name": r"\RepoMap\ASYNC15-Probe",
        "user_id": "S-1-5-21-100-200-300-1001",
        "command": r"C:\Python\python.exe",
        "arguments": ("-c", "print('probe')"),
        "working_directory": r"C:\RepoMap\home",
        "stdout_path": r"C:\RepoMap\home\coordinator\stdout.log",
        "stderr_path": r"C:\RepoMap\home\coordinator\stderr.log",
        "logon_type": "InteractiveToken",
    }
    values.update(overrides)
    return values


def test_task_xml_is_deterministic_and_preserves_exact_foreground_argv():
    first = probe.build_task_xml(**_definition())
    second = probe.build_task_xml(**_definition())

    assert first == second
    assert first[:2] in (b"\xff\xfe", b"\xfe\xff")
    semantics = probe.parse_task_xml(first)
    assert semantics["task_identity"] == r"\RepoMap\ASYNC15-Probe"
    assert semantics["user_id"] == "S-1-5-21-100-200-300-1001"
    assert semantics["logon_type"] == "InteractiveToken"
    assert semantics["run_level"] == "LeastPrivilege"
    assert semantics["command"] == r"C:\Python\python.exe"
    assert semantics["arguments"] == ("-c", "print('probe')")
    assert semantics["working_directory"] == r"C:\RepoMap\home"

    queried_text = first.decode("utf-16")
    assert probe.parse_task_xml(queried_text.encode("utf-16")) == semantics


def test_task_xml_contains_no_password_shell_or_arbitrary_environment():
    content = probe.build_task_xml(**_definition())
    text = content.decode("utf-16")

    assert "Password" not in text
    assert "<Environment" not in text
    assert "cmd.exe" not in text.lower()
    assert "powershell" not in text.lower()
    assert "<Command>" in text
    assert "<Arguments>" in text


def test_manager_error_classification_is_bounded_and_path_free():
    result: subprocess.CompletedProcess[object] = subprocess.CompletedProcess(
        args=("schtasks.exe", "/Create"),
        returncode=1,
        stdout="ERROR: Access is denied. C:\\private\\task.xml",
        stderr="",
    )

    assert probe._manager_category(result) == "access_denied"
    assert probe._manager_category(None) is None
    diagnostic = probe._manager_diagnostic(result)
    assert diagnostic is not None
    assert "private-path" in diagnostic
    assert "C:\\private" not in diagnostic


def test_task_scheduler_com_probe_is_explicitly_native_only(monkeypatch):
    monkeypatch.setattr(probe.sys, "platform", "linux")

    assert probe._task_scheduler_com_probe() == {
        "available": False,
        "hresult": None,
        "error": "native_windows_required",
    }


@pytest.mark.parametrize(
    "field, value",
    [
        ("task_name", "RepoMap\\ASYNC15-Probe"),
        ("user_id", ""),
        ("command", "python.exe"),
        ("working_directory", "relative"),
        ("logon_type", "Password"),
    ],
)
def test_task_xml_rejects_unsafe_or_credentialed_definitions(field, value):
    values = _definition(**{field: value})

    with pytest.raises(ValueError, match="task_definition_invalid"):
        probe.build_task_xml(**values)
