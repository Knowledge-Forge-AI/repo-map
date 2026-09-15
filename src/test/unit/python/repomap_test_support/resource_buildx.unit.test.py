"""TEST-HYGIENE1 dedicated Buildx builder containment contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repomap_test_support.resource_buildx import (
    BuildCacheOwnershipUnproved,
    DedicatedBuildxOwner,
)
from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity


class FakeRunner:
    def __init__(self):
        self.commands = []
        self.created = False

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        if command[:3] == ["docker", "buildx", "create"]:
            self.created = True
            return subprocess.CompletedProcess(command, 0, "builder-name\n", "")
        if command[:3] == ["docker", "buildx", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                0 if self.created else 1,
                "{}" if self.created else "",
                "",
            )
        if command[:3] == ["docker", "buildx", "rm"]:
            self.created = False
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 1, "", "missing")
        return subprocess.CompletedProcess(command, 0, "", "")


def _owner(tmp_path: Path):
    identity = RunIdentity("repo-map_dev", "TEST-HYGIENE1", "run1")
    ledger = ResourceLedger.create(tmp_path / "ledger.json", identity)
    runner = FakeRunner()
    owner = DedicatedBuildxOwner(
        identity,
        ledger,
        buildx_config=tmp_path / "bx",
        runner=runner,
    )
    return owner, ledger, runner


def test_dedicated_builder_is_unique_and_never_selected_as_shared_default(tmp_path):
    owner, _, runner = _owner(tmp_path)

    owner.create()

    create = runner.commands[0]
    assert "--driver" in create
    assert "docker-container" in create
    assert "--use" not in create
    assert "default" not in create
    assert "orbstack" not in create


def test_missing_local_buildkit_image_stops_before_bootstrap_or_build(tmp_path):
    owner, _, runner = _owner(tmp_path)
    owner.create()

    with pytest.raises(
        BuildCacheOwnershipUnproved, match="local_buildkit_image_absent"
    ):
        owner.require_bootstrap_ready()

    flattened = [item for command in runner.commands for item in command]
    assert "--bootstrap" not in flattened
    assert "build" not in flattened


def test_existing_buildkit_image_still_stops_without_label_injection(tmp_path):
    owner, _, runner = _owner(tmp_path)
    owner.create()
    original = runner.__call__

    def local_image(command, **kwargs):
        if command[:3] == ["docker", "image", "inspect"]:
            runner.commands.append(command)
            return subprocess.CompletedProcess(command, 0, "{}", "")
        return original(command, **kwargs)

    owner.runner = local_image

    with pytest.raises(
        BuildCacheOwnershipUnproved, match="builder_label_injection_unavailable"
    ):
        owner.require_bootstrap_ready()


def test_exact_builder_metadata_cleanup_uses_no_broad_prune(tmp_path):
    owner, ledger, runner = _owner(tmp_path)
    owner.create()

    owner.cleanup()

    commands = [" ".join(command) for command in runner.commands]
    assert any(command.startswith("docker buildx rm") for command in commands)
    assert all("prune" not in command for command in commands)
    assert ledger.public_projection()["phase_builders_remaining"] == 0


def test_missing_builder_readback_cannot_be_inferred_from_container_state(tmp_path):
    owner, _, _ = _owner(tmp_path)

    with pytest.raises(RuntimeError, match="not created"):
        owner.cleanup()
