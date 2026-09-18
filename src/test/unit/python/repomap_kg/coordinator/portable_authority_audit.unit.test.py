"""Unit tests for portable authority audit event validation rules."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from typing import Any, cast
from unittest.mock import patch

from repomap_kg.coordinator import _portable_authority as pa
from repomap_kg.coordinator.protocol import ProtocolSession
from repomap_kg.coordinator.refresh_adapter import refresh_terminal


class PortableAuthorityAuditUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repomap-audit-test-")).resolve()
        self.read_root = self.tmp / "read"
        self.read_root.mkdir()
        self.write_root = self.tmp / "write"
        self.write_root.mkdir()
        self.exact_root = self.tmp / "exact"
        self.exact_root.mkdir()
        self.read_roots = (self.read_root,)
        self.write_roots = (self.write_root,)
        self.exact_mkdir_roots = (self.exact_root,)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_import_denied_prefixes_raise_permission_error(self):
        for denied in (
            "psycopg", "psycopg2", "sqlite3",
            "repomap_kg.coordinator._control_test",
            "repomap_kg.storage.staged_ingestion",
            "repomap_kg.storage.staging_copy",
            "repomap_kg.coordinator.local_lifecycle",
            "repomap_kg.registry",
        ):
            with self.subTest(denied=denied):
                with self.assertRaisesRegex(PermissionError, "import authority denied"):
                    pa._validate_audit_event(
                        "import", (denied,), self.read_roots, self.write_roots
                    )

        # Allowed import
        pa._validate_audit_event("import", ("json",), self.read_roots, self.write_roots)

    def test_runtime_denied_events_raise_permission_error(self):
        for event in (
            "socket.connect", "subprocess.Popen", "os.exec", "os.posix_spawn",
            "os.spawn", "os.system", "os.fork", "os.forkpty",
        ):
            with self.subTest(event=event):
                with self.assertRaisesRegex(PermissionError, "runtime authority denied"):
                    pa._validate_audit_event(
                        event, (), self.read_roots, self.write_roots
                    )

    def test_open_event_read_write_modes_and_paths(self):
        read_file = self.read_root / "data.txt"
        write_file = self.write_root / "out.txt"
        outside_file = self.tmp / "forbidden.txt"

        # Empty args
        with self.assertRaisesRegex(PermissionError, "filesystem authority denied"):
            pa._validate_audit_event("open", (), self.read_roots, self.write_roots)

        # Read allowed
        pa._validate_audit_event("open", (str(read_file), "r"), self.read_roots, self.write_roots)
        # Read denied outside
        with self.assertRaises(PermissionError):
            pa._validate_audit_event("open", (str(outside_file), "r"), self.read_roots, self.write_roots)

        # Write allowed inside write_roots
        for mode in ("w", "a", "r+", "x"):
            pa._validate_audit_event("open", (str(write_file), mode), self.read_roots, self.write_roots)
        # Write flags allowed
        pa._validate_audit_event("open", (str(write_file), None, os.O_WRONLY), self.read_roots, self.write_roots)

        # Write denied outside write_roots (even if inside read_roots)
        with self.assertRaises(PermissionError):
            pa._validate_audit_event("open", (str(read_file), "w"), self.read_roots, self.write_roots)

    def test_enumeration_events_directory_validation(self):
        for ev in ("os.listdir", "os.scandir"):
            # Invalid args length
            with self.assertRaises(PermissionError):
                pa._validate_audit_event(ev, (), self.read_roots, self.write_roots)
            with self.assertRaises(PermissionError):
                pa._validate_audit_event(ev, ("a", "b"), self.read_roots, self.write_roots)

            # Inside read_roots: allowed
            pa._validate_audit_event(ev, (str(self.read_root),), self.read_roots, self.write_roots)

            # Outside read_roots: denied
            with self.assertRaises(PermissionError):
                pa._validate_audit_event(ev, (str(self.tmp),), self.read_roots, self.write_roots)

    def test_single_and_two_path_mutations(self):
        # Single path: mkdir, remove, rmdir, chmod
        # Invalid dir_fd
        with self.assertRaises(PermissionError):
            pa._validate_audit_event("os.mkdir", (str(self.write_root / "d"), 0o777, 99), self.read_roots, self.write_roots)

        # Missing arg
        with self.assertRaises(PermissionError):
            pa._validate_audit_event("os.mkdir", (), self.read_roots, self.write_roots)

        # Exact mkdir roots allowed
        pa._validate_audit_event("os.mkdir", (str(self.exact_root),), self.read_roots, self.write_roots, self.exact_mkdir_roots)

        # Normal mkdir inside write_roots allowed
        pa._validate_audit_event("os.mkdir", (str(self.write_root / "newdir"),), self.read_roots, self.write_roots)

        # Mkdir outside write_roots denied
        with self.assertRaises(PermissionError):
            pa._validate_audit_event("os.mkdir", (str(self.read_root / "baddir"),), self.read_roots, self.write_roots)

        # Two path mutations: rename, link
        src_ok = self.write_root / "src.txt"
        dst_ok = self.write_root / "dst.txt"
        dst_bad = self.read_root / "dst.txt"

        pa._validate_audit_event("os.rename", (str(src_ok), str(dst_ok)), self.read_roots, self.write_roots)
        with self.assertRaises(PermissionError):
            pa._validate_audit_event("os.rename", (str(src_ok), str(dst_bad)), self.read_roots, self.write_roots)

        # Symlink
        with self.assertRaises(PermissionError):
            pa._validate_audit_event("os.symlink", ("one_arg",), self.read_roots, self.write_roots)
        pa._validate_audit_event("os.symlink", (str(src_ok), str(dst_ok)), self.read_roots, self.write_roots)

    def test_subprocess_popen_allows_approved_go_helper_and_denies_others(self):
        code_root = self.tmp / "code"
        code_root.mkdir()
        helper = code_root / "repomap-go-extract"
        helper.touch(mode=0o755)
        outside_helper = self.tmp / "repomap-go-extract"
        outside_helper.touch(mode=0o755)

        pa._validate_audit_event(
            "subprocess.Popen", (str(helper),), self.read_roots, self.write_roots,
            code_roots=(code_root,),
        )
        pa._validate_audit_event(
            "subprocess.Popen", (None, [str(helper), "--root", "foo"]), self.read_roots, self.write_roots,
            code_roots=(code_root,),
        )

        with self.assertRaisesRegex(PermissionError, "runtime authority denied"):
            pa._validate_audit_event(
                "subprocess.Popen", (str(outside_helper),), self.read_roots, self.write_roots,
                code_roots=(code_root,),
            )

        bad_exe = code_root / "bash"
        bad_exe.touch(mode=0o755)
        with self.assertRaisesRegex(PermissionError, "runtime authority denied"):
            pa._validate_audit_event(
                "subprocess.Popen", (str(bad_exe),), self.read_roots, self.write_roots,
                code_roots=(code_root,),
            )

    def test_posix_spawn_allows_approved_go_helper_and_denies_others(self):
        code_root = self.tmp / "code"
        code_root.mkdir()
        helper = code_root / "repomap-go-extract"
        helper.touch(mode=0o755)
        outside_helper = self.tmp / "repomap-go-extract"
        outside_helper.touch(mode=0o755)

        pa._validate_audit_event(
            "os.posix_spawn", (str(helper), [str(helper)], {}), self.read_roots, self.write_roots,
            code_roots=(code_root,),
        )
        pa._validate_audit_event(
            "os.posix_spawnp", (str(helper), [str(helper)], {}), self.read_roots, self.write_roots,
            code_roots=(code_root,),
        )

        with self.assertRaisesRegex(PermissionError, "runtime authority denied"):
            pa._validate_audit_event(
                "os.posix_spawn", (str(outside_helper), [str(outside_helper)], {}), self.read_roots, self.write_roots,
                code_roots=(code_root,),
            )

        bad_exe = code_root / "bash"
        bad_exe.touch(mode=0o755)
        with self.assertRaisesRegex(PermissionError, "runtime authority denied"):
            pa._validate_audit_event(
                "os.posix_spawn", (str(bad_exe), [str(bad_exe)], {}), self.read_roots, self.write_roots,
                code_roots=(code_root,),
            )

        with self.assertRaisesRegex(PermissionError, "runtime authority denied"):
            pa._validate_audit_event(
                "os.exec", (str(helper), [str(helper)], {}), self.read_roots, self.write_roots,
                code_roots=(code_root,),
            )

    def test_posix_spawn_allows_go_helper_from_repomap_go_helper_env(self):
        outside_helper = self.tmp / "repomap-go-extract"
        outside_helper.touch(mode=0o755)

        with patch.dict(os.environ, {"REPOMAP_GO_HELPER": str(outside_helper)}):
            pa._validate_audit_event(
                "os.posix_spawn",
                (str(outside_helper), [str(outside_helper)], {}),
                self.read_roots,
                self.write_roots,
                code_roots=(),
            )

    def test_refresh_terminal_with_refresh_failed_diagnostic_round_trips_protocol(self):
        cap = SimpleNamespace(
            validate=lambda: None,
            job_id="job-refresh-1",
            attempt=2,
            graph_id="synthetic-graph",
            source_generation="sg1:test",
            config_generation="cg1:test",
            extractor_generation="eg1:test",
            canonicalizer_generation="kg1:test",
        )
        result = SimpleNamespace(
            result="failure",
            publication_state="not_started",
            diagnostics=[{"code": "refresh-failed"}],
            started_at="2026-09-17T22:00:00Z",
            finished_at="2026-09-17T22:00:01Z",
            warnings=(),
            error="portable worker did not complete",
            error_category="worker_crash",
        )
        term = refresh_terminal(cast(Any, cap), result)
        session = ProtocolSession({"job_id": "job-refresh-1", "attempt": 2})
        session.accept_worker(
            {
                "schema_version": 1,
                "message_type": "worker_hello",
                "protocol_versions": [1],
                "worker_generation": "worker-v1",
                "capabilities": ["refresh_graph"],
                "process_nonce": "nonce-test",
            }
        )
        session.accept_coordinator(
            {
                "schema_version": 1,
                "message_type": "job_start",
                "job_id": "job-refresh-1",
                "attempt": 2,
                "job_kind": "refresh_graph",
                "graph_id": "synthetic-graph",
                "source_generation": "sg1:test",
                "config_generation": "cg1:test",
            }
        )
        accepted = session.accept_worker(term)
        self.assertEqual(accepted["status"], "failed")
        self.assertEqual(accepted["publication_state"], "not_started")
        self.assertIn("refresh-failed", cast(list, accepted["diagnostics"]))


if __name__ == "__main__":
    unittest.main()
