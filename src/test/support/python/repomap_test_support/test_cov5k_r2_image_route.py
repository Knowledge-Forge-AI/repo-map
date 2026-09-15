"""Managed image-build adapter for the deferred Group K rehearsal."""

from __future__ import annotations

from pathlib import Path
import subprocess

import docker

from repomap_kg.runtime.release import (
    POSTGRES_RELEASE_IMAGE,
    PSYCOPG_RELEASE_VERSION,
    PYTHON_RELEASE_IMAGE,
    PYTHON_RELEASE_VERSION,
)
from repomap_test_support.build_profile_debt import enforce_build_profile_authority
from repomap_test_support.resource_run import active_resource_run
from repomap_test_support.resource_test_images import TestImageManager


def execute_group_k_ephemeral(
    repository_root: Path,
) -> tuple[tuple[str, str, str], subprocess.CompletedProcess[str]]:
    """Build and exactly clean K07 through the repository image manager."""

    enforce_build_profile_authority()
    resource_run = active_resource_run()
    if resource_run is None:
        raise RuntimeError("Group K image build requires a managed run")
    client = docker.from_env()
    manager = TestImageManager(
        repo_root=repository_root,
        resource_run=resource_run,
        client=client,
        base_reference=PYTHON_RELEASE_IMAGE,
        python_base_family="python:3.12-slim-bookworm",
        python_version=PYTHON_RELEASE_VERSION,
        psycopg_release_version=PSYCOPG_RELEASE_VERSION,
    )
    try:
        manager.build_ephemeral_image(
            f"FROM {POSTGRES_RELEASE_IMAGE}\n",
            ordinal=7,
            exact_local_base_reference=POSTGRES_RELEASE_IMAGE,
        )
    finally:
        try:
            manager.cleanup_ephemeral_run_images()
        finally:
            client.close()
    observed = ("TestImageManager", "build_ephemeral_image", "dependency-only-dockerfile")
    return observed, subprocess.CompletedProcess(observed, 0, "", "")
