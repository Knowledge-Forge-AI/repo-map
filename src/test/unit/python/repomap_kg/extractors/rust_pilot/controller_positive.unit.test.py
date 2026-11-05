"""Positive T1 Controller path through the private boundary seam."""

from __future__ import annotations

from pathlib import Path
import hashlib
import time
from typing import Any, NoReturn

from common_lore_index.extractors.rust_pilot import controller as controller_module, construction
from common_lore_index.extractors.rust_pilot.controller import RustPilotController
from common_lore_index.extractors.rust_pilot.docker_boundary import DockerBoundary, ResidueSnapshot
from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.graph.discovery_records import FileInfo
from repomap_test_support.rust_pilot_fake_docker import FakeDockerBridge, IMAGE
from repomap_test_support.rust_pilot_semantic_fixtures import prepare_synthetic_profile

import pytest

from repomap_test_support.rust_pilot_semantic_fixtures import live_pilot


def test_controller_processes_probe_and_file_through_real_guest_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with live_pilot(tmp_path, monkeypatch) as live:
        assert live.controller.verify_live()
        assert live.controller.selected_paths() == ("src/lib.rs",)
        assert live.controller.admit("src/lib.rs").admitted
        assert [
            item.metadata["language"] for item in live.legacy_observations
            if item.kind == "file" and item.path == "src/lib.rs"
        ] == ["unknown"]
        assert any(call[0] == "exec" for call in live.boundary.calls)
        creates = [call for call in live.boundary.calls if call[0] == "create"]
        assert creates and all("--pull" in call and call[call.index("--pull") + 1] == "never" for call in creates)
        assert all("--network" in call and call[call.index("--network") + 1] == "none" for call in creates)
        assert all("prune" not in call and "build" not in call for call in live.boundary.calls)


def _direct_controller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, FileInfo, RustPilotController]:
    root = tmp_path / "repository"
    root.mkdir()
    data = b"pub fn f() {}\n"
    (root / "lib.rs").write_bytes(data)
    info = FileInfo("lib.rs", "unknown", "source", hashlib.sha256(data).hexdigest(), False, False)
    profile = prepare_synthetic_profile(tmp_path, monkeypatch)
    bridge = FakeDockerBridge(tmp_path / "fake-docker")
    monkeypatch.setattr(controller_module, "_new_boundary",
                        lambda docker_cli: DockerBoundary(docker_cli, runner=bridge.as_runner()))
    run = RustPilotController(docker_cli="/usr/bin/docker", sdk_image_id=IMAGE,
                              profile_dir=profile, platform="linux/arm64")
    return root, info, run


def test_runtime_probe_refusal_is_inadmissible_without_inventing_a_crash(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, info, run = _direct_controller(tmp_path, monkeypatch)
    def refuse(*_args: object) -> NoReturn:
        raise ContractError("runtime_mismatch")
    monkeypatch.setattr(construction, "run_runtime_probe", refuse)
    with run:
        assert run.process(root, (info,)).run_outcome == "inadmissible"
        row = run.audit_snapshot()["files"][0]
        assert row["outcome"] == "inadmissible" and row["cleanup"] == "proven"
        assert not run.verify_live() and not run.admit("lib.rs").admitted


def test_settlement_cost_includes_cost_and_liveness_observation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, info, run = _direct_controller(tmp_path, monkeypatch)
    offset = [0.0]
    run._clock = lambda: time.monotonic() + offset[0]
    original_state = construction.container_state
    def cost(*_args: object, **_kwargs: object) -> tuple[int | None, str | None]:
        offset[0] += 2.0
        return None, "cgroup_peak_unavailable"
    def state(*args: Any, **kwargs: Any) -> tuple[bool, bool]:
        value = original_state(*args, **kwargs)
        offset[0] += 3.0
        return value
    monkeypatch.setattr(construction, "resource_facts", cost)
    monkeypatch.setattr(construction, "container_state", state)
    with run:
        assert run.process(root, (info,)).run_outcome == "processed"
        rows = run.audit_snapshot()["files"]
        assert len(rows) == 2
        assert all(row["cost"]["settlement_ms"] >= 5000 for row in rows)


@pytest.mark.parametrize("expire_after", [1, 2])
@pytest.mark.parametrize("residue_unavailable", [False, True])
def test_shared_work_expiry_between_containers_prevents_next_create(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expire_after: int, residue_unavailable: bool) -> None:
    root, info, run = _direct_controller(tmp_path, monkeypatch)
    other = b"pub fn other() {}\n"
    (root / "other.rs").write_bytes(other)
    other_info = FileInfo("other.rs", "unknown", "source", hashlib.sha256(other).hexdigest(), False, False)
    original = run._boundary.settle
    settled: list[str] = []
    def expire_after_settlement(container_id: str) -> bool:
        proven = original(container_id)
        settled.append(container_id)
        if len(settled) == expire_after:
            run._boundary.limit_work_deadline(time.monotonic() - 1.0)
        return proven
    monkeypatch.setattr(run._boundary, "settle", expire_after_settlement)
    original_snapshot = run._boundary.snapshot
    def snapshot(run_id: str) -> ResidueSnapshot:
        if residue_unavailable and len(settled) >= expire_after:
            raise ContractError("snapshot_unavailable")
        return original_snapshot(run_id)
    monkeypatch.setattr(run._boundary, "snapshot", snapshot)
    with pytest.raises(ContractError, match="internal_deadline_exceeded") as refused, run:
        run.process(root, (info, other_info))
    audit = run.audit_snapshot()
    assert audit["counters"]["containers"]["value"] == expire_after
    if residue_unavailable:
        assert audit["residue"] == {"observed": False}
        assert isinstance(refused.value.__cause__, ContractError)
        assert refused.value.__cause__.code == "cleanup_incomplete"
    else:
        assert audit["residue"]["owned_containers_remaining"] == 0
    assert len(audit["files"]) == expire_after  # No later refusal rows.
    assert not run.admit("other.rs").admitted
    assert len(settled) == expire_after
