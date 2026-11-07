"""Evaluator-only execution coordinator for the disposable W5 HNSW arm."""

from __future__ import annotations

import hashlib
import re

from retrieval_semantic_ann_contracts import (
    ExactBaselineExecutor,
    FixedArrayExecutor,
    FixedObjectExecutor,
    HnswIndexCatalogState,
    HnswEvaluationQuery,
    HnswKnobs,
    IndexCatalogReader,
    cleanup_owned_hnsw_index,
    match_candidate_publication,
    verify_hnsw_index_catalog,
)
from retrieval_semantic_ann_models import (
    CandidateIdentity,
    HnswEvaluationError,
    HnswExecutionState,
    HnswProvenance,
    HnswResult,
    HnswSourceScope,
)
from retrieval_semantic_ann_plan import compare_hnsw_to_exact, parse_hnsw_candidates, parse_hnsw_explain
from retrieval_semantic_ann_sql import (
    build_hnsw_explain_sql,
    build_hnsw_index_catalog_sql,
    build_hnsw_query_sql,
)
from common_lore_index.storage.semantic_candidate_sql import build_candidate_query_sql


_STATUS = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def _safe_status(value: object) -> str:
    return value if type(value) is str and _STATUS.fullmatch(value) else "invalid_status"


def _callback_refused(code: str) -> bool:
    return code.startswith((
        "stale_", "readback_", "generation_", "snapshot_", "invalid_publication", "publication_",
    ))


def _revalidate_after_callback(query: HnswEvaluationQuery) -> None:
    match_candidate_publication(query.candidate_query.publication, query.publication_pin)


def _provenance(query: HnswEvaluationQuery, baseline_sql: str) -> HnswProvenance:
    candidate = query.candidate_query
    spec = query.index_spec
    return HnswProvenance(
        candidate.publication.repository_identity,
        candidate.publication.publication.run_id,
        candidate.publication.receipt_identity,
        candidate.profile.identity,
        candidate.rebuild_id,
        spec.name,
        spec.query_digest,
        query.attempt_identity,
        query.public_source_scope,
        384,
        query.knobs.ef_search,
        query.knobs.iterative_scan,
        query.ann_scan_limit,
        query.owner_identity,
        "sha256:" + hashlib.sha256(baseline_sql.encode("utf-8")).hexdigest(),
    )


