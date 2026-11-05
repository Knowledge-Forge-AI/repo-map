"""Docker boundary: exact vectors, closed journal, inspection and exact-ID settlement (5.1, 5.2, 8)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult
from common_lore_index.extractors.rust_pilot.docker_boundary import (
    DockerBoundary,
    DockerRefused,
    check_container_config,
    container_name,
    create_arguments,
    exec_arguments,
    journal_violations,
)

RUN = "rp1.0123456789abcdef"
IMAGE = "sha256:" + "a" * 64
CID = "c" * 64


def result(code: int | None = 0, out: bytes = b"", *, timed_out: bool = False) -> ExecResult:
    return ExecResult(code, out, False, 0, "0" * 64, False, timed_out, True, 0.01)


class FakeClient:
    """Injected command runner: records argument vectors, answers from a table."""

    def __init__(self, answer: Callable[[list[str]], ExecResult]) -> None:
        self.answer = answer
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], stdin: bytes, limit: int, deadline: float,
                 on_deadline: Callable[[float], None] | None, *, hard_end: float | None = None) -> ExecResult:
        assert argv[0] == "/usr/bin/docker" and deadline <= 20.0
        self.calls.append(list(argv[1:]))
        return self.answer(list(argv[1:]))


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def boundary(answer: Callable[[list[str]], ExecResult]) -> tuple[DockerBoundary, FakeClient, Clock]:
    client, clock = FakeClient(answer), Clock()
    return DockerBoundary("/usr/bin/docker", runner=client, clock=clock, sleep=clock.sleep), client, clock


def inspect_document() -> dict[str, Any]:
    return {
        "Id": CID, "Image": IMAGE, "Name": "/repomap-rust-pilot-0123456789ab-000007",
        "State": {"Running": True}, "Mounts": [],
        "HostConfig": {"ReadonlyRootfs": True, "NetworkMode": "none", "CapDrop": ["ALL"], "CapAdd": None,
                       "SecurityOpt": ["no-new-privileges=true"], "Privileged": False, "PidsLimit": 32,
                       "Memory": 536870912, "MemorySwap": 536870912, "AutoRemove": True,
                       "Tmpfs": {"/opt/repomap-rust": "rw,exec,nosuid,nodev,size=16m,mode=0755,uid=0,gid=0",
                                 "/scratch": "rw,noexec,nosuid,nodev,size=4m,mode=0700,uid=10001,gid=10001"},
                       "Binds": None, "Mounts": None, "VolumesFrom": None, "Devices": [], "PidMode": "",
                       "IpcMode": "none", "UTSMode": ""},
        "Config": {"User": "10001:10001", "Entrypoint": ["/usr/local/bin/python3.13"],
                   "Labels": {"org.repomap.rust-pilot.run": RUN, "org.repomap.rust-pilot.seq": "7",
                              "org.opencontainers.image.title": "sdk"}},
    }


def test_create_vector_is_exactly_the_specified_argument_list() -> None:
    assert create_arguments(run_id=RUN, seq=7, docker_arch="arm64", image_id=IMAGE) == [
        "create", "--rm", "--name", "repomap-rust-pilot-0123456789ab-000007",
        "--label", f"org.repomap.rust-pilot.run={RUN}", "--label", "org.repomap.rust-pilot.seq=7",
        "--platform", "linux/arm64", "--pull", "never", "--network", "none", "--ipc", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true", "--pids-limit", "32",
        "--memory", "512m", "--memory-swap", "512m", "--ulimit", "core=0", "--ulimit", "nofile=64:64",
        "--user", "10001:10001", "--workdir", "/scratch", "--env", "LC_ALL=C.UTF-8", "--log-driver", "none",
        "--stop-timeout", "1",
        "--tmpfs", "/opt/repomap-rust:rw,exec,nosuid,nodev,size=16m,mode=0755,uid=0,gid=0",
        "--tmpfs", "/scratch:rw,noexec,nosuid,nodev,size=4m,mode=0700,uid=10001,gid=10001",
        "--entrypoint", "/usr/local/bin/python3.13", IMAGE, "-I", "-S", "-B", "-c", "import time; time.sleep(75)"]
    bad_arguments: tuple[dict[str, Any], ...] = (
        {"image_id": "busybox:latest"}, {"docker_arch": "riscv64"}, {"run_id": "rp1.XYZ"},
    )
    base_arguments: dict[str, Any] = {
        "run_id": RUN, "seq": 1, "docker_arch": "amd64", "image_id": IMAGE,
    }
    for bad in bad_arguments:
        with pytest.raises(DockerRefused):
            create_arguments(**{**base_arguments, **bad})
    with pytest.raises(DockerRefused):
        container_name(RUN, 1_000_000)


def test_exec_vectors_fix_principal_and_stdin_attachment() -> None:
    assert exec_arguments(CID, user="0:0", tail=["-c", "x"], interactive=True, workdir="/") == [
        "exec", "-i", "-u", "0:0", "-w", "/", CID, "/usr/local/bin/python3.13", "-c", "x"]
    assert exec_arguments(CID, user="10001:10001", tail=[], interactive=False, workdir=None)[:3] == [
        "exec", "-u", "10001:10001"]
    for user in ("root", "1000:1000", "0"):
        with pytest.raises(DockerRefused):
            exec_arguments(CID, user=user, tail=[], interactive=False, workdir=None)


@pytest.mark.parametrize("args", [["build", "."], ["pull", IMAGE], ["commit", CID], ["volume", "create"],
                                  ["image", "rm", IMAGE], ["system", "prune"], ["run", IMAGE], ["cp", "a", "b"]])
def test_commands_outside_the_closed_vocabulary_never_run(args: list[str]) -> None:
    docker, client, _ = boundary(lambda call: result())
    with pytest.raises(DockerRefused, match="command_refused"):
        docker.run(args)
    assert client.calls == [] and docker.journal == []


def test_client_must_be_an_explicit_absolute_path() -> None:
    for path in ("docker", "", "relative/docker", "/usr/bin/\x00docker"):
        with pytest.raises(DockerRefused, match="invalid_client_path"):
            DockerBoundary(path)


def test_server_and_image_inspection_are_strict() -> None:
    image = [{"Id": IMAGE, "Os": "linux", "Architecture": "arm64", "Config": {"Volumes": None}}]
    docker, _, _ = boundary(lambda call: result(0, json.dumps(
        {"Os": "linux", "Arch": "arm64"} if call[0] == "version" else image).encode()))
    assert (docker.server().os, docker.server().arch) == ("linux", "arm64")
    docker.check_image(IMAGE, "arm64")
    with pytest.raises(DockerRefused, match="image_mismatch"):
        docker.check_image(IMAGE, "amd64")
    image[0]["Config"] = {"Volumes": {"/data": {}}}
    with pytest.raises(DockerRefused, match="image_mismatch"):
        docker.check_image(IMAGE, "arm64")


MUTATIONS: list[Callable[[dict[str, Any]], None]] = [
    lambda d: d.update(Image="sha256:" + "b" * 64), lambda d: d["State"].update(Running=False),
    lambda d: d["HostConfig"].update(ReadonlyRootfs=False), lambda d: d["HostConfig"].update(NetworkMode="bridge"),
    lambda d: d["HostConfig"].update(CapAdd=["NET_RAW"]), lambda d: d["HostConfig"].update(CapDrop=[]),
    lambda d: d["HostConfig"].update(SecurityOpt=[]), lambda d: d["HostConfig"].update(Privileged=True),
    lambda d: d["HostConfig"].update(PidsLimit=0), lambda d: d["HostConfig"].update(MemorySwap=-1),
    lambda d: d["HostConfig"]["Tmpfs"].update({"/tmp": ""}), lambda d: d["HostConfig"].update(Binds=["/:/host"]),
    lambda d: d.update(Mounts=[{"Type": "volume"}]), lambda d: d["HostConfig"].update(PidMode="host"),
    lambda d: d["Config"].update(User="0:0"), lambda d: d["Config"]["Labels"].update(
        {"org.repomap.rust-pilot.extra": "1"}), lambda d: d["HostConfig"].update(AutoRemove=False),
    lambda d: d["HostConfig"].update(Devices=[{"PathOnHost": "/dev/kvm"}]),
]


@pytest.mark.parametrize("mutate", MUTATIONS)
def test_every_inspected_container_setting_is_required(mutate: Callable[[dict[str, Any]], None]) -> None:
    document = inspect_document()
    check_container_config(document, container_id=CID, image_id=IMAGE, run_id=RUN, seq=7)
    changed = copy.deepcopy(document)
    mutate(changed)
    with pytest.raises(DockerRefused, match="container_config_mismatch"):
        check_container_config(changed, container_id=CID, image_id=IMAGE, run_id=RUN, seq=7)


def test_advisory_removal_failure_still_settles_on_observed_absence() -> None:
    answers = {"kill": result(1), "rm": result(1), "container": result(0, b"")}
    docker, client, _ = boundary(lambda call: answers[call[0]])
    assert docker.settle(CID) is True
    assert [call[0] for call in client.calls] == ["kill", "rm", "container"]
    assert client.calls[-1] == ["container", "ls", "-a", "--no-trunc", "--filter", f"id={CID}", "-q"]


@pytest.mark.parametrize("absence", [result(1), result(0, CID.encode() + b"\n"), result(0, b"d" * 64 + b"\n"),
                                     result(0, b"", timed_out=True)])
def test_failed_query_or_remaining_id_never_proves_absence(absence: ExecResult) -> None:
    docker, client, clock = boundary(lambda call: absence if call[0] == "container" else result())
    assert docker.settle(CID) is False
    assert clock.now <= 15.0 and len([c for c in client.calls if c[0] == "container"]) >= 50


def test_residue_snapshot_and_journal_attribution() -> None:
    answers = {"image": result(0, b"sha256:1\nsha256:2\n"), "volume": result(0, b""), "container": result(0, b"")}
    docker, client, _ = boundary(lambda call: answers[call[0]])
    snapshot = docker.snapshot(RUN)
    assert snapshot.images == {"sha256:1", "sha256:2"} and not snapshot.volumes and not snapshot.labelled
    assert client.calls[-1][-1] == f"label=org.repomap.rust-pilot.run={RUN}"
    answers["volume"] = result(1)
    with pytest.raises(DockerRefused, match="snapshot_unavailable"):
        docker.snapshot(RUN)
    assert journal_violations(docker.journal) == ()
    assert journal_violations([("create", "-v", "/:/host"), ("build", ".")]) == ("create -v", "build .")
