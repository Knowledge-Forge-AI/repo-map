"""Public-safe doubles for exercising W5 vector orchestration boundaries."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import SimpleNamespace

from common_lore_index.storage.authority import GraphRunId
from common_lore_index.storage.publication_readback import RunPublicationRecord
from common_lore_index.storage.semantic_candidates import (
    CandidatePublication, CandidateQuery, EmbeddingProfile,
)
from repomap_test_support.w5_experiment_postgres import HNSW_OWNER_ROLE, HnswObservation
from repomap_test_support.w5_semantic_support import (
    BIND_CORE, SNAP_CORE_G1, make_w5_calibration_task, make_w5_verified_pin,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_ann_models import (
    HnswExecutionState, HnswPlanSummary, HnswProvenance, HnswResult,
)
from retrieval_semantic_experiment_contracts import ExperimentCell, digest_json
from retrieval_semantic_fusion import (
    AdmittedArmObservation, FileFusionResult, FileIdentityTuple, fuse_arm_observations_rrf,
)
from retrieval_semantic_generator_output_receipt import QueryEmbedding
from retrieval_semantic_provenance import VerifiedPublicationPin


DIGEST = "sha256:" + "a" * 64


class FakePostgres:
    """Transport-shaped object; the candidate adapter is replaced by the test."""

    psql_command = "psql"
    psql_args: tuple[str, ...] = ()

    def psql_scalar(self, _sql: str) -> str:
        raise AssertionError("fake orchestration transport must not execute SQL")


@dataclass(frozen=True)
class OrchestrationFixture:
    task: EvaluationTask
    pin: VerifiedPublicationPin
    publication: CandidatePublication
    profile: EmbeddingProfile
    sealed: object
    inputs: object
    lexical_arm: AdmittedArmObservation


def make_fixture() -> OrchestrationFixture:
    task = make_w5_calibration_task(selected_bindings=(BIND_CORE,))
    pin = make_w5_verified_pin(backend="postgresql", selected_binding_ids=(BIND_CORE,))
    publication = CandidatePublication(
        pin.repository_identity, RunPublicationRecord(GraphRunId(pin.run_id), pin.receipt)
    )
    profile = EmbeddingProfile("fixture-model", "1", "fixture-generator", "1", 3)
    query = QueryEmbedding(task.task_id, DIGEST, "admitted", None, (1.0, 0.0, 0.0))
    sealed = SimpleNamespace(
        artifact=SimpleNamespace(profile=profile, queries=(query,)),
    )
    hit = FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/a.py")
    lexical = AdmittedArmObservation(
        arm_id="postgres_native_fts:postgresql", mode=task.requested_mode,
        verified_pin=pin, selected_binding_ids=(BIND_CORE,),
        raw_file_hits=((hit, 1, "chunk:lexical"),),
    )
    return OrchestrationFixture(task, pin, publication, profile, sealed, object(), lexical)


def exact_stub(
    state: ExecutionState = ExecutionState.COMPLETED, reason: str | None = None,
) -> Callable[..., tuple[ExperimentCell, tuple[dict[str, object], ...]]]:
    def execute(
        _postgres: object, publication: CandidatePublication, profile: EmbeddingProfile,
        *, rebuild_id: str, vector: tuple[float, ...], task_id: str,
        publication_pin: VerifiedPublicationPin | None = None,
        source_binding_id: str | None = None, limit: int = 20, evidence_limit: int = 5,
        query_observer: Callable[[CandidateQuery, str], None] | None = None,
    ) -> tuple[ExperimentCell, tuple[dict[str, object], ...]]:
        assert publication_pin is not None and source_binding_id is not None
        query = CandidateQuery(
            publication, profile, rebuild_id, vector, selected=True, limit=limit,
            evidence_limit=evidence_limit, source_binding_id=source_binding_id,
        )
        if query_observer is not None and state is ExecutionState.COMPLETED:
            query_observer(query, DIGEST)
        return (
            ExperimentCell(
                "exact_vector", task_id, state, reason, elapsed_ns=1,
                cleanup_status="not_applicable",
            ),
            (),
        )
    return execute


def candidate_arm_stub(
    _rows: Sequence[Mapping[str, object]], *, arm_id: str, task: EvaluationTask,
    pin: VerifiedPublicationPin, inputs: object,
) -> AdmittedArmObservation:
    del inputs
    hit = FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/a.py")
    return AdmittedArmObservation(
        arm_id=arm_id, mode=task.requested_mode, verified_pin=pin,
        selected_binding_ids=(BIND_CORE,), raw_file_hits=((hit, 1, "chunk:vector"),),
    )


def grade_stub(
    arm: AdmittedArmObservation, task: EvaluationTask, pin: VerifiedPublicationPin,
    *, lexical_arm: AdmittedArmObservation | None = None,
    fusion_sink: Callable[[FileFusionResult], None] | None = None,
) -> tuple[ExperimentCell, None]:
    arms = (arm,) if lexical_arm is None else (lexical_arm, arm)
    fused = fuse_arm_observations_rrf(
        arms, expected_pin=pin, allow_explicit_single_arm_fallback=lexical_arm is None,
    )
    if fusion_sink is not None:
        fusion_sink(fused)
    arm_id = "hybrid_rrf" if lexical_arm is not None else arm.arm_id
    return ExperimentCell(arm_id, task.task_id, fused.execution_state, cleanup_status="not_applicable"), None


def hnsw_stub(
    _postgres: object, publication: CandidatePublication, profile: EmbeddingProfile,
    *, task_id: str, source_binding_id: str, state: ExecutionState = ExecutionState.NOT_RUN,
    reason: str = "index_not_selected", cleanup_status: str = "verified_absent",
    creation_error: str | None = None,
    rebuild_id: str = "rebuild-1", attempt_identity: str = "w5-semantic-g1",
    **_kwargs: object,
) -> tuple[HnswObservation, None, None, int, int, dict[str, object]]:
    completed = creation_error is None and (
        state is ExecutionState.COMPLETED or cleanup_status == "failed"
    )
    plan_model = HnswPlanSummary(
        ("Limit", "Index Scan") if completed else ("Limit", "Seq Scan"),
        ("w5_hnsw_fixture",) if completed else (), 1 if completed else 0,
        0.1, 0.2, 4, 0, completed, not completed, completed,
    )
    plan = (
        plan_model.to_dict()
        if creation_error is None and state not in {ExecutionState.REFUSED, ExecutionState.UNAVAILABLE}
        else {}
    )
    provenance = None
    result = None
    query_digest = (
        DIGEST
        if state not in {ExecutionState.REFUSED, ExecutionState.UNAVAILABLE}
        else None
    )
    if completed:
        provenance = HnswProvenance(
            publication.repository_identity, publication.publication.run_id,
            publication.receipt_identity, profile.identity, rebuild_id,
            "w5_hnsw_fixture", DIGEST, attempt_identity,
            ((BIND_CORE, SNAP_CORE_G1),), profile.dimensions, 40, "off", 20,
            HNSW_OWNER_ROLE, DIGEST,
        )
        result = HnswResult(
            HnswExecutionState.COMPLETED, None, (), plan_model, None, provenance,
        )
    elif state is ExecutionState.NOT_RUN and creation_error is None:
        result = HnswResult(
            HnswExecutionState.NOT_RUN, reason, (), plan_model, None, None,
        )
    receipt: dict[str, object] = {
        "attempt_identity": attempt_identity,
        "query_digest": query_digest,
        "creation": {} if query_digest is not None else None,
    }
    if query_digest is None:
        receipt.pop("creation")
    if creation_error is not None:
        receipt.pop("creation", None)
        receipt["creation_error"] = creation_error
    else:
        receipt["cleanup"] = {"status": cleanup_status}
    cell_cleanup = "verified" if cleanup_status == "verified_absent" else cleanup_status
    cell_reason = (
        creation_error
        if creation_error is not None
        else "hnsw_cleanup_failed" if cleanup_status == "failed" else reason
    )
    cell_state = ExecutionState.FAILED if creation_error is not None else state
    cell_cleanup = "not_applicable" if creation_error is not None else cell_cleanup
    observation = HnswObservation(
        ExperimentCell("hnsw_vector", task_id, cell_state, cell_reason, cleanup_status=cell_cleanup),
        plan, digest_json(plan) if plan else "", result=result,
    )
    return observation, None, None, 0, 0, receipt


__all__ = [
    "DIGEST", "FakePostgres", "OrchestrationFixture", "candidate_arm_stub",
    "exact_stub", "grade_stub", "hnsw_stub", "make_fixture",
]
