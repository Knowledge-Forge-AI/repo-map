"""Unit tests for portable worker bootstrap causality and supervision reaping."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.coordinator import _portable_authority as pa
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_test_support.run25_portable_workflows import (
    WorkerLaunchSpec,
    build_clean_explicit_pythonpath,
    build_run25_worker_limits,
    create_run25_test_capability,
    make_test_manifest_reference,
    run_worker_spec,
)
from runner_coverage_execution import prepare_child_coverage_environment



class PortableBootstrapCausalityUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[6]
        self.tmp = Path(tempfile.mkdtemp(prefix="repomap-causality-test-")).resolve()
        self.tmp.chmod(0o700)
        self.read_root = self.tmp / "read"
        self.read_root.mkdir()
        self.read_root.chmod(0o700)
        self.write_root = self.tmp / "write"
        self.write_root.mkdir()
        self.write_root.chmod(0o700)
        self.read_roots = (self.read_root,)
        self.write_roots = (self.write_root,)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_explicit_pythonpath_pinning_has_no_ambient_or_empty_components(self) -> None:
        pythonpath = build_clean_explicit_pythonpath(self.repo_root)
        parts = pythonpath.split(os.pathsep)
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(bool(p.strip()) for p in parts))
        for p in parts:
            resolved = Path(p)
            self.assertTrue(resolved.is_absolute())
            self.assertTrue(resolved.is_dir())
        self.assertEqual(Path(parts[0]), self.repo_root / "tools")
        self.assertEqual(Path(parts[1]), self.repo_root / "src" / "main" / "python")
        self.assertEqual(Path(parts[2]), self.repo_root / "src" / "test" / "support" / "python")

    def test_prepare_child_coverage_environment_honors_maintained_families(self) -> None:
        pp = build_clean_explicit_pythonpath(self.repo_root)
        env_unmeasured = prepare_child_coverage_environment(
            family="unmeasured", extra_env={"PYTHONPATH": pp}
        )
        self.assertIn("PYTHONPATH", env_unmeasured)
        self.assertNotIn("COVERAGE_PROCESS_START", env_unmeasured)

        with self.assertRaises(ValueError):
            prepare_child_coverage_environment(family="invalid_family_name")

        with self.assertRaises(ValueError):
            prepare_child_coverage_environment(
                family="unmeasured", extra_env={"COVERAGE_PROCESS_START": "invalid"}
            )

    def test_direct_audit_event_validation_denies_psycopg_sqlite3_and_control(self) -> None:
        for denied in (
            "psycopg",
            "psycopg2",
            "sqlite3",
            "repomap_kg.coordinator._control_test",
            "repomap_kg.registry",
        ):
            with self.subTest(denied=denied):
                with self.assertRaisesRegex(PermissionError, "import authority denied"):
                    pa._validate_audit_event(
                        "import", (denied,), self.read_roots, self.write_roots
                    )
        pa._validate_audit_event("import", ("json",), self.read_roots, self.write_roots)

    def test_child_process_bootstrap_causality_denies_psycopg_under_guard(self) -> None:
        clean_pp = build_clean_explicit_pythonpath(self.repo_root)
        env = prepare_child_coverage_environment(
            family="unmeasured", extra_env={"PYTHONPATH": clean_pp}
        )
        script = (
            "from pathlib import Path\n"
            "from repomap_kg.coordinator._portable_authority import install_portable_authority_guard\n"
            f"install_portable_authority_guard(store_root=Path({str(self.write_root)!r}), "
            f"workspace_root=Path({str(self.write_root)!r}), code_roots=[Path({str(self.repo_root)!r})])\n"
            "import psycopg\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=self.tmp,
            timeout=10.0,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("PermissionError", proc.stderr)
        self.assertIn("portable worker import authority denied", proc.stderr)

    def test_child_process_bootstrap_causality_denies_sqlite3_under_guard(self) -> None:
        clean_pp = build_clean_explicit_pythonpath(self.repo_root)
        env = prepare_child_coverage_environment(
            family="unmeasured", extra_env={"PYTHONPATH": clean_pp}
        )
        script = (
            "from pathlib import Path\n"
            "from repomap_kg.coordinator._portable_authority import install_portable_authority_guard\n"
            f"install_portable_authority_guard(store_root=Path({str(self.write_root)!r}), "
            f"workspace_root=Path({str(self.write_root)!r}), code_roots=[Path({str(self.repo_root)!r})])\n"
            "import sqlite3\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=self.tmp,
            timeout=10.0,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("PermissionError", proc.stderr)
        self.assertIn("portable worker import authority denied", proc.stderr)

    def test_supervision_reaping_and_authorization_terminal_on_denied_imports(self) -> None:
        clean_pp = build_clean_explicit_pythonpath(self.repo_root)
        env = prepare_child_coverage_environment(
            family="unmeasured", extra_env={"PYTHONPATH": clean_pp}
        )
        limits = build_run25_worker_limits()
        for target in ("psycopg", "sqlite3"):
            with self.subTest(target=target):
                script = f"""
