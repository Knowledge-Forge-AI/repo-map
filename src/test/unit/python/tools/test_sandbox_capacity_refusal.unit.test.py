"""Pure capacity evidence, independent domains, and workload release contracts."""

import json
import stat
import subprocess
from types import SimpleNamespace

import pytest
import test_sandbox as sandbox
import test_sandbox_capacity as capacity


UPPER = "/var/lib/docker/overlay2/layer/diff"
TOKEN = "a" * 64
DIGEST = "b" * 64
GIB = capacity.GIB


def evidence(free=10 * GIB):
    return {
        "upper": UPPER,
        "mount_sha256": DIGEST,
        "free_bytes": free,
        "total_bytes": 100 * GIB,
        "free_percent": free * 100 // (100 * GIB),
    }




@pytest.fixture
def binding(monkeypatch, tmp_path):
    path = tmp_path / "capacity"
    owner = tmp_path / "owner"
    owner.write_text(TOKEN)
    monkeypatch.setattr(capacity, "BINDING_PATH", path)
    monkeypatch.setattr(capacity, "OWNER_PATH", owner)
    monkeypatch.setattr(capacity, "root_mount", lambda: (UPPER, DIGEST))
    monkeypatch.setattr(capacity.time, "time", lambda: 1000)
    monkeypatch.setattr(
        capacity.os,
        "fstat",
        lambda fd: SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o600),
    )
    value = {
        "schema": capacity.SCHEMA,
        "token": TOKEN,
        "mount_sha256": DIGEST,
        "issued_seconds": 1000,
    }
    path.write_text(json.dumps(value))
    return path, value


def test_capacity_commands_respect_existing_deadline():
    def expired(seconds):
        raise RuntimeError("system test deadline is exhausted")

    with pytest.raises(RuntimeError, match="deadline is exhausted"):
        capacity.bind_backing_capacity(
            lambda *a, **k: pytest.fail("Docker called after deadline"),
            "d" * 64,
            TOKEN,
            timeout_limit=expired,
        )


def test_inner_pull_exhaustion_has_its_own_reason():
    def full(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 1, "", "write layer: no space left on device"
        )

    with pytest.raises(RuntimeError, match="inner_docker_capacity_refused: exhausted"):
        sandbox._prepare_inner_images(full, "d" * 64)


@pytest.mark.parametrize("driver", ["overlayfs", "btrfs", "fuse-overlayfs"])
def test_parent_refuses_unsupported_driver_without_installing_binding(driver):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if command[1] == "inspect":
            value = json.dumps({"Name": driver, "Data": {"UpperDir": UPPER}})
        else:
            value = json.dumps(driver if "Driver" in command[-1] else "/var/lib/docker")
        return subprocess.CompletedProcess(command, 0, value, "")

    with pytest.raises(RuntimeError, match="unsupported_backing_mapping"):
        capacity.bind_backing_capacity(runner, "d" * 64, TOKEN)
    assert not any(command[1] == "exec" for command in calls)


@pytest.mark.parametrize(
    "case,status_val,graph_val,c_driver,storage_val,upper_val,expected_reason",
    [
        ("contradictory_graph_driver", [["driver-type", "io.containerd.snapshotter.v1"]], {"Name": "overlay2"}, "overlayfs", {"RootFS": {"Snapshot": {"Name": "overlayfs"}}}, "/var/lib/docker/containerd/daemon/io.containerd.snapshotter.v1.overlayfs/snapshots/1/fs", "unsupported_backing_mapping"),
        ("missing_snapshotter_status", [["driver-type", "other"]], None, "overlayfs", {"RootFS": {"Snapshot": {"Name": "overlayfs"}}}, "/var/lib/docker/containerd/daemon/io.containerd.snapshotter.v1.overlayfs/snapshots/1/fs", "unsupported_backing_mapping"),
        ("mismatched_container_driver", [["driver-type", "io.containerd.snapshotter.v1"]], None, "vfs", {"RootFS": {"Snapshot": {"Name": "overlayfs"}}}, "/var/lib/docker/containerd/daemon/io.containerd.snapshotter.v1.overlayfs/snapshots/1/fs", "unsupported_backing_mapping"),
        ("mismatched_storage_snapshotter", [["driver-type", "io.containerd.snapshotter.v1"]], None, "overlayfs", {"RootFS": {"Snapshot": {"Name": "other"}}}, "/var/lib/docker/containerd/daemon/io.containerd.snapshotter.v1.overlayfs/snapshots/1/fs", "unsupported_backing_mapping"),
        ("unbound_upper_path", [["driver-type", "io.containerd.snapshotter.v1"]], None, "overlayfs", {"RootFS": {"Snapshot": {"Name": "overlayfs"}}}, "/var/lib/other/snapshots/1/fs", "unbound_backing_evidence"),
    ],
)
def test_overlayfs_refuses_invalid_or_contradictory_metadata(
    case, status_val, graph_val, c_driver, storage_val, upper_val, expected_reason
):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        output = ""
        if command[1] == "info":
            if "DriverStatus" in command[-1]:
                output = json.dumps(status_val)
            elif "Driver" in command[-1]:
                output = json.dumps("overlayfs")
            else:
                output = json.dumps("/var/lib/docker")
        elif command[1] == "inspect":
            if "GraphDriver" in command[-1]:
                output = json.dumps(graph_val)
            elif "Driver" in command[-1]:
                output = json.dumps(c_driver)
            elif "Storage" in command[-1]:
                output = json.dumps(storage_val)
        elif command[-1] == "probe":
            output = json.dumps(evidence() | {"upper": upper_val})
        return subprocess.CompletedProcess(command, 0, output, "")

    with pytest.raises(RuntimeError, match=expected_reason):
        capacity.bind_backing_capacity(runner, "d" * 64, TOKEN)


