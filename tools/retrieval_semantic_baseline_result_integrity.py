"""Closed result-v2 integrity gates shared by validation and frame decoding."""

from __future__ import annotations

from collections.abc import Mapping
from typing import NoReturn, cast

from retrieval_semantic_experiment_contracts import ExperimentRefusal, canonical_json_bytes
from retrieval_semantic_experiment_scope import (
    BASELINE_ARM_OBSERVED_BACKENDS,
    BASELINE_ARM_TARGET_BACKENDS,
    W5_BASELINE_CORRESPONDENCE_SCHEMA_V1,
)

_SIDECAR_FIELDS = frozenset({
    "schema", "arm_id", "task_id", "observed_backend", "target_backend",
    "verification",
})
_VERIFICATION_FIELDS = frozenset({"status", "gap_reason", "verified", "cost"})
_COST_FIELDS = frozenset({
    "correspondence_verification_ns", "correspondence_verification_bytes_read",
    "correspondence_failures", "known_artifact_bytes_read",
    "known_materialized_bytes_read",
})
_STATUSES = frozenset({
    "verified", "gap", "unavailable", "refused", "stale", "not_applicable",
})


def _refuse(code: str) -> NoReturn:
    raise ExperimentRefusal(code)


def validate_correspondence_sidecar(
    sidecar: Mapping[str, object],
    *,
    arm_id: str,
    task_id: str,
    cost: Mapping[str, object],
) -> None:
    """Validate the public sidecar identity and its nested cost witness."""
    if not _SIDECAR_FIELDS <= frozenset(sidecar):
        _refuse("result_sidecar_fields")
    if sidecar.get("schema") != W5_BASELINE_CORRESPONDENCE_SCHEMA_V1:
        _refuse("result_sidecar_schema")
    if sidecar.get("arm_id") != arm_id or sidecar.get("task_id") != task_id:
        _refuse("result_sidecar_identity")
    expected_observed = BASELINE_ARM_OBSERVED_BACKENDS.get(arm_id)
    expected_target = BASELINE_ARM_TARGET_BACKENDS.get(arm_id)
    if expected_observed is None or expected_target is None:
        _refuse("result_sidecar_arm")
    if (
        sidecar.get("observed_backend") != expected_observed
        or sidecar.get("target_backend") != expected_target
    ):
        _refuse("result_sidecar_backend")

    raw_verification = sidecar.get("verification")
    if not isinstance(raw_verification, Mapping):
        _refuse("result_sidecar_verification")
    if frozenset(raw_verification) != _VERIFICATION_FIELDS:
        _refuse("result_sidecar_verification_fields")
    verification = cast(dict[str, object], raw_verification)
    status = verification.get("status")
    if type(status) is not str or status not in _STATUSES:
        _refuse("result_sidecar_status")
    verified = verification.get("verified")
    if type(verified) is not bool or verified != (status == "verified"):
        _refuse("result_sidecar_verified")
    gap_reason = verification.get("gap_reason")
    if gap_reason is not None and (type(gap_reason) is not str or not gap_reason):
        _refuse("result_sidecar_gap_reason")
    if status == "verified" and gap_reason is not None:
        _refuse("result_sidecar_gap_reason")

    raw_cost = verification.get("cost")
    if not isinstance(raw_cost, Mapping) or frozenset(raw_cost) != _COST_FIELDS:
        _refuse("result_sidecar_cost")
    nested_cost = cast(dict[str, object], raw_cost)
    if canonical_json_bytes(nested_cost) != canonical_json_bytes(cost):
        _refuse("result_sidecar_cost_mismatch")
    if status == "verified" and cost.get("correspondence_failures") != 0:
        _refuse("result_verified_cost_failures")


def _axis_strings(plan: Mapping[str, object], name: str) -> tuple[str, ...]:
    value = plan.get(name)
    if not isinstance(value, list) or any(type(item) is not str for item in value):
        _refuse("result_plan_lists")
    return tuple(cast(str, item) for item in value)


def _repetitions(plan: Mapping[str, object]) -> int:
    value = plan.get("repetitions")
    if type(value) is not int or value < 1:
        _refuse("result_plan_repetitions")
    return value


def _record_keys(
    records: list[dict[str, object]], *, kind: str,
) -> set[tuple[str, str, int]]:
    result: set[tuple[str, str, int]] = set()
    for record in records:
        raw_identity = record.get("identity")
        if not isinstance(raw_identity, Mapping):
            _refuse("result_" + kind + "_identity")
        identity = cast(dict[str, object], raw_identity)
        arm_id = identity.get("arm_id")
        task_id = identity.get("task_id")
        repetition = identity.get("repetition")
        if (
            type(arm_id) is not str or type(task_id) is not str
            or type(repetition) is not int
        ):
            _refuse("result_" + kind + "_identity")
        key = (arm_id, task_id, repetition)
        if key in result:
            _refuse("result_duplicate_identity")
        result.add(key)
    return result


def require_completed_records(
    plan: Mapping[str, object],
    *,
    cells: list[dict[str, object]],
    correspondence: list[dict[str, object]],
    byte_work: list[dict[str, object]],
) -> None:
    """Require every planned cell and every required baseline/native witness."""
    arms = _axis_strings(plan, "arms")
    task_ids = _axis_strings(plan, "task_ids")
    repetitions = _repetitions(plan)
    planned = {
        (arm_id, task_id, repetition)
        for arm_id in arms
        for task_id in task_ids
        for repetition in range(1, repetitions + 1)
    }
    if _record_keys(cells, kind="cells") != planned:
        _refuse("result_completed_cells")

    baseline_arms = tuple(arm for arm in arms if arm in BASELINE_ARM_TARGET_BACKENDS)
    expected_correspondence = {
        (arm_id, task_id, repetition)
        for arm_id in baseline_arms
        for task_id in task_ids
        for repetition in range(1, repetitions + 1)
    }
    if _record_keys(correspondence, kind="correspondence") != expected_correspondence:
        _refuse("result_completed_correspondence")

    native_arms = ("native_tools_baseline",) if "native_tools_baseline" in arms else ()
    expected_byte_work = {
        (arm_id, task_id, repetition)
        for arm_id in native_arms
        for task_id in task_ids
        for repetition in range(1, repetitions + 1)
    }
    if _record_keys(byte_work, kind="byte_work") != expected_byte_work:
        _refuse("result_completed_byte_work")
