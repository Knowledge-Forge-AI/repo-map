"""Neutral protocol declarations and validation helpers for coordinator core and service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import timedelta
import threading
from typing import Protocol, TypeVar

from repomap_kg.coordinator._control_types import (
    JobClaim,
    JobListPage,
    JobStatus,
    SubmissionResult,
)
from repomap_kg.coordinator.contracts import JobRequest
from repomap_kg.coordinator.startup_recovery import RecoveryStore

_T = TypeVar("_T")

_Claim = JobClaim
WorkerRunner = Callable[[JobClaim, threading.Event], Mapping[str, object]]
PublicationReader = Callable[[object], Mapping[str, object] | None]

_Transport = AbstractContextManager[object]
TransportFactory = Callable[..., _Transport]
RequestResolver = Callable[[object], JobRequest]


class CoordinatorStore(RecoveryStore, Protocol):
    def maintenance_activity(self) -> AbstractContextManager[object]: ...
    def claim_next(
        self,
        instance_id: str,
        fencing_epoch: int,
        lease_ttl: timedelta,
        *,
        automatic_only: bool = False,
    ) -> JobClaim | None: ...
    def mark_reconciliation_required(
        self,
        claim: JobClaim,
        *,
        expected_state: str,
        category: str,
        diagnostic_summary: str | None = None,
    ) -> bool: ...
    def mark_attempt_terminated(
        self,
        claim: JobClaim,
        *,
        process_cleanup_proved: bool,
        reconciler_instance_id: str | None = None,
        reconciler_epoch: int | None = None,
        diagnostic_summary: str | None = None,
    ) -> bool: ...
    def schedule_retry(
        self,
        claim: JobClaim,
        *,
        expected_state: str,
        delay: timedelta,
        category: str,
        diagnostic_summary: str | None = None,
    ) -> bool: ...
    def heartbeat_singleton(
        self, instance_id: str, fencing_epoch: int, ttl: timedelta
    ) -> bool: ...
    def request_cancellation(self, job_id: str) -> str: ...
    def compare_and_set_state(
        self,
        job_id: str,
        *,
        expected_state: str,
        new_state: str,
        attempt: int,
        instance_id: str,
        fencing_epoch: int,
        publication_state: str | None = None,
        error_category: str | None = None,
        diagnostic_summary: str | None = None,
    ) -> bool: ...
    def release_graph_lease(
        self,
        graph_id: str,
        job_id: str,
        attempt: int,
        owner_instance_id: str,
        owner_epoch: int,
        *,
        reconciler_instance_id: str,
        reconciler_epoch: int,
    ) -> bool: ...


class ServiceCoordinator(Protocol):
    def startup(self, reconcile_startup: Callable[[], object]) -> int: ...
    def shutdown(self) -> None: ...
    def run_once(self) -> str | None: ...
    def heartbeat(self) -> bool: ...
    def submit(self, action: Callable[[], _T]) -> _T: ...
    def request_cancel(self, job_id: str) -> str: ...


class ServiceStore(Protocol):
    def submit(self, request: JobRequest) -> SubmissionResult: ...
    def status(self, job_id: str) -> JobStatus: ...
    def list_recent_jobs(
        self,
        *,
        limit: int,
        graph_id: str | None = None,
        cursor: str | None = None,
    ) -> JobListPage: ...


class DesiredReconciler(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health(self) -> dict[str, object]: ...


_DesiredReconciler = DesiredReconciler


def require_payload_string(payload: Mapping[str, object], field: str) -> str:
    val = payload[field]
    if not isinstance(val, str):
        raise ValueError(f"{field} must be a string")
    return val


def require_payload_int(payload: Mapping[str, object], field: str) -> int:
    val = payload[field]
    if not isinstance(val, int) or isinstance(val, bool):
        raise ValueError(f"{field} must be an integer")
    return val


__all__ = [
    "CoordinatorStore",
    "DesiredReconciler",
    "JobClaim",
    "PublicationReader",
    "RequestResolver",
    "ServiceCoordinator",
    "ServiceStore",
    "TransportFactory",
    "WorkerRunner",
    "_Claim",
    "_DesiredReconciler",
    "_Transport",
    "require_payload_int",
    "require_payload_string",
]
