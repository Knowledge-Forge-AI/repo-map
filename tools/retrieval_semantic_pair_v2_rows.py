"""Row and fixed-comparison projections for the W5 V2 report."""

from __future__ import annotations

from collections.abc import Mapping

from retrieval_semantic_experiment_contracts import canonical_json_bytes
from retrieval_semantic_pair_artifacts import digest_bytes, refuse
from retrieval_semantic_pair_v2_context import Identity
from retrieval_semantic_pair_v2_projection import (
    _BYTE_SOURCES,
    _CAPABILITIES,
    _CLASSIFICATIONS,
    _COMPARISON_GAPS,
    _FILE_STATUSES,
    _GRADES,
    _OBSERVATION_BYTES,
    _PAIR_FIELDS,
    _POLICY_SOURCES,
    _RULES,
    _STATES,
    _TIMING_SOURCES,
    _alignment,
    _boolean,
    _byte_map,
    _choice,
    _grade,
    _label,
    _mapping,
    _numeric_map,
    _observation,
    _policy,
    _reason,
    _result,
    _safe_text,
    _timing,
    _unit,
)
from retrieval_semantic_pair_v2_rational import rational_projection


def project_pair(
    pair: Mapping[str, object], context: Mapping[str, object], work: Mapping[str, object]
) -> dict[str, object]:
    if frozenset(pair) != _PAIR_FIELDS - {"context", "recorded_work"}:
        raise refuse("pair_v2_base_pair_fields")
    identity = _mapping(pair.get("identity"), "pair_v2_identity")
    return {
        "identity": dict(identity),
        "classification": pair.get("classification"),
        "alignment": _alignment(pair.get("alignment")),
        "journal_observation": _observation(pair.get("journal_observation")),
        "journal_grade": _grade(pair.get("journal_grade")),
        "result_v2": _result(pair.get("result_v2")),
        "file_grading_policy_version": _policy(pair.get("file_grading_policy_version")),
        "file_grading_policy_version_source": _choice(
            pair.get("file_grading_policy_version_source"), _POLICY_SOURCES, "not_recorded"
        ),
        "rational_fusion": rational_projection(pair.get("rational_fusion")),
        "context": dict(context),
        "recorded_work": dict(work),
    }


def project_generation(summary: Mapping[str, object], work: Mapping[str, object]) -> dict[str, object]:
    plan = _mapping(summary.get("plan"), "pair_v2_plan")
    legacy = summary.get("legacy_report")
    legacy_map = legacy if isinstance(legacy, Mapping) else {}
    events = summary.get("event_counts")
    event_map = events if isinstance(events, Mapping) else {}
    safe_plan: dict[str, object] = {}
    task_ids = plan.get("task_ids")
    task_digests = plan.get("task_digests")
    if type(task_ids) is not list:
        raise refuse("pair_v2_plan_task_identity")
    if any(type(task) is not str or not task for task in task_ids):
        raise refuse("pair_v2_plan_task_identity")
    task_pairs: list[list[object]] | None = None
    if task_digests is not None and (
        type(task_digests) is not list or len(task_ids) != len(task_digests)
    ):
        raise refuse("pair_v2_plan_task_identity")
    if type(task_digests) is list and any(
        type(task) is not str or not task
        or type(digest) is not str or len(digest) != 71 or not digest.startswith("sha256:")
        for task, digest in zip(task_ids, task_digests, strict=True)
    ):
        raise refuse("pair_v2_plan_task_identity")
    if type(task_digests) is list:
        task_pairs = [[task, digest] for task, digest in zip(task_ids, task_digests, strict=True)]
    source_closure = plan.get("source_closure")
    if source_closure is not None and (not isinstance(source_closure, Mapping) or len(source_closure) > 10_000):
        raise refuse("pair_v2_plan_source_closure")
    if isinstance(source_closure, Mapping) and any(
        type(key) is not str or not key or type(value) is not str
        or len(value) != 71 or not value.startswith("sha256:")
        for key, value in source_closure.items()
    ):
        raise refuse("pair_v2_plan_source_closure")
    closure_pairs = sorted(source_closure.items(), key=lambda item: str(item[0])) if isinstance(source_closure, Mapping) else None
    for key in (
        "schema", "fixture_id", "task_ids", "task_digests", "arms", "repetitions", "freeze_sha256",
        "policy_digest", "publication_identity", "input_identity", "result_v2_sha256",
        "representation_report_identity", "artifact_profile_identity", "controller_admission_sha256",
    ):
        raw = plan.get(key)
        if key in {"task_ids", "arms"}:
            if type(raw) is not list:
                raise refuse("pair_v2_plan_population")
            safe_plan[key] = [_safe_text(item) for item in raw]
        elif key == "task_digests":
            if raw is None:
                safe_plan[key] = None
            elif type(raw) is list:
                safe_plan[key] = [_safe_text(item) for item in raw]
            else:
                raise refuse("pair_v2_plan_task_identity")
        elif key == "repetitions":
            safe_plan[key] = raw
        elif key.endswith("_sha256"):
            safe_plan[key] = raw
        else:
            safe_plan[key] = _safe_text(raw)
    safe_plan["task_digests"] = task_digests
    safe_plan["task_identity"] = {
        "count": len(task_ids),
        "sha256": digest_bytes(canonical_json_bytes(task_pairs)) if task_pairs is not None else None,
    }
    safe_plan["source_closure"] = {
        "count": len(closure_pairs) if closure_pairs is not None else None,
        "sha256": digest_bytes(canonical_json_bytes(closure_pairs)) if closure_pairs is not None else None,
    }
    return {
        "generation": summary.get("generation"),
        "attempt_id": _safe_text(summary.get("attempt_id")),
        "terminal_status": _label(summary.get("terminal_status"), _STATES),
        "legacy_report": {
            "status": _label(legacy_map.get("status"), _STATES),
            "failure_code": _reason(legacy_map.get("failure_code")),
        },
        "result_v2_status": _label(summary.get("result_v2_status"), _STATES),
        "result_v2_failure_code": _reason(summary.get("result_v2_failure_code")),
        "plan": safe_plan,
        "event_counts": {
            key: value
            for key, value in event_map.items()
            if type(key) is str and type(value) is int and value >= 0
        },
        "denominators": summary.get("denominators"),
        "recorded_work": dict(work),
        "pair_count": summary.get("pair_count"),
    }


