"""Opt-in W5 result-v2 retention; the six legacy journal members stay intact."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import math
from typing import TypedDict, cast

from retrieval_evaluation_accounting import EvaluatorByteBreakdownV1
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_experiment_artifacts import (
    ATTEMPT_IDS, MEMBER_LIMITS, MEMBER_NAMES,
)
from retrieval_semantic_experiment_contracts import (
    ExperimentCell,
    ExperimentPlan,
    ExperimentRefusal,
)
from retrieval_semantic_experiment_scope import (
    CorrespondenceCostSample,
    W5_EXPERIMENT_RESULT_SCHEMA_V2,
)
from retrieval_semantic_baseline_result_integrity import (
    require_completed_records,
    validate_correspondence_sidecar,
)

RESULT_SCHEMA = W5_EXPERIMENT_RESULT_SCHEMA_V2
_RESULT_FIELDS = frozenset({
    "schema", "attempt_id", "generation", "status", "failure_code",
    "plan", "cells", "correspondence", "byte_work", "raw_journal",
})
_IDENTITY_FIELDS = frozenset({"arm_id", "task_id", "repetition"})
_CELL_FIELDS = frozenset({
    "arm_id", "task_id", "execution_state", "reason", "candidates",
    "elapsed_ns", "query_bytes", "cleanup_status",})
_CORRESPONDENCE_COST_FIELDS = frozenset({
    "correspondence_verification_ns", "correspondence_verification_bytes_read",
    "correspondence_failures", "known_artifact_bytes_read",
    "known_materialized_bytes_read",})
_BYTE_FIELDS = frozenset({
    "schema_version", "raw_process_stdout_bytes", "direct_selected_text_bytes",
    "native_process_stdout_cap_bytes", "decoded_candidate_count",
    "returned_hit_count", "serialized_envelope_bytes",
    "observed_output_payload_bytes", "correspondence_verification_bytes_read",
    "correspondence_verification_ns",})
_RAW_REF_FIELDS = frozenset({"length", "sha256"})
_PLAN_FIELDS = frozenset({
    "schema", "attempt_id", "generation", "task_ids", "task_digests",
    "input_identity", "representation_report_identity", "publication_identity",
    "artifact_profile_identity", "controller_admission_sha256", "source_closure",
    "fixture_id", "freeze_sha256", "policy_digest", "arms", "repetitions",
    "timeout_policy",})

class ResultRefusal(ExperimentRefusal):
    """Public-safe refusal for malformed or unbound result-v2 data."""


class _ByteMeasurement(TypedDict):
    schema_version: str
    raw_process_stdout_bytes: int | None
    direct_selected_text_bytes: int | None
    native_process_stdout_cap_bytes: int | None
    decoded_candidate_count: int
    returned_hit_count: int
    serialized_envelope_bytes: int
    observed_output_payload_bytes: int | None
    correspondence_verification_bytes_read: int
    correspondence_verification_ns: int


class _CorrespondenceMeasurement(TypedDict):
    correspondence_verification_ns: int
    correspondence_verification_bytes_read: int | None
    correspondence_failures: int
    known_artifact_bytes_read: int
    known_materialized_bytes_read: int

def _refuse(code: str) -> ResultRefusal: return ResultRefusal(code)

def _sha(raw: bytes) -> str: return "sha256:" + hashlib.sha256(raw).hexdigest()


def _json_value(value: object) -> object:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise _refuse("result_nonfinite_value")
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise _refuse("result_object_key")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise _refuse("result_private_value")




def _digest(value: object, code: str) -> str:
    if (
        type(value) is not str or len(value) != 71 or not value.startswith("sha256:")
        or any(char not in "0123456789abcdef" for char in value[7:])
    ):
        raise _refuse(code)
    return value

def _failure_code(value: object) -> str:
    if (
        type(value) is not str or not value or value != value.strip()
        or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_.-" for char in value)
    ):
        raise _refuse("result_failure_code")
    return value

def _identity(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or frozenset(value) != _IDENTITY_FIELDS:
        raise _refuse("result_identity_fields")
    result = dict(value)
    for name in ("arm_id", "task_id"):
        if type(result[name]) is not str or not result[name].strip():
            raise _refuse("result_identity_value")
    if type(result["repetition"]) is not int or result["repetition"] < 1:
        raise _refuse("result_identity_repetition")
    return result


def _validate_plan(value: object, attempt_id: str, generation: int) -> dict[str, object]:
    if not isinstance(value, Mapping) or frozenset(value) != _PLAN_FIELDS:
        raise _refuse("result_plan_fields")
    ready = _json_value(value)
    if type(ready) is not dict:
        raise _refuse("result_plan_fields")
    plan = ready
    if plan.get("schema") != "cloe-w5-semantic-experiment-v1":
        raise _refuse("result_plan_schema")
    if plan.get("attempt_id") != attempt_id or plan.get("generation") != generation:
        raise _refuse("result_plan_identity")
    if any(type(plan.get(name)) is not list for name in ("task_ids", "task_digests", "arms")):
        raise _refuse("result_plan_lists")
    source_closure = plan.get("source_closure")
    if not isinstance(source_closure, Mapping):
        raise _refuse("result_plan_closure")
    try:
        ExperimentPlan(
            attempt_id=plan["attempt_id"], generation=plan["generation"],
            task_ids=tuple(plan["task_ids"]), task_digests=tuple(plan["task_digests"]),
            input_identity=plan["input_identity"],
            representation_report_identity=plan["representation_report_identity"],
            publication_identity=plan["publication_identity"],
            artifact_profile_identity=plan["artifact_profile_identity"],
            controller_admission_sha256=plan["controller_admission_sha256"],
            source_closure=tuple(source_closure.items()),
            fixture_id=plan["fixture_id"], freeze_sha256=plan["freeze_sha256"],
            policy_digest=plan["policy_digest"], arms=tuple(plan["arms"]),
            repetitions=plan["repetitions"],
        ).validate()
    except ResultRefusal:
        raise
    except Exception as error:
        raise _refuse("result_plan_invalid") from error
    return plan


def _validate_cell(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or frozenset(value) != _CELL_FIELDS:
        raise _refuse("result_cell_fields")
    ready = _json_value(value)
    if type(ready) is not dict:
        raise _refuse("result_cell_fields")
    cell = ready
    states = {state.value for state in ExecutionState}
    if type(cell["execution_state"]) is not str or cell["execution_state"] not in states:
        raise _refuse("result_cell_state")
    try:
        ExperimentCell(
            cell["arm_id"], cell["task_id"],
            ExecutionState(cell["execution_state"]),
            cell["reason"], tuple(cell["candidates"]), cell["elapsed_ns"],
            cell["query_bytes"], cell["cleanup_status"],
        ).validate()
    except Exception as error:
        raise _refuse("result_cell_invalid") from error
    return cell


def _validate_measurement(value: object, *, kind: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _refuse("result_" + kind + "_mapping")
    safe = _json_value(value)
    if type(safe) is not dict:
        raise _refuse("result_" + kind + "_mapping")
    mapping = cast(dict[str, object], safe)
    if kind == "byte_work":
        if frozenset(mapping) != _BYTE_FIELDS:
            raise _refuse("result_byte_work_fields")
        try:
            # Closed keys were checked above; the owner validates every runtime
            # value after this static constructor-shape cast, without coercion.
            EvaluatorByteBreakdownV1(**cast(_ByteMeasurement, mapping)).validate()
        except Exception as error:
            raise _refuse("result_byte_work_invalid") from error
    elif frozenset(mapping) != _CORRESPONDENCE_COST_FIELDS:
        raise _refuse("result_correspondence_cost_fields")
    else:
        try:
            CorrespondenceCostSample(**cast(_CorrespondenceMeasurement, mapping)).validate()
        except Exception as error:
            raise _refuse("result_correspondence_cost_invalid") from error
    return mapping


def _validate_raw_journal(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or frozenset(value) != set(MEMBER_NAMES):
        raise _refuse("result_raw_journal_members")
    result: dict[str, object] = {}
    for name in MEMBER_NAMES:
        entry = value[name]
        if not isinstance(entry, Mapping) or frozenset(entry) != _RAW_REF_FIELDS:
            raise _refuse("result_raw_journal_ref")
        length = entry["length"]
        if type(length) is not int or length < 0 or length > MEMBER_LIMITS[name]:
            raise _refuse("result_raw_journal_length")
        result[name] = {
            "length": length,
            "sha256": _digest(entry["sha256"], "result_raw_journal_digest"),
        }
    return result


def _bind_record_identity(
    raw: Mapping[str, object],
    *,
    plan: Mapping[str, object] | None,
    seen: set[tuple[str, str, int]],
) -> tuple[dict[str, object], str, str]:
    identity = _identity(raw["identity"])
    arm_id = cast(str, identity["arm_id"])
    task_id = cast(str, identity["task_id"])
    repetition = cast(int, identity["repetition"])
    if plan is not None:
        plan_arms = plan["arms"]
        plan_task_ids = plan["task_ids"]
        plan_repetitions = plan["repetitions"]
        if (
            not isinstance(plan_arms, list)
            or not isinstance(plan_task_ids, list)
            or type(plan_repetitions) is not int
        ):
            raise _refuse("result_plan_lists")
        allowed_arms = cast(list[object], plan_arms)
        allowed_task_ids = cast(list[object], plan_task_ids)
        max_repetitions = plan_repetitions
        if (
            arm_id not in allowed_arms
            or task_id not in allowed_task_ids
            or repetition > max_repetitions
        ):
            raise _refuse("result_identity_unbound")
    key = (arm_id, task_id, repetition)
    if key in seen:
        raise _refuse("result_duplicate_identity")
    seen.add(key)
    return identity, arm_id, task_id


def _validate_records(
    value: object, *, kind: str, plan: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    if type(value) is not list:
        raise _refuse("result_" + kind + "_list")
    records: list[dict[str, object]] = []
    seen: set[tuple[str, str, int]] = set()
    for raw in value:
        fields = {"identity", "cell"} if kind == "cells" else (
            {"identity", "sidecar", "cost"} if kind == "correspondence"
            else {"identity", "accounting"}
        )
        if not isinstance(raw, Mapping) or frozenset(raw) != fields:
            raise _refuse("result_" + kind + "_fields")
        identity, arm_id, task_id = _bind_record_identity(
            raw, plan=plan, seen=seen,
        )
        record: dict[str, object] = {"identity": identity}
        if kind == "cells":
            cell = _validate_cell(raw["cell"])
            if cell.get("arm_id") != arm_id or cell.get("task_id") != task_id:
                raise _refuse("result_cell_identity")
            record["cell"] = cell
        elif kind == "correspondence":
            sidecar = raw["sidecar"]
            if not isinstance(sidecar, Mapping):
                raise _refuse("result_sidecar_mapping")
            safe_sidecar = _json_value(sidecar)
            if type(safe_sidecar) is not dict:
                raise _refuse("result_sidecar_mapping")
            if type(safe_sidecar.get("schema")) is not str or not safe_sidecar["schema"]:
                raise _refuse("result_sidecar_schema")
            if (
                safe_sidecar.get("arm_id") != arm_id
                or safe_sidecar.get("task_id") != task_id
            ):
                raise _refuse("result_sidecar_identity")
            cost = _validate_measurement(raw["cost"], kind="correspondence_cost")
            try:
                validate_correspondence_sidecar(
                    safe_sidecar, arm_id=arm_id, task_id=task_id, cost=cost,
                )
            except ExperimentRefusal as error:
                raise _refuse(error.code) from error
            record["sidecar"] = safe_sidecar
            record["cost"] = cost
        else:
            record["accounting"] = _validate_measurement(raw["accounting"], kind="byte_work")
        records.append(record)
    return records


def _validate_result(value: Mapping[str, object]) -> None:
    if not isinstance(value, Mapping) or frozenset(value) != _RESULT_FIELDS:
        raise _refuse("result_fields")
    if value["schema"] != RESULT_SCHEMA:
        raise _refuse("result_schema")
    attempt_id = value["attempt_id"]
    generation = value["generation"]
    status = value["status"]
    if type(attempt_id) is not str or attempt_id not in ATTEMPT_IDS:
        raise _refuse("result_attempt_id")
    if type(generation) is not int or generation not in (1, 2):
        raise _refuse("result_generation")
    if type(status) is not str or status not in {"completed", "failed"}:
        raise _refuse("result_status")
    failure = value["failure_code"]
    if status == "failed":
        _failure_code(failure)
    if status == "completed" and failure is not None:
        raise _refuse("result_failure_code")
    plan = _validate_plan(value["plan"], attempt_id, generation)
    cells = _validate_records(value["cells"], kind="cells", plan=plan)
    correspondence = _validate_records(
        value["correspondence"], kind="correspondence", plan=plan,
    )
    byte_work = _validate_records(value["byte_work"], kind="byte_work", plan=plan)
    if status == "completed":
        try:
            require_completed_records(
                plan, cells=cells, correspondence=correspondence, byte_work=byte_work,
            )
        except ExperimentRefusal as error:
            raise _refuse(error.code) from error
    _validate_raw_journal(value["raw_journal"])
