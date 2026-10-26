"""ADR 0095 Route B diagnostic server Dockerfile recipe rendering and pure identity helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from repomap_kg.runtime.commands import render_server_dockerfile
from repomap_kg.runtime.release_manifest import (
    D12_CANDIDATE_LIBPQ_VERSION,
    D12_CANDIDATE_PACKAGE_MANIFEST,
)

CONTEXT_PATHS = (
    "pyproject.toml",
    "README.md",
    "src/main/python",
    "src/main/resources",
    "src/main/go",
)


class D12ProfileError(RuntimeError):
    """The optional D12 profile refused before any candidate Docker work."""


def recipe_text() -> str:
    """Render the diagnostic server Dockerfile with explicit candidate-only data."""
    return render_server_dockerfile(
        manifest=D12_CANDIDATE_PACKAGE_MANIFEST,
        libpq_version=D12_CANDIDATE_LIBPQ_VERSION,
    )


def build_args(platform: str) -> dict[str, str]:
    """Return the canonical Docker build arguments for the target platform."""
    return {"TARGETOS": "linux", "TARGETARCH": platform.split("/", 1)[1]}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def context_files(repo_root: Path) -> tuple[str, ...]:
    """Exact non-ignored build-context files, as the recipe's COPY paths name them."""
    command = ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--"]
    listed = subprocess.run(
        [*command, *CONTEXT_PATHS], cwd=repo_root, capture_output=True, check=True
    ).stdout
    return tuple(sorted(os.fsdecode(name) for name in set(listed.split(b"\0")) - {b""}))


def digest_files(root: Path, names: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for name in names:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise D12ProfileError(f"build-context entry is not a regular file: {name}")
        executable = b"x" if path.stat().st_mode & 0o111 else b"-"
        digest.update(
            name.encode() + b"\0" + executable + bytes.fromhex(_sha256(path.read_bytes()))
        )
    return digest.hexdigest()


def compute_recipe_digest(
    platform: str,
    *,
    dockerfile_text: str,
    platform_build_args: Mapping[str, str],
) -> str:
    payload = {
        "dockerfile": dockerfile_text,
        "build_args": dict(platform_build_args),
        "platform": platform,
    }
    return _sha256(json.dumps(payload, sort_keys=True).encode())


def recipe_digest(platform: str) -> str:
    return compute_recipe_digest(
        platform,
        dockerfile_text=recipe_text(),
        platform_build_args=build_args(platform),
    )


def compute_frozen_identity(
    repo_root: Path,
    platform: str,
    *,
    context_files_fn: Callable[[Path], tuple[str, ...]],
    digest_files_fn: Callable[[Path, Sequence[str]], str],
    recipe_digest_fn: Callable[[str], str],
    recipe_text_fn: Callable[[], str],
) -> dict[str, Any]:
    names = context_files_fn(repo_root)
    return {
        "source_sha256": digest_files_fn(repo_root, names),
        "recipe_sha256": recipe_digest_fn(platform),
        "dockerfile_sha256": _sha256(recipe_text_fn().encode()),
        "context_file_count": len(names),
    }


def frozen_identity(repo_root: Path, platform: str) -> dict[str, Any]:
    return compute_frozen_identity(
        repo_root,
        platform,
        context_files_fn=context_files,
        digest_files_fn=digest_files,
        recipe_digest_fn=recipe_digest,
        recipe_text_fn=recipe_text,
    )
