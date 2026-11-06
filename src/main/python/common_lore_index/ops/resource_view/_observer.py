"""Call-owned observer hooks for the internal resource view."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import threading
import time
from typing import Callable, TypedDict, TypeVar

from ._contracts import (
    Basis, Backend, Operation, ResourceLimit, ResourceMetric, ResourceReport, Unit, UnavailableReason,
)
from ._controls import lexical_limits, manifest_limits, sealing_io_limit, worker_limits
from ._observer_reporting import (
    build_report, finish_lexical as _finish_lexical_report,
    finish_local as _finish_local_report, finish_server as _finish_server_report,
)


class ObserverKwargs(TypedDict, total=False):
    resource_observer: ResourceObserver


_Result = TypeVar("_Result")


_STAGES = {
    "lock_and_reconcile": "lock_and_reconcile_elapsed",
    "capture": "capture_elapsed",
    "validation": "validation_elapsed",
    "publication": "publication_elapsed",
}
_STAGE_UNITS = {name: Unit.NANOSECONDS for name in _STAGES.values()}
_OBSERVED_OPERATIONS = frozenset(
    {
        Operation.LOCAL_REFRESH.value,
        Operation.SERVER_REFRESH.value,
        Operation.LEXICAL_BUILD.value,
    }
)


def _int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _value(source: object, name: str) -> object:
    if isinstance(source, Mapping):
        return source[name]
    return getattr(source, name)


class ResourceObserver:
    """One operation's bounded observations and existing owner controls."""

    def __init__(
        self,
        *,
        _monotonic_ns: Callable[[], int] | None = None,
        _process_time_ns: Callable[[], int] | None = None,
    ) -> None:
        self._monotonic = _monotonic_ns if _monotonic_ns is not None else time.monotonic_ns
        self._process_time = _process_time_ns if _process_time_ns is not None else time.process_time_ns
        self._owner_thread: int | None = None
        self._begun = self._sealed = self._degraded = self._outcome_recorded = False
        self._operation: str | None = None
        self._backend: str | None = None
        self._outcome = "not_recorded"
        self._start_ns: int | None = None
        self._start_cpu_ns: int | None = None
        self._stages: dict[str, tuple[int, int | None]] = {}
        self._metrics: dict[str, ResourceMetric] = {}
        self._limits: dict[str, ResourceLimit] = {}
        self._worker_launched = self._worker_noted = False
        self._manifest_noted = self._validated_noted = False
        self._lexical_controls: Mapping[str, object] | None = None
        self._cached_report: ResourceReport | None = None

    def _degrade(self) -> None:
        self._degraded = True
        self._outcome_recorded = False
        self._outcome = "not_recorded"
        for name in self._limits:
            self._replace_limit(name, applies_this_call=None)

    def _active(self) -> bool:
        if self._sealed:
            return False
        if self._degraded:
            raise ValueError("resource observer is degraded")
        if self._outcome_recorded:
            self._degrade()
            raise ValueError("resource observer outcome is already recorded")
        if not self._begun or self._owner_thread != threading.get_ident():
            self._degrade()
            raise ValueError("resource observer lifecycle misuse")
        return True

    def _add_metric(self, metric: ResourceMetric) -> None:
        if metric.name in self._metrics:
            raise ValueError("resource metric slot repeated")
        self._metrics[metric.name] = metric

    def _add_limit(self, limit: ResourceLimit) -> None:
        if limit.name in self._limits:
            raise ValueError("resource limit slot repeated")
        self._limits[limit.name] = limit

    def _replace_limit(self, name: str, *, applies_this_call: bool | None) -> None:
        current = self._limits[name]
        self._limits[name] = ResourceLimit(
            current.name, current.value, current.unit, current.enforcement, applies_this_call,
        )

    def _begin(self, operation: str, backend: str) -> None:
        if self._sealed or self._degraded:
            return
        if self._begun:
            self._degrade()
            raise ValueError("resource observer began more than once")
        if operation not in _OBSERVED_OPERATIONS:
            raise ValueError("resource observer operation is unsupported")
        if backend not in {item.value for item in Backend}:
            raise ValueError("resource backend is invalid")
        if operation == Operation.LOCAL_REFRESH.value and backend != Backend.SQLITE.value:
            raise ValueError("local refresh requires sqlite backend")
        if operation in {Operation.SERVER_REFRESH.value, Operation.LEXICAL_BUILD.value}:
            if backend != Backend.POSTGRESQL.value:
                raise ValueError("server and lexical operations require postgresql backend")
        self._owner_thread = threading.get_ident()
        self._begun, self._operation, self._backend = True, operation, backend
        self._start_ns = _int(self._monotonic(), "monotonic clock")
        self._start_cpu_ns = _int(self._process_time(), "process clock")
        if operation in {Operation.LOCAL_REFRESH, Operation.SERVER_REFRESH}:
            self._add_limit(sealing_io_limit())
            for row in manifest_limits(applies_this_call=None):
                self._add_limit(row)
        # Lexical controls are recorded by note_lexical_limits immediately
        # before the owner enters its build path; begin stays a small hook.

    def _mark(self, stage: str) -> None:
        if not self._active():
            return
        if stage not in _STAGES or stage in self._stages:
            raise ValueError("resource stage is invalid or repeated")
        self._stages[stage] = (_int(self._monotonic(), "monotonic clock"), None)

    def _end_stage(self, stage: str) -> None:
        if not self._active():
            return
        existing = self._stages.get(stage)
        if existing is None or existing[1] is not None:
            raise ValueError("resource stage was not started or already ended")
        started = existing[0]
        ended = _int(self._monotonic(), "monotonic clock")
        self._stages[stage] = (started, ended)
        self._add_metric(ResourceMetric.measured(
            _STAGES[stage], max(0, ended - started), _STAGE_UNITS[_STAGES[stage]], Basis.MONOTONIC_SPAN,
        ))

    def _note_worker_launch(self, capability: object, leaf_limits: object) -> None:
        if not self._active():
            return
        if self._operation not in {Operation.LOCAL_REFRESH, Operation.SERVER_REFRESH} or self._worker_noted:
            raise ValueError("worker launch is invalid or repeated")
        self._worker_noted = self._worker_launched = True
        self._add_metric(ResourceMetric.unavailable(
            "worker_cpu", Unit.NANOSECONDS, None, UnavailableReason.NOT_OBSERVED,
        ))
        self._add_metric(ResourceMetric.unavailable(
            "worker_peak_rss", Unit.BYTES, None, UnavailableReason.NOT_OBSERVED,
        ))
        for row in worker_limits(capability, leaf_limits):
            self._add_limit(row)

    def _note_manifest(self, manifest: object) -> None:
        if not self._active():
            return
        if self._manifest_noted:
            raise ValueError("manifest was repeated")
        self._manifest_noted = True
        self._add_metric(ResourceMetric.measured(
            "sealed_manifest_files", _int(_value(manifest, "total_files"), "manifest files"),
            Unit.COUNT, Basis.ACCEPTED_MANIFEST_TOTAL,
        ))
        self._add_metric(ResourceMetric.measured(
            "sealed_manifest_bytes", _int(_value(manifest, "total_bytes"), "manifest bytes"),
            Unit.BYTES, Basis.ACCEPTED_MANIFEST_TOTAL,
        ))
        for name in ("manifest_max_artifacts", "manifest_max_total_bytes"):
            self._replace_limit(name, applies_this_call=True)

    def _note_validated(self, validated: object) -> None:
        if not self._active():
            return
        if self._validated_noted or self._stages.get("validation", (0, None))[1] is None:
            raise ValueError("validated bundle is repeated or validation is open")
        summaries = _value(validated, "family_summaries")
        if not isinstance(summaries, Sequence):
            raise ValueError("validated family summaries are invalid")
        records = sum(_int(_value(item, "record_count"), "validated records") for item in summaries)
        bytes_total = sum(_int(_value(item, "byte_length"), "validated bytes") for item in summaries)
        self._validated_noted = True
        self._add_metric(ResourceMetric.measured(
            "validated_bundle_records", records, Unit.COUNT, Basis.PARENT_VALIDATED_TOTAL,
        ))
        self._add_metric(ResourceMetric.measured(
            "validated_bundle_bytes", bytes_total, Unit.BYTES, Basis.PARENT_VALIDATED_TOTAL,
        ))

    def _note_lexical_limits(self, controls: Mapping[str, object]) -> None:
        if not self._active():
            return
        if self._operation != Operation.LEXICAL_BUILD or self._lexical_controls is not None:
            raise ValueError("lexical controls are invalid or repeated")
        self._lexical_controls = dict(controls)
        for row in lexical_limits(self._lexical_controls, applies_this_call=None):
            self._add_limit(row)

    def _finish_local(self, result: _Result) -> _Result:
        return _finish_local_report(self, result)

    def _finish_server(self, result: _Result) -> _Result:
        return _finish_server_report(self, result)

    def _finish_lexical(self, result: _Result) -> _Result:
        return _finish_lexical_report(self, result)

    def _build_report(self) -> ResourceReport:
        return build_report(self)

    def report(self) -> ResourceReport:
        """Seal on first read; subsequent reads return the identical object."""
        if self._cached_report is None:
            self._cached_report = self._build_report()
            self._sealed = True
        return self._cached_report


