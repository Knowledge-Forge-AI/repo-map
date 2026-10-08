from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
from typing import Any, cast
import unittest
from unittest import mock

from repomap_kg.coordinator.polling import PollingScheduler, PollOutcome
from repomap_kg.ops.config import load_ops_config, load_ops_config_home
from repomap_kg.ops.readback import (
    OpsPsqlExecution,
    _OpsContainerReadbackPlan,
    execute_ops_json_readback,
)
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.readback_driver import (
    PG_CONNECTOR_ENV,
    READBACK_DRIVER_ENV,
)
from repomap_kg.storage.staging_event_transport import (
    StagingEventChannel,
    StagingEventTransportError,
)
from repomap_test_support.ops_refresh import VALID_REFRESH_CONFIG
from repomap_test_support.staging_transport_test_harness import BoundedTestPeer


class Slice7ControlReadbackIntegrationTests(unittest.TestCase):
    """Integration scenarios for Slice 7 Group S7-C scheduling, transport, and readback workflows."""

    def test_s7_c01_polling_scheduler_injected_clock_backoff_and_timing(self) -> None:
        """Injected-clock scheduler enforces exponential backoff formula and public health timing."""
        resolver = mock.MagicMock()
        reconciler = mock.MagicMock()
        now = 100.0

        def clock() -> float:
            return now

        sched = PollingScheduler(
            resolver,
            reconciler,
            interval_seconds=10.0,
            retry_seconds=2.0,
            retry_multiplier=2.0,
            max_retry_seconds=30.0,
            jitter_seconds=0.0,
            monotonic=clock,
        )
        sched._sync_targets(("graph-1",), now)
        self.assertIn("graph-1", sched._next_due)

        # First failure: delay = retry * (multiplier ** 0) = 2.0
        outcome_fail = PollOutcome("source_timeout", False, 0, 0)
        sched._finish_poll("graph-1", outcome_fail, now)
        self.assertEqual(sched._next_due["graph-1"], 102.0)
        h1 = sched.health()
        self.assertEqual(h1["graphs_in_backoff"], 1)
        self.assertEqual(h1["next_poll_at"], 2.0)

        # Second failure: delay = retry * (multiplier ** 1) = 4.0
        now = 102.0
        sched._finish_poll("graph-1", outcome_fail, now)
        self.assertEqual(sched._next_due["graph-1"], 106.0)
        self.assertEqual(sched.health()["next_poll_at"], 4.0)

        # Third failure: delay = retry * (multiplier ** 2) = 8.0
        now = 106.0
        sched._finish_poll("graph-1", outcome_fail, now)
        self.assertEqual(sched._next_due["graph-1"], 114.0)
        self.assertEqual(sched.health()["next_poll_at"], 8.0)

        # Recovery on success: failure count reset, delay = interval (10.0)
        now = 114.0
        outcome_ok = PollOutcome("current", False, 0, 0)
        sched._finish_poll("graph-1", outcome_ok, now)
        self.assertEqual(sched._next_due["graph-1"], 124.0)
        self.assertEqual(sched.health()["graphs_in_backoff"], 0)

    def test_s7_c02_polling_scheduler_thread_lifecycle_and_cancellation(self) -> None:
        """Scheduler enforces single-start lifecycle, joins worker thread, and cancels reconciler on stop."""
        resolver = mock.MagicMock()
        reconciler = mock.MagicMock()
        sched = PollingScheduler(resolver, reconciler, interval_seconds=1.0)

        sched.start()
        try:
            self.assertEqual(sched.health()["status"], "running")
            with self.assertRaises(RuntimeError) as cm_dup:
                sched.start()
            self.assertIn("already started", str(cm_dup.exception))
        finally:
            sched.stop()

        self.assertEqual(sched.health()["status"], "stopped")
        reconciler.cancel.assert_called_once()

        with self.assertRaises(RuntimeError) as cm_restart:
            sched.start()
        self.assertIn("cannot be restarted", str(cm_restart.exception))

    def test_s7_c03_staging_event_transport_duplicate_and_out_of_order_sequence_refusal(self) -> None:
        """Transport rejects invalid sequence frames without advancing state or transmitting ACK."""
        s_raw, c_raw = socket.socketpair()
        try:
            chan = StagingEventChannel(s_raw)

            # Frame with sequence=2 sent when expected is 1
            bad_frame = json.dumps({
                "schema_version": 1,
                "frame_sequence": 2,
                "frame_category": "operation",
                "payload": {},
            }).encode("utf-8")
            c_raw.sendall(struct.pack("!I", len(bad_frame)) + bad_frame)

            with self.assertRaises(StagingEventTransportError) as cm_seq:
                chan.receive(timeout_seconds=1.0)
            self.assertIn("staging event sequence is invalid: expected=1, received=2", str(cm_seq.exception))
            self.assertEqual(chan._receive_sequence, 0)
            # Bound read and verify real negative observation: no ACK transmitted on refusal
            c_raw.settimeout(0.05)
            with self.assertRaises((socket.timeout, TimeoutError)):
                c_raw.recv(1)

            # Valid frame with sequence=1 recovers channel
            valid_frame = json.dumps({
                "schema_version": 1,
                "frame_sequence": 1,
                "frame_category": "operation",
                "payload": {},
            }).encode("utf-8")
            c_raw.sendall(struct.pack("!I", len(valid_frame)) + valid_frame)

            received = chan.receive(timeout_seconds=1.0)
            self.assertEqual(received.sequence, 1)
            self.assertEqual(chan._receive_sequence, 1)
            c_raw.settimeout(1.0)
            ack = c_raw.recv(1)
            self.assertEqual(ack, b"\x06")

            # Duplicate frame with sequence=1 refused (expected is 2)
            c_raw.sendall(struct.pack("!I", len(valid_frame)) + valid_frame)
            with self.assertRaises(StagingEventTransportError) as cm_dup:
                chan.receive(timeout_seconds=1.0)
            self.assertIn("staging event sequence is invalid: expected=2, received=1", str(cm_dup.exception))
            self.assertEqual(chan._receive_sequence, 1)
            # Real negative observation for no ACK on duplicate refusal
            c_raw.settimeout(0.05)
            with self.assertRaises((socket.timeout, TimeoutError)):
                c_raw.recv(1)

            chan.close()
        finally:
            s_raw.close()
            c_raw.close()

    def test_s7_c04_staging_event_transport_acknowledgement_refusal_and_channel_recovery(self) -> None:
        """Invalid acknowledgement byte breaks outgoing channel; fresh channel recovers frame exchange."""
        s_raw, c_raw = socket.socketpair()
        try:
            chan_sender = StagingEventChannel(s_raw)
            with BoundedTestPeer(c_raw) as peer:
                def peer_respond_nak() -> None:
                    _flen, _body = peer.recv_frame(timeout_seconds=1.0)
                    peer.send_nak()

                peer.start_worker(peer_respond_nak)
                with self.assertRaises(StagingEventTransportError) as cm_nak:
                    chan_sender.send("operation", {"status": "starting"})
                self.assertIn("acknowledgement is invalid", str(cm_nak.exception))

                # Channel is now broken
                with self.assertRaises(StagingEventTransportError) as cm_broken:
                    chan_sender.send("operation", {"status": "retrying"})
                self.assertIn("channel is broken", str(cm_broken.exception))
            chan_sender.close()
        finally:
            s_raw.close()
            c_raw.close()

        # Channel recovery over fresh socket pair with monitored sender worker
        s2, c2 = socket.socketpair()
        try:
            s_chan2 = StagingEventChannel(s2)
            c_chan2 = StagingEventChannel(c2)
            with BoundedTestPeer(s2) as sender_peer:
                sender_peer.start_worker(lambda: s_chan2.send("operation", {"status": "recovered"}))
                rec = c_chan2.receive(timeout_seconds=1.0)

            self.assertEqual(rec.sequence, 1)
            self.assertEqual(rec.category, "operation")
            s_chan2.close()
            c_chan2.close()
        finally:
            s2.close()
            c2.close()

    def test_s7_c05_ops_json_readback_mode_validation_and_unsupported_refusal(self) -> None:
        """execute_ops_json_readback enforces mode boundaries and respects host_only constraints."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            home = tmp_root / "home"
            repo = tmp_root / "repo"
            home.mkdir()
            repo.mkdir()
            (home / "repomap.rpl.toml").write_text(
                VALID_REFRESH_CONFIG.format(repo_root=repo, private_root=repo / "priv")
                .replace('host = "127.0.0.1"', 'host = "postgres"'),
                encoding="utf-8",
            )
            config = load_ops_config_home(home)

            with self.assertRaises(StorageSchemaError) as cm_mode:
                execute_ops_json_readback(
                    config,
                    database="repomap",
                    sql="SELECT 1",
                    label="test_mode",
                    expected_shape="object",
                    mode=cast(Any, "invalid_mode"),
                )
            self.assertIn("unsupported operational readback mode: invalid_mode", str(cm_mode.exception))

            # Under host_only, failure raises without attempting container fallback planning or execution
            with mock.patch.dict("os.environ", {PG_CONNECTOR_ENV: "psql"}):
                os.environ.pop(READBACK_DRIVER_ENV, None)
                with mock.patch("repomap_kg.storage.readback_driver.run_psql", side_effect=OSError("host connect refused")) as mock_run_psql:
                    with mock.patch("repomap_kg.ops.readback._resolve_container_readback_plan") as mock_plan:
                        with self.assertRaises(StorageSchemaError):
                            execute_ops_json_readback(
                                config,
                                database="repomap",
                                sql="SELECT 1",
                                label="test_host_only",
                                expected_shape="object",
                                mode="host_only",
                            )
                        mock_plan.assert_not_called()
                        self.assertEqual(mock_run_psql.call_count, 1)

            # Paired positive control: host_then_container with identical failure reaches fallback seam
            with mock.patch.dict("os.environ", {PG_CONNECTOR_ENV: "psql"}):
                os.environ.pop(READBACK_DRIVER_ENV, None)
                container_exec = OpsPsqlExecution(command="podman", args_prefix=("exec", "-i", "c1", "psql"))
                container_plan = _OpsContainerReadbackPlan(execution=container_exec, unavailable_hint="")
                mock_proc = subprocess.CompletedProcess(
                    args=["podman", "exec", "-i", "c1", "psql"],
                    returncode=0,
                    stdout='{"status": "fallback_ok"}',
                    stderr="",
                )
                with mock.patch(
                    "repomap_kg.storage.readback_driver.run_psql",
                    side_effect=[OSError("host connect refused"), mock_proc],
                ) as mock_run_psql_paired:
                    with mock.patch(
                        "repomap_kg.ops.readback._resolve_container_readback_plan",
                        return_value=container_plan,
                    ) as mock_plan_paired:
                        result = execute_ops_json_readback(
                            config,
                            database="repomap",
                            sql="SELECT 1",
                            label="test_host_then_container",
                            expected_shape="object",
                            mode="host_then_container",
                        )
                        self.assertEqual(result, {"status": "fallback_ok"})
                        mock_plan_paired.assert_called_once_with(config, allow_loopback_host=True)
                        self.assertEqual(mock_run_psql_paired.call_count, 2)
                        second_call_argv = mock_run_psql_paired.call_args_list[1].args[0]
                        self.assertEqual(second_call_argv[0], "podman")
                        self.assertEqual(list(second_call_argv[1:5]), ["exec", "-i", "c1", "psql"])

    def test_s7_c06_ops_json_readback_psycopg_host_error_topology_augmentation(self) -> None:
        """psycopg driver transforms chained SQLState into structured authentication and connection errors."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            cfg_file = tmp_root / "repomap.local.toml"
            cfg_file.write_text(
                VALID_REFRESH_CONFIG.format(repo_root=tmp_root, private_root=tmp_root / "priv"),
                encoding="utf-8",
            )
            config = load_ops_config(cfg_file)

            class FakePsycopgAuthError(Exception):
                __module__ = "psycopg.errors"
                sqlstate = "28P01"

            class FakePsycopgConnError(Exception):
                __module__ = "psycopg.errors"
                sqlstate = "08006"

            with mock.patch.dict("os.environ", {PG_CONNECTOR_ENV: "psycopg"}):
                os.environ.pop(READBACK_DRIVER_ENV, None)
                with mock.patch("repomap_kg.storage.readback_driver._import_psycopg") as mock_import:
                    mock_psycopg = mock.MagicMock()
                    mock_import.return_value = mock_psycopg

                    # Authentication failure: sqlstate 28P01
                    mock_psycopg.connect.side_effect = FakePsycopgAuthError("auth failure")
                    with self.assertRaises(StorageSchemaError) as cm_auth:
                        execute_ops_json_readback(
                            config,
                            database="repomap",
                            sql="SELECT 1",
                            label="auth_probe",
                            expected_shape="object",
                            mode="host_then_container",
                        )
                    self.assertIn("psycopg authentication failed for auth_probe", str(cm_auth.exception))

                    # Connection failure: sqlstate 08006
                    mock_psycopg.connect.side_effect = FakePsycopgConnError("connection refused")
                    with self.assertRaises(StorageSchemaError) as cm_conn:
                        execute_ops_json_readback(
                            config,
                            database="repomap",
                            sql="SELECT 1",
                            label="conn_probe",
                            expected_shape="object",
                            mode="host_then_container",
                        )
                    self.assertIn("psycopg connection failed for conn_probe", str(cm_conn.exception))


if __name__ == "__main__":
    import sys
    sys.exit('Direct execution unsupported; use tools/run_tests.py for container sandbox admission.')
