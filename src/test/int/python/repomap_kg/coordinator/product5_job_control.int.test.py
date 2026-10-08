"""Integration coverage for coordinator job control wire semantics, health validation, and table formats."""

from __future__ import annotations

from contextlib import contextmanager

import os
import secrets
import sys
from repomap_test_support.test_scratch import short_test_directory
import unittest
from typing import Any

from repomap_kg.coordinator.client import CoordinatorClientError, LocalCoordinatorClient
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.job_control import (
    CoordinatorModeError,
    cancel_coordinator_job,
    coordinator_health,
    coordinator_job_status,
    format_coordinator_health_table,
    format_coordinator_job_table,
    format_coordinator_jobs_table,
    list_coordinator_jobs,
    wait_for_coordinator_job,
)
from repomap_kg.coordinator.local_mode import coordinator_runtime_paths
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.coordinator.startup_recovery import StartupRecoveryReport
from repomap_kg.coordinator.transport import (
    LocalRequestDispatcher,
    LoopbackTcpService,
    UnixSocketService,
)
from repomap_test_support.startup_recovery_scenarios import _harness, _req


def _valid_health_payload(version: int = 2, status: str = "ready") -> dict[str, object]:
    sections = {
        name: {"status": "ready"}
        for name in ("service", "ownership", "queue", "workers", "publication", "polling", "transport", "storage")
    }
    payload: dict[str, object] = {"health_schema_version": version, "status": status, **sections}
    if version == 2:
        payload["recovery_diagnostics"] = [{"sequence": 1, "category": "worker_crash", "summary": "exit_code_1"}]
    return payload


class _CommandCoordinator:
    """Pause only background claims while testing control commands on the real store."""

    def __init__(self, coordinator: SyntheticCoordinator) -> None:
        self.coordinator = coordinator

    def __getattr__(self, name: str) -> Any:
        return getattr(self.coordinator, name)

    def run_once(self) -> str:
        return "idle"


