"""FIX13 owning-area probes borrow one exact admitted parent lifecycle."""

from __future__ import annotations

from typing import TypedDict


class _InvocationCapture(TypedDict, total=False):
    command: list[str]
    environment: dict[str, str]

import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import run_tests

from repomap_test_support.resource_retention import TerminalOutcome
from repomap_test_support.resource_run import (
    ENV_RESOURCE_LEDGER,
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
    TestScratchError,
    establish_run,
)

pytestmark = pytest.mark.usefixtures("isolate_test_resource_run_process_state")


def _entry(owning_area: str):
    return next(
        entry
        for entry in build_closed_catalog()
        if entry.semantic_group == "I"
        and dict(entry.parameter_values)["owning_area"] == owning_area
    )


def _parent(tmp_path: Path):
    return establish_run(
        {ENV_SCRATCH_ROOT: str(tmp_path)},
        project="repo-map_dev",
        phase="run-tests-all",
    )


def _install_parent_environment(
    monkeypatch: pytest.MonkeyPatch,
    parent,
) -> None:
    for key, value in parent.child_environment().items():
        monkeypatch.setenv(key, value)


def test_configured_child_receives_exact_parent_identity_and_clean_pytest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _parent(tmp_path)
    _install_parent_environment(monkeypatch, parent)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "outer contaminated identity")
    observed: _InvocationCapture = {}

    def runner(command, **kwargs):
        observed["command"] = command
        observed["environment"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    execute_owning_area_execution(
        _entry("scale14"), repository_root=tmp_path, runner=runner
    )

    environment = observed["environment"]
    command = observed["command"]
    assert environment[ENV_RUN_ROOT] == str(parent.run_root)
    assert environment[ENV_PROJECT] == parent.project
    assert environment[ENV_PHASE] == parent.phase
    assert "PYTEST_CURRENT_TEST" not in environment
    assert command[-3] == "--"
    assert command[-2] == (
        f"--basetemp={parent.tmp}/owning-area/scale14"
    )
    assert command[-2].startswith("--basetemp=")


def test_invalid_inherited_parent_refuses_instead_of_allocating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_SCRATCH_ROOT, str(tmp_path))
    monkeypatch.setenv(ENV_RUN_ROOT, str(tmp_path / "missing-run"))
    called = False

    def runner(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("runner must not start")

    with pytest.raises(TestScratchError):
        execute_owning_area_execution(
            _entry("scale14"), repository_root=tmp_path, runner=runner
        )

    assert called is False
    assert not (tmp_path / "r").exists()


def test_explicit_inherited_phase_mismatch_remains_fail_closed(
    tmp_path: Path,
) -> None:
    parent = _parent(tmp_path)
    environment = parent.child_environment()
    environment[ENV_PHASE] = "run-tests-unit"

    with pytest.raises(TestScratchError, match="another phase"):
        establish_run(environment, project="repo-map_dev")


@pytest.mark.parametrize("selected_result", [0, 1])
def test_real_unit_runner_borrows_without_second_lifecycle_or_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selected_result: int,
) -> None:
    prior_active = active_resource_run()
    prior_ledger_present = ENV_RESOURCE_LEDGER in os.environ
    prior_ledger_value = os.environ.get(ENV_RESOURCE_LEDGER)
    identity_keys = (ENV_RUN_ROOT, ENV_PROJECT, ENV_PHASE)
    prior_identity = {
        key: (key in os.environ, os.environ.get(key)) for key in identity_keys
    }
    prior_manifest = (
        prior_active.layout.manifest.read_bytes()
        if prior_active is not None
        else None
    )
    parent = _parent(tmp_path)
    with preserve_resource_run_process_state():
        with monkeypatch.context() as inner_environment:
            _install_parent_environment(inner_environment, parent)
            basetemp = parent.tmp / "owning-area" / "scale14"
            owner_resource = TestResourceRun.start(
                parent, host_signals=admitted_host_signals()
            )
            assert owner_resource is not None

            try:
                with patch.object(
                    run_tests, "run_selected_suites", return_value=selected_result
                ) as selected:
                    result = run_tests.main(
                        [
                            "--suite",
                            "unit",
                            "--no-coverage",
                            "--",
                            f"--basetemp={basetemp}",
                            "src/test/unit/python/example.unit.test.py",
                        ]
                    )

                assert result == selected_result
                assert selected.call_args.args[1] == [
                    f"--basetemp={basetemp}",
                    "src/test/unit/python/example.unit.test.py",
                ]
                assert selected.call_args.args[2] is None
                assert owner_resource.ledger.path == (
                    parent.run_root / "resource-ledger.json"
                )
                assert owner_resource.ledger.path.exists()
                assert len(list((tmp_path / "r").iterdir())) == 1
                index = tmp_path / "index" / parent.project / parent.phase
                assert [entry.resolve() for entry in index.iterdir()] == [
                    parent.run_root
                ]
                manifest = json.loads(parent.manifest.read_text(encoding="utf-8"))
                assert manifest["state"] == "running"
            finally:
                close_projection = owner_resource.close(TerminalOutcome.PASSED)

            assert close_projection["current_run_teardown_complete"] is True
            assert close_projection["scratch_transient_bytes_remaining"] == 0
            assert close_projection["scratch_unknown_owned_bytes"] == 0
            assert owner_resource.index.reconcile().active_runs == 0

    assert active_resource_run() is prior_active
    assert (ENV_RESOURCE_LEDGER in os.environ) is prior_ledger_present
    assert os.environ.get(ENV_RESOURCE_LEDGER) == prior_ledger_value
    assert {
        key: (key in os.environ, os.environ.get(key)) for key in identity_keys
    } == prior_identity
    if prior_active is not None:
        assert prior_active.layout.manifest.read_bytes() == prior_manifest


def test_without_parent_environment_wrapper_retains_standalone_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (ENV_RUN_ROOT, ENV_PROJECT, ENV_PHASE, ENV_SCRATCH_ROOT):
        monkeypatch.delenv(key, raising=False)
    observed: _InvocationCapture = {}

    def runner(command, **kwargs):
        observed["command"] = command
        observed["environment"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    execute_owning_area_execution(
        _entry("scale23"), repository_root=tmp_path, runner=runner
    )

    assert ENV_RUN_ROOT not in observed["environment"]
    assert ENV_PROJECT not in observed["environment"]
    assert ENV_PHASE not in observed["environment"]
    assert not any(arg.startswith("--basetemp=") for arg in observed["command"])


def test_standalone_unit_runner_scratch_still_allocates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_SCRATCH_ROOT, str(tmp_path))
    for key in (ENV_RUN_ROOT, ENV_PROJECT, ENV_PHASE):
        monkeypatch.delenv(key, raising=False)

    layout = run_tests.establish_test_scratch(SimpleNamespace(suite="unit"))

    assert layout.allocated is True
    assert layout.project == "repo-map_dev"
    assert layout.phase == "run-tests-unit"
    assert len(list((tmp_path / "r").iterdir())) == 1