def _call(observer: object | None, method: str, *args: object, **kwargs: object) -> None:
    if observer is None or type(observer) is not ResourceObserver:
        return
    try:
        getattr(observer, method)(*args, **kwargs)
    except Exception:
        observer._degrade()


def begin(observer: object | None, operation: str, backend: str) -> None:
    _call(observer, "_begin", operation, backend)


def mark(observer: object | None, stage: str) -> None:
    _call(observer, "_mark", stage)


def end_stage(observer: object | None, stage: str) -> None:
    _call(observer, "_end_stage", stage)


def note_worker_launch(observer: object | None, capability: object, leaf_limits: object) -> None:
    _call(observer, "_note_worker_launch", capability, leaf_limits)


def note_manifest(observer: object | None, manifest: object) -> None:
    _call(observer, "_note_manifest", manifest)


def note_validated(observer: object | None, validated: object) -> None:
    _call(observer, "_note_validated", validated)


def note_lexical_limits(
    observer: object | None, *, max_projected_files: int, max_aggregate_input_bytes: int,
    max_input_artifact_bytes: int, max_projected_file_bytes: int, max_chunk_lines: int,
    max_chunk_bytes: int, statement_timeout_ms: int,
) -> None:
    _call(observer, "_note_lexical_limits", {
        "max_projected_files": max_projected_files,
        "max_aggregate_input_bytes": max_aggregate_input_bytes,
        "max_input_artifact_bytes": max_input_artifact_bytes,
        "max_projected_file_bytes": max_projected_file_bytes,
        "max_chunk_lines": max_chunk_lines,
        "max_chunk_bytes": max_chunk_bytes,
        "lexical_build_statement_timeout": statement_timeout_ms,
    })


def finish_local(observer: ResourceObserver | None, result: _Result) -> _Result:
    if observer is None or type(observer) is not ResourceObserver:
        return result
    try:
        return observer._finish_local(result)
    except Exception:
        observer._degrade()
        return result


def observer_kwargs(observer: ResourceObserver | None) -> ObserverKwargs:
    return {"resource_observer": observer} if type(observer) is ResourceObserver else {}


__all__ = (
    "ObserverKwargs", "ResourceObserver", "begin", "end_stage", "finish_local", "mark",
    "note_lexical_limits", "note_manifest", "note_validated", "note_worker_launch", "observer_kwargs",
)
