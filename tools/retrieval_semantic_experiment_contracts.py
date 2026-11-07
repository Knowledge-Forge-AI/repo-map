"""Immutable plans and public-safe cells for the optional W5 experiment.

The plan is deliberately independent of PostgreSQL and of the component
supervisor.  It is the small boundary that makes the calibration population,
source closure, and controller admission visible before a query is attempted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any

from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask


EXPERIMENT_SCHEMA = "cloe-w5-semantic-experiment-v1"
TIMEOUT_POLICY: Mapping[str, int] = MappingProxyType({
    "controller_admission_seconds": 120,
    "model_seconds": 550,
    "component_response_seconds": 600,
})
EXPERIMENT_ARMS: tuple[str, ...] = (
    "native_tools_baseline",
    "current_graph_baseline:sqlite",
    "current_graph_baseline:postgresql",
    "captured_projection_reference:sqlite",
    "captured_projection_reference:postgresql",
    "postgres_native_fts:postgresql",
    "exact_vector",
    "hnsw_vector",
    "hybrid_rrf",
)
_ATTEMPT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ExperimentRefusal(ValueError):
    """Public-safe refusal code; payloads and host paths are not echoed."""

    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or not code or any(ord(c) < 32 for c in code):
            code = "experiment_refused"
        self.code = code
        super().__init__(code)


def canonical_json_bytes(value: object) -> bytes:
    """Encode the stable JSON form used by plans, request records, and hashes."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError) as exc:
        raise ExperimentRefusal("noncanonical_json") from exc


def digest_bytes(value: bytes) -> str:
    if type(value) is not bytes:
        raise ExperimentRefusal("digest_input")
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest_json(value: object) -> str:
    return digest_bytes(canonical_json_bytes(value))


def _digest(value: object, code: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ExperimentRefusal(code)
    return value


def _portable_name(value: object, *, code: str) -> str:
    if type(value) is not str or _ATTEMPT.fullmatch(value) is None:
        raise ExperimentRefusal(code)
    return value


def _closure(value: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping) or not value:
        raise ExperimentRefusal("source_closure_required")
    result: list[tuple[str, str]] = []
    for name, digest in sorted(value.items()):
        if (
            type(name) is not str
            or not name
            or name.startswith(("/", "\\"))
            or "\\" in name
            or ":" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))
        ):
            raise ExperimentRefusal("unsafe_source_closure")
        result.append((name, _digest(digest, "invalid_source_digest")))
    return tuple(result)


def _task_digest(task: EvaluationTask) -> str:
    if type(task) is not EvaluationTask:
        raise ExperimentRefusal("invalid_calibration_task")
    try:
        task.validate()
        mapping = task.to_dict()
    except Exception as exc:
        raise ExperimentRefusal("invalid_calibration_task") from exc
    if not isinstance(mapping, Mapping):
        raise ExperimentRefusal("invalid_calibration_task")
    return digest_json(mapping)


def _require_evaluation_task(value: object) -> EvaluationTask:
    if type(value) is not EvaluationTask:
        raise ExperimentRefusal("invalid_calibration_task")
    assert isinstance(value, EvaluationTask)
    return value


def validate_calibration_tasks(
    tasks: object,
    *, generation: int | None = None, require_nonempty: bool = True
) -> tuple[EvaluationTask, ...]:
    """Validate the selected calibration subset without reading held-out gold."""
    if not isinstance(tasks, Sequence) or isinstance(tasks, (str, bytes)):
        raise ExperimentRefusal("invalid_calibration_tasks")
    task_values: tuple[object, ...] = tuple(tasks)
    frozen = tuple(_require_evaluation_task(value) for value in task_values)
    if require_nonempty and not frozen:
        raise ExperimentRefusal("empty_calibration_tasks")
    if len(frozen) > 24:
        raise ExperimentRefusal("calibration_task_cap")
    seen: set[str] = set()
    for task in frozen:
        try:
            task.validate()
        except Exception as exc:
            raise ExperimentRefusal("invalid_calibration_task") from exc
        task_id = task.task_id
        if type(task_id) is not str or not task_id or task_id in seen:
            raise ExperimentRefusal("duplicate_calibration_task")
        if task.split != "calibration":
            raise ExperimentRefusal("held_out_execution_forbidden")
        task_generation = task.generation
        if type(task_generation) is not int or task_generation not in (1, 2):
            raise ExperimentRefusal("invalid_calibration_generation")
        if generation is not None and task_generation != generation:
            raise ExperimentRefusal("calibration_generation_mismatch")
        seen.add(task_id)
        _task_digest(task)
    return frozen


