from pathlib import Path
import os
import time

import psycopg

from repomap_kg.coordinator._control_types import (
    JobListPage,
    JobStatus,
    SubmissionResult,
)
from repomap_kg.coordinator.contracts import JobRequest
from repomap_kg.coordinator.startup_recovery import StartupRecoveryReport
from repomap_test_support.test_scratch import short_test_directory
from repomap_kg.coordinator.client import CoordinatorClientError, LocalCoordinatorClient
from repomap_kg.coordinator.configured_refresh import (
    ConfiguredRefreshResolver,
    build_configured_refresh_coordinator,
)
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.coordinator.storage import ControlStore
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.synthetic_worker_adapter import (
    build_synthetic_coordinator,
)


class ServiceCoordinator:
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

    def request_cancel(self, job_id):
        self.store.state = "cancelled"
        return "cancelled"

    def shutdown(self):
        self.started = False


class ServiceStore:
    def __init__(self) -> None:
        self.state = "queued"

    def submit(self, request: JobRequest) -> SubmissionResult:
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


def request():
    return {
        "schema_version": 1,
        "job_kind": "refresh_graph",
        "graph_id": "synthetic-service",
        "request_id": "job-service-1",
        "idempotency_key": "service-key-1",
        "priority": "manual",
        "operation_options": {"reason": "service-integration"},
    }


def test_service_and_client_own_authentication_restart_and_cleanup():
    with short_test_directory("async3-", "coordinator.sock") as directory:
        _exercise_service_restart(Path(directory))


def _exercise_service_restart(runtime_directory):
    store = ServiceStore()
    coordinator = ServiceCoordinator(store)
    service = CoordinatorService(
        coordinator,
        store,
        runtime_directory,
        idle_poll_seconds=0.01,
        heartbeat_seconds=0.02,
    )

    service.start(lambda: None)
    first_client = LocalCoordinatorClient(service.socket_path, service.token_path)
    first_health = first_client.health()
    assert first_health["status"] == "ready"
    assert first_health["health_schema_version"] == 1
    assert first_health["transport"] == {"status": "ready"}
    assert first_client.submit(request()) == {
        "job_id": "job-service-1",
        "state": "queued",
        "replayed": False,
    }
    invalid = request()
    invalid["operation_options"] = {"reason": "not;a-category"}
    try:
        first_client.submit(invalid)
    except CoordinatorClientError as error:
        assert str(error) == "invalid_request"
    else:
        raise AssertionError("an invalid request was accepted")
    assert first_client.status("job-service-1")["state"] == "queued"
    assert first_client.cancel("job-service-1") == {
        "job_id": "job-service-1",
        "state": "cancelled",
    }
    assert first_client.wait("job-service-1")["state"] == "cancelled"
    service.stop()
    assert not service.socket_path.exists()
    assert not service.token_path.exists()

    store.state = "queued"
    service.start(lambda: None)
    try:
        try:
            first_client.health()
        except CoordinatorClientError as error:
            assert str(error) == "unauthorized"
        else:
            raise AssertionError("a stale client token was accepted")
        replacement = LocalCoordinatorClient(service.socket_path, service.token_path)
        replacement_health = replacement.health()
        assert replacement_health["status"] == "ready"
        assert replacement_health["health_schema_version"] == 1
    finally:
        service.stop()


def test_real_control_store_runs_synthetic_job_through_service_client_seam():
    require_postgres_binaries()
    with temporary_postgres() as postgres:
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
        coordinator = build_synthetic_coordinator(
            store, "coordinator-service", "success"
        )
        with short_test_directory("async3-", "coordinator.sock") as directory:
            service = CoordinatorService(
                coordinator,
                store,
                Path(directory),
                idle_poll_seconds=0.01,
                heartbeat_seconds=0.05,
            )
            service.start(lambda: None)
            try:
                client = LocalCoordinatorClient(
                    service.socket_path, service.token_path
                )
                submitted = client.submit(request())
                assert submitted["state"] == "queued"
                job_id = submitted["job_id"]
                assert isinstance(job_id, str)
                listed = client.list_jobs(limit=1, graph_id="synthetic-service")
                listed_jobs = listed["jobs"]
                assert isinstance(listed_jobs, list)
                first_job = listed_jobs[0]
                assert isinstance(first_job, dict)
                assert first_job["job_id"] == job_id
                assert first_job["graph_id"] == "synthetic-service"
                deadline = time.monotonic() + 3
                while True:
                    status = client.wait(job_id)
                    if status["state"] == "succeeded":
                        break
                    assert time.monotonic() < deadline
            finally:
                service.stop()


