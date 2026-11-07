"""Connected T1 fixture: real Controller, real guest IO, and live witness."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Iterator

import pytest

from common_lore_index.canonicalization.main import canonicalize_observations
from common_lore_index.canonicalization.records import CanonicalizationResult
from common_lore_index.canonicalization.rust_pilot_family import (
    WitnessedCanonicalization,
    canonicalize_rust_pilot,
)
from common_lore_index.extractors.rust_pilot import controller as controller_module
from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult
from common_lore_index.extractors.rust_pilot.controller import RustPilotController
from common_lore_index.extractors.rust_pilot.docker_boundary import DockerBoundary
from common_lore_index.extractors.rust_pilot import prepared_profile
from common_lore_index.extractors.rust_pilot.component_lock import WheelLock
from common_lore_index.graph.discovery import extract_observations_from_repository_files
from common_lore_index.graph.discovery_records import FileInfo
from common_lore_index.observations.raw import RawObservation
from repomap_test_support.rust_pilot_fake_docker import FakeDockerBridge, IMAGE
from repomap_test_support.rust_pilot_fake_tree_sitter.wheels import stand_in_wheels


@dataclass
class LivePilot:
    root: Path
    infos: tuple[FileInfo, ...]
    legacy_observations: tuple[RawObservation, ...]
    legacy_result: CanonicalizationResult
    controller: RustPilotController
    witnessed: WitnessedCanonicalization
    boundary: FakeDockerBridge
    profile_dir: Path


def prepare_synthetic_profile(base: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Use real profile/archive verification with public synthetic wheel bytes."""

    source = base / "wheel-source"
    source.mkdir(mode=0o700)
    wheels = stand_in_wheels()
    locks = tuple(wheel.lock for wheel in wheels)
    def synthetic_wheels(_cpu: str) -> tuple[WheelLock, ...]:
        return locks

    monkeypatch.setattr(prepared_profile, "wheels_for_cpu", synthetic_wheels, raising=True)
    for wheel in wheels:
        wheel_path = source / wheel.lock.filename
        wheel_path.write_bytes(wheel.data)
        wheel_path.chmod(0o600)
    profile = base / "profile"
    prepared_profile.prepare_profile(source, profile, "aarch64")
    assert prepared_profile.load_profile(profile, server_cpu="aarch64").cpu == "aarch64"
    return profile


@contextmanager
def live_pilot(base: Path, monkeypatch: pytest.MonkeyPatch,
               guest_executor: Callable[..., ExecResult] | None = None) -> Iterator[LivePilot]:
    base.mkdir(parents=True, exist_ok=True)
    root = base / "repository"
    root.mkdir()
    data = b"pub mod nested { pub fn f() {} }\n"
    (root / "src").mkdir()
    (root / "src" / "lib.rs").write_bytes(data)
    info = FileInfo("src/lib.rs", "unknown", "source", hashlib.sha256(data).hexdigest(), False, False)
    profile = prepare_synthetic_profile(base, monkeypatch)
    boundary = FakeDockerBridge(base / "fake-docker", guest_executor=guest_executor)
    def make_boundary(docker_cli: str) -> DockerBoundary:
        return DockerBoundary(docker_cli, runner=boundary.as_runner())

    monkeypatch.setattr(controller_module, "_new_boundary", make_boundary, raising=True)
    controller = RustPilotController(
        docker_cli="/usr/bin/docker", sdk_image_id=IMAGE, profile_dir=profile,
        platform="linux/arm64", audit_dir=None,
    )
    summary = controller.process(root, (info,))
    assert summary.run_outcome == "processed", summary
    assert controller.verify_live()
    legacy = tuple(extract_observations_from_repository_files(root, (info,)))
    legacy_result = canonicalize_observations(legacy, repository_scope="synthetic")
    witnessed = canonicalize_rust_pilot(controller, legacy, repository_scope="synthetic")
    try:
        yield LivePilot(root, (info,), legacy, legacy_result, controller, witnessed, boundary, profile)
    finally:
        controller.close()


__all__ = ("LivePilot", "live_pilot", "prepare_synthetic_profile")
