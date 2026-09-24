"""Admitted coordinator refresh and control workflow integration tests."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import types
from typing import Any
import unittest
from unittest import mock

from repomap_kg.coordinator.refresh_adapter import (
    _truncate_bytes,
    _extract_diagnostic_summary,
    _nonnegative_count,
)
from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator._core_disposition import CoreDispositionMixin
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.coordinator.local_mode import (
    _coordinator_endpoint_names,
    _resolve_psql_executable,
    serve_configured_coordinator,
    CoordinatorModeError as LocalCoordinatorModeError,
)
from repomap_kg.coordinator.configured_refresh import (
    ConfiguredRefreshResolver,
)
from repomap_kg.coordinator.polling import (
    PollingScheduler,
    PollOutcome,
)


class _MockStore:
    def __init__(self) -> None:
        self.leases_released: list[Any] = []
        self.markers: list[Any] = []
        self.reconciliations: list[Any] = []
        self.retries: list[Any] = []
        self.state_status = mock.MagicMock(state="cancel_requested")

    def status(self, job_id: str) -> Any:
        return self.state_status

    def release_graph_lease(self, *args: Any, **kwargs: Any) -> bool:
        self.leases_released.append((args, kwargs))
        return True

    def record_publication_marker(self, claim: Any, **kwargs: Any) -> bool:
        self.markers.append((claim, kwargs))
        return True

    def mark_reconciliation_required(self, *args: Any, **kwargs: Any) -> bool:
        self.reconciliations.append((args, kwargs))
        return True

    def mark_attempt_terminated(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def schedule_retry(self, *args: Any, **kwargs: Any) -> bool:
        self.retries.append((args, kwargs))
        return True


class _MockCore(CoreDispositionMixin):
    def __init__(self, store: Any) -> None:
        self._store = store
        self._instance_id = "inst-core-1"
        self._fencing_epoch = 1
        self._publication_reader = mock.MagicMock()
        self._retry_policy: Any = mock.MagicMock()
        self._transitions: list[Any] = []

    def _require_started(self) -> int:
        return 1

    def _transition(
        self,
        claim: Any,
        expected_state: str,
        new_state: str,
        publication_state: str | None = None,
        error_category: str | None = None,
        diagnostic_summary: str | None = None,
    ) -> bool:
        self._transitions.append((claim, expected_state, new_state))
        return True

    def _reconcile_current(self, claim: Any) -> str:
        return "reconciled_current"


class RefreshControlWorkflowsIntegrationTests(unittest.TestCase):
    def test_refresh_adapter_diagnostics_and_truncation(self) -> None:
        self.assertEqual(_truncate_bytes("abc", 5), "abc")
        self.assertEqual(_truncate_bytes("你好世界", 4), "你")
        self.assertEqual(_truncate_bytes("你好世界", 6), "你好")
        self.assertEqual(_truncate_bytes("你好世界", 20), "你好世界")

        res_stderr = types.SimpleNamespace(stderr="refresh-failure: detail msg\nsecond line")
        self.assertEqual(_extract_diagnostic_summary(res_stderr), "refresh-failure: detail msg")

        res_term = types.SimpleNamespace(terminal={"diagnostics": ["diag1", "diag2"]})
        self.assertEqual(_extract_diagnostic_summary(res_term), "diag1;diag2")

        res_trunc = types.SimpleNamespace(stderr="x" * 300, stderr_truncated=True)
        summary = _extract_diagnostic_summary(res_trunc)
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertTrue(summary.endswith("..."))

        res_timeout = types.SimpleNamespace(process_timed_out=True)
        self.assertEqual(_extract_diagnostic_summary(res_timeout), "worker_timed_out")
        res_hb = types.SimpleNamespace(heartbeat_timed_out=True)
        self.assertEqual(_extract_diagnostic_summary(res_hb), "heartbeat_timed_out")
        res_hello = types.SimpleNamespace(hello_timed_out=True)
        self.assertEqual(_extract_diagnostic_summary(res_hello), "hello_timed_out")
        res_ret = types.SimpleNamespace(returncode=137)
        self.assertEqual(_extract_diagnostic_summary(res_ret), "worker_exit:137")
        res_abrupt = types.SimpleNamespace(returncode=None)
        self.assertEqual(_extract_diagnostic_summary(res_abrupt), "worker_exit:abrupt_termination")

        self.assertEqual(_nonnegative_count(None), 0)
        self.assertEqual(_nonnegative_count(42), 42)
        with self.assertRaises(ValueError):
            _nonnegative_count(-1)
        with self.assertRaises(ValueError):
            _nonnegative_count(True)
        with self.assertRaises(ValueError):
            _nonnegative_count(2**64)

    def test_core_disposition_lifecycle_and_markers(self) -> None:
        store = _MockStore()
        core = _MockCore(store)
        claim = JobClaim(
            job_id="j1",
            graph_id="g1",
            attempt=1,
            instance_id="inst1",
            fencing_epoch=1,
            config_generation="cg1:0",
        )

        store.state_status = mock.MagicMock(state="cancel_requested")
        outcome = core._finish_prestart_cancel(claim)
        self.assertEqual(outcome, "cancelled")
        self.assertEqual(len(store.leases_released), 1)

        store.state_status = mock.MagicMock(state="running")
        self.assertEqual(core._finish_prestart_cancel(claim), "ownership_lost")

        self.assertFalse(core._record_marker_if_available(claim, {}))
        valid_term = {
            "latest_run_identity": "r1",
            "source_generation": "sg1:0",
            "config_generation": "cg1:0",
            "extractor_generation": "eg1:0",
            "canonicalizer_generation": "kag1:0",
        }
        self.assertTrue(core._record_marker_if_available(claim, valid_term))

        core._retry_policy.may_retry.return_value = True
        core._retry_policy.delay_seconds.return_value = 5.0
        res = core._dispose_terminal(
            claim,
            "running",
            {
                "status": "failed",
                "error_category": "transient",
                "publication_state": "not_started",
                "_termination_proved": True,
            },
        )
        self.assertEqual(res, "queued")

    def test_service_lifecycle_transitions(self) -> None:
        coord = mock.MagicMock()
        store = mock.MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chmod(tmpdir, 0o700)
            service = CoordinatorService(coord, store, Path(tmpdir))
            service.stop()
            coord.startup.side_effect = RuntimeError("simulated startup failure")
            with self.assertRaises(RuntimeError):
                service.start(lambda: None)
            h = service.health()
            self.assertEqual(h["status"], "stopped")
            svc_obj = h.get("service")
            self.assertIsInstance(svc_obj, dict)
            assert isinstance(svc_obj, dict)
            self.assertEqual(svc_obj["status"], "stopped")
            self.assertFalse(service.socket_path.exists())
            self.assertFalse(service.token_path.exists())

            coord.startup.side_effect = None
            coord.startup.return_value = 1
            coord.run_once.return_value = "idle"
            coord.heartbeat.return_value = True
            service.start(lambda: None)
            try:
                self.assertEqual(service.health()["status"], "ready")
                self.assertTrue(service.socket_path.exists())
                self.assertTrue(service.token_path.exists())
            finally:
                service.stop()
            self.assertEqual(service.health()["status"], "stopped")
            self.assertFalse(service.socket_path.exists())
            self.assertFalse(service.token_path.exists())

    def test_local_mode_runtime_and_executable_resolution(self) -> None:
        sock, token = _coordinator_endpoint_names("posix")
        self.assertEqual(sock, "coordinator.sock")
        self.assertEqual(token, "coordinator.token")
        ep_json, cred_json = _coordinator_endpoint_names("nt")
        self.assertEqual(ep_json, "coordinator.endpoint.json")

        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(LocalCoordinatorModeError):
                _resolve_psql_executable(None)

        runtime = mock.MagicMock()
        runtime.ready_payload.return_value = {"ready": True}
        runtime.health.return_value = {"status": "degraded"}
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(LocalCoordinatorModeError):
                serve_configured_coordinator(
                    Path(tmpdir) / "fake-home",
                    ready_callback=lambda p: None,
                    runtime_factory=lambda h, **kw: runtime,
                    stop_event=mock.MagicMock(wait=mock.MagicMock(return_value=False)),
                )

    def test_configured_refresh_and_polling_scheduler(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "cfg.toml"
            psql_path = Path(tmpdir) / "bin_psql"
            with self.assertRaises(ValueError):
                ConfiguredRefreshResolver(
                    cfg_path,
                    psql_path,
                    postgres_user="u1",
                    postgres_password=None,
                )
            resolver = ConfiguredRefreshResolver(cfg_path, psql_path)
            bad_req: Any = "not-a-map"
            with self.assertRaises(ValueError):
                resolver.resolve_request(bad_req)

        sched = PollingScheduler(mock.MagicMock(), mock.MagicMock(), interval_seconds=1.0)
        outcome_cur = PollOutcome(category="current", refresh_requested=False, file_count=1, total_bytes=100)
        sched._record_outcome(outcome_cur)
        self.assertEqual(sched.health()["polls_current"], 1)
        self.assertEqual(sched.health()["last_poll_category"], "current")

        outcome_canc = PollOutcome(category="cancelled", refresh_requested=False, file_count=1, total_bytes=100)
        sched._record_outcome(outcome_canc)
        self.assertEqual(sched.health()["polls_cancelled"], 1)
        self.assertEqual(sched.health()["last_poll_category"], "cancelled")

        outcome_to = PollOutcome(category="source_timeout", refresh_requested=False, file_count=1, total_bytes=100)
        sched._record_outcome(outcome_to)
        self.assertEqual(sched.health()["polls_timed_out"], 1)

        outcome_inv = PollOutcome(category="source_invalid", refresh_requested=False, file_count=1, total_bytes=100)
        sched._record_outcome(outcome_inv)
        self.assertEqual(sched.health()["polls_invalid"], 1)
        self.assertEqual(sched.health()["last_poll_category"], "source_invalid")