import sys, json
from pathlib import Path
from repomap_kg.coordinator._portable_authority import install_portable_authority_guard
install_portable_authority_guard(store_root=Path(sys.argv[1]), workspace_root=Path(sys.argv[2]), code_roots=[Path(sys.argv[3])])
print(json.dumps(dict(schema_version=1, message_type="worker_hello", protocol_versions=[1], capabilities=["refresh_graph"], worker_generation="wg1:fixture", process_nonce="nonce")), flush=True)
start = json.loads(sys.stdin.readline())
try:
    __import__({target!r})
except PermissionError:
    terminal = dict(start, message_type="error", status="failed", error_category="authorization",
        publication_state="not_started", retryable=False, latest_run_identity=None, phase="complete",
        started_at="2026-09-20T12:00:00.000000Z", finished_at="2026-09-20T12:01:00.000000Z",
        extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
        files=0, observations=0, canonical_nodes=0, canonical_edges=0, warnings=[], diagnostics=[])
    print(json.dumps(terminal), flush=True)
"""
                spec = WorkerLaunchSpec(
                    argv=(
                        sys.executable,
                        "-c",
                        script,
                        str(self.write_root),
                        str(self.write_root),
                        str(self.repo_root),
                    ),
                    environment=env,
                    cwd=self.repo_root,
                )
                identity = {"job_id": f"job-causality-{target}", "attempt": 1}
                result = run_worker_spec(spec, identity, limits)
                self.assertIsNone(result.protocol_error)
                self.assertTrue(result.waited)
                self.assertTrue(result.process_group_cleaned)
                self.assertFalse(result.synthesized_terminal)
                self.assertEqual(result.terminal["message_type"], "error")
                self.assertEqual(result.terminal["status"], "failed")
                self.assertEqual(result.terminal["error_category"], "authorization")
                self.assertEqual(result.terminal["publication_state"], "not_started")

    def test_supervision_reaping_and_authorization_terminal_on_filesystem_violation(self) -> None:
        clean_pp = build_clean_explicit_pythonpath(self.repo_root)
        env = prepare_child_coverage_environment(
            family="unmeasured", extra_env={"PYTHONPATH": clean_pp}
        )
        limits = build_run25_worker_limits()
        target_forbidden = self.read_root / "forbidden_write.txt"
        script = """
import sys, json
from pathlib import Path
from repomap_kg.coordinator._portable_authority import install_portable_authority_guard
install_portable_authority_guard(store_root=Path(sys.argv[1]), workspace_root=Path(sys.argv[2]), code_roots=[Path(sys.argv[3])])
print(json.dumps(dict(schema_version=1, message_type="worker_hello", protocol_versions=[1], capabilities=["refresh_graph"], worker_generation="wg1:fixture", process_nonce="nonce")), flush=True)
start = json.loads(sys.stdin.readline())
try:
    with open(sys.argv[4], 'w') as f:
        f.write('bad')
except PermissionError:
    terminal = dict(start, message_type="error", status="failed", error_category="authorization",
        publication_state="not_started", retryable=False, latest_run_identity=None, phase="complete",
        started_at="2026-09-20T12:00:00.000000Z", finished_at="2026-09-20T12:01:00.000000Z",
        extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
        files=0, observations=0, canonical_nodes=0, canonical_edges=0, warnings=[], diagnostics=[])
    print(json.dumps(terminal), flush=True)
"""
        spec = WorkerLaunchSpec(
            argv=(
                sys.executable,
                "-c",
                script,
                str(self.write_root),
                str(self.write_root),
                str(self.repo_root),
                str(target_forbidden),
            ),
            environment=env,
            cwd=self.repo_root,
        )
        identity = {"job_id": "job-causality-fs", "attempt": 1}
        result = run_worker_spec(spec, identity, limits)
        self.assertIsNone(result.protocol_error)
        self.assertTrue(result.waited)
        self.assertTrue(result.process_group_cleaned)
        self.assertFalse(result.synthesized_terminal)
        self.assertEqual(result.terminal["message_type"], "error")
        self.assertEqual(result.terminal["status"], "failed")
        self.assertEqual(result.terminal["error_category"], "authorization")
        self.assertEqual(result.terminal["publication_state"], "not_started")

    def test_run25_support_helpers(self) -> None:
        limits = build_run25_worker_limits()
        self.assertEqual(limits.hello_deadline_seconds, 0.5)
        self.assertEqual(limits.heartbeat_seconds, 0.15)
        self.assertEqual(limits.process_deadline_seconds, 0.8)

        ref = make_test_manifest_reference()
        self.assertEqual(ref.media_type, "application/x-repomap-snapshot-manifest-v1+json")
        self.assertEqual(ref.privacy, PrivacyClassification.RAW_SOURCE)

        store_dir = self.tmp / "art_store"
        store_dir.mkdir(mode=0o700)
        store_dir.chmod(0o700)
        store = FileSystemArtifactStore(store_dir)
        workspace_dir = self.tmp / "workspace"
        workspace_dir.mkdir(mode=0o700)
        workspace_dir.chmod(0o700)
        cap = create_run25_test_capability(self.tmp, store, workspace_dir)
        self.assertEqual(cap.job_id, "job-r25-01")
        self.assertEqual(cap.attempt, 1)
        self.assertEqual(cap.graph_id, "run25-graph")
        self.assertTrue(cap.manifest_reference.content_digest.startswith("sha256:"))



if __name__ == "__main__":
    unittest.main()
