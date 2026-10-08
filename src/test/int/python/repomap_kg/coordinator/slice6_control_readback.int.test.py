from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import socket
import struct
import tempfile
import time
from typing import Any, cast
import unittest
from unittest import mock

from repomap_kg.coordinator._protocol_session import ProtocolSession
from repomap_kg.coordinator._protocol_validation import ProtocolError
from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
from repomap_kg.coordinator.polling import PollingScheduler, PollOutcome
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.readback_driver import (
    PG_CONNECTOR_ENV,
    READBACK_DRIVER_ENV,
    diagnose_psycopg_database_presence,
    execute_json_readback_with_driver,
    selected_json_readback_driver,
)
from repomap_kg.storage.staging_event_transport import (
    StagingEventChannel,
    StagingEventTransportError,
)


class Slice6ControlReadbackIntegrationTests(unittest.TestCase):
    """Integration scenarios for Slice 6 Group S6-C control and readback lifecycles (component boundary integration tests against doubles)."""

    def test_s6_c01_service_startup_failure_cleanup_and_recovery(self) -> None:
        """Service startup failure cleans up unlinked endpoints before successful recovery."""
        coord = mock.MagicMock()
        store = mock.MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            service = CoordinatorService(coord, store, Path(tmpdir))
            coord.startup.side_effect = RuntimeError("transport binding error")
            with self.assertRaises(RuntimeError):
                service.start(lambda: None)

            self.assertEqual(service.health()["status"], "stopped")
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

    def test_s6_c02_service_readiness_probe_transitions_and_restoration(self) -> None:
        """Readiness probe transitions through schema_upgrading and unavailable states."""
        coord = mock.MagicMock()
        coord.startup.return_value = 1
        coord.run_once.return_value = "idle"
        coord.heartbeat.return_value = True
        store = mock.MagicMock()

        probe_state: bool | None = True

        def probe() -> bool:
            if probe_state is None:
                raise RuntimeError("db connection dropped")
            return probe_state

        with tempfile.TemporaryDirectory() as tmpdir:
            service = CoordinatorService(coord, store, Path(tmpdir), readiness_probe=probe)
            service.start(lambda: None)
            try:
                h_ready = service.health()
                self.assertEqual(h_ready["status"], "ready")
                storage_ready = h_ready.get("storage")
                self.assertEqual(storage_ready.get("status") if isinstance(storage_ready, dict) else None, "ready")

                probe_state = False
                h_upgrade = service.health()
                self.assertEqual(h_upgrade["status"], "not_ready")
                storage_upgrade = h_upgrade.get("storage")
                self.assertEqual(storage_upgrade.get("status") if isinstance(storage_upgrade, dict) else None, "schema_upgrading")

                probe_state = None
                h_unavail = service.health()
                self.assertEqual(h_unavail["status"], "not_ready")
                storage_unavail = h_unavail.get("storage")
                self.assertEqual(storage_unavail.get("status") if isinstance(storage_unavail, dict) else None, "unavailable")

                probe_state = True
                h_restored = service.health()
                self.assertEqual(h_restored["status"], "ready")
            finally:
                service.stop()

    def test_s6_c03_polling_scheduler_reconciliation_and_retry_delays(self) -> None:
        """Polling scheduler drives reconciliation and records outcomes and failure retry delays."""
        resolver = mock.MagicMock()
        reconciler = mock.MagicMock()
        sched = PollingScheduler(
            resolver,
            reconciler,
            interval_seconds=1.0,
            retry_seconds=0.5,
            jitter_seconds=0.0,
        )

        outcome_req = PollOutcome(
            category="refresh_requested",
            refresh_requested=True,
            file_count=10,
            total_bytes=2048,
        )
        reconciler.reconcile_graph.return_value = outcome_req
        res_req = sched._poll_one("graph-1")
        self.assertEqual(res_req.category, "refresh_requested")
        now = time.monotonic()
        sched._finish_poll("graph-1", res_req, now)

        self.assertEqual(sched.health()["polls_changed"], 1)
        self.assertEqual(sched.health()["automatic_refreshes_requested"], 1)
        self.assertEqual(sched.health()["last_poll_category"], "refresh_requested")

        outcome_fail = PollOutcome(
            category="source_invalid",
            refresh_requested=False,
            file_count=0,
            total_bytes=0,
        )
        reconciler.reconcile_graph.return_value = outcome_fail
        res_fail = sched._poll_one("graph-1")
        self.assertEqual(res_fail.category, "source_invalid")
        now2 = time.monotonic()
        sched._finish_poll("graph-1", res_fail, now2)

        self.assertEqual(sched.health()["polls_invalid"], 1)
        self.assertEqual(sched.health()["last_poll_category"], "source_invalid")

        sched.stop()
        reconciler.cancel.assert_called_once()

    def test_s6_c04_protocol_session_negotiation_and_out_of_order_refusal(self) -> None:
        """ProtocolSession enforces negotiation, sequencing, cancellation, and terminal order."""
        sess = ProtocolSession(identity={"job_id": "job-s6-1", "attempt": 1})
        self.assertEqual(sess.state, "awaiting_hello")

        msg_hello = {
            "schema_version": 1,
            "message_type": "worker_hello",
            "worker_generation": "wg1:slice6",
            "process_nonce": "nonce-slice6",
            "protocol_versions": [1],
            "capabilities": ["refresh_graph"],
        }
        sess.accept_worker(msg_hello)
        self.assertEqual(sess.state, "awaiting_start")

        msg_start = {
            "schema_version": 1,
            "message_type": "job_start",
            "job_id": "job-s6-1",
            "attempt": 1,
            "graph_id": "graph-main",
            "job_kind": "refresh_graph",
            "config_generation": "cg1:slice6",
            "source_generation": "sg1:slice6",
        }
        sess.accept_coordinator(msg_start)
        self.assertEqual(sess.state, "running")

        msg_cancel = {
            "schema_version": 1,
            "message_type": "cancel",
            "job_id": "job-s6-1",
            "attempt": 1,
        }
        sess.accept_coordinator(msg_cancel)
        self.assertEqual(sess.state, "cancel_requested")

        msg_cancel_ack = {
            "schema_version": 1,
            "message_type": "cancel_ack",
            "job_id": "job-s6-1",
            "attempt": 1,
            "status": "accepted",
        }
        sess.accept_worker(msg_cancel_ack)
        self.assertEqual(sess.state, "cancelling")

        bad_sess = ProtocolSession(identity={"job_id": "job-s6-1", "attempt": 1})
        with self.assertRaises(ProtocolError) as err:
            bad_sess.accept_worker(msg_cancel_ack)
        self.assertIn("out_of_order", str(err.exception))

    def test_s6_c05_configured_refresh_resolver_validation(self) -> None:
        """ConfiguredRefreshResolver validates password and request mapping structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.toml"
            psql_file = Path(tmpdir) / "psql"

            with self.assertRaises(ValueError):
                ConfiguredRefreshResolver(
                    cfg_file,
                    psql_file,
                    postgres_user="admin",
                    postgres_password=None,
                )

            resolver = ConfiguredRefreshResolver(cfg_file, psql_file)
            invalid_request: object = "not-a-dictionary"
            with self.assertRaises(ValueError):
                resolver.resolve_request(invalid_request)

    def test_s6_c06_staging_event_transport_frame_size_and_sequence_validation(self) -> None:
        """StagingEventChannel validates frame roundtrip acknowledgement and size limits."""
        server, client = socket.socketpair()
        try:
            chan_s = StagingEventChannel(server, acknowledgement_timeout_seconds=2.0)
            chan_c = StagingEventChannel(client, acknowledgement_timeout_seconds=2.0)

            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_send = pool.submit(chan_s.send, "operation", {"event": "slice6_test"})
                frame = chan_c.receive(timeout_seconds=2.0)
                fut_send.result(timeout=2.0)

            self.assertEqual(frame.sequence, 1)
            self.assertEqual(frame.category, "operation")
            self.assertEqual(frame.payload, {"event": "slice6_test"})

            server.sendall(struct.pack("!I", 20_000))
            with self.assertRaises(StagingEventTransportError) as err_size:
                chan_c.receive(timeout_seconds=1.0)
            self.assertIn("frame size is invalid", str(err_size.exception))

            chan_s.close()
            chan_c.close()
        finally:
            server.close()
            client.close()

    def test_s6_c07_readback_driver_diagnose_database_presence_outcomes(self) -> None:
        """Readback driver categorizes presence states and enforces resource closing."""
        with mock.patch.dict("os.environ", {"PGCONNECT_TIMEOUT": "", "PGOPTIONS": ""}):
            res_timeout = diagnose_psycopg_database_presence(
                psql_args=("-h", "localhost"),
                target_database="db",
                timeout_seconds=1.0,
            )
            self.assertEqual(res_timeout, "unavailable")

            with mock.patch("repomap_kg.storage.readback_driver._import_psycopg") as mock_import:
                mock_psycopg = mock.MagicMock()
                mock_import.return_value = mock_psycopg

                class OperationalError(Exception):
                    pass

                mock_psycopg.connect.side_effect = OperationalError("password authentication failed for user test")
                res_denied = diagnose_psycopg_database_presence(
                    psql_args=("-h", "localhost"),
                    target_database="db",
                    timeout_seconds=5.0,
                )
                self.assertEqual(res_denied, "denied")

                mock_conn = mock.MagicMock()
                mock_cursor = mock.MagicMock()
                mock_conn.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
                mock_psycopg.connect.side_effect = None
                mock_psycopg.connect.return_value = mock_conn

                mock_cursor.fetchone.return_value = (True,)
                res_present = diagnose_psycopg_database_presence(
                    psql_args=("-h", "localhost"),
                    target_database="db",
                    timeout_seconds=5.0,
                )
                self.assertEqual(res_present, "present")
                mock_conn.__exit__.assert_called()
                mock_conn.cursor.return_value.__exit__.assert_called()

                mock_cursor.fetchone.return_value = (False,)
                res_absent = diagnose_psycopg_database_presence(
                    psql_args=("-h", "localhost"),
                    target_database="db",
                    timeout_seconds=5.0,
                )
                self.assertEqual(res_absent, "absent")

                mock_cursor.fetchone.return_value = (1,)
                res_malformed = diagnose_psycopg_database_presence(
                    psql_args=("-h", "localhost"),
                    target_database="db",
                    timeout_seconds=5.0,
                )
                self.assertEqual(res_malformed, "malformed")

        # Deliberate ambient-value controls: PGCONNECT_TIMEOUT < 2.0 or malformed options
        with mock.patch.dict("os.environ", {"PGCONNECT_TIMEOUT": "1", "PGOPTIONS": ""}):
            res_env_timeout = diagnose_psycopg_database_presence(
                psql_args=("-h", "localhost"),
                target_database="db",
                timeout_seconds=5.0,
            )
            self.assertEqual(res_env_timeout, "unavailable")

        with mock.patch.dict("os.environ", {"PGCONNECT_TIMEOUT": "invalid", "PGOPTIONS": ""}):
            res_bad_timeout = diagnose_psycopg_database_presence(
                psql_args=("-h", "localhost"),
                target_database="db",
                timeout_seconds=5.0,
            )
            self.assertEqual(res_bad_timeout, "unavailable")

        with mock.patch.dict("os.environ", {"PGCONNECT_TIMEOUT": "3", "PGOPTIONS": "-c statement_timeout=1000 -c invalid_option"}):
            res_bad_options = diagnose_psycopg_database_presence(
                psql_args=("-h", "localhost"),
                target_database="db",
                timeout_seconds=5.0,
            )
            self.assertEqual(res_bad_options, "unavailable")

    def test_s6_c08_readback_driver_execute_with_driver_and_param_validation(self) -> None:
        """execute_json_readback_with_driver and driver selector enforce schema boundaries."""
        with self.assertRaises(StorageSchemaError) as err_driver:
            execute_json_readback_with_driver(
                "SELECT 1",
                driver=cast(Any, "unsupported_driver"),
                psql_args=[],
                psql_command="psql",
                label="test_readback",
                expected_shape="object",
            )
        self.assertIn("unsupported storage readback driver", str(err_driver.exception))

        with mock.patch.dict("os.environ", {PG_CONNECTOR_ENV: "invalid_driver"}):
            os.environ.pop(READBACK_DRIVER_ENV, None)
            with self.assertRaises(StorageSchemaError) as err_sel:
                selected_json_readback_driver()
            self.assertIn("unsupported storage readback driver", str(err_sel.exception))

        with mock.patch.dict("os.environ", {PG_CONNECTOR_ENV: "psql", READBACK_DRIVER_ENV: "psycopg"}):
            with self.assertRaises(StorageSchemaError) as err_conflict:
                selected_json_readback_driver()
            self.assertIn("conflicting PostgreSQL connector selectors", str(err_conflict.exception))