def test_configured_graph_recovers_committed_attempt_before_restart_ready(monkeypatch):
    require_postgres_binaries()
    with short_test_directory("async7-", "coordinator/coordinator.sock") as directory:
        root = Path(directory)
        repository = root / "repository"
        repository.mkdir()
        (repository / "README.md").write_text("# Configured\n", encoding="utf-8")
        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            with psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname=postgres.database,
                password=postgres.password,
                autocommit=True,
            ) as bootstrap:
                bootstrap.execute("CREATE DATABASE async7_control")
            config_path = root / "ops.toml"
            config_path.write_text(
                _configured_ops_text(postgres, repository), encoding="utf-8"
            )
            monkeypatch.setenv("ASYNC7_TEST_PASSWORD", postgres.password)
            ambient_pgpassword = os.environ.get("PGPASSWORD")

            def connect():
                return psycopg.connect(
                    host=postgres.host,
                    port=postgres.port,
                    user=postgres.user,
                    dbname="async7_control",
                    password=postgres.password,
                )

            store = ControlStore(connect)
            store.initialize_schema()
            managed_psql = Path(postgres.psql_command)
            assert managed_psql.name == "psql"
            resolver = ConfiguredRefreshResolver(
                config_path, managed_psql
            )
            coordinator = build_configured_refresh_coordinator(
                store, "coordinator-configured", resolver, root
            )
            service = CoordinatorService(
                coordinator,
                store,
                root,
                request_resolver=resolver.resolve_request,
                idle_poll_seconds=0.01,
                heartbeat_seconds=0.05,
            )
            service.start(lambda: None)
            try:
                client = LocalCoordinatorClient(
                    service.socket_path, service.token_path
                )
                payload = request()
                payload["graph_id"] = "configured-refresh"
                payload["request_id"] = "configured-service-request"
                payload["idempotency_key"] = "configured-service-key"
                submitted = client.submit(payload)
                job_id = submitted["job_id"]
                assert isinstance(job_id, str)
                deadline = time.monotonic() + 10
                while True:
                    status = client.wait(job_id)
                    if status["state"] == "succeeded":
                        break
                    assert time.monotonic() < deadline, status
                assert postgres.password not in repr(status)
            finally:
                service.stop()
            with connect() as control_connection:
                with control_connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE jobs SET state = 'reconciliation_required', "
                        "publication_state = 'commit_unknown', finished_at = NULL, "
                        "error_category = 'publication_unknown' WHERE job_id = %s",
                        (job_id,),
                    )
                    cursor.execute(
                        "UPDATE job_attempts SET publication_state = 'commit_unknown', "
                        "is_current = true "
                        "WHERE job_id = %s AND attempt = 1",
                        (job_id,),
                    )
                    cursor.execute(
                        "INSERT INTO graph_leases("
                        "graph_id, job_id, attempt, coordinator_instance_id, "
                        "fencing_epoch, worker_identity, expires_at) "
                        "SELECT j.graph_id, j.job_id, a.attempt, "
                        "a.coordinator_instance_id, a.fencing_epoch, "
                        "a.worker_identity, now() - interval '1 second' "
                        "FROM jobs AS j JOIN job_attempts AS a "
                        "ON a.job_id = j.job_id AND a.attempt = j.current_attempt "
                        "WHERE j.job_id = %s",
                        (job_id,),
                    )
            restarted_coordinator = build_configured_refresh_coordinator(
                store, "coordinator-restarted", resolver, root
            )
            restarted_service = CoordinatorService(
                restarted_coordinator,
                store,
                root,
                request_resolver=resolver.resolve_request,
                idle_poll_seconds=0.01,
                heartbeat_seconds=0.05,
            )
            restarted_service.start(restarted_coordinator.recover_startup)
            try:
                report = restarted_coordinator.startup_recovery_report
                assert isinstance(report, StartupRecoveryReport)
                assert report.scanned == 1, report
                assert report.resolved == 1
                assert report.pending == 0
                assert store.status(job_id).state == "succeeded"
            finally:
                restarted_service.stop()
            with psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname=postgres.database,
                password=postgres.password,
            ) as graph_connection:
                receipt = graph_connection.execute(
                    "SELECT publication_job_id, publication_attempt "
                    "FROM runs ORDER BY id DESC LIMIT 1"
                ).fetchone()
            assert receipt == (job_id, 1)
            assert not tuple(root.glob("refresh-*.json"))
            assert os.environ.get("PGPASSWORD") == ambient_pgpassword


def _configured_ops_text(postgres, repository: Path) -> str:
    return f'''schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"
password_env = "ASYNC7_TEST_PASSWORD"

[[graphs]]
id = "configured-refresh"
name = "Configured Refresh"
root_path = "{repository}"
repository_name = "configured-refresh"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
'''
