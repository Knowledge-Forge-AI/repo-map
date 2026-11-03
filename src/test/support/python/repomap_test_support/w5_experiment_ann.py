"""PostgreSQL adapter for the maintained evaluator-owned W5 HNSW contracts."""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import json
from typing import TYPE_CHECKING, Any, Protocol

from common_lore_index.storage.semantic_candidates import (
    CandidatePublication,
    CandidateQuery,
    EmbeddingProfile,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_ann import (
    HnswEvaluationQuery,
    HnswExecutionState,
    HnswResult,
    run_hnsw_evaluation,
)
from retrieval_semantic_ann_models import HnswEvaluationError
from retrieval_semantic_ann_contracts import HnswIndexCatalogState
from retrieval_semantic_ann_lifecycle import (
    HnswCleanupDisposition,
    HnswCreationReceipt,
    capture_creation_receipt,
    cleanup_created_hnsw_index,
)
from retrieval_semantic_ann_sql import DEFAULT_OWNER_IDENTITY, build_hnsw_index_create_sql
from retrieval_semantic_experiment_contracts import ExperimentCell, ExperimentRefusal
from retrieval_semantic_provenance import VerifiedPublicationPin

if TYPE_CHECKING:
    from repomap_test_support.w5_experiment_postgres import HnswObservation


READ_ROLE = "w5_experiment_reader"
HNSW_OWNER_ROLE = DEFAULT_OWNER_IDENTITY


class PostgresHandle(Protocol):
    psql_command: str
    psql_args: Sequence[str]

    def psql_scalar(self, sql: str) -> str: ...


def create_hnsw_index(
    postgres: PostgresHandle,
    *,
    candidate_query: CandidateQuery | None = None,
    publication_pin: VerifiedPublicationPin | None = None,
    attempt_identity: str | None = None,
    rebuild_id: str | None = None,
    dimensions: int = 384,
) -> HnswCreationReceipt:
    """Create and receipt one exact invocation-owned 384-D HNSW index."""
    if candidate_query is None or publication_pin is None or attempt_identity is None:
        raise ExperimentRefusal("hnsw_query_pin_and_attempt_required")
    if dimensions != 384 or (rebuild_id is not None and rebuild_id != candidate_query.rebuild_id):
        raise ExperimentRefusal("invalid_hnsw_settings")
    try:
        from repomap_test_support.w5_experiment_postgres import _catalog, execute_sql

        evaluation_query = HnswEvaluationQuery(
            candidate_query, publication_pin, attempt_identity,
            owner_identity=HNSW_OWNER_ROLE,
        ).validate()
        spec = evaluation_query.index_spec
        before = _catalog(postgres, spec, label="hnsw index preflight")
        if before.present:
            raise ExperimentRefusal("hnsw_index_preexisting")
        execute_sql(postgres, build_hnsw_index_create_sql(spec), role=spec.owner_identity)
        after = _catalog(postgres, spec, label="hnsw index creation")
        return capture_creation_receipt(
            before, after, spec, attempt_identity=attempt_identity,
        )
    except ExperimentRefusal:
        raise
    except Exception as exc:
        code = getattr(exc, "code", "hnsw_index_creation_failed")
        raise ExperimentRefusal(code if isinstance(code, str) else "hnsw_index_creation_failed") from exc


def _candidate_rows(result: HnswResult) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "node_id": item.node_id,
            "canonical_key": item.canonical_key,
            "source_binding_id": item.source_binding_id,
            "raw_rank": item.raw_rank,
            "distance": item.cosine_distance,
            "input_digest": item.input_digest,
            "snapshot_id": item.snapshot_id,
            "kind": item.kind,
            "display_name": item.display_name,
            "evidence": item.evidence,
        }
        for item in result.candidates
    )


def _plan_digest(plan: object) -> tuple[object, str]:
    to_dict = getattr(plan, "to_dict", None)
    value: object = to_dict() if callable(to_dict) else {}
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return value, "sha256:" + hashlib.sha256(raw).hexdigest()


def _observation(
    task_id: str, result: HnswResult, *, cleanup_status: str = "pending"
) -> HnswObservation:
    from repomap_test_support.w5_experiment_postgres import HnswObservation

    plan, plan_sha256 = _plan_digest(result.plan)
    return HnswObservation(
        ExperimentCell(
            "hnsw_vector", task_id, ExecutionState(result.state.value), result.reason,
            cleanup_status=cleanup_status,
        ),
        plan, plan_sha256, _candidate_rows(result), result,
    )


