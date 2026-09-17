"""Integration test for container PID namespace correlation across host/inner boundaries."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
import uuid

import pytest

from runner_coverage_bootstrap import (
    BOOTSTRAP_TEMPLATE,
    BootstrapCapabilityRecord,
    derive_container_mount_aliases,
)
from runner_coverage_container import launch_observed_container_process
from runner_coverage_diagnostics import create_shard_snapshot
from runner_coverage_observer import ProcessObserver
from runner_portable_coverage import validate_shard_directory_integrity
from test_sandbox_contract import INNER_TEST_SCRATCH_ROOT


def _docker_is_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        res = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return res.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def test_container_pid_namespace_correlation_translated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _docker_is_available():
        pytest.skip("Docker is not available or daemon is not reachable")

    image = "repomap-test-sandbox:py313-go125-docker294-v1"
    container_id: str | None = None
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(scratch_dir))

    try:
        # 1. Run container with isolated PID namespace and mounted scratch root
        run_res = subprocess.run(
            [
                "docker", "run", "-d", "--rm",
                "-v", f"{scratch_dir}:{INNER_TEST_SCRATCH_ROOT}",
                image, "sleep", "60",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        container_id = run_res.stdout.strip()
        assert container_id, "Failed to obtain container ID"

        # 2. Build session directory, config file, manifest directory, and capability record
        invocation_id = f"inv-{uuid.uuid4().hex[:12]}"
        session_dir = scratch_dir / invocation_id
        session_dir.mkdir(parents=True, exist_ok=True)
        obs_dir = session_dir / "observations"
        obs_dir.mkdir(parents=True, exist_ok=True)
        manifest_dir = session_dir / "child_procs"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        config_file = session_dir / "coverage.rc"
        config_file.write_text("[run]\nbranch = False\n", encoding="utf-8")
        b_dir = session_dir / "bootstrap"
        b_dir.mkdir(parents=True, exist_ok=True)
        (b_dir / "sitecustomize.py").write_text(BOOTSTRAP_TEMPLATE, encoding="utf-8")

        aliases = (
            *derive_container_mount_aliases(b_dir, scratch_root=scratch_dir),
            *derive_container_mount_aliases(session_dir, scratch_root=scratch_dir),
        )
        assert len(aliases) >= 2, f"Expected container mount aliases, got {aliases}"
        assert all(str(INNER_TEST_SCRATCH_ROOT) in a for a in aliases)

        b_ident = hashlib.sha256(BOOTSTRAP_TEMPLATE.encode("utf-8")).hexdigest()
        cap = BootstrapCapabilityRecord(
            identity=b_ident,
            host_visible_path=b_dir,
            same_namespace_path=b_dir,
            container_mount_aliases=aliases,
            additional_host_paths=(session_dir,),
        )
        cap.save(session_dir / "bootstrap_capability.json")

        observer = ProcessObserver(
            observation_dir=obs_dir,
            invocation_id=invocation_id,
            capability=cap,
        )

        measured_env = {
            "COVERAGE_PROCESS_START": str(config_file),
            "COVERAGE_CHILD_MANIFEST_DIR": str(manifest_dir),
            "COVERAGE_SESSION_INVOCATION_ID": invocation_id,
            "COVERAGE_SESSION_SUITE": "int",
            "PYTHONPATH": str(b_dir),
        }

        # 3. Production launch seam executes container child, builds/applies measured coverage environment,
        # translates host paths to container-visible paths, extracts host/inner PIDs
        # with explicit PID header checks, and observes launch
        match_token = f"tok-{uuid.uuid4().hex[:12]}"
        launch_args = [
            "python3", "-c",
            f"import time; # {match_token}\ntime.sleep(30)",
        ]

        record = launch_observed_container_process(
            container_id=container_id,
            args=launch_args,
            family="portable_worker",
            observer=observer,
            capability=cap,
            env=measured_env,
            scratch_root=scratch_dir,
            invocation_id=invocation_id,
            match_token=match_token,
            settle_timeout=10.0,
        )

        assert record is not None, "launch_observed_container_process returned None"
        print(f"\n[DOCKER PROOF] container={container_id[:12]} host_pid={record.host_pid} inner_pid={record.inner_pid} relation={record.pid_namespace_relation}")
        assert record.host_pid > 0
        assert record.inner_pid is not None and record.inner_pid > 1
        assert record.host_pid != record.inner_pid
        assert record.pid_namespace_relation == "translated"
        assert record.invocation_id == invocation_id
        assert record.executable_family == "portable_worker"
        assert record.has_coverage_capability is True
        assert record.has_bootstrap_pythonpath is True
        assert record.has_manifest_authority is True

        # Confirm container child booted under translated bootstrap and wrote inner PID start marker
        start_marker = manifest_dir / f"{record.inner_pid}.start"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not start_marker.is_file():
            time.sleep(0.1)
        assert start_marker.is_file(), f"Expected inner PID start marker {start_marker} written by container child"

        # 4. Correlation via find_observation_by_inner_pid
        found = observer.find_observation_by_inner_pid(
            inner_pid=record.inner_pid,
            invocation_id=invocation_id,
        )
        assert found is not None
        assert found.host_pid == record.host_pid
        assert found.inner_pid == record.inner_pid
        assert found.pid_namespace_relation == "translated"

        # 5. Cross-process recovery from observation directory
        restored_observer = ProcessObserver(
            observation_dir=obs_dir,
            invocation_id=invocation_id,
        )
        restored = restored_observer.find_observation_by_inner_pid(
            inner_pid=record.inner_pid,
            invocation_id=invocation_id,
        )
        assert restored is not None
        assert restored.host_pid == record.host_pid
        assert restored.inner_pid == record.inner_pid

        # 6. Production correlation: positive acceptance when shard is allowed
        shards_dir = session_dir / "shards"
        shards_dir.mkdir(parents=True, exist_ok=True)
        shard_path = shards_dir / f".coverage.sandbox_host_worker.pid{record.inner_pid}.shard"
        shard_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 96)

        accepted_snapshots: list[object] = []
        validate_shard_directory_integrity(
            data_dir=shards_dir,
            allowed_shards={str(shard_path.resolve()), str(shard_path)},
            parent_shard=None,
            snapshot_fn=create_shard_snapshot,
            record_fn=accepted_snapshots.append,
            observer=observer,
            invocation_id=invocation_id,
        )

        # 7. Production correlation: unregistered shard rejection
        recorded_snapshots: list[object] = []
        with pytest.raises(RuntimeError, match="unregistered coverage shard rejected"):
            validate_shard_directory_integrity(
                data_dir=shards_dir,
                allowed_shards=set(),
                parent_shard=None,
                snapshot_fn=create_shard_snapshot,
                record_fn=recorded_snapshots.append,
                observer=observer,
                invocation_id=invocation_id,
            )

        assert len(recorded_snapshots) == 1
        snap: Any = recorded_snapshots[0]
        assert snap.launch_role == "observed_unregistered"
        assert snap.failure_class == "unregistered_child_process"
        assert snap.failure_reason.startswith("child_never_registered_bootstrap")

        # 8. Ambiguity rejection: second observation with conflicting host PID for same inner PID
        observer.observe_launch(
            host_pid=record.host_pid + 99999,
            inner_pid=record.inner_pid,
            pid_namespace_relation="translated",
            invocation_id=invocation_id,
            executable_family="portable_worker",
        )
        assert observer.find_observation_by_inner_pid(record.inner_pid, invocation_id) is None

        # 9. Negative mappings: stale invocation and unknown inner PID rejection
        assert observer.find_observation_by_inner_pid(record.inner_pid, "stale-inv") is None
        assert observer.find_observation_by_inner_pid(999999, invocation_id) is None
    finally:
        if container_id:
            subprocess.run(
                ["docker", "kill", container_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
