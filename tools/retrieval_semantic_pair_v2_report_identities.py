"""Closed plan and fixed-comparison identity validation for the V2 report."""

from __future__ import annotations

from collections.abc import Mapping

from retrieval_semantic_experiment_contracts import canonical_json_bytes
from retrieval_semantic_pair_artifacts import digest_bytes, refuse
from retrieval_semantic_pair_v2_comparison_validation import validate_comparison_side


COMPARISON_FAMILIES = (
    ("postgres_native_fts:postgresql", "exact_vector"),
    ("postgres_native_fts:postgresql", "hybrid_rrf"),
    ("exact_vector", "hnsw_vector"),
)
PLAN_FIELDS = {
    "schema", "fixture_id", "task_ids", "task_digests", "arms", "repetitions", "freeze_sha256",
    "policy_digest", "publication_identity", "input_identity", "result_v2_sha256",
    "representation_report_identity", "artifact_profile_identity", "controller_admission_sha256",
    "task_identity", "source_closure",
}
COMPARISON_FIELDS = {
    "family", "left_arm", "right_arm", "identity", "declared_input_identity", "left", "right",
    "comparability",
}


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise refuse(code)
    return value


def validate_plan(value: object) -> tuple[tuple[str, ...], tuple[str, ...], int]:
    plan = _mapping(value, "pair_v2_plan")
    if frozenset(plan) != PLAN_FIELDS or plan.get("schema") != "cloe-w5-semantic-experiment-v1":
        raise refuse("pair_v2_plan")
    tasks, arms = plan.get("task_ids"), plan.get("arms")
    if (
        type(tasks) is not list or not tasks or any(type(item) is not str or not item for item in tasks)
        or len(set(tasks)) != len(tasks)
        or type(arms) is not list or not arms or any(type(item) is not str or not item for item in arms)
        or len(set(arms)) != len(arms)
    ):
        raise refuse("pair_v2_plan_population")
    task_digests = plan.get("task_digests")
    if task_digests is not None:
        if type(task_digests) is not list or len(task_digests) != len(tasks):
            raise refuse("pair_v2_plan_task_identity")
        if any(
            type(digest) is not str or len(digest) != 71 or not digest.startswith("sha256:")
            or any(char not in "0123456789abcdef" for char in digest[7:])
            for digest in task_digests
        ):
            raise refuse("pair_v2_plan_task_identity")
    repetitions = plan.get("repetitions")
    if type(repetitions) is not int or not 1 <= repetitions <= 100:
        raise refuse("pair_v2_plan_repetitions")
    for field in (
        "freeze_sha256", "policy_digest", "publication_identity", "result_v2_sha256",
        "representation_report_identity", "artifact_profile_identity", "controller_admission_sha256",
        "input_identity",
    ):
        digest = plan.get(field)
        if digest is not None and (
            type(digest) is not str or len(digest) != 71 or not digest.startswith("sha256:")
            or any(char not in "0123456789abcdef" for char in digest[7:])
        ):
            raise refuse("pair_v2_plan_identity")
    if plan.get("input_identity") is None:
        raise refuse("pair_v2_plan_input_identity")
    task_identity = _mapping(plan.get("task_identity"), "pair_v2_plan_task_identity")
    if frozenset(task_identity) != {"count", "sha256"} or task_identity.get("count") != len(tasks):
        raise refuse("pair_v2_plan_task_identity")
    if task_digests is None:
        if task_identity.get("sha256") is not None:
            raise refuse("pair_v2_plan_task_identity")
    else:
        task_pairs = [[task, digest] for task, digest in zip(tasks, task_digests, strict=True)]
        if task_identity.get("sha256") != digest_bytes(canonical_json_bytes(task_pairs)):
            raise refuse("pair_v2_plan_task_identity")
    closure_value = plan.get("source_closure")
    if closure_value is None:
        return tuple(tasks), tuple(arms), repetitions
    closure = _mapping(closure_value, "pair_v2_plan_source_closure")
    if frozenset(closure) != {"count", "sha256"}:
        raise refuse("pair_v2_plan_source_closure")
    count, digest = closure.get("count"), closure.get("sha256")
    if count is None and digest is None:
        return tuple(tasks), tuple(arms), repetitions
    if (
        type(count) is not int or count < 0
        or type(digest) is not str or len(digest) != 71 or not digest.startswith("sha256:")
        or any(char not in "0123456789abcdef" for char in digest[7:])
    ):
        raise refuse("pair_v2_plan_source_closure")
    return tuple(tasks), tuple(arms), repetitions


def validate_comparison(value: object) -> None:
    comparison = _mapping(value, "pair_v2_comparison")
    if frozenset(comparison) != COMPARISON_FIELDS:
        raise refuse("pair_v2_comparison_fields")
    family, left_arm, right_arm = (
        comparison.get("family"), comparison.get("left_arm"), comparison.get("right_arm")
    )
    if (
        type(family) is not str or type(left_arm) is not str or type(right_arm) is not str
        or (left_arm, right_arm) not in COMPARISON_FAMILIES
        or family != left_arm + "_vs_" + right_arm
    ):
        raise refuse("pair_v2_comparison_identity")
    identity = _mapping(comparison.get("identity"), "pair_v2_comparison_identity")
    repetition = identity.get("repetition")
    if (
        type(identity.get("generation")) is not int or identity.get("generation") not in {1, 2}
        or type(identity.get("task_id")) is not str or not identity.get("task_id")
    ):
        raise refuse("pair_v2_comparison_identity")
    if type(repetition) is not int:
        raise refuse("pair_v2_comparison_identity")
    if repetition < 1:
        raise refuse("pair_v2_comparison_identity")
    input_identity = comparison.get("declared_input_identity")
    if (
        type(input_identity) is not str or len(input_identity) != 71
        or not input_identity.startswith("sha256:")
        or any(char not in "0123456789abcdef" for char in input_identity[7:])
    ):
        raise refuse("pair_v2_comparison_identity")
    validate_comparison_side(comparison.get("left"))
    validate_comparison_side(comparison.get("right"))
    comparability = _mapping(comparison.get("comparability"), "pair_v2_comparability")
    if frozenset(comparability) != {"status", "reasons", "quality_comparison", "context_gaps"}:
        raise refuse("pair_v2_comparability")
    if comparability.get("quality_comparison") != "not_emitted":
        raise refuse("pair_v2_comparability")
    if comparability.get("status") not in {"gap", "stored_values", "stored_safety_or_absence"}:
        raise refuse("pair_v2_comparability")
    for field in ("reasons", "context_gaps"):
        values = comparability.get(field)
        if type(values) is not list or any(type(item) is not str for item in values):
            raise refuse("pair_v2_comparability")


__all__ = ["COMPARISON_FAMILIES", "validate_comparison", "validate_plan"]
