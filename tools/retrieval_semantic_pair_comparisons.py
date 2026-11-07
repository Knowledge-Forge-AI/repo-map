"""Fixed, descriptive arm-to-arm views over paired W5 evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from retrieval_semantic_pair_artifacts import refuse


COMPARISON_FAMILIES = (
    ("postgres_native_fts:postgresql", "exact_vector"),
    ("postgres_native_fts:postgresql", "hybrid_rrf"),
    ("exact_vector", "hnsw_vector"),
)
_MISSING_CLASSIFICATIONS = {"missing", "missing_result_v2"}
_UNAVAILABLE_CLASSIFICATIONS = {"failed", "refused", "unsupported", "unavailable"}
_QUALITY_ONLY_CLASSIFICATIONS = {
    "absence_correct", "absence_incorrect", "absence_not_recorded",
    "inapplicable", "safety_correct", "safety_incorrect", "safety_not_recorded",
}
_COMPARISON_FIELDS = {
    "family", "left_arm", "right_arm", "identity", "declared_input_identity",
    "left", "right", "comparability",
}
_COMPARISON_SIDE_FIELDS = {
    "classification", "alignment", "execution_state", "reason", "capability_state",
    "ann_exact_reference_recall", "grading", "safety_refusal_correct",
    "absent_answer_correct", "metrics", "file_metrics", "file_metrics_status",
    "timing", "byte_accounting", "result_byte_work", "correspondence_cost",
    "timing_source", "byte_accounting_source", "scope_complete", "omission_count",
    "omissions_status", "rational_fusion",
}


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise refuse(code)
    return value


def _identity(pair: Mapping[str, object]) -> tuple[int, str, int]:
    identity = _mapping(pair.get("identity"), "pair_comparison_identity")
    generation, task_id, repetition = (
        identity.get("generation"), identity.get("task_id"), identity.get("repetition")
    )
    if (
        type(generation) is not int or generation not in {1, 2}
        or type(task_id) is not str or not task_id
        or type(repetition) is not int or repetition < 1
    ):
        raise refuse("pair_comparison_identity")
    return generation, task_id, repetition


def _side(pair: Mapping[str, object] | None) -> dict[str, object] | None:
    if pair is None:
        return None
    observed = pair.get("journal_observation")
    observed_map = observed if isinstance(observed, Mapping) else {}
    grade = pair.get("journal_grade")
    grade_map = grade if isinstance(grade, Mapping) else {}
    result = _mapping(pair.get("result_v2"), "pair_comparison_result")
    cell = result.get("cell")
    cell_map = cell if isinstance(cell, Mapping) else {}
    correspondence = result.get("correspondence")
    correspondence_map = correspondence if isinstance(correspondence, Mapping) else {}
    rational = pair.get("rational_fusion")
    records = (
        rational.get("records") if isinstance(rational, Mapping)
        else rational if isinstance(rational, list) else None
    )
    rational_summary = {
        "status": "present" if isinstance(records, list) and records else "not_recorded",
        "record_count": len(records) if isinstance(records, list) else None,
    }
    grade_timing = grade_map.get("timing")
    observed_timing = observed_map.get("elapsed_ns")
    grade_bytes = grade_map.get("byte_accounting")
    observed_bytes = observed_map.get("byte_accounting")
    return {
        "classification": pair.get("classification"),
        "alignment": pair.get("alignment"),
        "execution_state": grade_map.get("execution_state") or observed_map.get("execution_state") or cell_map.get("execution_state"),
        "reason": cell_map.get("reason") or observed_map.get("reason"),
        "capability_state": grade_map.get("capability_state") or observed_map.get("capability_state"),
        "ann_exact_reference_recall": observed_map.get("ann_exact_reference_recall"),
        "scope_complete": observed_map.get("scope_complete"),
        "omission_count": observed_map.get("omission_count"),
        "omissions_status": observed_map.get("omissions_status"),
        "grading": {
            "rule": grade_map.get("grading_rule"),
            "state": grade_map.get("grading_state"),
            "quality_credit": grade_map.get("quality_credit"),
            "file_grading_policy_version": pair.get("file_grading_policy_version"),
        },
        "safety_refusal_correct": grade_map.get("safety_refusal_correct"),
        "absent_answer_correct": grade_map.get("absent_answer_correct"),
        "metrics": grade_map.get("metrics"),
        "file_metrics": grade_map.get("file_metrics"),
        "file_metrics_status": grade_map.get("file_metrics_status"),
        "timing": grade_timing if grade_timing is not None else observed_timing,
        "byte_accounting": grade_bytes if grade_bytes is not None else observed_bytes,
        "timing_source": (
            grade_map.get("timing_source") if grade_timing is not None
            else observed_map.get("timing_source")
        ),
        "byte_accounting_source": (
            grade_map.get("byte_accounting_source") if grade_bytes is not None
            else observed_map.get("byte_accounting_source")
        ),
        "result_byte_work": result.get("byte_work"),
        "correspondence_cost": correspondence_map.get("cost"),
        "rational_fusion": rational_summary,
    }


def _gap_reasons(pair: Mapping[str, object] | None) -> list[str]:
    if pair is None:
        return ["arm_identity_missing"]
    reasons: list[str] = []
    classification = pair.get("classification")
    if classification in _MISSING_CLASSIFICATIONS:
        reasons.append("classification_" + str(classification))
    elif classification in _UNAVAILABLE_CLASSIFICATIONS:
        reasons.append("classification_" + str(classification))
    alignment = pair.get("alignment")
    if isinstance(alignment, Mapping) and alignment.get("status") == "gapped":
        raw_reasons = alignment.get("reasons")
        if isinstance(raw_reasons, Sequence) and not isinstance(raw_reasons, (str, bytes)):
            reasons.extend(str(reason) for reason in raw_reasons)
    if pair.get("journal_grade") is None:
        reasons.append("grade_not_recorded")
    observation = pair.get("journal_observation")
    if isinstance(observation, Mapping):
        scope = observation.get("scope_complete")
        if scope is False:
            reasons.append("scope_incomplete")
        elif scope is not True:
            reasons.append("scope_not_recorded")
        if observation.get("omissions_status") != "recorded":
            reasons.append("omissions_not_recorded")
        elif observation.get("omission_count") not in (0, None):
            reasons.append("scope_omissions_present")
    else:
        reasons.extend(("scope_not_recorded", "omissions_not_recorded"))
    result = pair.get("result_v2")
    if not isinstance(result, Mapping):
        reasons.append("result_not_recorded")
    else:
        correspondence = result.get("correspondence")
        if not isinstance(correspondence, Mapping):
            reasons.append("correspondence_not_recorded")
        else:
            sidecar = correspondence.get("sidecar")
            verification = sidecar.get("verification") if isinstance(sidecar, Mapping) else None
            status = verification.get("status") if isinstance(verification, Mapping) else None
            if status != "verified":
                reasons.append("correspondence_not_verified")
        if result.get("byte_work") is None:
            reasons.append("byte_work_not_recorded")
    return sorted(set(reasons))


def _comparability(
    left: Mapping[str, object] | None, right: Mapping[str, object] | None,
) -> dict[str, object]:
    reasons = sorted(set(_gap_reasons(left) + _gap_reasons(right)))
    classes = {
        pair.get("classification")
        for pair in (left, right)
        if pair is not None
    }
    if reasons:
        status = "gap"
    elif classes & _QUALITY_ONLY_CLASSIFICATIONS:
        status = "stored_safety_or_absence"
    else:
        status = "stored_values"
    return {
        "status": status,
        "reasons": reasons,
        "quality_comparison": "not_emitted",
    }


def build_pair_comparisons(
    pairs: Sequence[Mapping[str, object]],
    plan_input_identities: Mapping[int, object],
) -> list[dict[str, object]]:
    """Emit only the three accepted fixed families, joined by recorded identity."""

    by_identity: dict[tuple[int, str, str, int], Mapping[str, object]] = {}
    for pair in pairs:
        generation, task_id, repetition = _identity(pair)
        identity = _mapping(pair["identity"], "pair_comparison_identity")
        arm_id = identity.get("arm_id")
        if type(arm_id) is not str or not arm_id:
            raise refuse("pair_comparison_arm")
        key = (generation, task_id, arm_id, repetition)
        if key in by_identity:
            raise refuse("pair_comparison_duplicate_identity")
        by_identity[key] = pair

    comparisons: list[dict[str, object]] = []
    for left_arm, right_arm in COMPARISON_FAMILIES:
        family = left_arm + "_vs_" + right_arm
        identities: list[tuple[int, str, int]] = []
        seen_identities: set[tuple[int, str, int]] = set()
        for pair in pairs:
            generation, task_id, repetition = _identity(pair)
            identity = _mapping(pair["identity"], "pair_comparison_identity")
            arm_id = identity.get("arm_id")
            candidate = (generation, task_id, repetition)
            if arm_id in {left_arm, right_arm} and candidate not in seen_identities:
                identities.append(candidate)
                seen_identities.add(candidate)
        for generation, task_id, repetition in identities:
            input_identity = plan_input_identities.get(generation)
            if type(input_identity) is not str or not input_identity:
                raise refuse("pair_comparison_input_identity")
            left = by_identity.get((generation, task_id, left_arm, repetition))
            right = by_identity.get((generation, task_id, right_arm, repetition))
            comparisons.append({
                "family": family,
                "left_arm": left_arm,
                "right_arm": right_arm,
                "identity": {
                    "generation": generation,
                    "task_id": task_id,
                    "repetition": repetition,
                },
                "declared_input_identity": input_identity,
                "left": _side(left),
                "right": _side(right),
                "comparability": _comparability(left, right),
            })
    return comparisons


def validate_pair_comparisons(value: object) -> None:
    """Validate the fixed comparison projection without authorizing inference."""

    if type(value) is not list:
        raise refuse("pair_report_comparisons")
    seen: set[tuple[str, int, str, int]] = set()
    for raw in value:
        comparison = _mapping(raw, "pair_report_comparison")
        if frozenset(comparison) != _COMPARISON_FIELDS:
            raise refuse("pair_report_comparison_fields")
        family = comparison.get("family")
        left_arm = comparison.get("left_arm")
        right_arm = comparison.get("right_arm")
        if (
            type(family) is not str or not family
            or type(left_arm) is not str or not left_arm
            or type(right_arm) is not str or not right_arm
        ):
            raise refuse("pair_report_comparison_identity")
        if (left_arm, right_arm) not in COMPARISON_FAMILIES or family != left_arm + "_vs_" + right_arm:
            raise refuse("pair_report_comparison_family")
        identity = _mapping(comparison.get("identity"), "pair_report_comparison_identity")
        generation, task_id, repetition = (
            identity.get("generation"), identity.get("task_id"), identity.get("repetition")
        )
        if (
            type(generation) is not int or generation not in {1, 2}
            or type(task_id) is not str or not task_id
            or type(repetition) is not int or repetition < 1
        ):
            raise refuse("pair_report_comparison_identity")
        key = (family, generation, task_id, repetition)
        if key in seen:
            raise refuse("pair_report_comparison_duplicate_identity")
        seen.add(key)
        input_identity = comparison.get("declared_input_identity")
        if type(input_identity) is not str or not input_identity:
            raise refuse("pair_report_comparison_input_identity")
        for side_name in ("left", "right"):
            side = comparison.get(side_name)
            if side is None:
                continue
            side_map = _mapping(side, "pair_report_comparison_side")
            if frozenset(side_map) != _COMPARISON_SIDE_FIELDS:
                raise refuse("pair_report_comparison_side_fields")
        comparability = _mapping(comparison.get("comparability"), "pair_report_comparability")
        if frozenset(comparability) != {"status", "reasons", "quality_comparison"}:
            raise refuse("pair_report_comparability")
        if comparability.get("status") not in {"gap", "stored_values", "stored_safety_or_absence"}:
            raise refuse("pair_report_comparability")
        reasons = comparability.get("reasons")
        if type(reasons) is not list or any(type(reason) is not str for reason in reasons):
            raise refuse("pair_report_comparability")
        if comparability.get("quality_comparison") != "not_emitted":
            raise refuse("pair_report_comparability")


__all__ = ["COMPARISON_FAMILIES", "build_pair_comparisons", "validate_pair_comparisons"]
