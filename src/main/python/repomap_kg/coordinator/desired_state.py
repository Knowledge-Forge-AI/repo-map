"""Polling-first desired-state comparison and the deferred watcher seam."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
import re
from threading import Event
from typing import Mapping, Protocol

from repomap_kg.coordinator.contracts import JobRequest, normalize_request
from repomap_kg.storage.errors import StorageSchemaError


class SourceSnapshot(Protocol):
    @property
    def category(self) -> str: ...

    @property
    def generation(self) -> str | None: ...

    @property
    def file_count(self) -> int: ...

    @property
    def total_bytes(self) -> int: ...


class PollingSnapshot(Protocol):
    @property
    def source(self) -> SourceSnapshot: ...

    @property
    def config_generation(self) -> str: ...

    @property
    def extractor_generation(self) -> str: ...

    @property
    def canonicalizer_generation(self) -> str: ...


class Resolver(Protocol):
    def latest_publication(self, graph_id: str) -> Mapping[str, object] | None: ...
    def polling_snapshot(
        self, graph_id: str, *, cancel_event: Event | None = None
    ) -> PollingSnapshot: ...


class ReconcilerStore(Protocol):
    def coalesce_automatic(
        self, request: JobRequest, *, requester: str = "polling"
    ) -> object: ...


_GRAPH_ID = re.compile(r"[a-z][a-z0-9._-]{0,127}\Z")
_CATEGORY = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_GENERATION_FIELDS = (
    "source_generation",
    "config_generation",
    "extractor_generation",
    "canonicalizer_generation",
)


@dataclass(frozen=True)
class PollOutcome:
    """Path-free result of one graph reconciliation attempt."""

    category: str
    refresh_requested: bool
    file_count: int
    total_bytes: int

    def to_public(self) -> dict[str, object]:
        return {
            "category": self.category,
            "refresh_requested": self.refresh_requested,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
        }


@dataclass(frozen=True)
class WatcherHint:
    """Bounded event hint reserved for a later polling accelerator."""

    graph_id: str
    category: str
    observed_at: str
    overflow: bool = False

    def __post_init__(self) -> None:
        if (
            _GRAPH_ID.fullmatch(self.graph_id) is None
            or _CATEGORY.fullmatch(self.category) is None
            or _TIMESTAMP.fullmatch(self.observed_at) is None
            or not isinstance(self.overflow, bool)
        ):
            raise ValueError("watcher hint is invalid")

    def to_public(self) -> dict[str, object]:
        return {
            "graph_id": self.graph_id,
            "category": self.category,
            "observed_at": self.observed_at,
            "overflow": self.overflow,
        }


class WatcherAdapter(Protocol):
    """Narrow future watcher interface; no implementation is selected here."""

    def start(self, graph_id: str, configured_source: object, excludes: object) -> None: ...

    def next_hint(self) -> WatcherHint | None: ...

    def health(self) -> Mapping[str, object]: ...

    def rescan_required(self) -> bool: ...

    def stop(self) -> None: ...


class DesiredStateReconciler:
    """Compare configured desired state with committed publication receipts."""

    def __init__(
        self,
        resolver: Resolver,
        store: ReconcilerStore,
        *,
        next_reconcile_seconds: float = 60.0,
        retry_seconds: float = 15.0,
        cancel_event: Event | None = None,
    ) -> None:
        if next_reconcile_seconds <= 0 or retry_seconds <= 0:
            raise ValueError("reconciliation timing is invalid")
        self._resolver = resolver
        self._store = store
        self._next_reconcile_seconds = next_reconcile_seconds
        self._retry_seconds = retry_seconds
        self._cancel = cancel_event or Event()

    def cancel(self) -> None:
        self._cancel.set()

    def reconcile_graph(self, graph_id: str) -> PollOutcome:
        """Perform one read-only comparison and optional automatic coalescing."""

        if self._cancel.is_set():
            return PollOutcome("cancelled", False, 0, 0)
        try:
            snapshot = _polling_snapshot(
                self._resolver, graph_id, cancel_event=self._cancel
            )
        except (OSError, StorageSchemaError, ValueError):
            self._record_condition(graph_id, "configuration_invalid")
            return PollOutcome("configuration_invalid", False, 0, 0)
        source = snapshot.source
        if source.generation is None:
            self._record_condition(graph_id, source.category)
            return PollOutcome(
                source.category,
                False,
                source.file_count,
                source.total_bytes,
            )
        if self._cancel.is_set():
            return PollOutcome("cancelled", False, source.file_count, source.total_bytes)
        try:
            publication = self._resolver.latest_publication(graph_id)
            actual = _publication_generations(publication)
        except (OSError, StorageSchemaError, ValueError, TypeError, KeyError):
            self._record_condition(graph_id, "publication_unavailable")
            return PollOutcome(
                "publication_unavailable",
                False,
                source.file_count,
                source.total_bytes,
            )
        source_generation = source.generation
        desired = (
            source_generation,
            snapshot.config_generation,
            snapshot.extractor_generation,
            snapshot.canonicalizer_generation,
        )
        if actual == desired:
            self._record_current(graph_id, desired)
            return PollOutcome("current", False, source.file_count, source.total_bytes)
        if self._cancel.is_set():
            return PollOutcome("cancelled", False, source.file_count, source.total_bytes)
        try:
            request = _automatic_request(graph_id, desired)
            result = self._store.coalesce_automatic(request, requester="polling")
        except ValueError:
            self._record_condition(graph_id, "automatic_intent_blocked")
            return PollOutcome(
                "automatic_intent_blocked",
                False,
                source.file_count,
                source.total_bytes,
            )
        replayed = bool(getattr(result, "replayed", False))
        return PollOutcome(
            "refresh_coalesced" if replayed else "refresh_requested",
            not replayed,
            source.file_count,
            source.total_bytes,
        )

    def _record_current(self, graph_id: str, generations: tuple[str, ...]) -> None:
        recorder = getattr(self._store, "record_reconciliation_current", None)
        if recorder is not None:
            recorder(
                graph_id,
                generations,
                next_reconcile_seconds=self._next_reconcile_seconds,
            )

    def _record_condition(self, graph_id: str, category: str) -> None:
        recorder = getattr(self._store, "record_reconciliation_condition", None)
        if recorder is not None:
            recorder(
                graph_id,
                category,
                next_reconcile_seconds=self._retry_seconds,
            )


def _automatic_request(
    graph_id: str,
    generations: tuple[str, str, str, str],
) -> JobRequest:
    digest = hashlib.sha256(
        "|".join((graph_id, *generations)).encode("utf-8")
    ).hexdigest()
    payload = {
        "schema_version": 1,
        "job_kind": "refresh_graph",
        "graph_id": graph_id,
        "request_id": f"poll-{digest}",
        "idempotency_key": f"poll-{digest}",
        "priority": "automatic",
        "operation_options": {"reason": "polling"},
    }
    return normalize_request(
        payload,
        source_generation=generations[0],
        config_generation=generations[1],
        extractor_generation=generations[2],
        canonicalizer_generation=generations[3],
        require_synthetic_graph=False,
    )


def _polling_snapshot(
    resolver: Resolver,
    graph_id: str,
    *,
    cancel_event: Event,
) -> PollingSnapshot:
    method = resolver.polling_snapshot
    if "cancel_event" in inspect.signature(method).parameters:
        return method(graph_id, cancel_event=cancel_event)
    return method(graph_id)


def _publication_generations(
    publication: Mapping[str, object] | None,
) -> tuple[str, str, str, str] | None:
    if publication is None:
        return None
    raw_values = [publication.get(field) for field in _GENERATION_FIELDS]
    if len(raw_values) != 4 or not all(
        isinstance(v, str) and bool(v) for v in raw_values
    ):
        raise ValueError("publication receipt is incomplete")
    v0, v1, v2, v3 = raw_values
    if not (
        isinstance(v0, str)
        and isinstance(v1, str)
        and isinstance(v2, str)
        and isinstance(v3, str)
    ):
        raise ValueError("publication receipt is incomplete")
    return (v0, v1, v2, v3)


__all__ = [
    "DesiredStateReconciler",
    "PollOutcome",
    "WatcherAdapter",
    "WatcherHint",
]
