"""Real control records reach authenticated status, wait and CLI readback."""
from datetime import timedelta
import json
from pathlib import Path

import psycopg
import pytest

from repomap_kg.coordinator.client import LocalCoordinatorClient
from repomap_kg.coordinator.contracts import normalize_request
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.coordinator.storage import ControlStore
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.test_scratch import short_test_directory


class ReadbackCoordinator:
    """Keep the service live without scheduling fixture records."""

    def startup(self, reconcile):
        reconcile()
        return 1

    def run_once(self):
        return "idle"

    def heartbeat(self):
        return True

    def submit(self, action):
        raise AssertionError("readback fixture must not submit")

    def request_cancel(self, job_id):
        raise AssertionError("readback fixture must not cancel")

    def shutdown(self):
        pass


def test_persisted_current_attempt_diagnostic_reaches_supported_cli_and_wait():
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        def connect():
            return psycopg.connect(host=postgres.host, port=postgres.port,
                                   user=postgres.user, dbname=postgres.database,
                                   password=postgres.password)

        store = ControlStore(connect)
        store.initialize_schema()
        request = normalize_request({
            "schema_version": 1, "job_kind": "refresh_graph", "graph_id": "synthetic-diagnostic",
            "request_id": "diagnostic-1", "idempotency_key": "diagnostic-1",
            "priority": "manual", "operation_options": {"reason": "diagnostic-test"},
        }, source_generation="sg1:synthetic", config_generation="cg1:synthetic")
        job_id = store.submit(request).job_id
        assert store.status(job_id).diagnostic_summary is None
        epoch = store.acquire_singleton("diagnostic-owner", timedelta(seconds=60))
        claim = store.claim_next("diagnostic-owner", epoch, timedelta(seconds=60))
        assert claim is not None
        assert store.mark_reconciliation_required(
            claim, expected_state="claimed", category="worker_crash",
            diagnostic_summary="worker_exit:old")
        with connect() as connection:
            connection.execute("UPDATE job_attempts SET is_current = false WHERE job_id = %s", (job_id,))
            connection.execute(
                "INSERT INTO job_attempts (job_id, attempt, coordinator_instance_id, fencing_epoch, "
                "source_generation, config_generation, extractor_generation, canonicalizer_generation, "
                "diagnostic_summary, is_current) SELECT job_id, 2, coordinator_instance_id, fencing_epoch, "
                "source_generation, config_generation, extractor_generation, canonicalizer_generation, "
                "'worker_exit:17', false FROM job_attempts WHERE job_id = %s AND attempt = 1", (job_id,))
            connection.execute("UPDATE jobs SET current_attempt = 2 WHERE job_id = %s", (job_id,))
        # Closed current attempts still own diagnostics; older rows must never win.
        assert store.status(job_id).diagnostic_summary == "worker_exit:17"
        with short_test_directory("diag-", "coordinator/coordinator.sock") as directory:
            home = Path(directory)
            runtime = home / "coordinator"
            runtime.mkdir(mode=0o700)
            service = CoordinatorService(ReadbackCoordinator(), store, runtime,
                                         idle_poll_seconds=0.01, wait_seconds=0.001)
            service.start(lambda: None)
            try:
                client = LocalCoordinatorClient(service.socket_path, service.token_path)
                for diagnostic, expected in (
                    ("worker_exit:17", "worker_exit:17"),
                    ("refresh-failure:permission-denied", "refresh-failure:permission-denied"),
                    ("refresh-failure:/synthetic/source", "diagnostic_withheld"),
                    ("refresh-failure:password=synthetic-sensitive", "diagnostic_withheld"),
                    ("Traceback\nprivate payload", "diagnostic_withheld"),
                    ("é" * 200, "é" * 128), (None, None),
                ):
                    with connect() as connection:
                        connection.execute("UPDATE job_attempts SET diagnostic_summary = %s "
                                           "WHERE job_id = %s AND attempt = 2", (diagnostic, job_id))
                    for read in (client.status, client.wait):
                        status = read(job_id)
                        assert status["state"] == "reconciliation_required"
                        assert status.get("diagnostic_summary") == expected
                        assert ("diagnostic_summary" in status) == (expected is not None)
                    code, stdout, stderr = run_repo_map_in_process(
                        "ops", "coordinator-job-status", "--repo-map-home", str(home),
                        "--job-id", job_id, "--json")
                    assert code == 0 and not stderr
                    assert json.loads(stdout)["job"].get("diagnostic_summary") == expected
                page = client.list_jobs(limit=10)
                jobs = page["jobs"]
                assert isinstance(jobs, list)
                assert all("diagnostic_summary" not in item for item in jobs)
                with connect() as connection:
                    connection.execute("UPDATE jobs SET state = 'queued', publication_state = 'not_started' "
                                       "WHERE job_id = %s", (job_id,))
                    connection.execute("UPDATE job_attempts SET diagnostic_summary = 'worker_exit:17' "
                                       "WHERE job_id = %s AND attempt = 2", (job_id,))
                assert client.status(job_id)["diagnostic_summary"] == "worker_exit:17"
                with connect() as connection:
                    connection.execute("UPDATE jobs SET state = 'running', error_category = NULL "
                                       "WHERE job_id = %s", (job_id,))
                assert "diagnostic_summary" not in client.status(job_id)
            finally:
                service.stop()


