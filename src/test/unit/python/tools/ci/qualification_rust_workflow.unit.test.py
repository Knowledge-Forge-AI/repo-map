"""Executable workflow owners for the exact AMD Rust qualification projection."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

import pytest

from ci.qualification_native_contracts import validate_d12_native_amd64_job
from ci.qualification_rust_contracts import validate_rust_qualification_job
from ci.workflow_model import Workflow, load_workflow

ROOT = Path(__file__).resolve().parents[6]
WORKFLOW = ROOT / ".github/workflows/repomap-release-qualification.yml"


def _workflow(transform: Callable[[list[dict[str, Any]]], None] | None = None) -> Workflow:
    original = load_workflow(WORKFLOW)
    document = copy.deepcopy(original.document)
    steps = document["jobs"]["d12-native-amd64"]["steps"]
    if transform is not None:
        transform(steps)
    return Workflow(original.path, document)


def _indices(steps: list[dict[str, Any]]) -> tuple[int, int, int]:
    return (
        next(i for i, step in enumerate(steps) if step.get("name") == "Upload native D12 qualification evidence"),
        next(i for i, step in enumerate(steps) if step.get("name") == "Run Rust parser component qualification"),
        next(i for i, step in enumerate(steps) if step.get("name") == "Upload Rust parser component evidence"),
    )


def test_actual_public_workflow_has_one_ordered_always_gated_rust_pair() -> None:
    workflow = _workflow()
    assert validate_rust_qualification_job(workflow) == []
    d12, run, upload = _indices(workflow.jobs["d12-native-amd64"]["steps"])
    assert d12 < run < upload


@pytest.mark.parametrize("mutation", [
    lambda steps: steps.append(copy.deepcopy(next(step for step in steps if step.get("name") == "Run Rust parser component qualification"))),
    lambda steps: steps.append(copy.deepcopy(next(step for step in steps if step.get("name") == "Upload Rust parser component evidence"))),
    lambda steps: steps.remove(next(step for step in steps if step.get("name") == "Run Rust parser component qualification")),
    lambda steps: steps.remove(next(step for step in steps if step.get("name") == "Upload Rust parser component evidence")),
])
def test_step_multiplicity_is_closed(mutation: Callable[[list[dict[str, Any]]], None]) -> None:
    assert validate_rust_qualification_job(_workflow(mutation))


def test_run_and_upload_order_and_continue_on_error_are_closed() -> None:
    def reorder(steps: list[dict[str, Any]]) -> None:
        d12, run, upload = _indices(steps)
        steps[run], steps[upload] = steps[upload], steps[run]
        after_d12, after_run, after_upload = _indices(steps)
        assert after_d12 == d12 and after_d12 < after_upload < after_run

    assert validate_rust_qualification_job(_workflow(reorder))

    for name in ("Run Rust parser component qualification", "Upload Rust parser component evidence"):
        def weaken(steps: list[dict[str, Any]], step_name: str = name) -> None:
            next(step for step in steps if step.get("name") == step_name)["continue-on-error"] = True
        assert validate_rust_qualification_job(_workflow(weaken))


def test_shell_command_multiplicity_and_environment_bypass_are_refused() -> None:
    def duplicate_command(steps: list[dict[str, Any]]) -> None:
        step = next(step for step in steps if step.get("name") == "Run Rust parser component qualification")
        step["run"] = str(step["run"]) + "\n" + str(step["run"])
    assert validate_rust_qualification_job(_workflow(duplicate_command))

    def env_override(steps: list[dict[str, Any]]) -> None:
        step = next(step for step in steps if step.get("name") == "Run Rust parser component qualification")
        step["env"] = {"PYTHONPATH": "$" + "{GITHUB_WORKSPACE}/unreviewed"}
    assert validate_rust_qualification_job(_workflow(env_override))


def test_d12_and_rust_uploads_cannot_cross_claim_each_other() -> None:
    def cross_claim(steps: list[dict[str, Any]]) -> None:
        d12, _run, rust = _indices(steps)
        d12_with = dict(steps[d12]["with"])
        rust_with = dict(steps[rust]["with"])
        steps[d12]["with"] = {**d12_with, "name": rust_with["name"], "path": rust_with["path"]}
        steps[rust]["with"] = {**rust_with, "name": d12_with["name"], "path": d12_with["path"]}

    workflow = _workflow(cross_claim)
    rust_violations = validate_rust_qualification_job(workflow)
    d12_violations = validate_d12_native_amd64_job(workflow)
    assert rust_violations or d12_violations


def test_extra_artifact_upload_is_not_silently_accepted() -> None:
    def extra(steps: list[dict[str, Any]]) -> None:
        steps.append({
            "name": "Unreviewed upload", "if": "always()",
            "uses": "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
            "with": {"name": "other", "path": "other"},
        })
    assert validate_rust_qualification_job(_workflow(extra))


@pytest.mark.parametrize("nesting", ["work_in_report", "report_in_work", "same"])
def test_work_and_uploaded_report_paths_cannot_overlap(tmp_path: Path, nesting: str) -> None:
    from ci.qualification_rust_shape import check_work_report_paths
    from common_lore_index.extractors.contracts.vocabulary import ContractError
    work, report = tmp_path / "work", tmp_path / "report"
    if nesting == "work_in_report":
        work = report / "private-work"
    elif nesting == "report_in_work":
        report = work / "reports"
    else:
        report = work
    with pytest.raises(ContractError, match="qualification_paths_overlap"):
        check_work_report_paths(work, report)
    check_work_report_paths(tmp_path / "separate-work", tmp_path / "separate-report")


def test_one_absolute_command_cutoff_never_resets_or_extends(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from ci import qualification_rust_shape as contracts
    from common_lore_index.extractors.contracts.vocabulary import ContractError
    clock = [100.0]
    monkeypatch.setattr(contracts.time, "monotonic", lambda: clock[0])
    cutoff = contracts.command_work_deadline()
    assert cutoff == 1300.0
    clock[0] = 200.0
    assert contracts.command_work_deadline(cutoff) == cutoff
    contracts.require_work_deadline(cutoff)
    clock[0] = cutoff
    with pytest.raises(ContractError, match="internal_deadline_exceeded"):
        contracts.require_work_deadline(cutoff)