@dataclass(frozen=True)
class ExperimentPlan:
    """Pre-query identity for one generation's public calibration exchange."""

    attempt_id: str
    generation: int
    task_ids: tuple[str, ...]
    task_digests: tuple[str, ...]
    input_identity: str
    representation_report_identity: str
    publication_identity: str
    artifact_profile_identity: str
    controller_admission_sha256: str
    source_closure: tuple[tuple[str, str], ...]
    fixture_id: str
    freeze_sha256: str
    policy_digest: str
    arms: tuple[str, ...] = EXPERIMENT_ARMS
    repetitions: int = 3

    def validate(self) -> ExperimentPlan:
        _portable_name(self.attempt_id, code="invalid_attempt_id")
        if type(self.generation) is not int or self.generation not in (1, 2):
            raise ExperimentRefusal("invalid_generation")
        if not self.task_ids or len(self.task_ids) > 24 or len(set(self.task_ids)) != len(self.task_ids):
            raise ExperimentRefusal("invalid_task_population")
        if len(self.task_digests) != len(self.task_ids):
            raise ExperimentRefusal("task_digest_count_mismatch")
        for task_id in self.task_ids:
            if type(task_id) is not str or not task_id:
                raise ExperimentRefusal("invalid_task_id")
        for digest in self.task_digests:
            _digest(digest, "invalid_task_digest")
        for name, value in (
            ("input_identity", self.input_identity),
            ("representation_report_identity", self.representation_report_identity),
            ("publication_identity", self.publication_identity),
            ("artifact_profile_identity", self.artifact_profile_identity),
            ("controller_admission_sha256", self.controller_admission_sha256),
            ("freeze_sha256", self.freeze_sha256),
            ("policy_digest", self.policy_digest),
        ):
            _digest(value, "invalid_" + name)
        if type(self.fixture_id) is not str or not self.fixture_id.strip():
            raise ExperimentRefusal("invalid_fixture_id")
        _closure(dict(self.source_closure))
        if not self.arms or len(set(self.arms)) != len(self.arms):
            raise ExperimentRefusal("invalid_experiment_arms")
        if any(type(arm) is not str or arm not in EXPERIMENT_ARMS for arm in self.arms):
            raise ExperimentRefusal("unsupported_experiment_arm")
        if type(self.repetitions) is not int or self.repetitions != 3:
            raise ExperimentRefusal("invalid_repetition_count")
        if TIMEOUT_POLICY["model_seconds"] >= TIMEOUT_POLICY["component_response_seconds"]:
            raise ExperimentRefusal("invalid_timeout_policy")
        return self

    def to_mapping(self) -> dict[str, object]:
        self.validate()
        return {
            "schema": EXPERIMENT_SCHEMA,
            "attempt_id": self.attempt_id,
            "generation": self.generation,
            "task_ids": list(self.task_ids),
            "task_digests": list(self.task_digests),
            "input_identity": self.input_identity,
            "representation_report_identity": self.representation_report_identity,
            "publication_identity": self.publication_identity,
            "artifact_profile_identity": self.artifact_profile_identity,
            "controller_admission_sha256": self.controller_admission_sha256,
            "source_closure": dict(self.source_closure),
            "fixture_id": self.fixture_id,
            "freeze_sha256": self.freeze_sha256,
            "policy_digest": self.policy_digest,
            "arms": list(self.arms),
            "repetitions": self.repetitions,
            "timeout_policy": dict(TIMEOUT_POLICY),
        }


def make_plan(
    *, attempt_id: str, generation: int, tasks: Sequence[EvaluationTask], input_identity: str,
    representation_report_identity: str, publication_identity: str,
    artifact_profile_identity: str, controller_admission_sha256: str,
    source_closure: Mapping[str, str], arms: Sequence[str] = EXPERIMENT_ARMS,
    fixture_id: str = "mixed-v1", freeze_sha256: str | None = None,
    policy_digest: str | None = None,
) -> ExperimentPlan:
    selected = validate_calibration_tasks(tasks, generation=generation)
    plan = ExperimentPlan(
        attempt_id=_portable_name(attempt_id, code="invalid_attempt_id"),
        generation=generation,
        task_ids=tuple(task.task_id for task in selected),
        task_digests=tuple(_task_digest(task) for task in selected),
        input_identity=_digest(input_identity, "invalid_input_identity"),
        representation_report_identity=_digest(
            representation_report_identity, "invalid_representation_identity"
        ),
        publication_identity=_digest(publication_identity, "invalid_publication_identity"),
        artifact_profile_identity=_digest(artifact_profile_identity, "invalid_artifact_identity"),
        controller_admission_sha256=_digest(
            controller_admission_sha256, "invalid_admission_identity"
        ),
        source_closure=_closure(source_closure),
        fixture_id=fixture_id,
        freeze_sha256=_digest(freeze_sha256, "invalid_freeze_identity") if freeze_sha256 is not None else digest_json({"fixture_id": fixture_id}),
        policy_digest=_digest(policy_digest, "invalid_policy_identity") if policy_digest is not None else digest_json({"fixture_id": fixture_id}),
        arms=tuple(arms),
    )
    return plan.validate()


