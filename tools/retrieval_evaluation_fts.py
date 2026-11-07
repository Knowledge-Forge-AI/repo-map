"""PostgreSQL-native FTS evaluation arm adapter over cloe_lexical (Unit 3)."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import time

from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.lexical_service import query_graph_lexical_generation
from common_lore_index.retrieval.lexical_envelopes import LexicalQueryRequest
from common_lore_index.retrieval.projection_policy import (
    ALLOWED_BINDING_PRIVACY,
    ALLOWED_EVIDENCE_RETENTION,
    ALLOWED_GRAPH_PRIVACY,
    ExclusionReason,
    ResolvedBindingPolicy,
    _is_email_role_or_path,
    _is_feed_role_or_path,
)
from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    FallbackDisclosure,
    OmissionRecord,
    QueryEnvelope,
    QueryMode,
    QueryScope,
    refused_envelope,
    unavailable_envelope,
)
from repomap_test_support.retrieval_evaluation_fixture import (
    binding_id_for_alias,
    build_mixed_v1_projection_policy,
)
from retrieval_evaluation_accounting import ByteLayerAccounting
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask


def _outcome(
    state: ExecutionState,
    envelope: QueryEnvelope,
    elapsed_ns: int,
) -> tuple[ExecutionState, QueryEnvelope, int, ByteLayerAccounting]:
    return (
        state,
        envelope,
        elapsed_ns,
        ByteLayerAccounting(
            observed_output_payload_bytes=len(
                json.dumps(envelope.to_dict(), sort_keys=True).encode("utf-8")
            ),
            artifact_store_bytes_read=0,
        ),
    )


def _resolve_lexical_style_and_fallback(
    requested_mode: QueryMode,
    plan_style: str | None,
    projection_query_mode: str | None = None,
) -> tuple[str, FallbackDisclosure | None]:
    if requested_mode == QueryMode.LITERAL_CAPTURED_TEXT:
        if plan_style == "ranked_terms" or projection_query_mode == "lexical":
            return (
                "ranked_terms",
                FallbackDisclosure(
                    caller_selected=True,
                    from_mode=QueryMode.LITERAL_CAPTURED_TEXT,
                    to_mode=QueryMode.RANKED_DISCOVERY,
                    reason_code="lexical_fts_ranked_terms_for_prose",
                ),
            )
        return "literal_captured_text", None
    if requested_mode == QueryMode.CURRENT_LITERAL_ENUMERATION:
        return (
            "literal_captured_text",
            FallbackDisclosure(
                caller_selected=True,
                from_mode=QueryMode.CURRENT_LITERAL_ENUMERATION,
                to_mode=QueryMode.LITERAL_CAPTURED_TEXT,
                reason_code="lexical_captured_text_literal_scan",
            ),
        )
    if requested_mode == QueryMode.EXACT_IDENTITY:
        style = plan_style if plan_style in {"ranked_terms", "normalized_phrase", "literal_captured_text"} else "ranked_terms"
        to_mode = (
            QueryMode.LITERAL_CAPTURED_TEXT
            if style == "literal_captured_text"
            else QueryMode.RANKED_DISCOVERY
        )
        return (
            style,
            FallbackDisclosure(
                caller_selected=True,
                from_mode=QueryMode.EXACT_IDENTITY,
                to_mode=to_mode,
                reason_code="lexical_fts_ranked_terms_for_identity",
            ),
        )
    style = (
        plan_style
        if plan_style in {"ranked_terms", "normalized_phrase", "literal_captured_text"}
        else "ranked_terms"
    )
    fallback = (
        FallbackDisclosure(
            caller_selected=True,
            from_mode=QueryMode.RANKED_DISCOVERY,
            to_mode=QueryMode.LITERAL_CAPTURED_TEXT,
            reason_code="lexical_captured_text_literal_scan",
        )
        if style == "literal_captured_text"
        else None
    )
    return style, fallback


def _evaluate_resolved_binding(resolved: ResolvedBindingPolicy) -> ExclusionReason | None:
    if "inherit" in {
        resolved.resolved_graph_privacy,
        resolved.resolved_binding_privacy,
        resolved.resolved_evidence_retention,
    }:
        return ExclusionReason.UNRESOLVED_INHERIT_POLICY
    if resolved.resolved_graph_privacy != ALLOWED_GRAPH_PRIVACY:
        return ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED
    if resolved.resolved_binding_privacy != ALLOWED_BINDING_PRIVACY:
        return ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED
    if resolved.resolved_evidence_retention != ALLOWED_EVIDENCE_RETENTION:
        return ExclusionReason.RETENTION_NOT_AUTHORIZED
    if _is_email_role_or_path(resolved.role, resolved.source_kind, resolved.alias, None):
        return ExclusionReason.EMAIL_BODY_FORBIDDEN
    if _is_feed_role_or_path(resolved.role, resolved.source_kind, resolved.alias, None):
        return ExclusionReason.FEED_BODY_FORBIDDEN
    return None


def execute_postgres_native_fts_task(
    task: EvaluationTask,
    postgres_home: Path,
) -> tuple[ExecutionState, QueryEnvelope, int, ByteLayerAccounting]:
    """Execute one evaluation task against the PostgreSQL-native cloe_lexical arm."""
    config = load_graph_registry_config_home(postgres_home)
    if not isinstance(config, OpsConfig):
        raise ValueError("postgres_native_fts:postgresql requires PostgreSQL configuration")

    requested_mode = QueryMode(task.requested_mode)
    selected_b_ids = tuple(
        sorted(binding_id_for_alias(a, task.graph_id) for a in task.selected_bindings)
    )
    scope = QueryScope(
        graph_id=task.graph_id,
        backend="postgresql",
        selected_binding_ids=selected_b_ids,
        source_path_prefix=task.source_path_prefix,
    )
    if not selected_b_ids:
        return _outcome(
            ExecutionState.UNAVAILABLE,
            unavailable_envelope(
                requested_mode=requested_mode,
                scope=scope,
                reason="empty_selected_bindings",
            ),
            0,
        )

    plan = task.permitted_query_plan
    if (
        str(plan.get("workflow") or "") == "direct_handoff"
        or task.intended_match_surface == "direct_handoff"
        or requested_mode in {QueryMode.GRAPH_INVESTIGATION, QueryMode.SEMANTIC_DISCOVERY}
    ):
        return _outcome(
            ExecutionState.UNAVAILABLE,
            unavailable_envelope(
                requested_mode=requested_mode,
                scope=scope,
                reason="postgres_native_fts_supports_captured_text_bodies_only",
            ),
            0,
        )

    if (
        set(task.selected_bindings).issubset({"feeds", "mailbox"})
        and task.intended_match_surface != "captured_text"
    ):
        return _outcome(
            ExecutionState.UNAVAILABLE,
            unavailable_envelope(
                requested_mode=requested_mode,
                scope=scope,
                reason="non_body_feed_or_mailbox_excluded_from_lexical_index",
            ),
            0,
        )

    raw_style = plan.get("lexical_query_style")
    proj_mode = plan.get("projection_query_mode")
    query_style, fallback = _resolve_lexical_style_and_fallback(
        requested_mode,
        str(raw_style) if isinstance(raw_style, str) else None,
        str(proj_mode) if isinstance(proj_mode, str) else None,
    )
    policy = build_mixed_v1_projection_policy(
        task.graph_id, selected_aliases=task.selected_bindings
    )
    excluded_reasons = [
        (b_id, reason.value)
        for b_id in selected_b_ids
        if b_id in policy.bindings
        and (reason := _evaluate_resolved_binding(policy.bindings[b_id])) is not None
    ]
    if len(excluded_reasons) == len(selected_b_ids):
        omissions = tuple(
            OmissionRecord(
                b_id,
                None,
                r_code,
                f"binding {b_id} excluded from lexical body query ({r_code})",
            ).validate()
            for b_id, r_code in excluded_reasons
        )
        return _outcome(
            ExecutionState.REFUSED,
            refused_envelope(
                requested_mode=requested_mode,
                scope=scope,
                refusal_code=excluded_reasons[0][1],
                omissions=omissions,
                provenance={
                    "policy_digest": policy.policy_digest(),
                    "query_style": query_style,
                    "policy_enforcement_layer": "evaluator_precheck",
                    "backend_policy_enforcement_observed": False,
                },
            ),
            0,
        )

    excluded_by_id = dict(excluded_reasons)
    admitted_b_ids = tuple(b_id for b_id in selected_b_ids if b_id not in excluded_by_id)
    q_text = str(plan.get("query", ""))
    limit = int(plan.get("limit", 10))
    req = LexicalQueryRequest(
        query=q_text,
        query_style=query_style,
        selected_binding_ids=admitted_b_ids,
        source_path_prefix=task.source_path_prefix,
        limit=limit,
        offset=0,
        fallback=fallback,
    )

    t0 = time.perf_counter_ns()
    env = query_graph_lexical_generation(config, task.graph_id, req, authorize_body=True)
    elapsed = time.perf_counter_ns() - t0
    precheck_omissions = tuple(
        OmissionRecord(binding_id, None, reason, "binding excluded by frozen evaluator policy").validate()
        for binding_id, reason in excluded_reasons
    )
    env = replace(
        env,
        scope=replace(env.scope, selected_binding_ids=selected_b_ids),
        omissions=env.omissions + precheck_omissions,
        scope_complete=env.scope_complete and not precheck_omissions,
        capability_state=(CapabilityState.PARTIAL if precheck_omissions and
                          env.capability_state == CapabilityState.AVAILABLE else env.capability_state),
        provenance=dict(env.provenance) | {
            "policy_enforcement_layer": "evaluator_precheck_over_public_backend_view",
            "backend_policy_enforcement_observed": False,
            "evaluator_policy_digest": policy.policy_digest(),
        },
    ).validate()

    if env.capability_state == CapabilityState.REFUSED:
        exec_state = ExecutionState.REFUSED
    elif env.capability_state in {CapabilityState.UNAVAILABLE, CapabilityState.STALE}:
        exec_state = ExecutionState.UNAVAILABLE
    elif env.capability_state == CapabilityState.FAILED:
        exec_state = ExecutionState.FAILED
    else:
        exec_state = ExecutionState.COMPLETED

    return _outcome(exec_state, env, elapsed)


__all__ = ["execute_postgres_native_fts_task"]
