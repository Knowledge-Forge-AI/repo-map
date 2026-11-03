"""W5 publication-scope and metric-surface contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from common_lore_index.retrieval.query_contracts import (
    DEFAULT_ORDERING_POLICY_VERSION,
    CapabilityState,
    EvaluationLocator,
    MatchSurface,
    QueryEnvelope,
    QueryHit,
    QueryMode,
    QueryScope,
    QUERY_CONTRACT_VERSION,
    unavailable_envelope,
)
from repomap_test_support.w5_experiment_vector import baseline_file_metrics
from repomap_test_support.w5_semantic_support import (
    BIND_CORE,
    make_w5_calibration_task,
    make_w5_verified_pin,
)
from repomap_test_support.w5_experiment_support import (
    EXPERIMENT_SOURCE_PATHS,
    experiment_source_closure,
)
from retrieval_semantic_experiment_scope import accepted_candidate_evidence
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_experiment_contracts import ExperimentRefusal, digest_bytes
from retrieval_semantic_generator_inputs import DocumentInput, PublicGenerationInput
from retrieval_semantic_primitives import (
    VerifiedNodeRepresentation,
    canonical_node_v1_digest,
    encode_canonical_node_v1_bytes,
)
from retrieval_semantic_grading import grade_w5_task_slot
from retrieval_semantic_representation import (
    RepresentationValidationError,
    RepresentationValidationReport,
)
from retrieval_semantic_fusion import FileIdentityTuple


def _scope(
    pin,
    task,
    *,
    backend: str | None = None,
    bundle: str | None = None,
    manifest: str | None = None,
) -> QueryScope:
    return QueryScope(
        graph_id=pin.graph_id,
        backend=pin.backend if backend is None else backend,
        publication_bundle_id=pin.publication_bundle_id if bundle is None else bundle,
        snapshot_manifest_id=pin.snapshot_manifest_id if manifest is None else manifest,
        selected_binding_ids=tuple(sorted(task.selected_bindings)),
    ).validate()


def _envelope(
    pin,
    task,
    *,
    provenance: dict[str, object] | None = None,
    scope: QueryScope | None = None,
) -> QueryEnvelope:
    locator = EvaluationLocator(
        binding_id=BIND_CORE,
        source_relative_path="pkg/pipeline.py",
    ).validate()
    hit = QueryHit(
        locator=locator,
        match_surface=MatchSurface.STORED_METADATA,
        rank=1,
        score=1.0,
    ).validate()
    return QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=QueryMode.RANKED_DISCOVERY,
        effective_mode=QueryMode.RANKED_DISCOVERY,
        match_surface=MatchSurface.STORED_METADATA,
        scope=_scope(pin, task) if scope is None else scope,
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.AVAILABLE,
        hits=(hit,),
        scope_complete=True,
        provenance={"accepted_run_id": pin.run_id} if provenance is None else provenance,
    ).validate()


def _candidate_inputs() -> tuple[EvaluationTask, PublicGenerationInput, VerifiedNodeRepresentation]:
    pin = make_w5_verified_pin()
    task = make_w5_calibration_task()
    binding_revision, snapshot_id = pin.snapshot_by_binding()[BIND_CORE]
    canonical_key = "file:src/a.py"
    kind = "file"
    display_name = "src/a.py"
    representation = VerifiedNodeRepresentation(
        canonical_key=canonical_key,
        kind=kind,
        display_name=display_name,
        source_binding_id=BIND_CORE,
        snapshot_id=snapshot_id,
        binding_revision=binding_revision,
        source_relative_paths=("src/a.py",),
        evidence_keys=("ev:observed",),
        representation_bytes_len=len(
            encode_canonical_node_v1_bytes(canonical_key, kind, display_name)
        ),
        input_digest=canonical_node_v1_digest(canonical_key, kind, display_name),
    )

    def unreachable_report() -> RepresentationValidationReport:
        raise AssertionError("candidate evidence tests do not re-read the report")

    inputs = PublicGenerationInput(
        provenance=pin,
        documents=(DocumentInput("record:1", representation),),
        query_decisions=(),
        records=(),
        input_identity="sha256:" + "0" * 64,
        representation_report_identity="sha256:" + "1" * 64,
        partial_publication_coverage=False,
        excluded_representation_count=0,
        truncated_representation_count=0,
        _read_current=lambda: pin,
        _read_representations=unreachable_report,
        _frozen_tasks=(task,),
        _tasks_identity="tasks",
        _content_identity="content",
    )
    return task, inputs, representation


def _candidate_row(
    representation: VerifiedNodeRepresentation, evidence: tuple[str, ...]
) -> dict[str, object]:
    return {
        "canonical_key": representation.canonical_key,
        "source_binding_id": representation.source_binding_id,
        "input_digest": representation.input_digest,
        "snapshot_id": representation.snapshot_id,
        "kind": representation.kind,
        "display_name": representation.display_name,
        "evidence": [{"evidence_key": key} for key in evidence],
    }


def test_candidate_evidence_accepts_observed_representation_key() -> None:
    task, inputs, representation = _candidate_inputs()

    accepted = accepted_candidate_evidence(
        _candidate_row(representation, ("ev:observed",)), task=task, inputs=inputs
    )

    assert len(accepted.evidence) == 1
    assert accepted.evidence[0]["path"] == "src/a.py"


@pytest.mark.parametrize(
    "evidence", [("ev:inferred",), ("ev:observed", "ev:observed")]
)
def test_candidate_evidence_rejects_inferred_or_repeated_keys(
    evidence: tuple[str, ...],
) -> None:
    task, inputs, representation = _candidate_inputs()

    with pytest.raises(ExperimentRefusal, match="candidate_evidence_mismatch"):
        accepted_candidate_evidence(
            _candidate_row(representation, evidence), task=task, inputs=inputs
        )


def test_baseline_file_metrics_require_full_current_publication_provenance() -> None:
    task = make_w5_calibration_task()
    pin = make_w5_verified_pin(backend="postgresql")
    envelope = _envelope(pin, task)

    metrics, status, reason = baseline_file_metrics(
        task,
        "current_graph_baseline:postgresql",
        ExecutionState.COMPLETED,
        envelope,
        pin,
    )

    assert status == "verified"
    assert reason is None
    assert metrics is not None
    assert metrics["file_recall@5"] == 1.0


def test_experiment_source_closure_binds_report_owner_hash_and_refuses_missing_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert {
        "src/main/python/common_lore_index/storage/errors.py",
        "src/main/python/common_lore_index/storage/psql.py",
        "src/main/python/common_lore_index/storage/publication_readback.py",
        "src/main/python/common_lore_index/storage/authority.py",
        "src/main/python/common_lore_index/storage/publication.py",
        "src/test/support/python/repomap_test_support/semantic_candidate_restore.py",
        "src/test/support/python/repomap_test_support/semantic_candidate_cleanup.py",
        "src/test/support/python/repomap_test_support/postgres_logical_backup.py",
        "src/test/support/python/repomap_test_support/postgres_harness.py",
        "src/test/support/python/repomap_test_support/w5_generator_support.py", "src/test/support/python/repomap_test_support/w5_semantic_support.py", "src/test/support/python/repomap_test_support/w5_semantic_store_support.py",
        "src/main/python/common_lore_index/ops/config.py", "src/main/python/common_lore_index/ops/config_local.py", "src/main/python/common_lore_index/ops/config_records.py", "src/main/python/common_lore_index/canonicalization/_go_family.py",
        "src/main/python/common_lore_index/storage/context_postgres_identity.py", "src/main/python/common_lore_index/storage/readback_driver.py", "src/main/python/common_lore_index/storage/sqlite_local/connection.py",
    } <= set(EXPERIMENT_SOURCE_PATHS)
    root = tmp_path / "closure"
    for relative in EXPERIMENT_SOURCE_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode("utf-8"))
    monkeypatch.setattr("retrieval_evaluation_admission.candidate_source_files", lambda _root: {})
    monkeypatch.setattr(
        "repomap_test_support.w5_experiment_support.worker_source_closure",
        lambda _root: ({}, {}),
    )

    files, closure = experiment_source_closure(root)
    report_owner = "tools/test_sandbox_contract.py"
    assert files[report_owner] == report_owner.encode("utf-8")
    assert closure[report_owner] == digest_bytes(files[report_owner])

    (root / report_owner).unlink()
    with pytest.raises(ExperimentRefusal, match="experiment_source_missing"):
        experiment_source_closure(root)


def test_baseline_file_metrics_gap_when_run_aliases_are_missing() -> None:
    task = make_w5_calibration_task()
    pin = make_w5_verified_pin(backend="postgresql")

    metrics, status, reason = baseline_file_metrics(
        task,
        "current_graph_baseline:postgresql",
        ExecutionState.COMPLETED,
        _envelope(pin, task, provenance={}),
        pin,
    )

    assert metrics is None
    assert status == "gap"
    assert reason == "file_metric_provenance_unresolved"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("backend", "sqlite"),
        ("repository_identity", "repo1:other"),
        ("accepted_run_id", 2),
        ("accepted_run_id", "1"),
        ("accepted_run_id", True),
        ("run_id", 2),
    ],
)
def test_baseline_file_metrics_reject_mismatched_or_untyped_provenance(
    field: str, value: object
) -> None:
    task = make_w5_calibration_task()
    pin = make_w5_verified_pin(backend="postgresql")
    provenance: dict[str, object] = {"accepted_run_id": pin.run_id}
    provenance[field] = value

    metrics, status, reason = baseline_file_metrics(
        task,
        "current_graph_baseline:postgresql",
        ExecutionState.COMPLETED,
        _envelope(pin, task, provenance=provenance),
        pin,
    )

    assert metrics is None
    assert status == "gap"
    assert reason == "file_metric_provenance_unresolved"


def test_baseline_file_metrics_reject_scope_backend_mismatch() -> None:
    task = make_w5_calibration_task()
    pin = make_w5_verified_pin(backend="postgresql")
    envelope = _envelope(pin, task, scope=_scope(pin, task, backend="sqlite"))

    metrics, status, reason = baseline_file_metrics(
        task,
        "current_graph_baseline:postgresql",
        ExecutionState.COMPLETED,
        envelope,
        pin,
    )

    assert metrics is None
    assert status == "gap"
    assert reason == "file_metric_provenance_unresolved"


@pytest.mark.parametrize("field", ["publication_bundle_id", "snapshot_manifest_id"])
def test_baseline_file_grade_requires_matching_publication_receipt(field: str) -> None:
    task = make_w5_calibration_task()
    pin = make_w5_verified_pin(backend="postgresql")
    scope = _scope(pin, task)
    altered = (
        replace(scope, publication_bundle_id="different-publication")
        if field == "publication_bundle_id"
        else replace(scope, snapshot_manifest_id="different-publication")
    )
    envelope = unavailable_envelope(
        requested_mode=QueryMode.RANKED_DISCOVERY,
        scope=altered,
        provenance=pin.to_dict(),
    )

    metrics, status, reason = baseline_file_metrics(
        task,
        "current_graph_baseline:postgresql",
        ExecutionState.UNAVAILABLE,
        envelope,
        pin,
    )

    assert metrics is None
    assert status == "gap"
    assert reason == "file_metric_provenance_unresolved"


def test_file_only_w5_slot_does_not_emit_unmeasured_span_metrics() -> None:
    task = make_w5_calibration_task()
    pin = make_w5_verified_pin()
    slot = grade_w5_task_slot(
        task,
        arm_id="hybrid_rrf",
        verified_pin=pin,
        returned_files=(
            FileIdentityTuple(
                BIND_CORE,
                pin.snapshot_by_binding()[BIND_CORE][1],
                "pkg/pipeline.py",
            ),
        ),
    )

    assert slot.metrics["file_recall@5"] == 1.0
    assert not any(key.startswith("recall@") for key in slot.metrics)


def test_explicit_empty_span_input_is_measured_as_zero() -> None:
    task = make_w5_calibration_task()
    pin = make_w5_verified_pin()
    slot = grade_w5_task_slot(
        task,
        arm_id="hybrid_rrf",
        verified_pin=pin,
        returned_files=(
            FileIdentityTuple(
                BIND_CORE,
                pin.snapshot_by_binding()[BIND_CORE][1],
                "pkg/pipeline.py",
            ),
        ),
        span_locators=(),
    )

    assert slot.metrics["recall@5"] == 0.0
    assert slot.metrics["file_recall@5"] == 1.0


def test_span_grading_requires_explicit_span_input() -> None:
    task = make_w5_calibration_task()
    pin = make_w5_verified_pin()

    with pytest.raises(RepresentationValidationError, match="span_locators_required"):
        grade_w5_task_slot(
            task,
            arm_id="hybrid_rrf",
            verified_pin=pin,
            returned_files=(),
            grading_granularity="span",
        )
