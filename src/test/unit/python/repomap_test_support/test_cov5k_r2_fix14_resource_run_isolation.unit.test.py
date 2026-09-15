"""FIX14 resource-run unit tests preserve a surrounding managed owner."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from repomap_test_support.resource_retention import TerminalOutcome
from repomap_test_support.resource_run import (
    ENV_RESOURCE_LEDGER,
    ResourceRunError,
    TestResourceRun,
    active_resource_run,
)
from repomap_test_support.resource_run_test_support import (
    admitted_host_signals,
    preserve_resource_run_process_state,
)
from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog
from repomap_test_support.test_cov5k_r2_fix2_observer import (
    execute_owning_area_execution,
)
from repomap_test_support.test_scratch import (
    ENV_PHASE,
    ENV_PROJECT,
    ENV_RUN_ROOT,
    ENV_SCRATCH_ROOT,
    establish_run,
)

pytestmark = pytest.mark.usefixtures("isolate_test_resource_run_process_state")


def _layout(root: Path, *, phase: str):
    return establish_run(
        {ENV_SCRATCH_ROOT: str(root)},
        project="repo-map_dev",
        phase=phase,
    )


def _entry(owning_area: str):
    return next(
        entry
        for entry in build_closed_catalog()
        if entry.semantic_group == "I"
        and dict(entry.parameter_values)["owning_area"] == owning_area
    )


@pytest.mark.parametrize("selected_result", [0, 1])
def test_nested_allocating_owner_preserves_outer_process_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selected_result: int,
) -> None:
    outer_layout = _layout(tmp_path / "outer", phase="run-tests-all")
    outer = TestResourceRun.start(
        outer_layout,
        host_signals=admitted_host_signals(),
    )
    assert outer is not None
    for key, value in outer_layout.child_environment().items():
        monkeypatch.setenv(key, value)
    outer_ledger = os.environ[ENV_RESOURCE_LEDGER]
    outer_manifest = outer_layout.manifest.read_bytes()
    outer_identity = {
        key: os.environ[key] for key in (ENV_RUN_ROOT, ENV_PROJECT, ENV_PHASE)
    }

    try:
        with preserve_resource_run_process_state():
            inner_layout = _layout(tmp_path / "inner", phase="run-tests-unit")
            inner = TestResourceRun.start(
                inner_layout,
                host_signals=admitted_host_signals(),
            )
            assert inner is not None
            inner.close(
                TerminalOutcome.PASSED
                if selected_result == 0
                else TerminalOutcome.FAILED
            )

        active_after = active_resource_run()
        ledger_after = os.environ.get(ENV_RESOURCE_LEDGER)
        assert (active_after, ledger_after) == (
            outer,
            outer_ledger,
        ), f"active_after={active_after!r}, ledger_after={ledger_after!r}"
        assert outer_layout.manifest.read_bytes() == outer_manifest
        assert {
            key: os.environ[key] for key in (ENV_RUN_ROOT, ENV_PROJECT, ENV_PHASE)
        } == outer_identity
    finally:
        outer.close(TerminalOutcome.PASSED)


@pytest.mark.parametrize("failure_kind", ["nested_error", "close_error"])
def test_nested_failure_cannot_poison_outer_process_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    outer_layout = _layout(tmp_path / "outer", phase="run-tests-all")
    outer = TestResourceRun.start(
        outer_layout,
        host_signals=admitted_host_signals(),
    )
    assert outer is not None
    outer_ledger = os.environ[ENV_RESOURCE_LEDGER]
    outer_manifest = outer_layout.manifest.read_bytes()

    expected_error = (
        RuntimeError if failure_kind == "nested_error" else ResourceRunError
    )
    try:
        with pytest.raises(expected_error):
            with preserve_resource_run_process_state():
                inner_layout = _layout(
                    tmp_path / "inner",
                    phase="run-tests-unit",
                )
                inner = TestResourceRun.start(
                    inner_layout,
                    host_signals=admitted_host_signals(),
                )
                assert inner is not None
                if failure_kind == "nested_error":
                    raise RuntimeError("injected nested runner failure")

                def fail_cleanup(*, record_boundaries=True):
                    raise RuntimeError("injected synthetic close failure")

                monkeypatch.setattr(inner.scratch, "cleanup_transient", fail_cleanup)
                inner.close(TerminalOutcome.FAILED)

        assert active_resource_run() is outer
        assert os.environ[ENV_RESOURCE_LEDGER] == outer_ledger
        assert outer_layout.manifest.read_bytes() == outer_manifest
    finally:
        outer.close(TerminalOutcome.PASSED)


@pytest.mark.parametrize("prior_ledger", [None, "sentinel-ledger"])
def test_process_state_isolation_restores_ledger_presence_and_value(
    monkeypatch: pytest.MonkeyPatch,
    prior_ledger: str | None,
) -> None:
    if prior_ledger is None:
        monkeypatch.delenv(ENV_RESOURCE_LEDGER, raising=False)
    else:
        monkeypatch.setenv(ENV_RESOURCE_LEDGER, prior_ledger)

    with preserve_resource_run_process_state():
        if prior_ledger is None:
            os.environ[ENV_RESOURCE_LEDGER] = "temporary-ledger"
        else:
            os.environ.pop(ENV_RESOURCE_LEDGER)

    assert (ENV_RESOURCE_LEDGER in os.environ) is (prior_ledger is not None)
    assert os.environ.get(ENV_RESOURCE_LEDGER) == prior_ledger


def test_owning_area_basetemp_closes_through_registered_parent_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_layout = _layout(tmp_path, phase="run-tests-all")
    parent = TestResourceRun.start(
        parent_layout,
        host_signals=admitted_host_signals(),
    )
    assert parent is not None
    for key, value in parent_layout.child_environment().items():
        monkeypatch.setenv(key, value)

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    execute_owning_area_execution(
        _entry("scale14"),
        repository_root=tmp_path,
        runner=runner,
    )
    projection = parent.close(TerminalOutcome.PASSED)

    assert projection["scratch_unknown_owned_bytes"] == 0
    assert projection["scratch_transient_bytes_remaining"] == 0
    assert not parent_layout.tmp.exists()