def _record(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return value


def _records(value: object) -> list[dict[str, Any]]:
    assert isinstance(value, list) and all(isinstance(item, dict) for item in value)
    return value


@contextmanager
def _service_harness():
    # PostgreSQL retains its harness; this owner supplies the portable endpoint root.
    with _harness() as (store, _cap_dir, connect):
        with short_test_directory("p5-service-", "coordinator/coordinator.sock") as home:
            yield store, home, connect


class Product5JobControlIntegrationTests(unittest.TestCase):
    def test_job_control_status_cancel_wait_live_wire(self) -> None:
        with _service_harness() as (store, cap_dir, _connect):
            rt_dir, _, _ = coordinator_runtime_paths(cap_dir, create=True)
            sub_run = store.submit(_req("synthetic-service", "jc-run"))
            sub_succ = store.submit(_req("synthetic-service", "jc-succ"))
            sub_canc = store.submit(_req("synthetic-service", "jc-canc"))

            def worker_runner(claim, cancel_event):
                if claim.job_id == sub_succ.job_id:
                    return {
                        "status": "succeeded", "publication_state": "committed",
                        "latest_run_identity": "r1", "source_generation": claim.source_generation,
                        "config_generation": claim.config_generation, "extractor_generation": claim.extractor_generation,
                        "canonicalizer_generation": claim.canonicalizer_generation, "_termination_proved": True,
                    }
                return {
                    "status": "failed", "publication_state": "rolled_back",
                    "error_category": "permanent", "_termination_proved": True,
                }

            coord = SyntheticCoordinator(store, "coord-jc", worker_runner)
            svc = CoordinatorService(_CommandCoordinator(coord), store, rt_dir, idle_poll_seconds=0.01, heartbeat_seconds=0.05)
            svc.start(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
            try:
                status_res = coordinator_job_status(cap_dir, sub_run.job_id)
                self.assertEqual(status_res["command"], "coordinator-job-status")
                self.assertEqual(status_res["result"], "ready")
                self.assertEqual(_record(status_res["job"])["job_id"], sub_run.job_id)
                self.assertEqual(_record(status_res["job"])["state"], "queued")

                cancel_res = cancel_coordinator_job(cap_dir, sub_run.job_id)
                self.assertEqual(cancel_res["command"], "coordinator-job-cancel")
                self.assertEqual(cancel_res["result"], "accepted")
                self.assertIn(_record(cancel_res["job"])["state"], ("cancel_requested", "cancelled"))

                for bad_wait in (0, -5, 86401):
                    with self.assertRaises(CoordinatorModeError) as cm_wait:
                        wait_for_coordinator_job(cap_dir, sub_succ.job_id, wait_timeout_seconds=bad_wait)
                    self.assertIn("coordinator_wait_invalid", str(cm_wait.exception))

                self.assertEqual(coord.run_once(), "succeeded")
                wait_succ = wait_for_coordinator_job(cap_dir, sub_succ.job_id)
                self.assertEqual(wait_succ["result"], "success")
                self.assertEqual(_record(wait_succ["job"])["state"], "succeeded")

                cancel_canc = cancel_coordinator_job(cap_dir, sub_canc.job_id)
                self.assertEqual(cancel_canc["result"], "accepted")
                self.assertEqual(_record(cancel_canc["job"])["state"], "cancelled")

                wait_fail = wait_for_coordinator_job(cap_dir, sub_canc.job_id)
                self.assertEqual(wait_fail["result"], "failure")
                self.assertEqual(_record(wait_fail["job"])["state"], "cancelled")

                sub_timeout = store.submit(_req("synthetic-service", "jc-timeout"))
                fake_now = [100.0]
                def monotonic_advancing():
                    val = fake_now[0]
                    fake_now[0] += 50.0
                    return val

                with self.assertRaises(CoordinatorModeError) as cm_to:
                    wait_for_coordinator_job(cap_dir, sub_timeout.job_id, wait_timeout_seconds=10, monotonic=monotonic_advancing)
                self.assertIn("coordinator_wait_timeout", str(cm_to.exception))
            finally:
                svc.stop()

    def test_job_control_listing_and_cursor_continuation_wire(self) -> None:
        with _service_harness() as (store, cap_dir, _connect):
            rt_dir, _, _ = coordinator_runtime_paths(cap_dir, create=True)
            store.submit(_req("synthetic-service", "list-1"))
            store.submit(_req("synthetic-service", "list-2"))

            coord = SyntheticCoordinator(store, "coord-list", lambda c, e: {})
            svc = CoordinatorService(_CommandCoordinator(coord), store, rt_dir, idle_poll_seconds=0.01, heartbeat_seconds=0.05)
            svc.start(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
            try:
                listed = list_coordinator_jobs(cap_dir, limit=10, graph_id="synthetic-service")
                self.assertEqual(listed["command"], "coordinator-jobs")
                self.assertEqual(listed["result"], "ready")
                self.assertGreaterEqual(len(_records(listed["jobs"])), 2)

                page1 = list_coordinator_jobs(cap_dir, limit=1, graph_id="synthetic-service")
                self.assertEqual(len(_records(page1["jobs"])), 1)
                cursor1 = page1["next_cursor"]
                assert isinstance(cursor1, str)
                if cursor1:
                    page2 = list_coordinator_jobs(cap_dir, limit=1, graph_id="synthetic-service", cursor=cursor1)
                    self.assertEqual(len(_records(page2["jobs"])), 1)
                    self.assertNotEqual(_records(page1["jobs"])[0]["job_id"], _records(page2["jobs"])[0]["job_id"])
            finally:
                svc.stop()

    def test_job_control_defensive_malformed_hostile_peer_wire(self) -> None:
        with short_test_directory("jc-hostile-", "coordinator/coordinator.sock") as home:
            rt_dir, socket_path, token_path = coordinator_runtime_paths(home, create=True)
            token = secrets.token_urlsafe(32)
            token_path.write_text(token, encoding="utf-8")
            os.chmod(token_path, 0o600)

            mock_payloads: dict[str, object] = {
                "health": _valid_health_payload(version=2),
                "status": {"job_id": "j-hostile", "graph_id": "g1", "state": "running"},
                "cancel": {"job_id": "j-hostile", "graph_id": "g1", "state": "running"},
                "list": {"jobs": [{"job_id": "j1", "graph_id": "g1", "state": "running", "submitted_at": "2026-10-04T12:00:00.000000Z"}], "next_cursor": "corrupted_token!"},
            }

            handlers = {
                "health": lambda p: mock_payloads["health"],
                "status": lambda p: mock_payloads["status"],
                "wait": lambda p: mock_payloads["status"],
                "cancel": lambda p: mock_payloads["cancel"],
                "list": lambda p: mock_payloads["list"],
                "submit": lambda p: {"job_id": "j1", "state": "queued", "replayed": False},
            }
            dispatcher = LocalRequestDispatcher(token, handlers, max_in_flight=4)
            with UnixSocketService(socket_path, dispatcher, max_connections=4):
                res_v2 = coordinator_health(home)
                self.assertEqual(res_v2["result"], "ready")
                self.assertEqual(_record(res_v2["health"])["health_schema_version"], 2)

                mock_payloads["health"] = _valid_health_payload(version=1, status="degraded")
                res_v1 = coordinator_health(home)
                self.assertEqual(res_v1["result"], "degraded")
                self.assertEqual(_record(res_v1["health"])["health_schema_version"], 1)

                for bad_ver in (0, 3, "2", None):
                    mock_payloads["health"] = {**_valid_health_payload(version=1), "health_schema_version": bad_ver}
                    with self.assertRaises(CoordinatorModeError):
                        coordinator_health(home)

                mock_payloads["health"] = {**_valid_health_payload(version=1), "status": "unknown_status"}
                with self.assertRaises(CoordinatorModeError):
                    coordinator_health(home)

                mock_payloads["health"] = {**_valid_health_payload(version=1), "unknown_extra": 1}
                with self.assertRaises(CoordinatorModeError):
                    coordinator_health(home)

                bad_sec = _valid_health_payload(version=1)
                bad_sec["storage"] = {"status": "invalid_status"}
                mock_payloads["health"] = bad_sec
                with self.assertRaises(CoordinatorModeError):
                    coordinator_health(home)

                base_v2 = _valid_health_payload(version=2)
                mock_payloads["health"] = {
                    **base_v2,
                    "recovery_diagnostics": [{"sequence": i, "category": "c", "summary": "s"} for i in range(33)],
                }
                with self.assertRaisesRegex(CoordinatorClientError, "invalid_response"):
                    coordinator_health(home)

                for wire_diag in (
                    [{"sequence": 1, "category": "", "summary": "s"}],
                    [{"sequence": 1, "category": "c", "summary": ""}],
                ):
                    mock_payloads["health"] = {**base_v2, "recovery_diagnostics": wire_diag}
                    with self.assertRaisesRegex(CoordinatorClientError, "invalid_response"):
                        coordinator_health(home)

                for mode_diag in (
                    "not_a_list",
                    ["not_a_mapping"],
                    [{"sequence": 1, "category": "c"}],
                    [{"sequence": 1, "category": "bad cat spaces", "summary": "s"}],
                    [{"sequence": 1, "category": "c", "summary": "x" * 257}],
                    [{"sequence": -1, "category": "c", "summary": "s"}],
                    [{"sequence": True, "category": "c", "summary": "s"}],
                    [{"sequence": "one", "category": "c", "summary": "s"}],
                    [{"sequence": 1, "category": 1, "summary": "s"}],
                    [{"sequence": 1, "category": "c" * 65, "summary": "s"}],
                    [{"sequence": 1, "category": "c", "summary": None}],
                ):
                    mock_payloads["health"] = {**base_v2, "recovery_diagnostics": mode_diag}
                    with self.assertRaises(CoordinatorModeError):
                        coordinator_health(home)

                mock_payloads["status"] = {"job_id": "j-hostile", "graph_id": "g1", "state": "not_a_valid_state"}
                with self.assertRaises(CoordinatorModeError):
                    coordinator_job_status(home, "j-hostile")

                mock_payloads["status"] = {"job_id": "j-hostile", "graph_id": "g1", "state": "running"}
                with self.assertRaises(CoordinatorModeError):
                    coordinator_job_status(home, "different-id")

                with self.assertRaises(CoordinatorModeError) as cm_can:
                    cancel_coordinator_job(home, "j-hostile")
                self.assertIn("coordinator_response_invalid", str(cm_can.exception))

                with self.assertRaises(CoordinatorModeError):
                    list_coordinator_jobs(home, limit=5)

                mock_payloads["health"] = {**_valid_health_payload(version=1), "credential": "secret"}
                with self.assertRaisesRegex(CoordinatorClientError, "invalid_response"):
                    coordinator_health(home)

    def test_job_control_table_formatting_complete_scenarios(self) -> None:
        health_with_diags = _valid_health_payload(version=2)
        formatted_health = format_coordinator_health_table({"health": health_with_diags})
        self.assertIn("RepoMap coordinator health", formatted_health)
        self.assertIn("recovery_diagnostic | sequence | category | summary", formatted_health)
        self.assertIn("recovery_diagnostic | 1 | worker_crash | exit_code_1", formatted_health)

        malformed = _valid_health_payload(version=2)
        malformed["recovery_diagnostics"] = ["invalid-row", {"sequence": 2, "category": "c", "summary": "s"}]
        with self.assertRaises(CoordinatorModeError):
            format_coordinator_health_table({"health": malformed})

        multi_diags = _valid_health_payload(version=2)
        multi_diags["recovery_diagnostics"] = [
            {"sequence": 2, "category": "c", "summary": "s"},
            {"sequence": 3, "category": "worker_crash", "summary": "exit_code_1"},
        ]
        formatted_multi = format_coordinator_health_table({"health": multi_diags})
        self.assertIn("recovery_diagnostic | 2 | c | s", formatted_multi)
        self.assertIn("recovery_diagnostic | 3 | worker_crash | exit_code_1", formatted_multi)
        health_no_diags = _valid_health_payload(version=1)
        formatted_v1 = format_coordinator_health_table({"health": health_no_diags})
        self.assertNotIn("recovery_diagnostic | sequence", formatted_v1)
        self.assertIn("service | ready", formatted_v1)

        with self.assertRaises(CoordinatorModeError):
            format_coordinator_health_table({"health": "invalid"})

        job_full = {
            "result": "ready",
            "job": {
                "job_id": "j-fmt-1", "graph_id": "synthetic-service", "state": "running",
                "attempt_count": 2, "phase": "scanning", "completed": 5, "total": 10,
                "error_category": "none", "diagnostic_summary": "running_normally",
            },
        }
        tbl_full = format_coordinator_job_table(job_full)
        self.assertIn("RepoMap coordinator job", tbl_full)
        self.assertIn("attempt_count | 2", tbl_full)
        self.assertIn("phase | scanning", tbl_full)
        self.assertIn("completed | 5", tbl_full)
        self.assertIn("diagnostic_summary | running_normally", tbl_full)

        with self.assertRaises(CoordinatorModeError):
            format_coordinator_job_table({"job": "not_dict"})

        jobs_page = {
            "jobs": [
                {"job_id": "j1", "graph_id": "synthetic-service", "state": "succeeded", "submitted_at": "2026-10-04T12:00:00.000000Z"},
                {"job_id": "j2", "graph_id": "synthetic-service", "state": "running", "submitted_at": "2026-10-04T12:05:00.000000Z"},
            ],
            "next_cursor": "cursor_token_123",
        }
        tbl_jobs = format_coordinator_jobs_table(jobs_page)
        self.assertIn("RepoMap coordinator jobs", tbl_jobs)
        self.assertIn("j1 | synthetic-service | succeeded | 2026-10-04T12:00:00.000000Z", tbl_jobs)
        self.assertIn("next_cursor | cursor_token_123", tbl_jobs)

        tbl_empty_jobs = format_coordinator_jobs_table({"jobs": []})
        self.assertIn("RepoMap coordinator jobs", tbl_empty_jobs)
        self.assertNotIn("next_cursor", tbl_empty_jobs)

        with self.assertRaises(CoordinatorModeError):
            format_coordinator_jobs_table({"jobs": "not_a_list"})

    def test_job_control_tcp_loopback_transport_wire(self) -> None:
        with _service_harness() as (store, cap_dir, _connect):
            rt_dir, _, _ = coordinator_runtime_paths(cap_dir, create=True)
            sub = store.submit(_req("synthetic-service", "tcp-jc"))
            coord = SyntheticCoordinator(store, "coord-tcp-jc", lambda c, e: {})
            svc = CoordinatorService(_CommandCoordinator(coord), store, rt_dir, transport_factory=LoopbackTcpService, idle_poll_seconds=0.01, heartbeat_seconds=0.05)
            svc.socket_path = rt_dir / "coordinator.endpoint.json"
            svc.token_path = svc.socket_path
            svc.start(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
            try:
                hlth = coordinator_health(cap_dir, client_factory=lambda s, t: LocalCoordinatorClient(svc.socket_path, svc.token_path))
                self.assertEqual(hlth["result"], "ready")
                status = coordinator_job_status(cap_dir, sub.job_id, client_factory=lambda s, t: LocalCoordinatorClient(svc.socket_path, svc.token_path))
                self.assertEqual(_record(status["job"])["state"], "queued")
                listed = list_coordinator_jobs(cap_dir, limit=5, graph_id="synthetic-service", client_factory=lambda s, t: LocalCoordinatorClient(svc.socket_path, svc.token_path))
                self.assertGreaterEqual(len(_records(listed["jobs"])), 1)
            finally:
                svc.stop()


if __name__ == "__main__":
    sys.exit("Direct execution unsupported: use tools/run_tests.py --suite int with container sandbox admission.")
