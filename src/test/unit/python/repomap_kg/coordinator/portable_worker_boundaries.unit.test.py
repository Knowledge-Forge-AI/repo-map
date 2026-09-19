"""Unit tests for portable worker CLI entrypoint boundaries and collaborator doubles."""

from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from repomap_kg.artifacts.references import ArtifactLocator, ArtifactReference
from repomap_kg.coordinator import portable_worker as pw
from repomap_kg.coordinator._portable_capability import PortableExecutionCapability
from repomap_kg.coordinator._portable_semantic_adapter import FailureReceiptWrite
from repomap_kg.coordinator._protocol_core import ProtocolError
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


def _make_manifest_ref() -> ArtifactReference:
    return ArtifactReference(
        "sha256:" + "a" * 64,
        123,
        "application/x-repomap-snapshot-manifest-v1+json",
        "canonical-json-v1",
        PrivacyClassification.RAW_SOURCE,
        ArtifactLocator("filesystem", "objects/aa/value", "filesystem-v1-abc"),
    )


def _make_receipt_ref() -> ArtifactReference:
    return ArtifactReference(
        "sha256:" + "c" * 64,
        123,
        "application/x-repomap-extraction-receipt-v1+json",
        "canonical-json-v1",
        PrivacyClassification.RAW_SOURCE,
        ArtifactLocator("filesystem", "objects/cc/value", "filesystem-v1-abc"),
    )


class PortableWorkerBoundariesUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repomap-worker-test-")).resolve()
        self.store = self.tmp / "store"
        self.workspace = self.tmp / "workspace"
        self.store.mkdir(mode=0o700)
        self.workspace.mkdir(mode=0o700)
        self.manifest_ref = _make_manifest_ref()
        self.receipt_ref = _make_receipt_ref()
        self.receipt_write = FailureReceiptWrite(self.receipt_ref, "stored", None)
        self.cap = PortableExecutionCapability(
            schema_version=1,
            job_id="job-123",
            attempt=1,
            graph_id="test-graph",
            store_root=self.store,
            workspace_root=self.workspace,
            manifest_reference=self.manifest_ref,
            source_generation="sg1:" + "1" * 64,
            config_generation="cg1:" + "2" * 64,
            extractor_generation="eg1:" + "3" * 64,
            canonicalizer_generation="kg1:" + "4" * 64,
            max_artifact_bytes=1024,
            max_bundle_bytes=4096,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cli_argument_parsing_requires_mandatory_flags(self):
        with self.assertRaises(SystemExit):
            pw.main([])

        with self.assertRaises(SystemExit):
            pw.main(["--capability", "/placeholder/cap"])

    def test_job_id_or_attempt_mismatch_returns_exit_code_two(self):
        with patch.object(pw, "load_portable_capability", return_value=self.cap):
            code1 = pw.main(["--capability", "/placeholder/cap", "--job-id", "other-job", "--attempt", "1"])
            self.assertEqual(code1, 2)

            code2 = pw.main(["--capability", "/placeholder/cap", "--job-id", "job-123", "--attempt", "2"])
            self.assertEqual(code2, 2)

    def test_missing_portable_snapshot_extension_returns_exit_code_two(self):
        with patch.object(pw, "load_portable_capability", return_value=self.cap), \
             patch.object(pw, "install_portable_authority_guard"), \
             patch.object(pw, "create_failure_receipt", return_value=self.receipt_write):

            job_start_bad_ext = {
                "schema_version": 1,
                "message_type": "job_start",
                "job_id": "job-123",
                "attempt": 1,
                "job_kind": "refresh_graph",
                "graph_id": "test-graph",
                "source_generation": self.cap.source_generation,
                "config_generation": self.cap.config_generation,
            }
            stdin_data = json.dumps(job_start_bad_ext).encode("utf-8") + b"\n"
            mock_stdin = types.SimpleNamespace(buffer=io.BytesIO(stdin_data))

            with patch.object(pw.sys, "stdin", mock_stdin), patch.object(pw, "_write"):
                code = pw.main(["--capability", "/placeholder/cap", "--job-id", "job-123", "--attempt", "1"])
                self.assertEqual(code, 2)

    def test_contract_validation_failure_on_manifest_decode_error(self):
        orig_from_mapping = ArtifactReference.from_mapping

        called = False

        def mock_from_mapping(mapping):
            nonlocal called
            if mapping == self.manifest_ref.to_mapping() and called:
                raise ValueError("corrupt manifest")
            called = True
            return orig_from_mapping(mapping)

        job_start = {
            "schema_version": 1,
            "message_type": "job_start",
            "job_id": "job-123",
            "attempt": 1,
            "job_kind": "refresh_graph",
            "graph_id": "test-graph",
            "source_generation": self.cap.source_generation,
            "config_generation": self.cap.config_generation,
            "portable_snapshot": {
                "contract_version": "1.0",
                "required": True,
                "snapshot_manifest": self.manifest_ref.to_mapping(),
            },
        }
        stdin_data = json.dumps(job_start).encode("utf-8") + b"\n"
        mock_stdin = types.SimpleNamespace(buffer=io.BytesIO(stdin_data))

        with patch.object(pw, "load_portable_capability", return_value=self.cap), \
             patch.object(pw, "install_portable_authority_guard"), \
             patch.object(pw, "create_failure_receipt", return_value=self.receipt_write), \
             patch.object(pw.sys, "stdin", mock_stdin), \
             patch.object(pw.ArtifactReference, "from_mapping", side_effect=mock_from_mapping), \
             patch.object(pw, "_write") as mock_write:
            code = pw.main(["--capability", "/placeholder/cap", "--job-id", "job-123", "--attempt", "1"])
            self.assertEqual(code, 0)
            terminals = [call.args[0] for call in mock_write.call_args_list if call.args[0].get("message_type") == "error"]
            self.assertEqual(len(terminals), 1)
            self.assertEqual(terminals[0]["error_category"], "contract_validation")

    def test_identity_mismatch_failures_for_manifest_and_identity_fields(self):
        with patch.object(pw, "load_portable_capability", return_value=self.cap), \
             patch.object(pw, "install_portable_authority_guard"), \
             patch.object(pw, "create_failure_receipt", return_value=self.receipt_write):

            # 1. Manifest reference mismatch -> identity_mismatch
            diff_manifest_ref = ArtifactReference(
                "sha256:" + "b" * 64,
                456,
                "application/x-repomap-snapshot-manifest-v1+json",
                "canonical-json-v1",
                PrivacyClassification.RAW_SOURCE,
                ArtifactLocator("filesystem", "objects/bb/value", "filesystem-v1-abc"),
            )
            job_start_diff_manifest = {
                "schema_version": 1,
                "message_type": "job_start",
                "job_id": "job-123",
                "attempt": 1,
                "job_kind": "refresh_graph",
                "graph_id": "test-graph",
                "source_generation": self.cap.source_generation,
                "config_generation": self.cap.config_generation,
                "portable_snapshot": {
                    "contract_version": "1.0",
                    "required": True,
                    "snapshot_manifest": diff_manifest_ref.to_mapping(),
                },
            }
            stdin_data = json.dumps(job_start_diff_manifest).encode("utf-8") + b"\n"
            mock_stdin = types.SimpleNamespace(buffer=io.BytesIO(stdin_data))
            with patch.object(pw.sys, "stdin", mock_stdin), patch.object(pw, "_write") as mock_write:
                code = pw.main(["--capability", "/placeholder/cap", "--job-id", "job-123", "--attempt", "1"])
                self.assertEqual(code, 0)
                terminals = [call.args[0] for call in mock_write.call_args_list if call.args[0].get("message_type") == "error"]
                self.assertEqual(len(terminals), 1)
                self.assertEqual(terminals[0]["error_category"], "identity_mismatch")

            # 2. Identity field mismatch (graph_id) -> identity_mismatch with updated identity
            job_start_diff_graph = {
                "schema_version": 1,
                "message_type": "job_start",
                "job_id": "job-123",
                "attempt": 1,
                "job_kind": "refresh_graph",
                "graph_id": "different-graph",
                "source_generation": self.cap.source_generation,
                "config_generation": self.cap.config_generation,
                "portable_snapshot": {
                    "contract_version": "1.0",
                    "required": True,
                    "snapshot_manifest": self.manifest_ref.to_mapping(),
                },
            }
            stdin_data2 = json.dumps(job_start_diff_graph).encode("utf-8") + b"\n"
            mock_stdin2 = types.SimpleNamespace(buffer=io.BytesIO(stdin_data2))
            with patch.object(pw.sys, "stdin", mock_stdin2), patch.object(pw, "_write") as mock_write2:
                code2 = pw.main(["--capability", "/placeholder/cap", "--job-id", "job-123", "--attempt", "1"])
                self.assertEqual(code2, 0)
                terminals2 = [call.args[0] for call in mock_write2.call_args_list if call.args[0].get("message_type") == "error"]
                self.assertEqual(len(terminals2), 1)
                self.assertEqual(terminals2[0]["error_category"], "identity_mismatch")
                self.assertEqual(terminals2[0]["graph_id"], "different-graph")

    def test_failure_terminal_and_receipt_write_helpers(self):
        term = pw._failure_terminal(
            {"job_id": "j1", "attempt": 1},
            self.cap,
            "2026-09-06T12:00:00Z",
            "custom_failure",
            receipt_ref=self.receipt_write,
        )
        self.assertEqual(term["schema_version"], 1)
        self.assertEqual(term["message_type"], "error")
        self.assertEqual(term["job_id"], "j1")
        self.assertEqual(term["error_category"], "custom_failure")
        self.assertFalse(term["retryable"])

        # Test _receipt_write with ArtifactReference
        converted = pw._receipt_write(self.receipt_ref)
        self.assertIsInstance(converted, FailureReceiptWrite)
        self.assertEqual(converted.status, "stored")
        self.assertEqual(converted.reference, self.receipt_ref)

        # Test _receipt_write with existing FailureReceiptWrite
        self.assertIs(pw._receipt_write(self.receipt_write), self.receipt_write)

    def test_execution_error_category_classification(self):
        self.assertEqual(pw._execution_error_category(PermissionError("denied")), "unsupported_capability")
        self.assertEqual(pw._execution_error_category(ProtocolError("bad protocol")), "malformed_protocol")
        self.assertEqual(pw._execution_error_category(KeyError("missing")), "contract_validation")
        self.assertEqual(pw._execution_error_category(TypeError("type")), "contract_validation")
        self.assertEqual(pw._execution_error_category(ValueError("val")), "contract_validation")
        self.assertEqual(pw._execution_error_category(FileNotFoundError("no file")), "source_capture")
        self.assertEqual(pw._execution_error_category(RuntimeError("semantic")), "semantic_workload")

    def test_classify_worker_cause_and_emit_stderr(self):
        from repomap_kg.coordinator._portable_semantic_adapter import PortableExecutionError
        from repomap_kg.extractors.languages.go_helper import GoHelperUnavailableError
        from repomap_kg.extractors.languages.go_protocol import GoProtocolError
        from repomap_kg.graph.multi_source_capture import MultiSourceCaptureError

        err1 = PortableExecutionError("source_capture")
        err1.__cause__ = MultiSourceCaptureError("helper missing")
        err1.__cause__.__cause__ = GoHelperUnavailableError("Go parser helper is unavailable")
        self.assertEqual(pw._classify_worker_cause(err1), "helper_unavailable")

        err2 = PortableExecutionError("source_capture")
        err2.__cause__ = GoProtocolError("helper protocol error")
        self.assertEqual(pw._classify_worker_cause(err2), "helper_protocol_violation")

        err3 = PortableExecutionError("source_capture")
        err3.__cause__ = PermissionError("portable worker runtime authority denied")
        self.assertEqual(pw._classify_worker_cause(err3), "helper_launch_denied")

        err_fs = PortableExecutionError("source_capture")
        err_fs.__cause__ = PermissionError("portable worker filesystem authority denied")
        self.assertEqual(pw._classify_worker_cause(err_fs), "filesystem_capture_denied")

        err_mut = PortableExecutionError("source_capture")
        err_mut.__cause__ = OSError("file changed during capture")
        self.assertEqual(pw._classify_worker_cause(err_mut), "source_mutation_failure")

        err4 = PortableExecutionError("source_unavailable")
        err4.__cause__ = MultiSourceCaptureError("source missing", category="source_unavailable")
        self.assertEqual(pw._classify_worker_cause(err4), "source_capture_source_unavailable")

        stderr_buf = io.StringIO()
        with patch.object(pw.sys, "stderr", stderr_buf):
            pw._emit_failure_stderr(err3)
        self.assertEqual(stderr_buf.getvalue(), "refresh-failure:portable-worker:helper_launch_denied\n")


if __name__ == "__main__":
    unittest.main()
