"""Integration test for container PID namespace correlation across host/inner boundaries."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
import uuid

import pytest

from runner_coverage_diagnostics import create_shard_snapshot
from runner_coverage_observer import ProcessObserver
from runner_portable_coverage import validate_shard_directory_integrity


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


def test_container_pid_namespace_correlation_translated(tmp_path: Path) -> None:
    if not _docker_is_available():
        pytest.skip("Docker is not available or daemon is not reachable")

    image = "repomap-test-sandbox:py313-go125-docker294-v1"
    container_id: str | None = None
    try:
        # 1. Run container with isolated PID namespace in background
        run_res = subprocess.run(
            ["docker", "run", "-d", "--rm", image, "sleep", "60"],
            capture_output=True,
            text=True,
            check=True,
        )
        container_id = run_res.stdout.strip()
        assert container_id, "Failed to obtain container ID"

        # 2. Launch background inner process (inner_pid > 1) via docker exec
        marker_file = "/tmp/inner_proc_pid.txt"
        subprocess.run(
            [
                "docker",
                "exec",
                "-d",
                container_id,
                "python3",
                "-c",
                f'import os, time; open("{marker_file}", "w").write(str(os.getpid())); time.sleep(30)',
            ],
            check=True,
        )

        inner_pid: int | None = None
        for _ in range(20):
            time.sleep(0.2)
            read_res = subprocess.run(
                ["docker", "exec", container_id, "cat", marker_file],
                capture_output=True,
                text=True,
                check=False,
            )
            if read_res.returncode == 0 and read_res.stdout.strip().isdigit():
                inner_pid = int(read_res.stdout.strip())
                break
        assert inner_pid is not None and inner_pid > 1, f"Expected inner PID > 1, got {inner_pid}"

        # 3. Retrieve host_pid via docker top
        top_res = subprocess.run(
            ["docker", "top", container_id],
            capture_output=True,
            text=True,
            check=True,
        )
        top_lines = top_res.stdout.splitlines()
        header = top_lines[0].split() if top_lines else []
        pid_idx = header.index("PID") if "PID" in header else 1
        host_pid: int | None = None
        for line in top_lines[1:]:
            if "inner_proc_pid.txt" in line:
                parts = line.split(maxsplit=len(header) - 1) if header else line.split()
                if len(parts) > pid_idx and parts[pid_idx].isdigit():
                    host_pid = int(parts[pid_idx])
                    break
        assert host_pid is not None and host_pid > 0, f"Expected valid host PID from docker top, got {host_pid}"
        assert host_pid != inner_pid, f"Expected host PID ({host_pid}) != inner PID ({inner_pid})"

        # 4. Record observation with pid_namespace_relation="translated"
        invocation_id = f"inv-{uuid.uuid4().hex[:12]}"
        obs_dir = tmp_path / "observations"
        observer = ProcessObserver(
            observation_dir=obs_dir,
            invocation_id=invocation_id,
        )

        record = observer.observe_launch(
            host_pid=host_pid,
            argv=["python3", "-c", "import os, time; ..."],
            executable_family="portable_worker",
            inner_pid=inner_pid,
            pid_namespace_relation="translated",
            invocation_id=invocation_id,
        )

        assert record.host_pid == host_pid
        assert record.inner_pid == inner_pid
        assert record.pid_namespace_relation == "translated"
        assert record.invocation_id == invocation_id

        # 5. Assert find_observation_by_inner_pid returns the record
        found = observer.find_observation_by_inner_pid(
            inner_pid=inner_pid,
            invocation_id=invocation_id,
        )
        assert found is not None
        assert found.host_pid == host_pid
        assert found.inner_pid == inner_pid
        assert found.pid_namespace_relation == "translated"

        # 6. Correlate via validate_shard_directory_integrity
        shards_dir = tmp_path / "shards"
        shards_dir.mkdir(parents=True, exist_ok=True)
        shard_path = shards_dir / f".coverage.sandbox_host_worker.pid{inner_pid}.shard"
        shard_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 96)

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
        assert snap.failure_reason == "child_never_registered_bootstrap"

        # 7. Verify cross-process recovery from observation directory
        restored_observer = ProcessObserver(
            observation_dir=obs_dir,
            invocation_id=invocation_id,
        )
        restored = restored_observer.find_observation_by_inner_pid(
            inner_pid=inner_pid,
            invocation_id=invocation_id,
        )
        assert restored is not None
        assert restored.host_pid == host_pid
        assert restored.inner_pid == inner_pid

        # 8. Fail closed on mismatched invocation_id or unknown inner pid
        assert observer.find_observation_by_inner_pid(inner_pid, "stale-inv") is None
        assert observer.find_observation_by_inner_pid(999999, invocation_id) is None
    finally:
        if container_id:
            subprocess.run(
                ["docker", "kill", container_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
