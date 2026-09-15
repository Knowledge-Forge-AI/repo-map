from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog
from repomap_test_support.test_cov5k_r2_fix2_observer import (
    ConfiguredOwningAreaRunnerError,
    OWNING_AREA_STREAM_EXCERPT_BYTES,
    execute_owning_area_execution,
)


def _entry(owning_area: str):
    return next(
        entry
        for entry in build_closed_catalog()
        if entry.semantic_group == "I"
        and dict(entry.parameter_values)["owning_area"] == owning_area
    )


def test_nonzero_runner_preserves_bounded_sanitized_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _entry("scale14")
    node = "src/test/unit/python/tools/scale14_actual_refresh_supervisor.unit.test.py"
    monkeypatch.setenv("FIX12_TEST_TOKEN", "environment-private-value")
    monkeypatch.setenv("GITHUB_TOKEN_PRESENT", "true")
    monkeypatch.setenv("CREDENTIAL_MODE", "none")

    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0],
            17,
            stdout=(
                f"progress marker at {tmp_path}\n"
                "TOKEN=private-value\n"
                '\"api_key\": \"json-private-value\"\n'
                "Authorization: Bearer header-private-value\n"
                "endpoint=https://user:url-private-value@example.invalid/path\n"
                "bare environment-private-value\n"
                "collected true items in none mode\n"
            ),
            stderr="root-cause marker: assertion rejected\n",
        )

    with pytest.raises(ConfiguredOwningAreaRunnerError) as raised:
        execute_owning_area_execution(entry, repository_root=tmp_path, runner=runner)

    error = raised.value
    assert error.failure_kind == "nonzero_exit"
    assert error.owning_area == "scale14"
    assert error.node == node
    assert error.runner_kind == "configured_unit_test_runner"
    assert error.command == (
        "<python>",
        "tools/run_tests.py",
        "--suite",
        "unit",
        "--no-coverage",
        "--",
        "--basetemp={run_root}/tmp/owning-area/scale14",
        node,
    )
    assert error.returncode == 17
    assert error.timeout_seconds is None
    assert "progress marker" in error.stdout_excerpt
    assert "root-cause marker: assertion rejected" in error.stderr_excerpt
    assert "private-value" not in str(error)
    assert "json-private-value" not in str(error)
    assert "header-private-value" not in str(error)
    assert "url-private-value" not in str(error)
    assert "environment-private-value" not in str(error)
    assert str(tmp_path) not in str(error)
    assert "{repository_root}" in error.stdout_excerpt
    assert "TOKEN=[REDACTED]" in error.stdout_excerpt
    assert '\"api_key\": \"[REDACTED]\"' in error.stdout_excerpt
    assert "Authorization: Bearer [REDACTED]" in error.stdout_excerpt
    assert "https://user:[REDACTED]@example.invalid/path" in error.stdout_excerpt
    assert "collected true items in none mode" in error.stdout_excerpt
    assert "returncode=17" in str(error)
    assert f"node={node}" in str(error)


def test_runner_output_keeps_utf8_tail_and_marks_truncation(tmp_path: Path) -> None:
    entry = _entry("scale23")
    stdout_tail = "stdout useful tail ☃"
    stderr_tail = "stderr useful tail ☃"

    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0],
            9,
            stdout="é" * 5000 + stdout_tail,
            stderr="λ" * 5000 + stderr_tail,
        )

    with pytest.raises(ConfiguredOwningAreaRunnerError) as raised:
        execute_owning_area_execution(entry, repository_root=tmp_path, runner=runner)

    error = raised.value
    assert error.stdout_truncated is True
    assert error.stderr_truncated is True
    assert len(error.stdout_excerpt.encode("utf-8")) <= OWNING_AREA_STREAM_EXCERPT_BYTES
    assert len(error.stderr_excerpt.encode("utf-8")) <= OWNING_AREA_STREAM_EXCERPT_BYTES
    assert error.stdout_excerpt.endswith(stdout_tail)
    assert error.stderr_excerpt.endswith(stderr_tail)
    assert "stdout_truncated=true" in str(error)
    assert "stderr_truncated=true" in str(error)
    assert len(str(error).encode("utf-8")) < 9000


def test_success_preserves_existing_executor_evidence(tmp_path: Path) -> None:
    entry = _entry("scale28_fix1")
    node = (
        "src/test/unit/python/tools/"
        "scale28_fix12_preparation_deadlines.unit.test.py"
    )

    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr="")

    evidence = execute_owning_area_execution(
        entry,
        repository_root=tmp_path,
        runner=runner,
    )

    assert evidence.authority_id == entry.authority_id
    assert evidence.owner_entered is True
    assert evidence.enacted_parameters == entry.parameter_values
    assert evidence.observed_fields == (
        ("primary_result_category", "passed"),
        ("owning_area", "scale28_fix1"),
        ("parent_readiness", (True, True, True, True)),
        ("actual_runner", node),
    )
    assert evidence.purpose == "qualification_executor_enactment_rehearsal"
    assert evidence.model_rehearsal_only is True
    assert evidence.qualification_status == "unqualified"


def test_timeout_preserves_identity_bound_and_partial_output(tmp_path: Path) -> None:
    entry = _entry("scale14")
    stdout_tail = b"timeout stdout tail"
    stderr_tail = b"timeout stderr tail"

    def runner(*args, **kwargs):
        assert kwargs["timeout"] == 300
        raise subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=300,
            output=b"x" * 5000 + stdout_tail,
            stderr=b"y" * 5000 + stderr_tail,
        )

    with pytest.raises(ConfiguredOwningAreaRunnerError) as raised:
        execute_owning_area_execution(entry, repository_root=tmp_path, runner=runner)

    error = raised.value
    assert error.failure_kind == "timeout"
    assert error.owning_area == "scale14"
    assert error.returncode is None
    assert error.timeout_seconds == 300
    assert error.stdout_excerpt.endswith(stdout_tail.decode())
    assert error.stderr_excerpt.endswith(stderr_tail.decode())
    assert error.stdout_truncated is True
    assert error.stderr_truncated is True
    assert "timeout_seconds=300" in str(error)
    assert error.__cause__ is None
