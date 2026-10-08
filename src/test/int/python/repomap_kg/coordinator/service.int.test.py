"""Integration coverage for CoordinatorService health, recovery diagnostics, and client wire contract."""

from collections import deque
from datetime import timedelta
from pathlib import Path
import threading


from repomap_kg.coordinator.client import LocalCoordinatorClient
from repomap_kg.coordinator.contracts import JobRequest
from repomap_kg.coordinator._control_types import JobListPage, JobStatus, SubmissionResult
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.coordinator.startup_recovery import (
    RecoveryDiagnostic,
    StartupRecoveryMixin,
    StartupRecoveryReport,
)
from repomap_kg.coordinator.transport import validate_public_result
from repomap_test_support.test_scratch import short_test_directory


class _IntegrationCoordinator(StartupRecoveryMixin):
    def __init__(self) -> None:
        self._instance_id = "coordinator-int-service"
        self._singleton_ttl = timedelta(seconds=30)
        self._epoch = 1
        self._publication_reader = None
        self._publication_closer = None
        self._publication_retirer = None
        self._recovery_diagnostics: deque[RecoveryDiagnostic] = deque(maxlen=32)
        self._recovery_diagnostics_lock = threading.Lock()
        self._recovery_diagnostic_sequence = 0
        self._started = False

    def startup(self, reconcile_startup):
        self._started = True
        self._record_startup_recovery_report(reconcile_startup())
        return self._epoch

    def shutdown(self) -> None:
        self._started = False

    def run_once(self) -> str:
        return "idle"

    def heartbeat(self) -> bool:
        return self._started

    def submit(self, action):
        return action()

    def request_cancel(self, job_id: str) -> str:
        return "cancel_requested"

    def _require_started(self) -> int:
        assert self._epoch is not None
        return self._epoch


class _IntegrationStore:
    def __init__(self) -> None:
        self.state = "queued"

    def submit(
        self, request: JobRequest, *, admission_deadline=None
    ) -> SubmissionResult:
        return SubmissionResult(
            job_id=request.request_id,
            state=self.state,
            replayed=False,
        )

    def status(self, job_id: str) -> JobStatus:
        return JobStatus(
            job_id=job_id,
            graph_id="synthetic-service",
            state=self.state,
            attempt=0,
            publication_state="unpublished",
            phase="waiting",
            completed=0,
            total=None,
            error_category=None,
        )

    def list_recent_jobs(
        self,
        *,
        limit: int,
        graph_id: str | None = None,
        cursor: str | None = None,
    ) -> JobListPage:
        return JobListPage(jobs=(), next_cursor=None)


def test_service_client_health_empty_diagnostics():
    with short_test_directory("svc-int-", "coordinator.sock") as directory:
        coordinator = _IntegrationCoordinator()
        store = _IntegrationStore()
        service = CoordinatorService(
            coordinator,
            store,
            Path(directory),
            idle_poll_seconds=0.01,
            heartbeat_seconds=0.02,
        )
        service.start(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
        try:
            client = LocalCoordinatorClient(service.socket_path, service.token_path)
            health = client.health()
            assert health["health_schema_version"] == 2
            assert health["status"] == "ready"
            assert health["recovery_diagnostics"] == []
            assert validate_public_result(health)
        finally:
            service.stop()
        assert not service.socket_path.exists()
        assert not service.token_path.exists()


def test_service_client_health_bounded_redacted_diagnostics_and_ack_preservation():
    with short_test_directory("svc-int-", "coordinator.sock") as directory:
        coordinator = _IntegrationCoordinator()
        store = _IntegrationStore()
        service = CoordinatorService(
            coordinator,
            store,
            Path(directory),
            idle_poll_seconds=0.01,
            heartbeat_seconds=0.02,
        )
        service.start(lambda: StartupRecoveryReport(
            1, 0, 1, 0, 0, unexpected=("RuntimeError", "ValueError")
        ))
        try:
            client = LocalCoordinatorClient(service.socket_path, service.token_path)
            health = client.health()
            expected = [
                {
                    "category": "unexpected_recovery_error",
                    "summary": "RuntimeError",
                    "sequence": 1,
                },
                {
                    "category": "unexpected_recovery_error",
                    "summary": "ValueError",
                    "sequence": 2,
                },
            ]
            assert health["recovery_diagnostics"] == expected

            # Readback must not implicitly acknowledge diagnostics
            health2 = client.health()
            assert health2["recovery_diagnostics"] == expected

            # Heartbeat must preserve diagnostics unchanged
            assert coordinator.heartbeat()
            health3 = client.health()
            assert health3["recovery_diagnostics"] == expected

            # Acknowledging sequence 1 preserves sequence 2
            service.acknowledge_recovery_diagnostics(1)
            health_after_ack = client.health()
            assert health_after_ack["recovery_diagnostics"] == [expected[1]]

            # Acknowledging sequence 2 clears all
            service.acknowledge_recovery_diagnostics(2)
            assert client.health()["recovery_diagnostics"] == []
        finally:
            service.stop()


def test_service_client_health_diagnostics_bound_and_redaction():
    with short_test_directory("svc-int-", "coordinator.sock") as directory:
        coordinator = _IntegrationCoordinator()
        store = _IntegrationStore()
        service = CoordinatorService(
            coordinator,
            store,
            Path(directory),
            idle_poll_seconds=0.01,
            heartbeat_seconds=0.02,
        )
        service.start(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
        try:
            for _ in range(40):
                coordinator._record_startup_recovery_report(StartupRecoveryReport(
                    1, 0, 1, 0, 0, unexpected=("postgresql://secret:credential@private/db",),
                ))
            client = LocalCoordinatorClient(service.socket_path, service.token_path)
            health = client.health()
            diags = health["recovery_diagnostics"]
            assert isinstance(diags, list)
            assert len(diags) == 32
            assert isinstance(diags[0], dict)
            assert diags[0]["sequence"] == 9
            assert all(isinstance(d, dict) and d["summary"] == "Exception" for d in diags)
            assert all(isinstance(d, dict) and d["category"] == "unexpected_recovery_error" for d in diags)
            assert validate_public_result(health)
        finally:
            service.stop()