def hnsw_candidates(
    postgres: PostgresHandle,
    publication: CandidatePublication | None = None,
    profile: EmbeddingProfile | None = None,
    *,
    rebuild_id: str | None = None,
    vector: tuple[float, ...] | None = None,
    task_id: str,
    publication_pin: VerifiedPublicationPin | None = None,
    source_binding_id: str | None = None,
    attempt_identity: str | None = None,
    creation_receipt: HnswCreationReceipt | None = None,
    candidate_query: CandidateQuery | None = None,
    limit: int = 20,
    evidence_limit: int = 5,
) -> HnswObservation:
    """Run only a receipt-bound maintained HNSW evaluation; no adoption/fallback."""
    if candidate_query is None:
        if (
            publication is None or profile is None or rebuild_id is None
            or vector is None or source_binding_id is None
        ):
            return _observation(
                task_id,
                HnswResult(HnswExecutionState.REFUSED, "hnsw_query_required", (), None, None, None),
                cleanup_status="not_applicable",
            )
        candidate_query = CandidateQuery(
            publication, profile, rebuild_id, vector, selected=True,
            limit=limit, evidence_limit=evidence_limit, source_binding_id=source_binding_id,
        )
    if publication_pin is None or attempt_identity is None:
        return _observation(
            task_id,
            HnswResult(HnswExecutionState.REFUSED, "hnsw_pin_and_attempt_required", (), None, None, None),
            cleanup_status="not_applicable",
        )
    if creation_receipt is None:
        return _observation(
            task_id,
            HnswResult(HnswExecutionState.REFUSED, "creation_receipt_required", (), None, None, None),
            cleanup_status="not_applicable",
        )
    try:
        from repomap_test_support.w5_experiment_postgres import (
            _catalog,
            _json_array,
            _json_object,
        )

        evaluation_query = HnswEvaluationQuery(
            candidate_query, publication_pin, attempt_identity,
            owner_identity=HNSW_OWNER_ROLE,
        ).validate()
        creation_receipt.validate()
        if creation_receipt.spec != evaluation_query.index_spec:
            raise ExperimentRefusal("creation_query_mismatch")
    except ExperimentRefusal as exc:
        return _observation(
            task_id,
            HnswResult(HnswExecutionState.REFUSED, exc.code, (), None, None, None),
            cleanup_status="not_applicable",
        )
    except Exception as exc:
        code = getattr(exc, "code", "hnsw_query_invalid")
        return _observation(
            task_id,
            HnswResult(
                HnswExecutionState.REFUSED,
                code if isinstance(code, str) else "hnsw_query_invalid",
                (), None, None, None,
            ),
            cleanup_status="not_applicable",
        )

    def read_catalog(sql: str, *, label: str) -> HnswIndexCatalogState:
        del sql
        state = _catalog(postgres, evaluation_query.index_spec, label=label)
        if (state.index_oid, state.table_oid) != (
            creation_receipt.index_oid, creation_receipt.table_oid
        ):
            raise HnswEvaluationError(
                "readback_creation_oid_mismatch",
                "catalog OIDs differ from the invocation creation receipt",
            )
        return state

    def explain_json(sql: str, *, label: str) -> list[Any]:
        return _json_array(postgres, sql, role=READ_ROLE, label=label)

    def execute_json(sql: str, *, label: str) -> dict[str, Any]:
        return _json_object(postgres, sql, role=READ_ROLE, label=label)

    expected_scope = evaluation_query.public_source_scope

    def exact_baseline_json(
        sql: str, *, source_scope: tuple[tuple[str, str], ...], label: str
    ) -> dict[str, Any]:
        if tuple(source_scope) != tuple(expected_scope):
            raise ExperimentRefusal("exact_baseline_scope_mismatch")
        return _json_object(postgres, sql, role=READ_ROLE, label=label)

    try:
        result = run_hnsw_evaluation(
            evaluation_query,
            read_catalog=read_catalog,
            explain_json=explain_json,
            execute_json=execute_json,
            exact_baseline_json=exact_baseline_json,
        )
    except Exception:
        result = HnswResult(
            HnswExecutionState.FAILED, "hnsw_evaluation_failed", (), None, None, None
        )
    return _observation(task_id, result)


def cleanup_hnsw_index(
    postgres: PostgresHandle,
    receipt: HnswCreationReceipt,
    *,
    primary_reason: str | None = None,
) -> HnswCleanupDisposition:
    """RESTRICT-drop only the index proven by the invocation creation receipt."""
    receipt.validate()
    from repomap_test_support.w5_experiment_postgres import _catalog, execute_sql

    def read_catalog(sql: str, *, label: str) -> HnswIndexCatalogState:
        del sql
        return _catalog(postgres, receipt.spec, label=label)

    def execute_ddl(sql: str, *, label: str) -> None:
        del label
        execute_sql(postgres, sql, role=receipt.spec.owner_identity)

    report = cleanup_created_hnsw_index(
        receipt, read_catalog=read_catalog, execute_ddl=execute_ddl,
    )
    return HnswCleanupDisposition.from_report(primary_reason, report)


__all__ = (
    "cleanup_hnsw_index", "create_hnsw_index", "hnsw_candidates",
)
