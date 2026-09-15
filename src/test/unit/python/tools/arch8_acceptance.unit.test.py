from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

import arch8_acceptance as arch8_acceptance

REPO_ROOT = Path(__file__).resolve().parents[5]


def load_tool_module():
    return arch8_acceptance


def test_arch8_catalog_is_closed_complete_and_executable() -> None:
    tool = load_tool_module()

    assert {gate.key for gate in tool.ACCEPTANCE_GATES} == tool.REQUIRED_GATE_KEYS
    assert len(tool.ACCEPTANCE_GATES) == len(tool.REQUIRED_GATE_KEYS)
    tool.validate_catalog(REPO_ROOT)

    for gate in tool.ACCEPTANCE_GATES:
        assert gate.evidence
        assert len(gate.evidence) == len(set(gate.evidence))


def test_arch8_public_payload_is_deterministic_and_path_free() -> None:
    tool = load_tool_module()

    first = tool.acceptance_payload(result="planned")
    second = tool.acceptance_payload(result="planned")

    assert first == second
    assert first["schema"] == "arch8.acceptance.v1"
    assert first["result"] == "planned"
    assert first["requirement_count"] == len(tool.REQUIRED_GATE_KEYS)
    assert first["requirements"] == sorted(tool.REQUIRED_GATE_KEYS)
    serialized = json.dumps(first, sort_keys=True)
    for forbidden in ("src/", "test.py", str(REPO_ROOT), "database", "credential"):
        assert forbidden not in serialized


def test_arch8_command_deduplicates_evidence_in_stable_order() -> None:
    tool = load_tool_module()

    command = tool.build_acceptance_command(
        REPO_ROOT,
        python_executable="python-test",
        pg_container_port=55434,
        pg_container_runtime="docker",
    )

    separator = command.index("--")
    evidence = command[separator + 1 :]
    assert command[:separator] == (
        "python-test",
        str(REPO_ROOT / "tools" / "run_tests.py"),
        "--suite",
        "staging",
        "--no-coverage",
        "--pg-container-port",
        "55434",
        "--pg-container-runtime",
        "docker",
    )
    assert evidence == tuple(sorted(set(evidence)))


def test_arch8_runner_sanitizes_subprocess_failure() -> None:
    tool = load_tool_module()
    failure = subprocess.CompletedProcess(
        ("python-test",),
        1,
        stdout="private path output",
        stderr="private database output",
    )

    with patch.object(tool.subprocess, "run", return_value=failure):
        with pytest.raises(tool.Arch8AcceptanceError, match="arch8_acceptance_failed"):
            tool.run_acceptance(
                REPO_ROOT,
                python_executable="python-test",
                pg_container_port=55434,
                pg_container_runtime="docker",
            )


def test_arch8_runner_returns_only_bounded_success_payload() -> None:
    tool = load_tool_module()
    success = subprocess.CompletedProcess(("python-test",), 0, stdout="", stderr="")

    with patch.object(tool.subprocess, "run", return_value=success) as run:
        payload = tool.run_acceptance(
            REPO_ROOT,
            python_executable="python-test",
            pg_container_port=55434,
            pg_container_runtime="docker",
        )

    assert payload == tool.acceptance_payload(result="passed")
    assert run.call_args.kwargs["capture_output"] is True
    assert run.call_args.kwargs["text"] is True
    assert run.call_args.kwargs["check"] is False