def run_hnsw_evaluation(
    query: HnswEvaluationQuery,
    *,
    read_catalog: IndexCatalogReader,
    explain_json: FixedArrayExecutor,
    execute_json: FixedObjectExecutor,
    exact_baseline_json: ExactBaselineExecutor,
) -> HnswResult:
    """Run generated SQL only and return truthful native-plan state."""
    try:
        query.validate()
        spec = query.index_spec
        source_scope = query.public_source_scope
        baseline_sql = build_candidate_query_sql(query.candidate_query)
        provenance = _provenance(query, baseline_sql)
    except HnswEvaluationError as exc:
        return HnswResult(HnswExecutionState.REFUSED, exc.code, (), None, None, None)
    except (TypeError, ValueError):
        return HnswResult(HnswExecutionState.REFUSED, "invalid_hnsw_query", (), None, None, None)

    try:
        baseline_payload = exact_baseline_json(
            baseline_sql, source_scope=source_scope, label="hnsw exact baseline"
        )
        _revalidate_after_callback(query)
        baseline_status = _safe_status(baseline_payload.get("status"))
        if baseline_status != "ok":
            reason = baseline_status
            return HnswResult(
                HnswExecutionState.UNAVAILABLE,
                "exact_baseline_" + reason,
                (), None, None, provenance,
            )
        baseline_candidates = parse_hnsw_candidates(
            baseline_payload,
            snapshot_by_binding=query.snapshot_by_binding,
            requested_limit=query.candidate_query.limit,
            evidence_limit=query.candidate_query.evidence_limit,
        )
        exact_identities = tuple(item.identity for item in baseline_candidates)
    except HnswEvaluationError as exc:
        if _callback_refused(exc.code):
            return HnswResult(HnswExecutionState.REFUSED, exc.code, (), None, None, provenance)
        return HnswResult(
            HnswExecutionState.FAILED,
            "exact_baseline_" + exc.code,
            (), None, None, provenance,
        )
    except Exception:
        return HnswResult(
            HnswExecutionState.UNAVAILABLE,
            "exact_baseline_unavailable",
            (), None, None, provenance,
        )

    try:
        catalog = read_catalog(
            build_hnsw_index_catalog_sql(spec), label="hnsw index catalog"
        )
        _revalidate_after_callback(query)
        catalog_reason = verify_hnsw_index_catalog(catalog, spec)
    except HnswEvaluationError as exc:
        state = HnswExecutionState.REFUSED if _callback_refused(exc.code) else HnswExecutionState.FAILED
        return HnswResult(state, exc.code, (), None, None, provenance)
    except Exception:
        return HnswResult(HnswExecutionState.UNAVAILABLE, "hnsw_catalog_unavailable", (), None, None, provenance)
    if catalog_reason is not None:
        state = (
            HnswExecutionState.UNAVAILABLE
            if catalog_reason == "hnsw_index_absent"
            else HnswExecutionState.REFUSED
        )
        return HnswResult(state, catalog_reason, (), None, None, provenance)

    plan = None
    try:
        plan = parse_hnsw_explain(
            explain_json(
                build_hnsw_explain_sql(
                    query.candidate_query,
                    source_scope=source_scope,
                    ann_scan_limit=query.ann_scan_limit,
                ),
                label="hnsw explain",
            ),
            expected_index_name=spec.name,
        )
        _revalidate_after_callback(query)
    except HnswEvaluationError as exc:
        state = HnswExecutionState.REFUSED if _callback_refused(exc.code) else HnswExecutionState.FAILED
        return HnswResult(state, exc.code, (), plan, None, provenance)
    except Exception:
        return HnswResult(HnswExecutionState.FAILED, "hnsw_explain_failed", (), plan, None, provenance)
    if not plan.used_expected_index:
        return HnswResult(HnswExecutionState.NOT_RUN, "hnsw_index_not_selected", (), plan, None, provenance)

    try:
        payload = execute_json(
            build_hnsw_query_sql(
                query.candidate_query,
                source_scope=source_scope,
                ann_scan_limit=query.ann_scan_limit,
            ),
            label="hnsw candidates",
        )
        _revalidate_after_callback(query)
        status = _safe_status(payload.get("status"))
        if status != "ok":
            return HnswResult(HnswExecutionState.UNAVAILABLE, status, (), plan, None, provenance)
        candidates = parse_hnsw_candidates(
            payload,
            snapshot_by_binding=query.snapshot_by_binding,
            requested_limit=query.candidate_query.limit,
            evidence_limit=query.candidate_query.evidence_limit,
        )
        recall = compare_hnsw_to_exact(
            candidates, exact_identities, limit=query.candidate_query.limit
        )
    except HnswEvaluationError as exc:
        state = HnswExecutionState.REFUSED if _callback_refused(exc.code) else HnswExecutionState.FAILED
        return HnswResult(state, exc.code, (), plan, None, provenance)
    except Exception:
        return HnswResult(HnswExecutionState.FAILED, "hnsw_query_failed", (), plan, None, provenance)
    return HnswResult(HnswExecutionState.COMPLETED, None, candidates, plan, recall, provenance)


__all__ = (
    "CandidateIdentity", "HnswEvaluationError", "HnswEvaluationQuery", "HnswExecutionState",
    "HnswSourceScope",
    "HnswIndexCatalogState", "HnswKnobs", "HnswResult", "cleanup_owned_hnsw_index",
    "match_candidate_publication",
    "run_hnsw_evaluation", "parse_hnsw_candidates", "parse_hnsw_explain",
    "compare_hnsw_to_exact", "verify_hnsw_index_catalog",
)
