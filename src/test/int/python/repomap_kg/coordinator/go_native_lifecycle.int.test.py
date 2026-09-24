"""Admitted native helper path refusal and owned cancellation authorings."""
from __future__ import annotations

import subprocess
from types import GeneratorType
from typing import Any
import unittest
from unittest import mock

from repomap_kg.extractors.languages import go_protocol
from repomap_kg.extractors.languages.go_helper import resolve_go_helper_command
from pathlib import Path
import tempfile

from repomap_kg.coordinator.contracts import (
    DEFAULT_LIMITS,
    JobRequest,
    _bounded_string,
    _valid_public_status_value,
    _valid_utc_timestamp,
    normalize_request,
    project_public_error,
)
from repomap_kg.coordinator._protocol_validation import (
    ProtocolError,
    decode_jsonl,
    retain_stderr,
    _validate_portable_snapshot_result_extension,
    _limit,
    _int_limit,
)
from repomap_kg.coordinator._protocol_session import ProtocolSession
from repomap_kg.coordinator.endpoint import (
    EndpointDescriptorError,
    LoopbackEndpointDescriptor,
    load_endpoint_descriptor,
    write_endpoint_descriptor,
)
from repomap_kg.coordinator.job_control import (
    CoordinatorModeError,
    cancel_coordinator_job,
    list_coordinator_jobs,
    format_coordinator_jobs_table,
    format_coordinator_job_table,
    format_coordinator_health_table,
    _validated_job,
    _validated_list_item,
    _required_text,
)
FIXTURE_ROOT = Path(__file__).resolve().parents[6] / "src" / "test" / "fixtures"


