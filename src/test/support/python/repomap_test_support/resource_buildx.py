"""Dedicated Buildx metadata ownership without shared-builder mutation."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Callable

from repomap_test_support.resource_ledger import (
    CleanupResult,
    FinalPresence,
    ResourceKind,
    ResourceLedger,
    RunIdentity,
)

DEFAULT_BUILDKIT_IMAGE = "moby/buildkit:buildx-stable-1"


class BuildCacheOwnershipUnproved(RuntimeError):
    """The build path stopped before touching unowned BuildKit state."""


Runner = Callable[..., subprocess.CompletedProcess[str]]


class DedicatedBuildxOwner:
    """Own one Buildx instance inside phase-owned ``BUILDX_CONFIG`` state."""

    def __init__(
        self,
        identity: RunIdentity,
        ledger: ResourceLedger,
        *,
        buildx_config: Path,
        runner: Runner = subprocess.run,
        buildkit_image: str = DEFAULT_BUILDKIT_IMAGE,
    ) -> None:
        if ledger.identity != identity:
            raise RuntimeError("Buildx owner and ledger run identity differ")
        config = Path(buildx_config)
        if not config.is_absolute() or config.is_symlink():
            raise RuntimeError("BUILDX_CONFIG must be an absolute plain directory")
        config.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.identity = identity
        self.ledger = ledger
        self.buildx_config = config
        self.runner = runner
        self.buildkit_image = buildkit_image
        safe_run = re.sub(r"[^a-zA-Z0-9_.-]+", "-", identity.run_id)[:40]
        self.builder_name = f"repomap-test-hygiene-{safe_run}"
        self._created = False

    def create(self) -> str:
        if self._created:
            raise RuntimeError("dedicated Buildx builder is already created")
        command = [
            "docker",
            "buildx",
            "create",
            "--name",
            self.builder_name,
            "--driver",
            "docker-container",
            "--driver-opt",
            "network=none",
        ]
        result = self._run(command)
        if result.returncode != 0:
            raise RuntimeError("dedicated Buildx builder creation failed")
        if not self._builder_present():
            raise RuntimeError("dedicated Buildx builder creation was not observed")
        self.ledger.register(
            ResourceKind.BUILDX_BUILDER,
            self.builder_name,
            creation_owner="dedicated-buildx-owner",
            created_before_run=False,
            creation_observed=True,
            cleanup_required=True,
        )
        self._created = True
        return self.builder_name

    def require_bootstrap_ready(self) -> None:
        """Refuse before bootstrap when it could pull or create unproved state."""
        if not self._created:
            raise RuntimeError("dedicated Buildx builder is not created")
        result = self._run(["docker", "image", "inspect", self.buildkit_image])
        if result.returncode != 0:
            raise BuildCacheOwnershipUnproved(
                "build_cache_ownership_unproved: local_buildkit_image_absent"
            )
        raise BuildCacheOwnershipUnproved(
            "build_cache_ownership_unproved: builder_label_injection_unavailable"
        )

    def cleanup(self) -> None:
        if not self._created:
            raise RuntimeError("dedicated Buildx builder is not created")
        kind = ResourceKind.BUILDX_BUILDER
        self.ledger.mark_cleanup_attempted(kind, self.builder_name)
        result = self._run(
            ["docker", "buildx", "rm", self.builder_name],
            timeout=60,
        )
        if result.returncode != 0:
            self.ledger.mark_cleanup_result(
                kind, self.builder_name, CleanupResult.FAILED
            )
            self.ledger.mark_final_presence(
                kind, self.builder_name, FinalPresence.PRESENT
            )
            raise RuntimeError("dedicated Buildx builder cleanup failed")
        present = self._builder_present()
        self.ledger.mark_cleanup_result(
            kind,
            self.builder_name,
            CleanupResult.FAILED if present else CleanupResult.REMOVED,
        )
        self.ledger.mark_final_presence(
            kind,
            self.builder_name,
            FinalPresence.PRESENT if present else FinalPresence.ABSENT,
        )
        if present:
            raise RuntimeError("dedicated Buildx builder remains after cleanup")
        self._created = False

    def _builder_present(self) -> bool:
        result = self._run(
            ["docker", "buildx", "inspect", self.builder_name],
            timeout=20,
        )
        return result.returncode == 0

    def _run(
        self,
        command: list[str],
        *,
        timeout: float = 30,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.pop("BUILDX_BUILDER", None)
        environment["BUILDX_CONFIG"] = str(self.buildx_config)
        try:
            return self.runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=environment,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError("dedicated Buildx command failed") from error


__all__ = [
    "BuildCacheOwnershipUnproved",
    "DEFAULT_BUILDKIT_IMAGE",
    "DedicatedBuildxOwner",
]