def _operation_summary(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    operation = _mapping(value, "pair_v2_operation_summary")
    actual = _mapping(operation.get("actual"), "pair_v2_operation_summary")
    work = _mapping(operation.get("work"), "pair_v2_operation_summary")
    selected = actual.get("selected_binding_ids")
    if type(selected) is not list or any(type(item) is not str for item in selected):
        raise refuse("pair_v2_operation_summary")
    per_binding = work.get("per_binding")
    if per_binding is None:
        per_binding_summary = None
    elif type(per_binding) is list:
        states: dict[str, int] = {}
        for item in per_binding:
            item_map = _mapping(item, "pair_v2_operation_summary")
            state = item_map.get("state")
            if type(state) is not str:
                raise refuse("pair_v2_operation_summary")
            states[state] = states.get(state, 0) + 1
        per_binding_summary = {"count": len(per_binding), "states": dict(sorted(states.items()))}
    else:
        raise refuse("pair_v2_operation_summary")
    return {
        "source": "query_observed.observed_operation",
        "schema": operation.get("schema"),
        "kind": operation.get("kind"),
        "state": operation.get("state"),
        "reason": operation.get("reason"),
        "record_sha256": operation.get("record_sha256"),
        "actual": {
            key: actual.get(key)
            for key in (
                "operation", "backend", "publication_identity", "profile_identity", "rebuild_id",
                "input_descriptor_sha256", "snapshot_manifest_id", "effective_mode", "match_surface", "fallback",
            )
        } | {
            "selected_binding_count": len(selected),
            "selected_binding_ids_sha256": digest_bytes(canonical_json_bytes(sorted(selected))),
        },
        "work": {
            "per_binding": per_binding_summary,
            "hnsw": work.get("hnsw"),
            "fusion": work.get("fusion"),
            "reference": work.get("reference"),
        },
    }


def _comparison_side(value: object, operation: object = None) -> dict[str, object] | None:
    if value is None:
        return None
    side = _mapping(value, "pair_v2_comparison_side")
    grading = side.get("grading")
    grading_map = _mapping(grading, "pair_v2_comparison_grading") if grading is not None else {}
    rational = side.get("rational_fusion")
    rational_map = _mapping(rational, "pair_v2_comparison_rational") if rational is not None else {}
    record_count = rational_map.get("record_count")
    if record_count is not None and (type(record_count) is not int or record_count < 0):
        raise refuse("pair_v2_comparison_rational")
    omission_count = side.get("omission_count")
    safe_omission_count = omission_count if type(omission_count) is int else None
    return {
        "classification": _label(side.get("classification"), _CLASSIFICATIONS),
        "alignment": _alignment(side.get("alignment")),
        "execution_state": _label(side.get("execution_state"), _STATES),
        "reason": _reason(side.get("reason")),
        "capability_state": _label(side.get("capability_state"), _CAPABILITIES),
        "ann_exact_reference_recall": _unit(side.get("ann_exact_reference_recall"), "pair_v2_comparison_recall"),
        "grading": {
            "rule": _label(grading_map.get("rule"), _RULES),
            "state": _label(grading_map.get("state"), _GRADES),
            "quality_credit": _choice(
                grading_map.get("quality_credit"), frozenset({"stored_only", "not_applicable"}), "stored_only"
            ),
            "file_grading_policy_version": _policy(grading_map.get("file_grading_policy_version")),
        },
        "safety_refusal_correct": _boolean(
            side.get("safety_refusal_correct"), "pair_v2_comparison_safety"
        ),
        "absent_answer_correct": _boolean(
            side.get("absent_answer_correct"), "pair_v2_comparison_absence"
        ),
        "metrics": _numeric_map(side.get("metrics"), "pair_v2_comparison_metrics"),
        "file_metrics": _numeric_map(side.get("file_metrics"), "pair_v2_comparison_file_metrics"),
        "file_metrics_status": _choice(
            side.get("file_metrics_status"), _FILE_STATUSES, None
        ),
        "timing": _timing(side.get("timing")),
        "byte_accounting": _numeric_map(side.get("byte_accounting"), "pair_v2_comparison_bytes", _OBSERVATION_BYTES),
        "result_byte_work": _byte_map(side.get("result_byte_work"), "pair_v2_comparison_work"),
        "correspondence_cost": _numeric_map(side.get("correspondence_cost"), "pair_v2_comparison_cost"),
        "rational_fusion": {
            "status": _choice(
                rational_map.get("status"), frozenset({"present", "not_recorded"}), "not_recorded"
            ),
            "record_count": record_count,
        },
        "observed_operation": _operation_summary(operation),
        "scope_complete": _boolean(side.get("scope_complete"), "pair_v2_comparison_scope"),
        "omission_count": safe_omission_count if safe_omission_count is None or safe_omission_count >= 0 else None,
        "omissions_status": _choice(
            side.get("omissions_status"), frozenset({"recorded", "not_recorded"}), "not_recorded"
        ),
        "timing_source": _choice(side.get("timing_source"), _TIMING_SOURCES, "not_recorded"),
        "byte_accounting_source": _choice(
            side.get("byte_accounting_source"), _BYTE_SOURCES, "not_recorded"
        ),
    }


def project_comparison(
    comparison: Mapping[str, object],
    context_gaps: Mapping[Identity, list[str]],
    contexts: Mapping[Identity, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    identity = _mapping(comparison.get("identity"), "pair_v2_comparison_identity")
    generation = identity.get("generation")
    task = identity.get("task_id")
    repetition = identity.get("repetition")
    if type(generation) is not int or type(task) is not str or type(repetition) is not int:
        raise refuse("pair_v2_comparison_identity")
    generation_value = generation
    task_value = task
    repetition_value = repetition
    left_arm = comparison.get("left_arm")
    right_arm = comparison.get("right_arm")
    if type(left_arm) is not str or type(right_arm) is not str:
        raise refuse("pair_v2_comparison_identity")
    left_arm_value = left_arm
    right_arm_value = right_arm
    gap_keys = [
        (generation_value, task_value, left_arm_value, repetition_value),
        (generation_value, task_value, right_arm_value, repetition_value),
    ]
    context_map = contexts or {}
    left_context = context_map.get((generation_value, task_value, left_arm_value, repetition_value))
    right_context = context_map.get((generation_value, task_value, right_arm_value, repetition_value))
    left_operation = left_context.get("observed_operation") if isinstance(left_context, Mapping) else None
    right_operation = right_context.get("observed_operation") if isinstance(right_context, Mapping) else None
    comparability = _mapping(comparison.get("comparability"), "pair_v2_comparability")
    reasons = comparability.get("reasons")
    if type(reasons) is not list or any(type(reason) is not str for reason in reasons):
        raise refuse("pair_v2_comparability")
    return {
        "family": comparison.get("family"),
        "left_arm": comparison.get("left_arm"),
        "right_arm": comparison.get("right_arm"),
        "identity": dict(identity),
        "declared_input_identity": comparison.get("declared_input_identity"),
        "left": _comparison_side(comparison.get("left"), left_operation),
        "right": _comparison_side(comparison.get("right"), right_operation),
        "comparability": {
            "status": comparability.get("status"),
            "reasons": [reason for reason in reasons if reason in _COMPARISON_GAPS],
            "quality_comparison": "not_emitted",
            "context_gaps": sorted({gap for key in gap_keys for gap in context_gaps.get(key, [])}),
        },
    }


__all__ = ["project_comparison", "project_generation", "project_pair"]