@dataclass(frozen=True)
class ExperimentCell:
    """One arm/task outcome; unavailable and not-run remain first-class states."""

    arm_id: str
    task_id: str
    execution_state: ExecutionState
    reason: str | None = None
    candidates: tuple[Mapping[str, Any], ...] = ()
    elapsed_ns: int | None = None
    query_bytes: int | None = None
    cleanup_status: str = "pending"

    def validate(self) -> ExperimentCell:
        if type(self.arm_id) is not str or self.arm_id not in EXPERIMENT_ARMS:
            raise ExperimentRefusal("invalid_experiment_arm")
        if type(self.task_id) is not str or not self.task_id:
            raise ExperimentRefusal("invalid_task_id")
        if not isinstance(self.execution_state, ExecutionState):
            raise ExperimentRefusal("invalid_execution_state")
        if self.reason is not None and (type(self.reason) is not str or not self.reason):
            raise ExperimentRefusal("invalid_cell_reason")
        if self.elapsed_ns is not None and (type(self.elapsed_ns) is not int or self.elapsed_ns < 0):
            raise ExperimentRefusal("invalid_cell_timing")
        if self.query_bytes is not None and (type(self.query_bytes) is not int or self.query_bytes < 0):
            raise ExperimentRefusal("invalid_cell_bytes")
        if self.cleanup_status not in {"pending", "verified", "not_applicable", "failed"}:
            raise ExperimentRefusal("invalid_cleanup_status")
        return self

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "arm_id": self.arm_id,
            "task_id": self.task_id,
            "execution_state": self.execution_state.value,
            "reason": self.reason,
            "candidates": [dict(item) for item in self.candidates],
            "elapsed_ns": self.elapsed_ns,
            "query_bytes": self.query_bytes,
            "cleanup_status": self.cleanup_status,
        }


@dataclass(slots=True)
class ExperimentCostLedger:
    """Measured phase costs; an unknown cleanup cost stays unknown."""

    preparation_ns: int = 0
    installation_ns: int = 0
    request_ns: int = 0
    component_ns: int = 0
    import_ns: int = 0
    index_ns: int = 0
    ann_cleanup_ns: int = 0
    query_ns: int = 0
    cleanup_ns: int | None = None
    failures: int = 0

    def validate(self) -> ExperimentCostLedger:
        for name in (
            "preparation_ns", "installation_ns", "request_ns", "component_ns", "import_ns",
            "index_ns", "ann_cleanup_ns", "query_ns",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ExperimentRefusal("invalid_cost_ledger")
        if self.cleanup_ns is not None and (type(self.cleanup_ns) is not int or self.cleanup_ns < 0):
            raise ExperimentRefusal("invalid_cost_ledger")
        if type(self.failures) is not int or self.failures < 0:
            raise ExperimentRefusal("invalid_cost_ledger")
        return self

    @property
    def total_ns(self) -> int | None:
        self.validate()
        if self.cleanup_ns is None:
            return None
        return (
            self.preparation_ns + self.installation_ns + self.request_ns + self.component_ns
            + self.import_ns + self.index_ns + self.ann_cleanup_ns + self.query_ns + self.cleanup_ns
        )

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "preparation_ns": self.preparation_ns,
            "installation_ns": self.installation_ns,
            "request_ns": self.request_ns,
            "component_ns": self.component_ns,
            "import_ns": self.import_ns,
            "index_ns": self.index_ns,
            "ann_cleanup_ns": self.ann_cleanup_ns,
            "query_ns": self.query_ns,
            "cleanup_ns": self.cleanup_ns,
            "total_ns": self.total_ns,
            "failures": self.failures,
        }


def exact_cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    """Independent finite cosine reference; relevance is graded separately."""
    if not isinstance(left, Sequence) or not isinstance(right, Sequence) or len(left) != len(right) or not left:
        raise ExperimentRefusal("vector_dimension_mismatch")
    values: list[float] = []
    for a, b in zip(left, right, strict=True):
        if type(a) not in (int, float) or type(b) not in (int, float):
            raise ExperimentRefusal("invalid_vector_value")
        fa, fb = float(a), float(b)
        if not math.isfinite(fa) or not math.isfinite(fb):
            raise ExperimentRefusal("invalid_vector_value")
        values.append(fa * fb)
    distance = 1.0 - math.fsum(values)
    if not math.isfinite(distance):
        raise ExperimentRefusal("invalid_vector_distance")
    return distance


__all__ = [
    "EXPERIMENT_ARMS", "EXPERIMENT_SCHEMA", "TIMEOUT_POLICY", "ExperimentCell", "ExperimentCostLedger", "ExperimentPlan",
    "ExperimentRefusal", "canonical_json_bytes", "digest_bytes", "digest_json",
    "exact_cosine_distance", "make_plan", "validate_calibration_tasks",
]
