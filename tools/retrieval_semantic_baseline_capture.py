"""Issued live capture and sidecar factory for optional baseline execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter_ns
from typing import Any, TypeVar

from common_lore_index.retrieval.projection_build import CapturedTextProjection
from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy
from common_lore_index.retrieval.publication_binding import ProjectionInputs
from common_lore_index.retrieval.query_contracts import QueryEnvelope
from retrieval_evaluation_schema import EvaluationTask
from retrieval_evaluation_correspondence_graph_scope import (
    GraphExecutionWork, collect_graph_execution_work,
)
from retrieval_evaluation_views import MaterializedNativeView
from retrieval_semantic_experiment_contracts import ExperimentRefusal, digest_json
from retrieval_semantic_provenance import VerifiedPublicationPin

T = TypeVar("T")
_CAPTURE_TOKEN = object()
_VERIFICATION_TOKEN = object()
_ISSUED_CAPTURES: dict[int, object] = {}
_VERIFIED_SIDECARS: dict[int, tuple[object, object, object]] = {}


def generation_aliases_for(manifest: Any) -> tuple[str, ...]:
    """Read the complete independent alias set; missing aliases cannot be dropped."""
    aliases = tuple(binding.alias for binding in manifest.bindings)
    if not aliases or any(type(alias) is not str or not alias for alias in aliases):
        raise ExperimentRefusal("generation_aliases_incomplete")
    if len(aliases) != len(set(aliases)):
        raise ExperimentRefusal("generation_aliases_duplicate")
    return aliases


def _record_verified_sidecar(
    sidecar: Any, pin: VerifiedPublicationPin, cost: Any, *, _token: object
) -> None:
    """Bind one successful strict verification to its exact in-process objects."""
    if _token is not _VERIFICATION_TOKEN:
        raise ExperimentRefusal("verified_sidecar_registry_forbidden")
    _VERIFIED_SIDECARS[id(sidecar)] = (sidecar, pin, cost)


def is_verified_sidecar(sidecar: Any, pin: VerifiedPublicationPin, cost: Any) -> bool:
    record = _VERIFIED_SIDECARS.get(id(sidecar))
    return record is not None and record[0] is sidecar and record[1] is pin and record[2] is cost


@dataclass(frozen=True)
class BaselinePinSnapshot:
    sqlite: VerifiedPublicationPin
    postgres: VerifiedPublicationPin

    def target_for_arm(self, arm_id: str) -> VerifiedPublicationPin:
        if arm_id == "native_tools_baseline" or arm_id.endswith(":sqlite"):
            return self.sqlite
        if arm_id.endswith(":postgresql"):
            return self.postgres
        raise ExperimentRefusal("unsupported_baseline_correspondence_arm")


@dataclass(frozen=True)
class IssuedBaselineCapture:
    """Immutable factory-issued binding for one completed arm/task envelope."""

    arm_id: str
    task_id: str
    envelope_digest: str
    generation_aliases: tuple[str, ...]
    pre: BaselinePinSnapshot
    post: BaselinePinSnapshot
    read_ns: int
    read_attempts: int
    execution_work: tuple[GraphExecutionWork, ...] = ()
    _token: object = field(default=None, repr=False, compare=False)

    def validate(self) -> IssuedBaselineCapture:
        if self._token is not _CAPTURE_TOKEN or _ISSUED_CAPTURES.get(id(self)) is not self:
            raise ExperimentRefusal("baseline_capture_not_issued")
        for work in self.execution_work:
            if not isinstance(work, GraphExecutionWork):
                raise ExperimentRefusal("baseline_execution_work_invalid")
            work.to_dict()
        if (
            type(self.arm_id) is not str or not self.arm_id
            or type(self.task_id) is not str or not self.task_id
            or type(self.envelope_digest) is not str or not self.envelope_digest.startswith("sha256:")
        ):
            raise ExperimentRefusal("baseline_capture_identity_invalid")
        if type(self.generation_aliases) is not tuple or not self.generation_aliases or any(
            type(alias) is not str or not alias for alias in self.generation_aliases
        ) or len(self.generation_aliases) != len(set(self.generation_aliases)):
            raise ExperimentRefusal("baseline_generation_aliases_invalid")
        if not isinstance(self.pre, BaselinePinSnapshot) or not isinstance(self.post, BaselinePinSnapshot):
            raise ExperimentRefusal("baseline_capture_snapshots_invalid")
        if not all(
            isinstance(pin, VerifiedPublicationPin)
            for pin in (self.pre.sqlite, self.pre.postgres, self.post.sqlite, self.post.postgres)
        ):
            raise ExperimentRefusal("baseline_capture_pins_invalid")
        if type(self.read_ns) is not int or self.read_ns < 0:
            raise ExperimentRefusal("baseline_capture_timing_invalid")
        if type(self.read_attempts) is not int or self.read_attempts < 1:
            raise ExperimentRefusal("baseline_capture_reads_invalid")
        return self


class _ReadMeter:
    def __init__(self) -> None:
        self.attempts = 0
        self.elapsed_ns = 0
        self.failures = 0

    def read(self, callback: Callable[[], VerifiedPublicationPin]) -> VerifiedPublicationPin:
        self.attempts += 1
        started = perf_counter_ns()
        try:
            return callback()
        except BaseException:
            self.failures += 1
            raise
        finally:
            self.elapsed_ns += max(0, perf_counter_ns() - started)


def _retain_meter_on_exception(error: BaseException, meter: _ReadMeter) -> None:
    """Keep read-attempt work attached without replacing the original exception."""
    for name, value in (
        ("baseline_capture_read_ns", meter.elapsed_ns),
        ("baseline_capture_read_attempts", meter.attempts),
        ("baseline_capture_read_failures", meter.failures),
    ):
        try:
            setattr(error, name, value)
        except Exception:
            pass


def _read_snapshot(
    meter: _ReadMeter,
    *,
    read_sqlite: Callable[[], VerifiedPublicationPin],
    read_postgres: Callable[[], VerifiedPublicationPin],
) -> BaselinePinSnapshot:
    return BaselinePinSnapshot(
        sqlite=meter.read(read_sqlite),
        postgres=meter.read(read_postgres),
    )


def execute_with_live_baseline_pins(
    *,
    arm_id: str,
    task: EvaluationTask,
    generation_aliases: tuple[str, ...],
    execute: Callable[[BaselinePinSnapshot], T],
    read_sqlite: Callable[[], VerifiedPublicationPin],
    read_postgres: Callable[[], VerifiedPublicationPin],
) -> tuple[T, IssuedBaselineCapture]:
    """Capture both stores around one query and preserve the original query exception."""
    meter = _ReadMeter()
    try:
        pre = _read_snapshot(meter, read_sqlite=read_sqlite, read_postgres=read_postgres)
    except BaseException as exc:
        _retain_meter_on_exception(exc, meter)
        raise
    try:
        with collect_graph_execution_work() as execution_work:
            result = execute(pre)
    except BaseException as exc:
        # Attempt both post reads for accounting, but never mask the query failure.
        for read in (read_sqlite, read_postgres):
            try:
                meter.read(read)
            except BaseException:
                pass
        _retain_meter_on_exception(exc, meter)
        raise
    try:
        post = _read_snapshot(meter, read_sqlite=read_sqlite, read_postgres=read_postgres)
    except BaseException as exc:
        _retain_meter_on_exception(exc, meter)
        raise
    if not isinstance(result, tuple) or len(result) < 2 or not isinstance(result[1], QueryEnvelope):
        raise ExperimentRefusal("baseline_envelope_required")
    capture = IssuedBaselineCapture(
        arm_id=arm_id,
        task_id=task.task_id,
        envelope_digest=digest_json(result[1].to_dict()),
        generation_aliases=tuple(generation_aliases),
        pre=pre,
        post=post,
        read_ns=meter.elapsed_ns,
        read_attempts=meter.attempts,
        execution_work=tuple(execution_work),
        _token=_CAPTURE_TOKEN,
    )
    _ISSUED_CAPTURES[id(capture)] = capture
    return result, capture.validate()


@dataclass
class BaselineCorrespondenceRunner:
    """Optional-experiment wiring that stamps issued captures onto sidecars."""

    sidecar_type: type[Any]
    read_sqlite: Callable[[], VerifiedPublicationPin]
    read_postgres: Callable[[], VerifiedPublicationPin]
    generation_aliases: tuple[str, ...]
    native_view: MaterializedNativeView
    sqlite_inputs: ProjectionInputs
    postgres_inputs: ProjectionInputs
    sqlite_policy: BodyProjectionPolicy
    postgres_policy: BodyProjectionPolicy
    live: IssuedBaselineCapture | None = None

    def execute(
        self,
        arm_id: str,
        task: EvaluationTask,
        callback: Callable[[VerifiedPublicationPin], T],
    ) -> T:
        self.live = None
        result, capture = execute_with_live_baseline_pins(
            arm_id=arm_id,
            task=task,
            generation_aliases=self.generation_aliases,
            execute=lambda pre: callback(pre.target_for_arm(arm_id)),
            read_sqlite=self.read_sqlite,
            read_postgres=self.read_postgres,
        )
        self.live = capture
        return result

    def sidecar(
        self,
        arm_id: str,
        task: EvaluationTask,
        *,
        envelope: QueryEnvelope,
        projection: CapturedTextProjection | None,
    ) -> Any:
        capture = self.live
        if capture is None:
            raise ExperimentRefusal("baseline_live_capture_missing")
        capture.validate()
        if capture.arm_id != arm_id or capture.task_id != task.task_id:
            raise ExperimentRefusal("baseline_live_capture_identity_mismatch")
        if capture.envelope_digest != digest_json(envelope.to_dict()):
            raise ExperimentRefusal("baseline_live_capture_envelope_mismatch")
        sqlite_arm = arm_id == "native_tools_baseline" or arm_id.endswith(":sqlite")
        inputs = self.sqlite_inputs if sqlite_arm else self.postgres_inputs
        policy = self.sqlite_policy if sqlite_arm else self.postgres_policy
        artifact_arm = arm_id == "native_tools_baseline" or arm_id.startswith("captured_projection_reference:")
        return self.sidecar_type(
            arm_id=arm_id,
            task_id=task.task_id,
            sqlite_pin=capture.pre.sqlite,
            postgres_pin=capture.pre.postgres,
            pre_query_pin=capture.pre.target_for_arm(arm_id),
            post_query_pin=capture.post.target_for_arm(arm_id),
            capture=capture,
            generation_aliases=capture.generation_aliases,
            native_witness=self.native_view.materialization_witness if arm_id == "native_tools_baseline" else None,
            native_view=self.native_view if arm_id == "native_tools_baseline" else None,
            projection_inputs=inputs if artifact_arm else None,
            projection_policy=policy if artifact_arm else None,
            projection=projection,
        )


def make_baseline_correspondence_runner(
    sidecar_type: type[Any],
    generation_aliases: tuple[str, ...],
    native_view: MaterializedNativeView,
    sqlite_reader: Any,
    postgres_reader: Any,
    sqlite_state: Any,
    postgres_state: Any,
) -> BaselineCorrespondenceRunner:
    return BaselineCorrespondenceRunner(
        sidecar_type=sidecar_type,
        read_sqlite=sqlite_reader.read_pin,
        read_postgres=postgres_reader.read_pin,
        generation_aliases=generation_aliases,
        native_view=native_view,
        sqlite_inputs=sqlite_state.projection_inputs(),
        postgres_inputs=postgres_state.projection_inputs(),
        sqlite_policy=sqlite_state.policy,
        postgres_policy=postgres_state.policy,
    )


__all__ = [
    "BaselineCorrespondenceRunner",
    "BaselinePinSnapshot",
    "IssuedBaselineCapture",
    "execute_with_live_baseline_pins",
    "is_verified_sidecar",
    "make_baseline_correspondence_runner",
]
