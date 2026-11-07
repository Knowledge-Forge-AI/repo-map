"""Capacity protocol across real processes and files with controlled backend inputs."""
from pathlib import Path
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest
import test_sandbox_capacity as capacity
from runner_coverage_execution import scrub_coverage_environment

REPO = Path(__file__).resolve().parents[5]
TOKEN = "a" * 64


@pytest.mark.parametrize("upper", [
    "/var/lib/docker/containerd/daemon/io.containerd.snapshotter.v1.overlayfs/snapshots/42/fs",
    "/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/42/fs",
])
def test_capacity_binding_subprocess_protocol_and_exclusive_owner_file(tmp_path, monkeypatch, upper):
    mount = f"1 2 0:3 / / rw - overlay overlay rw,upperdir={upper},workdir=/fixture-work"
    digest = hashlib.sha256(mount.encode()).hexdigest()
    builder = tmp_path / "fixture_docker.py"
    builder.write_text('''import io,json,os,sys
from pathlib import Path
args=sys.argv[1:]
responses={
 "{{json .Driver}}":"overlayfs", "{{json .DockerRootDir}}":"/var/lib/docker",
 "{{json .GraphDriver}}":None, "{{json .DriverStatus}}":[["driver-type","io.containerd.snapshotter.v1"]],
 "{{json .Storage}}":{"RootFS":{"Snapshot":{"Name":"overlayfs"}}},
}
if args[0] in ("info","inspect"):
 print(json.dumps(responses[args[-1]]))
elif args[-1]=="probe":
 sys.path.insert(0,os.environ["PROBE_TOOLS"])
 import test_sandbox_capacity as c
 actual_path=c.Path
 c.Path=lambda p: type("MountInput",(),{"open":lambda self,**kw:io.StringIO(os.environ["PROBE_MOUNT"])})() if p=="/proc/self/mountinfo" else actual_path(p)
 print(json.dumps(c.probe()))
elif args[:2]==["exec","-i"] and args[-2]=="-c":
 exec(compile(args[-1],"<binding-writer>","exec"))
else:
 raise AssertionError("unexpected fixture command")
''')
    binding, owner = tmp_path / "binding", tmp_path / "owner"
    owner.write_text(TOKEN)
    monkeypatch.setattr(capacity, "BINDING_PATH", binding)
    monkeypatch.setattr(capacity, "OWNER_PATH", owner)
    actual_path = capacity.Path
    monkeypatch.setattr(capacity, "Path", lambda p: SimpleNamespace(open=lambda **kw: io.StringIO(mount))
                        if p == "/proc/self/mountinfo" else actual_path(p))
    environment = scrub_coverage_environment(os.environ) | {
        "PROBE_TOOLS": str(REPO / "tools"), "PROBE_MOUNT": mount,
    }
    calls = []
    probes = []

    def runner(command, **kwargs):
        calls.append(command)
        done = subprocess.run([sys.executable, "-I", "-B", str(builder), *command[1:]], env=environment, **kwargs)
        if command[-1] == "probe" and done.returncode == 0:
            probes.append(json.loads(done.stdout))
        return done

    def enough_space(value):
        return value["free_bytes"] >= 10 * capacity.GIB and value["free_percent"] >= 5

    failure = None
    try:
        capacity.bind_backing_capacity(runner, "d" * 64, TOKEN)
    except RuntimeError as error:
        failure = str(error)
    assert len(probes) == 1
    if not enough_space(probes[-1]):
        assert failure == "host_admission_refused: free_disk_reserve"
        assert not binding.exists()
        print("capacity protocol: real low-capacity refusal, no binding created")
        return
    assert failure is None, failure
    assert stat.S_IMODE(binding.stat().st_mode) == 0o600
    value = capacity.read_binding()
    assert value["token"] == TOKEN and value["mount_sha256"] == digest
    assert not any(key.startswith("COVERAGE_") for key in environment)
    with pytest.raises(RuntimeError) as refused:
        capacity.bind_backing_capacity(runner, "d" * 64, TOKEN)
    assert len(probes) == 2
    expected = ("backing_measurement_unavailable" if enough_space(probes[-1])
                else "host_admission_refused: free_disk_reserve")
    assert expected in str(refused.value)
    assert capacity.read_binding() == value
    assert len([command for command in calls if command[-1] == "probe"]) == 2
    owner.write_text("b" * 64)
    with pytest.raises(RuntimeError, match="wrong_attempt_binding"):
        capacity.read_binding()
    print("capacity protocol: binding preserved after " + expected)
