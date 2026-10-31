"""Failure, divergence, source custody and runtime admission of evaluation attempts."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from common_lore_index.retrieval.query_contracts import QueryMode, QueryScope, unavailable_envelope
from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
from retrieval_evaluation_accounting import ByteLayerAccounting
from retrieval_evaluation_admission import admit_evaluation
from retrieval_evaluation_attempts import admit_attempt
from retrieval_evaluation_execution import measure_task_repetitions
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_harness import DEFAULT_ARMS, declare_calibration_attempt
from retrieval_evaluation_schema import load_freeze_manifest, load_task_catalog


def test_divergence_retains_all_repetitions_and_failed_spend(tmp_path: Path) -> None:
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks/catalog-v1.json")
    task = catalog.calibration_tasks()[0]
    journal = admit_attempt(tmp_path, {"attempt_id": "divergent", "candidate_closure_digests": {}}, {})
    calls = 0

    def execute():
        nonlocal calls
        calls += 1
        # Same state and empty hit identities, but a different actual refusal reason.
        envelope = unavailable_envelope(
            requested_mode=QueryMode(task.requested_mode),
            scope=QueryScope(graph_id=task.graph_id, backend="sqlite"),
            reason="first" if calls == 1 else "changed",
        )
        return ExecutionState.UNAVAILABLE, envelope, calls * 10, ByteLayerAccounting(
            observed_output_payload_bytes=calls * 100, model_tokens_spent=calls,
        )

    slot, observations, divergent = measure_task_repetitions(task, "fixture:sqlite", 3, execute, journal)
    assert divergent is True
    assert slot.execution_state == ExecutionState.FAILED
    assert len(observations) == calls == 3
    assert [item["byte_accounting"]["model_tokens_spent"] for item in observations] == [1, 2, 3]
    assert slot.byte_accounting is not None
    assert slot.byte_accounting.observed_output_payload_bytes == 300
    assert slot.timing is not None and slot.timing.raw_samples_ns == (10, 20, 30)
    journal.finish("failed", {"observations": observations})
    records = [json.loads(line) for line in (journal.directory / "observations.jsonl").read_text().splitlines()]
    assert len([item for item in records if item["event"] == "query_observed"]) == 3
    terminal = json.loads((journal.directory / "terminal.json").read_text())
    for key, filename in (
        ("report_sha256", "report.json"), ("source_manifest_sha256", "source-manifest.json"),
        ("sources_archive_sha256", "sources.zip"), ("journal_sha256", "observations.jsonl"),
    ):
        assert terminal[key] == "sha256:" + hashlib.sha256((journal.directory / filename).read_bytes()).hexdigest()


def test_adapter_exception_retains_failed_observation_with_unknown_bytes(tmp_path: Path) -> None:
    task = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks/catalog-v1.json").calibration_tasks()[0]
    journal = admit_attempt(tmp_path, {"attempt_id": "failed", "candidate_closure_digests": {}}, {})

    def execute():
        raise OSError("private runtime detail must never enter the retained report")

    slot, observations, divergent = measure_task_repetitions(task, "fixture:sqlite", 2, execute, journal)
    assert not divergent
    assert slot.execution_state == ExecutionState.FAILED
    assert len(observations) == 2
    assert all(item["byte_accounting"]["observed_output_payload_bytes"] is None for item in observations)
    assert "private runtime detail" not in (journal.directory / "observations.jsonl").read_text()


@pytest.mark.parametrize("drift", ["runtime", "source", "ordered_tasks", "arms"])
def test_runtime_source_task_or_arm_drift_refuses_before_attempt_admission(tmp_path: Path, drift: str) -> None:
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks/catalog-v1.json")
    freeze = load_freeze_manifest(MIXED_V1_FIXTURE_ROOT / "freeze-v1.json")
    declaration = declare_calibration_attempt(catalog, freeze, attempt_id="retained-3", execution_purpose="retained_calibration")
    if drift == "runtime":
        declaration = replace(declaration, runner_profile={**declaration.runner_profile, "python_version": "different"})
    elif drift == "source":
        declaration = replace(declaration, candidate_closure_digests={})
    elif drift == "ordered_tasks":
        declaration = replace(declaration, ordered_task_ids=tuple(reversed(declaration.ordered_task_ids)))
    else:
        declaration = replace(declaration, arms=("unsupported",))
    with pytest.raises(ValueError):
        admit_evaluation(declaration, catalog, freeze, attempt_root=tmp_path / "attempts", pg_port=55433, supported_arms=DEFAULT_ARMS)
    assert not (tmp_path / "attempts").exists()