class GoNativeLifecycleIntegrationTests(unittest.TestCase):
    def test_native_helper_refuses_escaping_path_and_next_request_recovers(self) -> None:
        command = resolve_go_helper_command()
        root = FIXTURE_ROOT / "go" / "syntax_basic"
        with self.assertRaises(go_protocol.GoProtocolError) as caught:
            list(go_protocol.iter_go_protocol_observations(root, ["../outside.go"], command))
        message = str(caught.exception)
        self.assertIn("helper exited before file_end", message)
        self.assertNotIn(str(root), message)
        self.assertNotIn("outside.go", message)
        recovered = list(go_protocol.iter_go_protocol_observations(root, ["declarations.go"], command))
        self.assertTrue(recovered)
        self.assertEqual({item.path for item in recovered}, {"declarations.go"})
        self.assertTrue(any(item.kind == "go.package" for item in recovered))

    def test_close_after_native_observation_joins_owned_process_and_closes_pipes(self) -> None:
        command = resolve_go_helper_command()
        root = FIXTURE_ROOT / "go" / "syntax_basic"
        terminated: list[subprocess.Popen[bytes]] = []
        terminate = go_protocol._terminate_process

        def observe_termination(process: subprocess.Popen[bytes], timeout: float) -> None:
            terminated.append(process)
            terminate(process, timeout)

        with mock.patch.object(go_protocol, "_terminate_process", side_effect=observe_termination):
            observations = go_protocol.iter_go_protocol_observations(root, ["declarations.go"], command)
            assert isinstance(observations, GeneratorType)
            try:
                first = next(observations)
                self.assertEqual(first.path, "declarations.go")
                self.assertEqual(first.extractor, "repo-go-ast")
            finally:
                observations.close()
        self.assertEqual(len(terminated), 1)
        process = terminated[0]
        self.assertIsNotNone(process.poll())
        for pipe in (process.stdin, process.stdout, process.stderr):
            assert pipe is not None
            self.assertTrue(pipe.closed)

    def test_coordinator_contracts_and_request_normalization_branches(self) -> None:
        bad_raw: Any = "not_a_mapping"
        with self.assertRaises(ValueError):
            normalize_request(bad_raw, source_generation="sg1:a", config_generation="cg1:b")
        bad_schema: Any = {"schema_version": True}
        with self.assertRaises(ValueError):
            normalize_request(bad_schema, source_generation="sg1:a", config_generation="cg1:b")
        base = {
            "schema_version": 1,
            "job_kind": "refresh_graph",
            "graph_id": "synthetic-test1",
            "request_id": "req1",
            "idempotency_key": "idem1",
            "priority": "manual",
            "operation_options": {"reason": "manual"},
        }
        valid_req = normalize_request(base, source_generation="sg1:valid1", config_generation="cg1:valid2")
        self.assertIsInstance(valid_req, JobRequest)
        with self.assertRaises(ValueError):
            normalize_request(dict(base, job_kind="unknown"), source_generation="sg1:v", config_generation="cg1:v")
        with self.assertRaises(ValueError):
            normalize_request(dict(base, priority="invalid"), source_generation="sg1:v", config_generation="cg1:v")
        with self.assertRaises(ValueError):
            normalize_request(dict(base, operation_options={"invalid": "opt"}), source_generation="sg1:v", config_generation="cg1:v")

        err_with_cat = {"error_category": "transient", "retryable": True}
        proj = project_public_error(err_with_cat)
        self.assertEqual(proj["summary"], "transient failure")
        with self.assertRaises(ValueError):
            project_public_error({"error_category": "bogus_cat"})
        bad_retryable: Any = {"retryable": "yes"}
        with self.assertRaises(ValueError):
            project_public_error(bad_retryable)
        with self.assertRaises(ValueError):
            project_public_error({"summary": "summary_only"})

        with self.assertRaises(ValueError):
            _bounded_string("has\x01ctrl", "test", DEFAULT_LIMITS)
        with self.assertRaises(ValueError):
            _bounded_string("a" * 500, "test", DEFAULT_LIMITS)
        with self.assertRaises(ValueError):
            normalize_request({"schema_version": 2, "graph_id": "g1"}, source_generation="sg1:0", config_generation="cg1:0")
        with self.assertRaises(ValueError):
            normalize_request({"schema_version": 1, "graph_id": "invalid!graph#id"}, source_generation="sg1:0", config_generation="cg1:0")

        self.assertTrue(_valid_utc_timestamp("2026-09-21T03:00:00Z", DEFAULT_LIMITS))
        self.assertFalse(_valid_utc_timestamp("invalid_ts", DEFAULT_LIMITS))
        self.assertTrue(_valid_public_status_value("job_kind", "refresh_graph", DEFAULT_LIMITS))
        self.assertFalse(_valid_public_status_value("job_kind", "other", DEFAULT_LIMITS))
        self.assertTrue(_valid_public_status_value("priority", "manual", DEFAULT_LIMITS))
        self.assertFalse(_valid_public_status_value("priority", "other", DEFAULT_LIMITS))
        self.assertTrue(_valid_public_status_value("state", "running", DEFAULT_LIMITS))
        self.assertFalse(_valid_public_status_value("state", "bad_state", DEFAULT_LIMITS))
        self.assertFalse(_valid_public_status_value("job_id", 123, DEFAULT_LIMITS))
        self.assertTrue(_valid_public_status_value("job_id", "valid-id-1", DEFAULT_LIMITS))
        self.assertFalse(_valid_public_status_value("submitted_at", "not-a-timestamp", DEFAULT_LIMITS))
        self.assertTrue(_valid_public_status_value("submitted_at", "2026-09-21T12:00:00.000000Z", DEFAULT_LIMITS))
        self.assertFalse(_valid_public_status_value("phase", "invalid_phase", DEFAULT_LIMITS))
        self.assertTrue(_valid_public_status_value("phase", "discovery", DEFAULT_LIMITS))
        self.assertFalse(_valid_public_status_value("source_generation_match", "not-a-bool", DEFAULT_LIMITS))
        self.assertTrue(_valid_public_status_value("source_generation_match", True, DEFAULT_LIMITS))
        self.assertFalse(_valid_public_status_value("unknown_key", "val", DEFAULT_LIMITS))

    def test_coordinator_protocol_validation_and_framing_branches(self) -> None:
        text, total, truncated = retain_stderr([b"short stderr\n"], max_bytes=100)
        self.assertEqual(text, "short stderr\n")
        self.assertFalse(truncated)
        text, total, truncated = retain_stderr([b"hello world foo bar"], max_bytes=5)
        self.assertEqual(text, "hello")
        self.assertTrue(truncated)
        text, _, _ = retain_stderr([b"error: password: xyz secret leaked"], max_bytes=100)
        self.assertIn("worker diagnostic redacted", text)
        with self.assertRaises(ValueError):
            retain_stderr([b"abc"], max_bytes=-1)
        with self.assertRaises(ValueError):
            retain_stderr([b"abc"], max_bytes=70000)
        bad_chunks: Any = ["not_bytes"]
        with self.assertRaises(TypeError):
            retain_stderr(bad_chunks, max_bytes=100)

        self.assertEqual(_limit({"timeout": 10.5}, "timeout", 1.0), 10.5)
        with self.assertRaises(ValueError):
            _limit({"timeout": True}, "timeout", 1.0)
        with self.assertRaises(ValueError):
            _limit({"timeout": "not-number"}, "timeout", 1.0)
        self.assertEqual(_int_limit({"count": 5}, "count", 1), 5)
        with self.assertRaises(ValueError):
            _int_limit({"count": True}, "count", 1)
        with self.assertRaises(ValueError):
            _int_limit({"count": 2.5}, "count", 1)

        with self.assertRaises(ProtocolError):
            decode_jsonl(b'{"dup": 1, "dup": 2}\n')
        with self.assertRaises(ProtocolError):
            decode_jsonl(b'"not_a_dict"\n')
        with self.assertRaises(ProtocolError):
            _validate_portable_snapshot_result_extension({"contract_version": "2.0"}, "result", {"status": "succeeded"})
        with self.assertRaises(ProtocolError):
            _validate_portable_snapshot_result_extension({"contract_version": "1.0", "outcome": 123}, "result", {})
        with self.assertRaises(ProtocolError):
            _validate_portable_snapshot_result_extension({"contract_version": "1.0", "outcome": "completed", "receipt": {"ref": 1}, "bundle": {"ref": 2}}, "result", {"status": "failed"})
        with self.assertRaises(ProtocolError):
            _validate_portable_snapshot_result_extension({"contract_version": "1.0", "outcome": "cancelled", "receipt": {"ref": 1}}, "result", {"status": "succeeded"})

    def test_coordinator_protocol_session_lifecycle(self) -> None:
        with self.assertRaises(ProtocolError):
            ProtocolSession({"invalid_key": "val"})
        with self.assertRaises(ProtocolError):
            ProtocolSession({"job_id": "job;bad", "attempt": 1})
        with self.assertRaises(ProtocolError):
            ProtocolSession({"job_id": "job1", "attempt": -1})
        with self.assertRaises(ProtocolError):
            ProtocolSession({"job_id": "job1", "attempt": True})

        session = ProtocolSession({"job_id": "job1", "attempt": 1})
        with self.assertRaises(ProtocolError):
            session.accept_worker({"schema_version": 1, "message_type": "job_start"})
        with self.assertRaises(ProtocolError):
            session.accept_coordinator({"schema_version": 1, "message_type": "worker_hello"})
        with self.assertRaises(ProtocolError):
            session.accept_worker({"schema_version": 2, "message_type": "worker_hello"})
        with self.assertRaises(ProtocolError):
            session.accept_worker({"schema_version": 1, "message_type": "worker_exit"})
        with self.assertRaises(ProtocolError):
            session.accept_worker({"schema_version": 1, "message_type": "unknown_type"})

        with self.assertRaises(ProtocolError):
            session.accept_worker({"schema_version": 1, "message_type": "worker_hello", "protocol_versions": ["1"], "capabilities": ["refresh_graph"], "worker_generation": "wg1", "process_nonce": "pn1"})
        with self.assertRaises(ProtocolError):
            session.accept_worker({"schema_version": 1, "message_type": "worker_hello", "protocol_versions": [99], "capabilities": ["refresh_graph"], "worker_generation": "wg1", "process_nonce": "pn1"})
        with self.assertRaises(ProtocolError):
            session.accept_worker({"schema_version": 1, "message_type": "worker_hello", "protocol_versions": [1], "capabilities": ["unsupported"], "worker_generation": "wg1", "process_nonce": "pn1"})

        session.accept_worker({"schema_version": 1, "message_type": "worker_hello", "protocol_versions": [1], "capabilities": ["refresh_graph"], "worker_generation": "wg1", "process_nonce": "pn1"})

        with self.assertRaises(ProtocolError):
            session.accept_coordinator({"schema_version": 1, "message_type": "job_start", "job_kind": "invalid", "graph_id": "g1", "source_generation": "sg1:0", "config_generation": "cg1:0"})
        with self.assertRaises(ProtocolError):
            session.accept_coordinator({"schema_version": 1, "message_type": "job_start", "job_kind": "refresh_graph", "graph_id": "bad!graph", "source_generation": "sg1:0", "config_generation": "cg1:0"})
        with self.assertRaises(ProtocolError):
            session.accept_coordinator({"schema_version": 1, "message_type": "job_start", "job_kind": "refresh_graph", "graph_id": "g1", "source_generation": "invalid", "config_generation": "cg1:0"})

    def test_coordinator_endpoint_and_job_control_branches(self) -> None:
        with self.assertRaises(EndpointDescriptorError):
            LoopbackEndpointDescriptor.from_mapping({"schema_version": 1})
        bad_desc: Any = {
            "schema_version": True,
            "host": "127.0.0.1",
            "port": 8000,
            "instance_id": "inst1",
            "fencing_epoch": 1,
            "auth_token": "tok1",
        }
        with self.assertRaises(EndpointDescriptorError):
            LoopbackEndpointDescriptor.from_mapping(bad_desc)
        desc = LoopbackEndpointDescriptor.fresh(port=8080, instance_id="inst-1", fencing_epoch=1)
        self.assertEqual(LoopbackEndpointDescriptor.from_mapping(desc.to_mapping()), desc)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "desc.json"
            write_endpoint_descriptor(target, desc)
            loaded = load_endpoint_descriptor(target)
            self.assertEqual(loaded, desc)

            mock_client = mock.MagicMock()
            mock_client.cancel.return_value = {"job_id": "job-1", "state": "running"}
            with self.assertRaises(CoordinatorModeError):
                cancel_coordinator_job(Path(tmpdir), "job-1", client_factory=lambda h, e: mock_client)
            mock_client.list_jobs.return_value = {"unexpected": True}
            with self.assertRaises(CoordinatorModeError):
                list_coordinator_jobs(Path(tmpdir), client_factory=lambda h, e: mock_client)

        with self.assertRaises(CoordinatorModeError):
            format_coordinator_jobs_table({"jobs": "not-a-list"})
        table = format_coordinator_jobs_table({
            "jobs": [{"job_id": "j1", "graph_id": "g1", "state": "queued", "submitted_at": "2026-09-21T12:00:00.000000Z"}],
            "next_cursor": "cursor123",
        })
        self.assertIn("next_cursor | cursor123", table)

        with self.assertRaises(CoordinatorModeError):
            format_coordinator_job_table({"job": "not-a-map"})

        with self.assertRaises(CoordinatorModeError):
            format_coordinator_health_table({
                "health_schema_version": 1,
                "status": "ready",
                "coordinator": "not-a-mapping",
                "postgres": {"status": "ready"},
                "storage": {"status": "ready"},
                "workers": {"status": "ready"},
            })

        with self.assertRaises(CoordinatorModeError):
            _validated_job("not-a-map", "j1")
        with self.assertRaises(CoordinatorModeError):
            _validated_job({"job_id": "other", "state": "queued"}, "j1")
        with self.assertRaises(CoordinatorModeError):
            _validated_list_item({"job_id": "j1", "graph_id": "g1", "state": "queued", "submitted_at": "2026-09-21T12:00:00.000000Z"}, "filter_mismatch")

        with self.assertRaises(CoordinatorModeError):
            _required_text({"field": 123}, "field")
        with self.assertRaises(CoordinatorModeError):
            _required_text({"field": ""}, "field")

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "desc.json"
            desc_large = LoopbackEndpointDescriptor(schema_version=1, host="127.0.0.1", port=8080, instance_id="inst-1", fencing_epoch=1, auth_token="x" * 10000)
            with self.assertRaises(EndpointDescriptorError):
                write_endpoint_descriptor(target, desc_large)