@pytest.mark.parametrize("secondary,probe_kind", [
    (None, "low"), ("cleanup", "low"), ("cleanup_io", "low"), ("diagnostic", "low"),
    (None, "malformed"), (None, "unbound"), (None, "wrong_mapping"),
    (None, "unsupported"),
])
def test_capacity_refusal_prevents_release_and_keeps_exact_cleanup(
    monkeypatch, tmp_path, capsys, secondary, probe_kind
):
    calls = []
    outer_id = "d" * 64
    low = evidence(10 * GIB - 1)
    if probe_kind == "malformed":
        low["free_bytes"] = True
    elif probe_kind == "unbound":
        low["upper"] = "/private/unbound"
    driver = "btrfs" if probe_kind == "unsupported" else "overlay2"
    upper = "/private/wrong" if probe_kind == "wrong_mapping" else UPPER
    snapshots = []
    report_calls = []

    def runner(command, **kwargs):
        calls.append(command)
        output = ""
        if command[:3] == ["docker", "run", "-d"]:
            output = outer_id
        elif command[:2] == ["docker", "info"]:
            output = json.dumps(driver if "Driver" in command[-1] else "/var/lib/docker")
        elif command[:2] == ["docker", "inspect"]:
            output = json.dumps({"Name": driver, "Data": {"UpperDir": upper}})
        elif command[-1] == "probe":
            output = json.dumps(low)
        if secondary == "cleanup" and command[:4] == ["docker", "rm", "-f", "-v"]:
            return subprocess.CompletedProcess(command, 1, "", "private cleanup detail")
        if secondary == "cleanup_io" and command[:4] == ["docker", "rm", "-f", "-v"]:
            raise OSError("private cleanup detail")
        status = 1 if command[:3] == ["docker", "container", "inspect"] else 0
        return subprocess.CompletedProcess(command, status, output, "")

    class Follower(subprocess.Popen[bytes]):
        running = True

        def __init__(self) -> None:
            self._child_created = False

        def wait(self, timeout=None):
            calls.append(["follower", "wait"])
            self.running = False
            return 0

    follower = Follower()
    if secondary == "diagnostic":
        class BrokenStream:
            def write(self, text):
                raise OSError("private diagnostic detail")

            def flush(self):
                pass

        monkeypatch.setattr(capacity.sys, "stderr", BrokenStream())

    empty = sandbox.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())

    def snapshotter(_runner):
        snapshots.append(empty)
        return empty

    def archive_reader(container_id, required):
        report_calls.append((container_id, required))
        return None

    assert sandbox.run_in_sandbox(
        ["--suite", "staging", "--report"],
        repo_root=tmp_path,
        image_id="sha256:" + "a" * 64,
        runner=runner,
        follower_factory=lambda *_: follower,
        snapshotter=snapshotter,
        boundary_prover=lambda *a, **k: None,
        archive_reader=archive_reader,
    ) == 2
    assert len(snapshots) == 2
    assert not follower.running
    assert report_calls == [(outer_id, False)]
    assert not (tmp_path / ".test-reports").exists()
    assert ["docker", "exec", outer_id, "touch", "/sandbox-scratch/start-tests"] not in calls
    assert ["docker", "wait", outer_id] not in calls
    stop = ["docker", "stop", "--time", "10", outer_id]
    remove = ["docker", "rm", "-f", "-v", outer_id]
    assert calls.index(stop) < calls.index(["follower", "wait"]) < calls.index(remove)
    if secondary not in {"cleanup", "cleanup_io"}:
        assert ["docker", "container", "inspect", outer_id] in calls
    captured = capsys.readouterr()
    text = captured.out + captured.err
    reason = {
        "low": "host_admission_refused: free_disk_reserve",
        "malformed": "sandbox_capacity_refused: malformed_backing_evidence",
        "unbound": "sandbox_capacity_refused: unbound_backing_evidence",
        "wrong_mapping": "sandbox_capacity_refused: unsupported_backing_mapping",
        "unsupported": "sandbox_capacity_refused: unsupported_backing_mapping",
    }[probe_kind]
    assert reason in text
    records = [json.loads(line) for line in text.splitlines() if line.startswith("{")]
    assert len(records) == 1
    if probe_kind == "low":
        assert records[0]["free_bytes"] == low["free_bytes"]
    else:
        assert set(records[0]) == {"event", "stage", "decision", "reason"}
        assert "host_admission_refused" not in text
    assert records[0]["stage"] == "outer_overlay_backing"
    assert records[0]["decision"] == "refused"
    assert "private" not in text and UPPER not in text and TOKEN not in text
    if secondary in {"cleanup", "cleanup_io"}:
        assert "integration sandbox cleanup failed" in text
    if secondary == "diagnostic":
        assert "diagnostic write failed" in text
