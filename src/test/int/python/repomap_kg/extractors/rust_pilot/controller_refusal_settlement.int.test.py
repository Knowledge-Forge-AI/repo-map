"""Connected T1 controller refusal and proven settlement; no native artifacts."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Sequence

import pytest

from common_lore_index.canonicalization.rust_pilot_family import canonicalize_rust_pilot
from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.contracts.witness import REQUIRED_BINDINGS
from common_lore_index.extractors.rust_pilot import controller as controller_module
from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult
from common_lore_index.extractors.rust_pilot.controller import RustPilotController
from common_lore_index.extractors.rust_pilot.docker_boundary import DockerBoundary
from common_lore_index.graph.discovery_records import FileInfo
from repomap_test_support.rust_pilot_fake_docker import FakeDockerBridge, IMAGE, _Container
from repomap_test_support.rust_pilot_semantic_fixtures import prepare_synthetic_profile


def _result(*, code: int | None = 0, stdout: bytes = b"", timeout: bool = False) -> ExecResult:
    return ExecResult(code, stdout, False, 0, "0" * 64, False, timeout, True, 0.0)


class _FactsBridge(FakeDockerBridge):
    """Only alter the named synthetic daemon/image fact or settlement readback."""

    def __init__(self, root: Path, *, server: dict[str, str] | None = None,
                 image_arch: str = "arm64", image_id: str = IMAGE,
                 fault: str | None = None, unproven_absence: bool = False) -> None:
        super().__init__(root)
        self.server, self.image_arch, self.image_id = server, image_arch, image_id
        self.fault, self.unproven_absence = fault, unproven_absence

    def run(self, args: Sequence[str], *, stdin: bytes = b"", stdout_limit: int = 1_048_576,
            deadline: float = 20.0, kill_id: str | None = None,
            hard_end: float | None = None) -> ExecResult:
        result = super().run(args, stdin=stdin, stdout_limit=stdout_limit,
                             deadline=deadline, kill_id=kill_id, hard_end=hard_end)
        if args == ["version", "--format", "{{json .Server}}"] and self.server is not None:
            return replace(result, stdout=json.dumps(self.server).encode("ascii"))
        if args == ["image", "inspect", IMAGE] and (self.image_arch != "arm64" or self.image_id != IMAGE):
            payload = [{"Id": self.image_id, "Os": "linux", "Architecture": self.image_arch,
                        "Config": {}}]
            return replace(result, stdout=json.dumps(payload).encode("ascii"))
        if self.unproven_absence and args[:3] == ["container", "ls", "-a"]:
            selector = args[5]
            return replace(result, stdout=(selector[3:] + "\n").encode("ascii"))
        return result

    def _guest(self, item: _Container, user: str, workdir: str | None, tail: tuple[str, ...],
               stdin: bytes, stdout_limit: int, deadline: float,
               hard_end: float | None) -> ExecResult:
        operation = None
        if user == "0:0" and workdir == "/":
            operation = "setup"
        elif workdir is None and any("Install readback" in value for value in tail):
            operation = "readback"
        elif workdir is None and any("Run-level runtime probe" in value for value in tail):
            operation = "probe"
        elif workdir == "/scratch" and item.seq > 0:
            operation = "parse"
        if operation == "parse" and self.fault == "parse-timeout":
            return _result(code=None, timeout=True)
        if operation == "parse" and self.fault == "parse-invalid":
            return _result(stdout=b"invalid-frame")
        if operation is not None and operation == self.fault:
            if operation == "parse":
                return _result(code=1, stdout=b"not-a-frame")
            return _result(code=1)
        return super()._guest(item, user, workdir, tail, stdin, stdout_limit, deadline, hard_end)


def _repo(tmp_path: Path, *, data: bytes = b"pub mod nested { pub fn f() {} }\n",
          path: str = "src/lib.rs", content_hash: str | None = None) -> tuple[Path, FileInfo]:
    root = tmp_path / "repository"
    (root / "src").mkdir(parents=True)
    (root / path).write_bytes(data)
    return root, FileInfo(path, "unknown", "source", content_hash or hashlib.sha256(data).hexdigest(), False, False)


def _controller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, bridge: _FactsBridge,
                platform: str = "linux/arm64", image_id: str = IMAGE) -> RustPilotController:
    profile = prepare_synthetic_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(
        controller_module, "_new_boundary",
        lambda docker_cli: DockerBoundary(docker_cli, runner=bridge.as_runner()),
    )
    return RustPilotController(
        docker_cli="/usr/bin/docker", sdk_image_id=image_id, profile_dir=profile,
        platform=platform,
    )


def _assert_no_rust_claim(run: RustPilotController, info: FileInfo) -> None:
    witness = canonicalize_rust_pilot(run, (info.to_observation(),), repository_scope="synthetic")
    assert witness.verify_live()
    assert not any(item.kind.startswith("rust.") for item in witness.observations)
    assert not any(node.kind.startswith("rust.") for node in witness.result.graph.nodes)
    assert not any("rust." in edge.source_key or "rust." in edge.target_key
                   for edge in witness.result.graph.edges)
    admission = run.admit(info.path)
    assert not admission.admitted
    assert admission.refused_bindings
    assert set(admission.refused_bindings) <= set(REQUIRED_BINDINGS)


@pytest.mark.parametrize(
    ("platform", "server", "image_arch", "image_id", "expected", "calls"),
    [
        ("linux/amd64", None, "arm64", IMAGE, "dependency_unavailable", ()),
        ("linux/arm64", {"Os": "windows", "Arch": "arm64"}, "arm64", IMAGE,
         "dependency_unavailable", ("version",)),
        ("linux/arm64", {"Os": "linux", "Arch": "amd64"}, "arm64", IMAGE,
         "dependency_unavailable", ("version",)),
        ("linux/arm64", None, "arm64", "sha256:" + "b" * 64, "inadmissible", ("version", "image inspect")),
    ],
)
def test_native_fact_mismatch_refuses_before_rust_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, server: dict[str, str] | None,
    image_arch: str, image_id: str, expected: str, calls: tuple[str, ...],
) -> None:
    bridge = _FactsBridge(tmp_path / "fake-docker", server=server, image_arch=image_arch, image_id=image_id)
    root, info = _repo(tmp_path)
    with _controller(tmp_path, monkeypatch, bridge=bridge, platform=platform, image_id=IMAGE) as run:
        summary = run.process(root, (info,))
        assert (summary.run_outcome, summary.refusal) == (expected, "dependency_unavailable" if expected == "dependency_unavailable" else "inadmissible_effects")
        assert not run.verify_live()
    verbs = tuple(call[0] if call[0] not in {"image", "container"} else " ".join(call[:2]) for call in bridge.calls)
    assert verbs == calls
    assert all(item.removed for item in bridge._containers.values())


@pytest.mark.parametrize(
    ("fault", "expected_outcome", "expected_file_outcome"),
    [("setup", "inadmissible", "inadmissible"), ("readback", "inadmissible", "inadmissible"),
     ("probe", "inadmissible", "inadmissible")],
)
def test_setup_readback_and_probe_refusals_settle_before_any_source_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
    expected_outcome: str, expected_file_outcome: str,
) -> None:
    bridge = _FactsBridge(tmp_path / "fake-docker", fault=fault)
    root, info = _repo(tmp_path)
    with _controller(tmp_path, monkeypatch, bridge=bridge) as run:
        summary = run.process(root, (info,))
        assert summary.run_outcome == expected_outcome
        audit = run.audit_snapshot()
        assert audit["files"][0]["outcome"] == expected_file_outcome
        assert audit["files"][0]["cleanup"] == "proven"
        assert audit["counters"]["containers"]["value"] == 1
        assert not run.verify_live()
    assert all(item.removed for item in bridge._containers.values())


@pytest.mark.parametrize(
    ("fault", "outcome"),
    [("parse", "crashed"), ("parse-timeout", "resource_bound_exceeded"), ("parse-invalid", "crashed")],
)
def test_parse_timeout_crash_or_invalid_output_is_a_file_refusal_without_rust_graph_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, outcome: str,
) -> None:
    bridge = _FactsBridge(tmp_path / "fake-docker", fault=fault)
    root, info = _repo(tmp_path)
    with _controller(tmp_path, monkeypatch, bridge=bridge) as run:
        summary = run.process(root, (info,))
        assert summary.run_outcome == "processed"
        row = next(item for item in run.audit_snapshot()["files"] if item["invocation_role"] == "source")
        assert row["outcome"] == outcome
        _assert_no_rust_claim(run, info)
    assert all(item.removed for item in bridge._containers.values())


@pytest.mark.parametrize("case", ["hash", "duplicate", "oversize", "symlink", "nonutf8"])
def test_selection_mismatch_duplicate_bound_and_path_refusals_never_enter_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    infos: tuple[FileInfo, ...]
    expected: tuple[str, ...]
    if case == "hash":
        root, info = _repo(tmp_path, content_hash="0" * 64)
        infos = (info,)
        expected = ("source_changed",)
    elif case == "duplicate":
        root, info = _repo(tmp_path)
        infos = (info, info)
        expected = ("selected", "selection_refused")
    elif case == "oversize":
        data = b"x" * (1_048_576 + 1)
        root, info = _repo(tmp_path, data=data)
        infos = (info,)
        expected = ("resource_bound_exceeded",)
    elif case == "symlink":
        root, info = _repo(tmp_path, path="src/real.rs")
        (root / "src" / "link.rs").symlink_to("real.rs")
        info = FileInfo("src/link.rs", "unknown", "source", "0" * 64, False, False)
        infos, expected = (info,), ("selection_refused",)
    else:
        data = b"pub fn f() {\xff }\n"
        root, info = _repo(tmp_path, data=data)
        infos, expected = (info,), ("input_not_utf8",)
    bridge = _FactsBridge(tmp_path / "fake-docker")
    with _controller(tmp_path, monkeypatch, bridge=bridge) as run:
        summary = run.process(root, infos)
        assert summary.run_outcome == "processed"
        audit = run.audit_snapshot()
        assert audit["counters"]["parses"]["value"] == (2 if case == "duplicate" else 1)
        if case == "duplicate":
            refused = [row for row in audit["files"] if "invocation_role" not in row]
            assert [row["outcome"] for row in refused] == ["selection_refused"]
            assert run.admit(info.path).admitted
        else:
            assert tuple(item[1] for item in summary.file_outcomes) == expected
            _assert_no_rust_claim(run, info)
    assert all(item.removed for item in bridge._containers.values())


def test_unproven_absence_is_categorical_cleanup_refusal_and_no_follow_on_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _FactsBridge(tmp_path / "fake-docker", unproven_absence=True)
    root, info = _repo(tmp_path)
    with pytest.raises(ContractError, match="cleanup_incomplete"):
        with _controller(tmp_path, monkeypatch, bridge=bridge) as run:
            summary = run.process(root, (info,))
            assert (summary.run_outcome, summary.refusal) == ("cleanup_incomplete", "witness_unavailable")
            audit = run.audit_snapshot()
            assert audit["files"][0]["cleanup"] == "incomplete"
            assert audit["counters"]["containers"]["value"] == 1
            assert not run.verify_live()
    assert len([call for call in bridge.calls if call[0] == "create"]) == 1
