"""Closed context joins for the opt-in W5 V2 report."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from retrieval_semantic_pair_artifacts import JournalArtifact, refuse
from retrieval_semantic_pair_v2_envelope import (
    _EXECUTION_STATES,
    _fallback,
    _mapping,
    _mode,
    _reason,
    _state,
    project_envelope,
    validate_projected_envelope,
)


Identity = tuple[int, str, str, int]
_BASELINE_ARMS = frozenset({
    "native_tools_baseline",
    "current_graph_baseline:sqlite",
    "current_graph_baseline:postgresql",
    "captured_projection_reference:sqlite",
    "captured_projection_reference:postgresql",
    "postgres_native_fts:postgresql",
})
_OPERATION_STATUSES = frozenset({"recorded", "envelope_only", "not_applicable", "not_recorded"})
_CONTEXT_FIELDS = {
    "actual_state", "declared_intent", "observed_envelope", "observed_operation", "source",
    "intent_comparison", "comparability_gaps", "observed_operation_status",
}


def _identity(event: Mapping[str, object], journal: JournalArtifact) -> Identity:
    task_id, arm_id, repetition = event.get("task_id"), event.get("arm_id"), event.get("repetition")
    if type(task_id) is not str or not task_id or type(arm_id) is not str or not arm_id:
        raise refuse("pair_v2_event_identity")
    if type(repetition) is not int or repetition < 1:
        raise refuse("pair_v2_event_identity")
    return journal.generation, task_id, arm_id, repetition


def index_query_observed(journal: JournalArtifact) -> dict[Identity, tuple[Mapping[str, object], int]]:
    """Index actual query observations and retain their public line locations."""

    indexed: dict[Identity, tuple[Mapping[str, object], int]] = {}
    for line, event in enumerate(journal.observations, start=1):
        if event.get("event") != "query_observed":
            continue
        identity = _identity(event, journal)
        if identity in indexed:
            raise refuse("pair_v2_duplicate_query_observed")
        indexed[identity] = (event, line)
    return indexed


def _declared_intent(pair: Mapping[str, object]) -> dict[str, object]:
    grade = pair.get("journal_grade")
    grade_map = grade if isinstance(grade, Mapping) else {}
    return {
        "requested_mode": _mode(grade_map.get("requested_mode")),
        "effective_mode": _mode(grade_map.get("effective_mode")),
        "fallback": _fallback({"fallback": grade_map.get("fallback")})
        if isinstance(grade_map.get("fallback"), Mapping) else None,
        "source": grade_map.get("grade_source", "not_recorded"),
    }


def _intent_comparison(
    declared: Mapping[str, object], observed: Mapping[str, object] | None,
) -> dict[str, object]:
    if observed is None or declared.get("source") == "not_recorded":
        return {"status": "not_recorded", "differences": []}
    differences: list[str] = []
    for field in ("requested_mode", "effective_mode", "fallback"):
        if declared.get(field) != observed.get(field):
            differences.append(field)
    return {"status": "different" if differences else "aligned", "differences": sorted(differences)}


def _operation_status(
    arm_id: str, operation: Mapping[str, object] | None, envelope: Mapping[str, object] | None,
) -> str:
    if operation is not None:
        return "recorded"
    if arm_id in _BASELINE_ARMS:
        return "envelope_only" if envelope is not None else "not_applicable"
    return "not_recorded"


def _validated_operation(value: object, identity: Identity) -> dict[str, object] | None:
    if value is None:
        return None
    try:
        from retrieval_semantic_observed_operation import validate_observed_operation

        validated = validate_observed_operation(
            value,
            identity={
                "generation": identity[0], "task_id": identity[1],
                "arm_id": identity[2], "repetition": identity[3],
            },
        )
    except ImportError as error:
        raise refuse("pair_v2_operation_validator_unavailable") from error
    except (KeyError, TypeError, ValueError, RecursionError) as error:
        raise refuse("pair_v2_operation_invalid") from error
    if not isinstance(validated, Mapping) or any(type(key) is not str for key in validated):
        raise refuse("pair_v2_operation_invalid")
    return dict(validated)


def build_context(
    pair: Mapping[str, object], event: Mapping[str, object] | None, line: int | None,
) -> dict[str, object]:
    identity_map = _mapping(pair.get("identity"), "pair_v2_pair_identity")
    identity = (
        cast(int, identity_map.get("generation")), cast(str, identity_map.get("task_id")),
        cast(str, identity_map.get("arm_id")), cast(int, identity_map.get("repetition")),
    )
    actual_state = None if event is None else _state(
        event.get("execution_state"), _EXECUTION_STATES, "pair_v2_execution_state"
    )
    operation = _validated_operation(
        event.get("observed_operation") if event is not None else None, identity
    )
    if operation is not None and actual_state is not None and operation.get("state") != actual_state:
        raise refuse("pair_v2_operation_state_mismatch")
    observed = project_envelope(event)
    declared = _declared_intent(pair)
    arm_id = cast(str, identity_map.get("arm_id"))
    observed_operation_status = _operation_status(arm_id, operation, observed)
    gaps: list[str] = []
    if event is None or event.get("envelope") is None:
        gaps.append("observed_envelope_not_recorded")
    if observed_operation_status == "not_recorded":
        gaps.append("observed_operation_not_recorded")
    return {
        "actual_state": actual_state,
        "declared_intent": declared,
        "observed_envelope": observed,
        "observed_operation": operation,
        "source": {"member": "observations.jsonl" if event is not None else None, "line": line},
        "intent_comparison": _intent_comparison(declared, observed),
        "comparability_gaps": sorted(set(gaps)),
        "observed_operation_status": observed_operation_status,
    }


def _validate_declared(value: object) -> None:
    declared = _mapping(value, "pair_v2_declared_intent")
    if frozenset(declared) != {"requested_mode", "effective_mode", "fallback", "source"}:
        raise refuse("pair_v2_declared_intent")
    if declared.get("source") not in {
        "task_graded.slot", "query_observed.slot", "task_graded.slot+query_observed.slot", "not_recorded",
    }:
        raise refuse("pair_v2_declared_intent")
    _mode(declared.get("requested_mode"))
    _mode(declared.get("effective_mode"))
    fallback = declared.get("fallback")
    if fallback is not None:
        fallback_map = _mapping(fallback, "pair_v2_declared_intent")
        if frozenset(fallback_map) != {"caller_selected", "from_mode", "to_mode", "reason_code"}:
            raise refuse("pair_v2_declared_intent")
        if fallback_map.get("caller_selected") is not True:
            raise refuse("pair_v2_declared_intent")
        _mode(fallback_map.get("from_mode"))
        _mode(fallback_map.get("to_mode"))
        if _reason(fallback_map.get("reason_code")) != fallback_map.get("reason_code"):
            raise refuse("pair_v2_declared_intent")


def validate_context(value: object, identity: Identity) -> None:
    context = _mapping(value, "pair_v2_context")
    if frozenset(context) != _CONTEXT_FIELDS:
        raise refuse("pair_v2_context_fields")
    actual = context.get("actual_state")
    if actual is not None and (type(actual) is not str or actual not in _EXECUTION_STATES):
        raise refuse("pair_v2_actual_state")
    source = _mapping(context.get("source"), "pair_v2_context_source")
    if frozenset(source) != {"member", "line"}:
        raise refuse("pair_v2_context_source")
    if source.get("member") not in {"observations.jsonl", None}:
        raise refuse("pair_v2_context_source")
    line = source.get("line")
    if line is not None and (type(line) is not int or line < 1):
        raise refuse("pair_v2_context_line")
    gaps = context.get("comparability_gaps")
    if type(gaps) is not list or any(
        type(item) is not str or item not in {"observed_envelope_not_recorded", "observed_operation_not_recorded"}
        for item in gaps
    ):
        raise refuse("pair_v2_context_gaps")
    _validate_declared(context.get("declared_intent"))
    _validate_intent_comparison(context.get("intent_comparison"))
    validate_projected_envelope(context.get("observed_envelope"))
    declared = _mapping(context.get("declared_intent"), "pair_v2_declared_intent")
    observed = context.get("observed_envelope")
    observed_map = _mapping(observed, "pair_v2_envelope") if observed is not None else None
    if context.get("intent_comparison") != _intent_comparison(declared, observed_map):
        raise refuse("pair_v2_intent_comparison")
    operation = context.get("observed_operation")
    operation_status = context.get("observed_operation_status")
    if type(operation_status) is not str or operation_status not in _OPERATION_STATUSES:
        raise refuse("pair_v2_operation_status")
    expected_status = _operation_status(
        identity[2], operation if isinstance(operation, Mapping) else None, observed_map,
    )
    if operation_status != expected_status:
        raise refuse("pair_v2_operation_status")
    expected_gaps = sorted([
        *(["observed_envelope_not_recorded"] if observed is None else []),
        *(["observed_operation_not_recorded"] if operation_status == "not_recorded" else []),
    ])
    if gaps != expected_gaps:
        raise refuse("pair_v2_context_gaps")
    if operation is not None:
        validated = _validated_operation(operation, identity)
        if actual is not None and validated is not None and validated.get("state") != actual:
            raise refuse("pair_v2_operation_state_mismatch")


def _validate_intent_comparison(value: object) -> None:
    comparison = _mapping(value, "pair_v2_intent_comparison")
    if frozenset(comparison) != {"status", "differences"}:
        raise refuse("pair_v2_intent_comparison")
    if comparison.get("status") not in {"aligned", "different", "not_recorded"}:
        raise refuse("pair_v2_intent_comparison")
    differences = comparison.get("differences")
    if type(differences) is not list or any(
        type(item) is not str or item not in {"requested_mode", "effective_mode", "fallback"}
        for item in differences
    ):
        raise refuse("pair_v2_intent_comparison")
    if comparison.get("status") == "aligned" and differences:
        raise refuse("pair_v2_intent_comparison")
    if comparison.get("status") == "different" and not differences:
        raise refuse("pair_v2_intent_comparison")


__all__ = ["Identity", "build_context", "index_query_observed", "validate_context"]
