"""Unit tests for portable authority audit event validation rules."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from repomap_kg.coordinator import _portable_authority as pa


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


if __name__ == "__main__":
    unittest.main()
