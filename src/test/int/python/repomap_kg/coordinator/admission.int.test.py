"""Disposable PostgreSQL proofs for coordinator submit admission."""

from pathlib import Path
import hashlib
import json
import time

import psycopg
import pytest

from repomap_kg.coordinator.client import CoordinatorClientError, LocalCoordinatorClient
from repomap_kg.coordinator.contracts import normalize_request
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.coordinator.storage import ControlStore
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.test_scratch import short_test_directory


class IdleCoordinator:
    """Keep admission tests from starting worker execution or publication."""

    def __init__(self, store):
        self.store = store
        self.started = False

    def startup(self, reconcile):
        reconcile()
        self.started = True
        return 1

    def run_once(self):
        return "idle"

    def heartbeat(self):
        return self.started

    def submit(self, callback):
        return callback()

    def request_cancel(self, _job_id):
        return "cancel_requested"

    def shutdown(self):
        self.started = False


def _request(suffix: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "job_kind": "refresh_graph",
        "graph_id": f"synthetic-admission-{suffix}",
        "request_id": f"admission-request-{suffix}",
        "idempotency_key": f"admission-key-{suffix}",
        "priority": "manual",
        "operation_options": {"reason": "admission-integration"},
    }


def _resolver(delay_seconds: float):
    def resolve(payload):
        time.sleep(delay_seconds)
        return normalize_request(
            payload,
            source_generation="sg1:admission-integration",
            config_generation="cg1:admission-integration",
        )

    return resolve


def _runtime(postgres):
    def connect():
        return psycopg.connect(
            host=postgres.host,
            port=postgres.port,
            user=postgres.user,
            dbname=postgres.database,
            password=postgres.password,
        )

    store = ControlStore(connect)
    store.initialize_schema()
    return connect, store


def _service(root: Path, store, resolver):
    service = CoordinatorService(
        IdleCoordinator(store),
        store,
        root,
        request_resolver=resolver,
        idle_poll_seconds=0.01,
        heartbeat_seconds=0.05,
    )
    service.start(lambda: None)
    return service


def _record_secret_fingerprints(postgres, service):
    values = (
        postgres.password,
        service.token_path.read_text(encoding="utf-8").strip(),
    )
    print(
        "CREDENTIAL_SCAN_FINGERPRINTS="
        + json.dumps(
            [
                {
                    "length": len(value.encode("utf-8")),
                    "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                }
                for value in values
            ],
            sort_keys=True,
        ),
        flush=True,
    )


def _counts(connect):
    with connect() as connection:
        return tuple(
            connection.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            for table in ("jobs", "job_attempts", "synthetic_publication_markers")
        )


def test_delayed_valid_submit_uses_submit_budget_and_one_durable_identity():
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        connect, store = _runtime(postgres)
        with short_test_directory("admission-valid-", "coordinator.sock") as directory:
            service = _service(Path(directory), store, _resolver(6.0))
            try:
                _record_secret_fingerprints(postgres, service)
                client = LocalCoordinatorClient(service.socket_path, service.token_path)
                started = time.monotonic()
                submitted = client.submit(
                    _request("delayed-valid"), admission_budget_seconds=10
                )
                elapsed = time.monotonic() - started
                assert elapsed >= 5.0
                assert submitted["state"] == "queued"
                job_id = submitted["job_id"]
                listed = client.list_jobs(
                    limit=10, graph_id="synthetic-admission-delayed-valid"
                )
                jobs = listed["jobs"]
                assert isinstance(jobs, list)
                assert len(jobs) == 1
                assert jobs[0]["job_id"] == job_id
                replay = client.submit(
                    _request("delayed-valid"), admission_budget_seconds=10
                )
                assert replay == {"job_id": job_id, "state": "queued", "replayed": True}
                assert _counts(connect) == (1, 0, 0)
            finally:
                service.stop()


def test_expired_submit_returns_admission_timeout_and_never_creates_late_rows():
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        connect, store = _runtime(postgres)
        with short_test_directory("admission-expired-", "coordinator.sock") as directory:
            service = _service(Path(directory), store, _resolver(0.4))
            try:
                _record_secret_fingerprints(postgres, service)
                client = LocalCoordinatorClient(service.socket_path, service.token_path)
                with pytest.raises(CoordinatorClientError, match="admission_timeout"):
                    client.submit(_request("expired"), admission_budget_seconds=0.15)
                time.sleep(0.1)
                assert client.list_jobs(
                    limit=10, graph_id="synthetic-admission-expired"
                )["jobs"] == []
                assert _counts(connect) == (0, 0, 0)
            finally:
                service.stop()


def test_contended_jobs_lock_expires_and_rolls_back_without_a_late_job():
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        connect, store = _runtime(postgres)
        with short_test_directory("admission-lock-", "coordinator.sock") as directory:
            service = _service(Path(directory), store, _resolver(0))
            try:
                _record_secret_fingerprints(postgres, service)
                client = LocalCoordinatorClient(service.socket_path, service.token_path)
                with connect() as blocker:
                    blocker.execute("BEGIN")
                    blocker.execute("LOCK TABLE jobs IN SHARE ROW EXCLUSIVE MODE")
                    with pytest.raises(
                        CoordinatorClientError, match="admission_timeout"
                    ):
                        client.submit(_request("lock"), admission_budget_seconds=0.15)
                    blocker.rollback()
                time.sleep(0.1)
                assert client.list_jobs(
                    limit=10, graph_id="synthetic-admission-lock"
                )["jobs"] == []
                assert _counts(connect) == (0, 0, 0)
            finally:
                service.stop()