@pytest.mark.parametrize(("message", "private", "public"), [
    pytest.param("invalid refresh capability", ":invalid refresh capability",
                 "coordinator_exception:ValueError:invalid refresh capability", id="safe"),
    pytest.param("", "", "coordinator_exception:ValueError", id="class-only"),
    pytest.param("missing /diagfix-7c92/int/source", ":missing [path]",
                 "diagnostic_withheld", id="path"),
    pytest.param("password=diagfix-7c92-int-secret", ":password=[REDACTED]",
                 "diagnostic_withheld", id="secret"),
    pytest.param("postgresql://svc:diagfix-7c92-int-url@host/db", "",
                 "coordinator_exception:ValueError", id="url"),
])
def test_real_catch_all_persists_provenance_and_supported_readback(message, private, public):
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        def connect():
            return psycopg.connect(host=postgres.host, port=postgres.port,
                                   user=postgres.user, dbname=postgres.database,
                                   password=postgres.password)

        store = ControlStore(connect)
        store.initialize_schema()
        request = normalize_request({
            "schema_version": 1, "job_kind": "refresh_graph", "graph_id": "synthetic-diagnostic",
            "request_id": "catch-1", "idempotency_key": "catch-1", "priority": "manual",
            "operation_options": {"reason": "diagnostic-test"},
        }, source_generation="sg1:synthetic", config_generation="cg1:synthetic")
        job_id = store.submit(request).job_id

        def fail(_claim, _cancel):
            raise ValueError(message)

        coordinator = SyntheticCoordinator(store, "diagnostic-owner", fail)
        coordinator.startup(lambda: None)
        try:
            assert coordinator.run_once() == "reconciliation_required"
        finally:
            coordinator.shutdown()
        before = store.status(job_id)
        assert before.state == "reconciliation_required"
        assert before.error_category == "worker_crash"
        assert before.publication_state == "commit_unknown"
        assert before.attempt == 1
        assert before.diagnostic_summary == "coordinator_exception:ValueError" + private
        assert before.diagnostic_summary is not None
        assert "diagfix-7c92" not in before.diagnostic_summary
        with connect() as connection:
            attempts = connection.execute("SELECT * FROM job_attempts WHERE job_id = %s", (job_id,)).fetchall()
            assert connection.execute("SELECT count(*) FROM synthetic_publication_markers").fetchone()[0] == 0
        with short_test_directory("catch-", "coordinator/coordinator.sock") as directory:
            home = Path(directory)
            runtime = home / "coordinator"
            runtime.mkdir(mode=0o700)
            service = CoordinatorService(ReadbackCoordinator(), store, runtime,
                                         idle_poll_seconds=0.01, wait_seconds=0.001)
            service.start(lambda: None)
            try:
                client = LocalCoordinatorClient(service.socket_path, service.token_path)
                status, wait = client.status(job_id), client.wait(job_id)
                assert status == wait
                assert status["diagnostic_summary"] == public
                assert status["state"] == "reconciliation_required"
                assert status["error_category"] == "worker_crash"
                code, stdout, stderr = run_repo_map_in_process(
                    "ops", "coordinator-job-status", "--repo-map-home", str(home),
                    "--job-id", job_id, "--json")
                assert code == 0 and not stderr
                assert json.loads(stdout)["job"] == status
                assert "diagfix-7c92" not in stdout
            finally:
                service.stop()
        assert store.status(job_id) == before
        with connect() as connection:
            assert connection.execute("SELECT * FROM job_attempts WHERE job_id = %s", (job_id,)).fetchall() == attempts
            assert connection.execute("SELECT count(*) FROM synthetic_publication_markers").fetchone()[0] == 0
