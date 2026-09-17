"""Unit tests for subprocess observation, host/inner PID mapping, and launch seams."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from runner_coverage_bootstrap import (
    BOOTSTRAP_TEMPLATE,
    BootstrapCapabilityRecord,
    derive_container_mount_aliases,
    extend_pythonpath,
    is_runner_bootstrap_path,
    resolve_bootstrap_capability,
)
from runner_coverage_container import (
    extract_pid_from_container_ps,
    extract_pid_from_docker_top,
    launch_observed_container_process,
    translate_path_to_container,
    translate_pythonpath_to_container,
)
from runner_coverage_execution import scrub_coverage_environment
from runner_coverage_observer import (
    ProcessObserver,
    launch_observed_process,
)
from test_sandbox_contract import INNER_TEST_SCRATCH_ROOT


class TestRunnerCoverageObservation(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.obs_dir = Path(self.temp_dir.name)
        self.invocation_id = "test-inv-001"
        self.observer = ProcessObserver(
            observation_dir=self.obs_dir,
            invocation_id=self.invocation_id,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_observed_launch_helper_records_host_pid_and_metadata(self) -> None:
        """Matrix Item 6: Real launch through ProcessObserver production helper."""
        res = launch_observed_process(
            [sys.executable, "-c", "import os; print(os.getpid())"],
            family="cli_module",
            cwd=Path.cwd(),
            pid_namespace_relation="shared",
            observer=self.observer,
        )
        self.assertEqual(res.returncode, 0)
        child_pid = int(res.stdout.strip())

        rec = self.observer.find_observation_by_inner_pid(
            child_pid, self.invocation_id
        )
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec.host_pid, child_pid)
        self.assertEqual(rec.inner_pid, child_pid)
        self.assertEqual(rec.executable_family, "cli_module")
        self.assertEqual(rec.pid_namespace_relation, "shared")

        obs_file = self.obs_dir / f"parent_obs_{child_pid}.json"
        self.assertTrue(obs_file.is_file())
        data = json.loads(obs_file.read_text(encoding="utf-8"))
        self.assertEqual(data["host_pid"], child_pid)
        self.assertEqual(data["invocation_id"], self.invocation_id)

    def test_observed_child_with_no_registration_marker(self) -> None:
        """Matrix Item 7: Observed child produces no marker, parent evidence exists."""
        clean_env = {
            k: v for k, v in os.environ.items() if not k.startswith("COVERAGE_")
        }
        res = launch_observed_process(
            [sys.executable, "-c", "import sys; sys.exit(0)"],
            family="cli_module",
            env=clean_env,
            pid_namespace_relation="shared",
            observer=self.observer,
        )
        self.assertEqual(res.returncode, 0)
        recs = list(self.observer._records.values())
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        self.assertFalse(rec.has_coverage_capability)
        self.assertFalse(rec.has_manifest_authority)
        self.assertTrue((self.obs_dir / f"parent_obs_{rec.host_pid}.json").is_file())

    def test_host_inner_pid_divergence_under_container_namespace(self) -> None:
        """Matrix Item 8: Host PID != inner PID mapping in ProcessObserver lookup."""
        host_pid, inner_pid = 9901, 2048
        rec = self.observer.observe_launch(
            host_pid=host_pid, inner_pid=inner_pid, pid_namespace_relation="translated",
            invocation_id=self.invocation_id, executable_family="container_isolated",
        )
        self.assertEqual(rec.host_pid, 9901)
        self.assertEqual(rec.inner_pid, 2048)
        self.assertEqual(rec.pid_namespace_relation, "translated")

        found = self.observer.find_observation_by_inner_pid(2048, self.invocation_id)
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.host_pid, 9901)
        self.assertEqual(found.inner_pid, 2048)
        self.assertIsNone(self.observer.find_observation_by_inner_pid(9901, self.invocation_id))

    def test_ambiguous_inner_pid_mapping_fails_closed(self) -> None:
        """Matrix Item 9: Two launches claiming same (invocation, inner_pid) fail closed."""
        self.observer.observe_launch(
            host_pid=7001, inner_pid=42, pid_namespace_relation="translated",
            invocation_id=self.invocation_id, executable_family="container_isolated",
        )
        self.observer.observe_launch(
            host_pid=7002, inner_pid=42, pid_namespace_relation="translated",
            invocation_id=self.invocation_id, executable_family="container_isolated",
        )
        self.assertIsNone(self.observer.find_observation_by_inner_pid(42, self.invocation_id))

    def test_stale_and_cross_invocation_mapping_rejected(self) -> None:
        """Matrix Item 10: Cross-invocation observation records are rejected."""
        self.observer.observe_launch(
            host_pid=8001, inner_pid=8001, pid_namespace_relation="shared",
            invocation_id="other-invocation-xyz", executable_family="cli_module",
        )
        self.assertIsNone(self.observer.find_observation_by_inner_pid(8001, self.invocation_id))
        self.assertIsNone(self.observer.find_observation_by_inner_pid(8001, None))

    def test_malformed_observation_file_raises_error(self) -> None:
        """Malformed retained observation records must not be silently swallowed."""
        corrupt_file = self.obs_dir / "parent_obs_9999.json"
        corrupt_file.write_text("{invalid_json: true", encoding="utf-8")
        fresh_observer = ProcessObserver(observation_dir=self.obs_dir, invocation_id=self.invocation_id)
        with self.assertRaises(RuntimeError):
            fresh_observer.find_observation_by_inner_pid(9999, self.invocation_id)

    def test_identity_less_observer_rejected(self) -> None:
        """ProcessObserver rejects missing or empty invocation_id or observation_dir."""
        with self.assertRaises(ValueError):
            ProcessObserver(observation_dir=self.obs_dir, invocation_id="")
        with self.assertRaises(ValueError):
            ProcessObserver(observation_dir=self.obs_dir, invocation_id="   ")
        with self.assertRaises(ValueError):
            ProcessObserver(observation_dir=None, invocation_id="valid-id")  # type: ignore[arg-type]

    def test_stale_parent_obs_files_ignored_during_load(self) -> None:
        """Observation records from previous/stale invocations are skipped on disk read."""
        stale_file = self.obs_dir / "parent_obs_5555.json"
        stale_data = {
            "process_identity": "proc:5555:0", "host_pid": 5555, "inner_pid": 5555,
            "pid_namespace_relation": "shared", "invocation_id": "stale-invocation-abc",
            "ppid": 1, "start_time": 0.0, "executable_family": "cli_module",
        }
        stale_file.write_text(json.dumps(stale_data), encoding="utf-8")
        fresh_observer = ProcessObserver(observation_dir=self.obs_dir, invocation_id=self.invocation_id)
        self.assertIsNone(fresh_observer.find_observation_by_inner_pid(5555, self.invocation_id))

    def test_pid_namespace_relation_validation(self) -> None:
        """Closed set PID_NAMESPACE_RELATIONS enforced with mandatory inner_pid for translated."""
        rec = self.observer.observe_launch(
            host_pid=3001, inner_pid=1, pid_namespace_relation="translated",
            invocation_id=self.invocation_id,
        )
        self.assertEqual(rec.pid_namespace_relation, "translated")
        with self.assertRaises(ValueError):
            self.observer.observe_launch(
                host_pid=3002, inner_pid=1, pid_namespace_relation="invalid_relation",
                invocation_id=self.invocation_id,
            )
        # Translated relation without inner_pid must fail closed
        with self.assertRaises(ValueError):
            self.observer.observe_launch(
                host_pid=3003, inner_pid=None, pid_namespace_relation="translated",
                invocation_id=self.invocation_id,
            )

    def test_unconditional_executable_family_validation(self) -> None:
        """Launch validation enforces closed launch families before any subprocess is spawned."""
        with self.assertRaises(ValueError):
            launch_observed_process([sys.executable, "-c", "pass"], family="unrecognized_family")
        # Measured family without explicit pid_namespace_relation fails closed before launch
        with self.assertRaises(ValueError):
            launch_observed_process([sys.executable, "-c", "pass"], family="cli_module", pid_namespace_relation=None)
        # Measured family without explicit observer fails closed before launch
        with self.assertRaises(RuntimeError):
            launch_observed_process(
                [sys.executable, "-c", "pass"], family="cli_module", pid_namespace_relation="shared",
                env={"COVERAGE_PROCESS_START": "/path/to/rc"}, observer=None,
            )

    def test_interleaved_two_session_isolation(self) -> None:
        """Two concurrent/interleaved ChildCoverageSessions remain strictly isolated with explicit observers."""
        import coverage
        from runner_coverage import ChildCoverageSession

        scratch1 = self.obs_dir / "s1"
        scratch2 = self.obs_dir / "s2"
        s1 = ChildCoverageSession(
            coverage_module=coverage,
            scratch_dir=scratch1,
            source_root=self.obs_dir,
            suite="unit",
        )
        s2 = ChildCoverageSession(
            coverage_module=coverage,
            scratch_dir=scratch2,
            source_root=self.obs_dir,
            suite="unit",
        )
        with s1, s2:
            r1 = launch_observed_process(
                [sys.executable, "-c", "import os; print(os.getpid())"],
                family="cli_module",
                cwd=Path.cwd(),
                pid_namespace_relation="shared",
                observer=s1.process_observer,
            )
            pid1 = int(r1.stdout.strip())

            r2 = launch_observed_process(
                [sys.executable, "-c", "import os; print(os.getpid())"],
                family="cli_module",
                cwd=Path.cwd(),
                pid_namespace_relation="shared",
                observer=s2.process_observer,
            )
            pid2 = int(r2.stdout.strip())

            self.assertIsNotNone(
                s1.process_observer.find_observation_by_inner_pid(pid1, s1.invocation_id)
            )
            self.assertIsNone(
                s2.process_observer.find_observation_by_inner_pid(pid1, s2.invocation_id)
            )

            self.assertIsNotNone(
                s2.process_observer.find_observation_by_inner_pid(pid2, s2.invocation_id)
            )
            self.assertIsNone(
                s1.process_observer.find_observation_by_inner_pid(pid2, s1.invocation_id)
            )

    def test_bootstrap_capability_record_aliases_and_foreign_paths(self) -> None:
        """F5/F7: Container mount alias derivation, additional host paths, and foreign path handling."""
        scratch = Path("/tmp/test-scratch-root")
        boot_dir = scratch / "sub" / "bootstrap"
        sess_dir = scratch / "sub"
        aliases = derive_container_mount_aliases(boot_dir, scratch_root=scratch)
        expected_alias = str(INNER_TEST_SCRATCH_ROOT / "sub" / "bootstrap")
        self.assertEqual(aliases, (expected_alias,))
        self.assertEqual(derive_container_mount_aliases(Path("/other/dir"), scratch_root=scratch), ())

        cap = BootstrapCapabilityRecord(
            identity="boot-001", host_visible_path=boot_dir, same_namespace_path=boot_dir,
            container_mount_aliases=aliases, additional_host_paths=(sess_dir,),
        )
        self.assertTrue(cap.is_alias(boot_dir))
        self.assertTrue(cap.is_alias(sess_dir))
        self.assertTrue(cap.is_alias(expected_alias))
        self.assertFalse(cap.is_alias("/foreign/nonexistent/path"))
        self.assertEqual(cap.to_dict()["additional_host_paths"], [str(sess_dir)])
        self.assertEqual(BootstrapCapabilityRecord.from_dict(cap.to_dict()).additional_host_paths, (sess_dir,))

        self.assertTrue(is_runner_bootstrap_path(expected_alias, capability=cap))
        self.assertFalse(is_runner_bootstrap_path("/foreign/nonexistent/path", capability=cap))

        obs = ProcessObserver(observation_dir=self.obs_dir, invocation_id="test-inv-boot", capability=cap)
        rec = obs.observe_launch(host_pid=9999, pid_namespace_relation="shared", env={"PYTHONPATH": aliases[0]})
        self.assertTrue(rec.has_bootstrap_pythonpath)

    def test_bootstrap_capability_validation_and_load_fail_closed(self) -> None:
        """F4/F5: Deterministic load validation, expected_dir containment, and fail-closed resolution."""
        import hashlib
        scratch = self.obs_dir / "cap_sess"
        scratch.mkdir(parents=True, exist_ok=True)
        boot_dir = scratch / "bootstrap"
        boot_dir.mkdir(parents=True, exist_ok=True)
        b_ident = hashlib.sha256(BOOTSTRAP_TEMPLATE.encode("utf-8")).hexdigest()
        cap = BootstrapCapabilityRecord(
            identity=b_ident, host_visible_path=boot_dir, same_namespace_path=boot_dir, additional_host_paths=(scratch,),
        )
        cap_file = scratch / "bootstrap_capability.json"
        cap.save(cap_file)

        # Valid load succeeds
        loaded = BootstrapCapabilityRecord.load(cap_file, expected_dir=scratch)
        self.assertEqual(loaded.identity, b_ident)

        # Identity mismatch fails closed
        bad_cap = BootstrapCapabilityRecord(identity="tampered-ident", host_visible_path=boot_dir, same_namespace_path=boot_dir)
        bad_cap.save(cap_file)
        with self.assertRaises(ValueError):
            BootstrapCapabilityRecord.load(cap_file, expected_dir=scratch)

        # Session escape fails closed
        escape_cap = BootstrapCapabilityRecord(identity=b_ident, host_visible_path=Path("/tmp/escape"), same_namespace_path=Path("/tmp/escape"))
        escape_cap.save(cap_file)
        with self.assertRaises(ValueError):
            BootstrapCapabilityRecord.load(cap_file, expected_dir=scratch)

        # resolve_bootstrap_capability fails closed on tampered json
        with self.assertRaises(ValueError):
            resolve_bootstrap_capability(env={"COVERAGE_CHILD_MANIFEST_DIR": str(scratch / "child_procs")})

    def test_container_launch_seam_validation_and_translation(self) -> None:
        """F2/F4: Container launch seam validation and container path translation."""
        scratch = Path("/tmp/scratch-trans")
        boot = scratch / "session" / "bootstrap"
        with self.assertRaises(ValueError):
            launch_observed_container_process("c1", ["python3"], family="unknown_family")
        with self.assertRaises(RuntimeError):
            launch_observed_container_process("c1", ["python3"], family="portable_worker", capability=None, env={})

        t_path = translate_path_to_container(str(boot), scratch_root=scratch)
        self.assertEqual(t_path, str(INNER_TEST_SCRATCH_ROOT / "session" / "bootstrap"))
        t_pp = translate_pythonpath_to_container(f"{boot}:/usr/local/lib", scratch_root=scratch)
        self.assertEqual(t_pp, f"{INNER_TEST_SCRATCH_ROOT}/session/bootstrap:/usr/local/lib")

    def test_extract_pid_from_docker_top_and_container_ps(self) -> None:
        """Strict header enforcement, lookup, multi-line tolerance, and ambiguity failure."""
        top_ok = "UID   PID  PPID  C STIME TTY          TIME CMD\nroot 1234  1000  0 00:00 ?        00:00:00 python3 run.py --tok tok-1\n"
        self.assertEqual(extract_pid_from_docker_top(top_ok, "tok-1"), 1234)
        top_multiline = "UID   PID  PPID  C STIME TTY          TIME CMD\nroot 1234  1000  0 00:00 ?        00:00:00 python3 -c import time; # tok-1\ntime.sleep(30)\n"
        self.assertEqual(extract_pid_from_docker_top(top_multiline, "tok-1"), 1234)
        with self.assertRaises(ValueError):
            extract_pid_from_docker_top("UID PPID CMD\n1 2 python3\n", "tok-1")
        with self.assertRaises(ValueError):
            extract_pid_from_docker_top("", "tok-1")
        with self.assertRaises(LookupError):
            extract_pid_from_docker_top(top_ok, "nonexistent-token")
        top_ambig = top_ok + "root 1235  1000  0 00:00 ?        00:00:00 python3 run.py --tok tok-1\n"
        with self.assertRaises(RuntimeError):
            extract_pid_from_docker_top(top_ambig, "tok-1")

        ps_ok = "PID COMMAND\n 42 python3 run.py --tok tok-1\n"
        self.assertEqual(extract_pid_from_container_ps(ps_ok, "tok-1"), 42)
        with self.assertRaises(ValueError):
            extract_pid_from_container_ps("COMMAND\npython3\n", "tok-1")
        with self.assertRaises(ValueError):
            extract_pid_from_container_ps("", "tok-1")
        with self.assertRaises(LookupError):
            extract_pid_from_container_ps(ps_ok, "nonexistent-token")
        ps_ambig = ps_ok + " 43 python3 run.py --tok tok-1\n"
        with self.assertRaises(RuntimeError):
            extract_pid_from_container_ps(ps_ambig, "tok-1")

    def test_sandbox_mount_regression_dedup_detection_and_scrub(self) -> None:
        """Prove host path, container alias, dedup, detection, and scrub refer to single capability."""
        scratch = Path("/tmp/scratch-regress")
        boot = scratch / "boot"
        aliases = derive_container_mount_aliases(boot, scratch_root=scratch)
        cap = BootstrapCapabilityRecord(
            identity="cap-regress", host_visible_path=boot, same_namespace_path=boot,
            container_mount_aliases=aliases,
        )
        alias_path = aliases[0]
        self.assertEqual(alias_path, str(INNER_TEST_SCRATCH_ROOT / "boot"))
        self.assertTrue(is_runner_bootstrap_path(boot, capability=cap))
        self.assertTrue(is_runner_bootstrap_path(alias_path, capability=cap))
        self.assertEqual(extend_pythonpath(f"/user/code:{alias_path}:{str(boot)}", capability=cap), "/user/code")
        cleaned = scrub_coverage_environment({"PYTHONPATH": f"/usr/lib:{alias_path}:{str(boot)}"}, capability=cap)
        self.assertEqual(cleaned.get("PYTHONPATH"), "/usr/lib")


if __name__ == "__main__":
    unittest.main()
