"""REPOMAP-CI0B-FIX2: the runner must not lose the cause of a failure.

Two live-gate defects are covered here. Go validation collapsed every cause
into one opaque sentence, and an evidence-retention failure escaped the
finalization ``finally`` and replaced the primary workload failure.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import run_tests as run_tests

REPO_ROOT = Path(__file__).resolve().parents[5]


def load_tool_module(name: str, relative_path: str):
    return run_tests


def test_ci0b_fix2_go_validation_failure_names_its_cause(monkeypatch) -> None:
    def failing_validate() -> None:
        raise RuntimeError(
            "Go validation step 'golangci-lint run' could not start: "
            "executable 'golangci-lint' was not found"
        )

    monkeypatch.setattr(run_tests, "validate_go_sources", failing_validate)

    with pytest.raises(RuntimeError) as raised:
        run_tests.prepare_go_test_environment("unit")

    message = str(raised.value)
    assert "Go helper validation failed" in message
    assert "golangci-lint run" in message
    assert "was not found" in message


def test_ci0b_fix2_go_build_failure_stays_distinguishable(monkeypatch) -> None:
    monkeypatch.setattr(run_tests, "validate_go_sources", lambda: None)

    def failing_build(*, package_root, instrumented: bool = False):
        assert package_root.name == "helper"
        assert instrumented is False
        raise subprocess.CalledProcessError(1, ("go", "build"))

    monkeypatch.setattr(run_tests, "build_go_helper", failing_build)

    with pytest.raises(RuntimeError, match="go', 'build"):
        run_tests.prepare_go_test_environment("unit")


class _Boundary:
    """A boundary whose evidence closeout fails, as it did on the live gate."""

    def __init__(self) -> None:
        self.closed = False

    def verify_terminal(self) -> dict[str, int]:
        return {}

    def close(self, _resource_run) -> None:
        self.closed = True
        raise ValueError("'docker_operation_journal' is not a valid RetainedReason")


def test_ci0b_fix2_closeout_failure_does_not_mask_the_primary_failure(
    monkeypatch, capsys, tmp_path
) -> None:
    layout = SimpleNamespace(
        run_root=tmp_path / "run", allocated=True, project="repo-map_dev"
    )
    resource_run = SimpleNamespace(
        quota_exceeded=False,
        close=lambda outcome: None,
        bounded_subprocess=lambda label: nullcontext(),
    )
    finalized: list[dict] = []
    boundary = _Boundary()

    monkeypatch.setattr(run_tests, "establish_test_scratch", lambda args: layout)
    monkeypatch.setattr(
        run_tests, "load_hygiene_config", lambda **kwargs: SimpleNamespace(
            requested_profile=None
        )
    )
    monkeypatch.setattr(
        run_tests,
        "resolve_runner_profile",
        lambda *a, **k: SimpleNamespace(
            selected_profile=None,
            operator_attested_exclusive=False,
            operator_attested_pressure_degradation=False,
            campaign_plan_id=None,
            declared_complete_gates=0,
        ),
    )
    monkeypatch.setattr(
        run_tests.TestResourceRun, "start", staticmethod(lambda *a, **k: resource_run)
    )
    monkeypatch.setattr(
        run_tests, "start_runwide_docker_boundary", lambda args, run: boundary
    )
    monkeypatch.setattr(
        run_tests, "report_docker_projection", lambda *a, **k: None
    )
    monkeypatch.setattr(
        run_tests,
        "finalize_run",
        lambda layout, status, **kwargs: finalized.append({"status": status, **kwargs}),
    )

    def failing_workload(*_args, **_kwargs):
        raise RuntimeError("Go helper validation failed: golangci-lint was not found")

    monkeypatch.setattr(run_tests, "run_selected_suites", failing_workload)
    monkeypatch.setattr(run_tests, "integration_sandbox_dispatch", lambda *_args: None)

    exit_code = run_tests.main(["--suite", "int"])

    errors = capsys.readouterr().err
    assert exit_code == 2
    assert boundary.closed is True
    # Both facts survive: the workload cause and the closeout cause.
    assert "golangci-lint was not found" in errors
    assert "Docker boundary closeout failed" in errors
    assert "not a valid RetainedReason" in errors
    # Finalization still ran, and it records that closeout did not complete.
    assert finalized == [
        {"status": "failed", "exit_status": 2, "live_runtime_residue": True}
    ]
