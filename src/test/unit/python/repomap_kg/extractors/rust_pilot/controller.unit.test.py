"""Controller run-level refusals, settlement halts and inert results (spec 3, 5, 8, 10; Q07, Q09, Q11).

Docker is an injected fake command runner. A positive admission is not
reachable here by design: it needs a verified readback and guest-observed
confinement that only a real container supplies (native gate).
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
import json
import os
import pickle
from unittest.mock import patch
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from common_lore_index.extractors.contracts.receipt_codec import decode_receipt
from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.contracts.witness import REQUIRED_BINDINGS
from common_lore_index.extractors.rust_pilot import controller as controller_module
from common_lore_index.extractors.rust_pilot.archive_verifier import verify_wheel
from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult
from common_lore_index.extractors.rust_pilot.controller import RustPilotController
from common_lore_index.extractors.rust_pilot.docker_boundary import DockerBoundary
from common_lore_index.extractors.rust_pilot.prepared_profile import VerifiedProfile, profile_bytes
from common_lore_index.graph.discovery_records import FileInfo
from repomap_test_support.rust_pilot_fake_tree_sitter.wheels import synthetic_wheel

IMAGE = "sha256:" + "a" * 64
CID = "c" * 64


def ok(out: bytes = b"", code: int = 0) -> ExecResult:
    return ExecResult(code, out, False, 0, "0" * 64, False, False, True, 0.0)


class FakeDocker:
    def __init__(self, *, server: dict[str, str] | None = None, arch: str = "arm64",
                 setup_code: int = 2, absent: bool = True) -> None:
        self.server = server or {"Os": "linux", "Arch": "arm64"}
        self.arch, self.setup_code, self.absent = arch, setup_code, absent
        self.calls: list[list[str]] = []
        self.run_id = ""

    def __call__(self, argv: Sequence[str], stdin: bytes, limit: int, deadline: float,
                 on_deadline: Callable[[float], None] | None, *, hard_end: float | None = None) -> ExecResult:
        args = list(argv[1:])
        self.calls.append(args)
        verb = args[0]
        if verb == "version":
            return ok(json.dumps(self.server).encode())
        if args[:2] == ["image", "inspect"]:
            return ok(json.dumps([{"Id": IMAGE, "Os": "linux", "Architecture": self.arch, "Config": {}}]).encode())
        if verb == "create":
            self.run_id = args[args.index("--label") + 1].split("=", 1)[1]
            return ok(CID.encode() + b"\n")
        if args[:2] == ["container", "inspect"]:
            return ok(json.dumps([self._inspect()]).encode())
        if verb == "exec":
            return ok(b"", self.setup_code)
        if args[:2] == ["container", "ls"] and "--filter" in args and args[-1] == "-q" and "id=" in args[-2]:
            return ok(b"" if self.absent else CID.encode() + b"\n")
        return ok()

    def _inspect(self) -> dict[str, object]:
        return {"Id": CID, "Image": IMAGE, "Name": f"/repomap-rust-pilot-{self.run_id[4:16]}-000000",
                "State": {"Running": True}, "Mounts": [],
                "HostConfig": {"ReadonlyRootfs": True, "NetworkMode": "none", "CapDrop": ["ALL"],
                               "SecurityOpt": ["no-new-privileges=true"], "Privileged": False, "PidsLimit": 32,
                               "Memory": 536870912, "MemorySwap": 536870912, "AutoRemove": True,
                               "Tmpfs": {"/opt/repomap-rust": "rw,exec,nosuid,nodev,size=16m,mode=0755,uid=0,gid=0",
                                         "/scratch": "rw,noexec,nosuid,nodev,size=4m,mode=0700,uid=10001,gid=10001"},
                               "IpcMode": "none"},
                "Config": {"User": "10001:10001", "Entrypoint": ["/usr/local/bin/python3.13"],
                           "Labels": {"org.repomap.rust-pilot.run": self.run_id, "org.repomap.rust-pilot.seq": "0"}}}

    def verbs(self) -> list[str]:
        return [" ".join(call[:2]) if call[0] in ("image", "container", "volume") else call[0] for call in self.calls]


@pytest.fixture
def synthetic_profile(monkeypatch: pytest.MonkeyPatch) -> VerifiedProfile:
    alpha = synthetic_wheel("alpha", {"alpha/__init__.py": b"A"})
    beta = synthetic_wheel("beta", {"beta/__init__.py": b"B"})
    document = profile_bytes("aarch64")
    profile = VerifiedProfile("aarch64", hashlib.sha256(document).hexdigest(), document,
                              (verify_wheel(alpha.data, alpha.lock), verify_wheel(beta.data, beta.lock)))
    monkeypatch.setattr(controller_module, "load_profile", lambda _path: profile)
    return profile


def _repo(tmp_path: Path) -> tuple[Path, list[FileInfo]]:
    root = tmp_path / "repo"
    root.mkdir()
    data = b"pub fn f() {}\n"
    (root / "lib.rs").write_bytes(data)
    return root, [FileInfo("lib.rs", "unknown", "source", hashlib.sha256(data).hexdigest(), False, False)]


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _controller(tmp_path: Path, docker: FakeDocker, platform: str = "linux/arm64") -> RustPilotController:
    audit = tmp_path / "audit"
    audit.mkdir(mode=0o700)
    clock = Clock()
    boundary = DockerBoundary("/usr/bin/docker", runner=docker, clock=clock, sleep=clock.sleep)
    with patch.object(controller_module, "_new_boundary", return_value=boundary):
        run = RustPilotController(docker_cli="/usr/bin/docker", sdk_image_id=IMAGE,
                                  profile_dir=tmp_path / "profile", platform=platform, audit_dir=audit)
    run._clock = clock
    return run


def _receipts(tmp_path: Path) -> list[dict[str, object]]:
    names = sorted(os.listdir(tmp_path / "audit"))
    return [decode_receipt((tmp_path / "audit" / name).read_bytes()).to_dict() for name in names
            if name.startswith("receipt-")]


def test_missing_profile_is_one_unavailable_outcome_with_no_docker_command(tmp_path: Path) -> None:
    docker = FakeDocker()
    root, infos = _repo(tmp_path)
    with _controller(tmp_path, docker) as run:
        summary = run.process(root, infos)
        assert (summary.run_outcome, summary.refusal) == ("dependency_unavailable", "dependency_unavailable")
        assert run.admit("lib.rs").refused_bindings == REQUIRED_BINDINGS and not run.verify_live()
    assert docker.calls == []
    receipts = _receipts(tmp_path)
    assert [(r["state"], r["refusal"]) for r in receipts] == [("unavailable", "dependency_unavailable")]
    assert sum(name.startswith("run-report-") for name in os.listdir(tmp_path / "audit")) == 1


@pytest.mark.parametrize(("platform", "server", "calls"), [
    ("linux/amd64", {"Os": "linux", "Arch": "arm64"}, []),
    ("linux/arm64", {"Os": "linux", "Arch": "amd64"}, ["version"]),
    ("linux/arm64", {"Os": "windows", "Arch": "arm64"}, ["version"]),
])
def test_wrong_platform_refuses_before_any_container(tmp_path: Path, synthetic_profile: VerifiedProfile,
                                                     platform: str, server: dict[str, str], calls: list[str]) -> None:
    docker = FakeDocker(server=server)
    root, infos = _repo(tmp_path)
    with _controller(tmp_path, docker, platform) as run:
        assert run.process(root, infos).run_outcome == "dependency_unavailable"
    assert docker.verbs() == calls


def test_image_mismatch_is_inadmissible_without_creating_anything(tmp_path: Path,
                                                                  synthetic_profile: VerifiedProfile) -> None:
    docker = FakeDocker(arch="amd64")
    root, infos = _repo(tmp_path)
    with _controller(tmp_path, docker) as run:
        assert run.process(root, infos).run_outcome == "inadmissible"
    assert "create" not in docker.verbs()


def test_failed_probe_construction_settles_and_refuses_the_whole_run(tmp_path: Path,
                                                                     synthetic_profile: VerifiedProfile) -> None:
    docker = FakeDocker(setup_code=2)
    root, infos = _repo(tmp_path)
    with _controller(tmp_path, docker) as run:
        summary = run.process(root, infos)
        assert summary.run_outcome == "inadmissible" and not run.verify_live()
        assert run.admit("lib.rs").refused_bindings == REQUIRED_BINDINGS
    verbs = docker.verbs()
    assert verbs.count("create") == 1 and verbs.index("kill") > verbs.index("exec")
    exec_call = next(call for call in docker.calls if call[0] == "exec")
    assert exec_call[:6] == ["exec", "-i", "-u", "0:0", "-w", "/"] and "lib.rs" not in " ".join(exec_call)
    assert [r["refusal"] for r in _receipts(tmp_path)] == ["inadmissible_effects", "inadmissible_effects"]


def test_unproven_absence_halts_the_run_and_no_further_container_is_created(
        tmp_path: Path, synthetic_profile: VerifiedProfile) -> None:
    docker = FakeDocker(absent=False)
    root, infos = _repo(tmp_path)
    with pytest.raises(ContractError, match="cleanup_incomplete"), _controller(tmp_path, docker) as run:
        summary = run.process(root, infos)
        assert (summary.run_outcome, summary.refusal) == ("cleanup_incomplete", "witness_unavailable")
        assert not run.verify_live()
    assert docker.verbs().count("create") == 1
    assert "prune" not in " ".join(" ".join(call) for call in docker.calls)


def test_runs_process_once_reject_unknown_platforms_and_cannot_be_pickled(tmp_path: Path) -> None:
    docker = FakeDocker()
    root, infos = _repo(tmp_path)
    run = _controller(tmp_path, docker)
    run.process(root, infos)
    with pytest.raises(ContractError, match="run_not_processable"):
        run.process(root, infos)
    with pytest.raises(ContractError):
        pickle.dumps(run)
    run.close()
    assert run.selected_paths() == ()
    with pytest.raises(ContractError, match="unsupported_platform"):
        RustPilotController(docker_cli="/usr/bin/docker", sdk_image_id=IMAGE, profile_dir=tmp_path,
                            platform="windows/amd64")
    assert run.run_id.startswith("rp1.") and len(run.run_id) == 20


@pytest.mark.parametrize(("stdout", "timeout", "code"), [(b"", False, 0), (b"invalid", False, 1), (b"", True, None)])
def test_unidentified_create_never_proves_absence_and_halts(
        tmp_path: Path, synthetic_profile: VerifiedProfile, stdout: bytes,
        timeout: bool, code: int | None) -> None:
    class UnidentifiedCreate(FakeDocker):
        def __call__(self, argv: Sequence[str], stdin: bytes, limit: int, deadline: float,
                     on_deadline: Callable[[float], None] | None, *, hard_end: float | None = None) -> ExecResult:
            result = super().__call__(argv, stdin, limit, deadline, on_deadline, hard_end=hard_end)
            if argv[1] == "create":
                return replace(result, stdout=stdout, timed_out=timeout, returncode=code)
            return result
    docker = UnidentifiedCreate()
    root, infos = _repo(tmp_path)
    with pytest.raises(ContractError, match="cleanup_incomplete"), _controller(tmp_path, docker) as run:
        summary = run.process(root, infos)
        assert (summary.run_outcome, summary.refusal) == ("cleanup_incomplete", "witness_unavailable")
        audit = run.audit_snapshot()
        assert audit["files"][0]["cleanup"] == "incomplete"
        assert not run.verify_live()
    assert docker.verbs().count("create") == 1
    assert not {"start", "exec", "kill", "rm"} & set(docker.verbs())
    for receipt in _receipts(tmp_path):
        observed = receipt["observed"]
        assert isinstance(observed, dict)
        assert observed["cleanup"] == "incomplete"


@pytest.mark.parametrize("exists", [False, True])
def test_unavailable_client_retains_one_refusal_and_run_report(
        tmp_path: Path, synthetic_profile: VerifiedProfile, exists: bool) -> None:
    client = tmp_path / "nonexecuting-client"
    if exists:
        client.write_bytes(b"inert fixture, never executable")
        client.chmod(0o600)
    root, infos = _repo(tmp_path)
    audit = tmp_path / "audit"
    audit.mkdir(mode=0o700)
    with RustPilotController(docker_cli=str(client), sdk_image_id=IMAGE,
                             profile_dir=tmp_path / "profile", platform="linux/arm64", audit_dir=audit) as run:
        summary = run.process(root, infos)
        assert (summary.run_outcome, summary.refusal) == ("inadmissible", "inadmissible_effects")
        assert not run.verify_live()
        assert run.audit_snapshot()["counters"]["containers"]["value"] == 0
    assert len(_receipts(tmp_path)) == 1
    assert sum(name.startswith("run-report-") for name in os.listdir(audit)) == 1


def test_context_cleanup_failure_preserves_primary_error_and_records_cleanup_cause(
        tmp_path: Path, synthetic_profile: VerifiedProfile) -> None:
    docker = FakeDocker(absent=False)
    root, infos = _repo(tmp_path)
    primary = ContractError("primary_fixture_failure")
    with pytest.raises(ContractError, match="primary_fixture_failure") as raised:
        with _controller(tmp_path, docker) as run:
            assert run.process(root, infos).run_outcome == "cleanup_incomplete"
            raise primary
    assert raised.value is primary and raised.value.__cause__ is not None
    assert isinstance(raised.value.__cause__, ContractError)
    assert raised.value.__cause__.code == "cleanup_incomplete"
    assert "rust_pilot_cleanup_incomplete" in raised.value.__notes__
    assert not run.verify_live()


@pytest.mark.parametrize(("unidentified", "chained"), [(True, False), (True, True), (False, True)])
def test_context_preserves_primary_and_existing_cause_when_absence_is_unproven(
        tmp_path: Path, synthetic_profile: VerifiedProfile, monkeypatch: pytest.MonkeyPatch,
        unidentified: bool, chained: bool) -> None:
    class UnidentifiedCreate(FakeDocker):
        def __call__(self, argv: Sequence[str], stdin: bytes, limit: int, deadline: float,
                     on_deadline: Callable[[float], None] | None, *, hard_end: float | None = None) -> ExecResult:
            result = super().__call__(argv, stdin, limit, deadline, on_deadline, hard_end=hard_end)
            return replace(result, stdout=b"") if argv[1] == "create" else result
    docker = UnidentifiedCreate() if unidentified else FakeDocker(absent=False)
    root, infos = _repo(tmp_path)
    primary, original_cause = ContractError("primary_fixture_failure"), ValueError("synthetic cause")
    with pytest.raises(ContractError, match="primary_fixture_failure") as raised:
        with _controller(tmp_path, docker) as run:
            assert run.process(root, infos).run_outcome == "cleanup_incomplete"
            if not unidentified:
                def broken_settlement(_container_id: str) -> bool:
                    raise RuntimeError("synthetic settlement failure")
                monkeypatch.setattr(run._boundary, "settle", broken_settlement)
            if chained:
                raise primary from original_cause
            raise primary
    assert raised.value is primary and not run.verify_live()
    assert "rust_pilot_cleanup_incomplete" in primary.__notes__
    if chained:
        assert primary.__cause__ is original_cause
    else:
        assert isinstance(primary.__cause__, ContractError)
        assert primary.__cause__.code == "cleanup_incomplete"
