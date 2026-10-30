"""Deterministic resolution for the RepoMap-owned Go parser helper."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Mapping


HELPER_ENV = "REPOMAP_GO_HELPER"
HELPER_NAME = "repomap-go-extract.exe" if os.name == "nt" else "repomap-go-extract"


class GoHelperUnavailableError(RuntimeError):
    """Raised when no explicit RepoMap-controlled helper is executable."""


def platform_tag(*, system: str | None = None, machine: str | None = None) -> str:
    selected_system = sys.platform if system is None else system
    selected_machine = platform.machine() if machine is None else machine
    normalized_machine = selected_machine.lower().replace("x86_64", "amd64").replace(
        "aarch64", "arm64"
    )
    return f"{selected_system}-{normalized_machine}"


def resolve_go_helper_command(
    *,
    environment: Mapping[str, str] | None = None,
    package_root: Path | None = None,
    target_platform: str | None = None,
) -> tuple[str, ...]:
    selected_environment = os.environ if environment is None else environment
    explicit = selected_environment.get(HELPER_ENV)
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_absolute():
            raise GoHelperUnavailableError("Go parser helper path must be absolute")
    else:
        root = Path(__file__).resolve().parents[2] if package_root is None else package_root
        tag = platform_tag() if target_platform is None else target_platform
        candidate = root / "_bin" / tag / HELPER_NAME
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise GoHelperUnavailableError(
            "Go parser helper is unavailable; run tools/build_go_helper.py"
        )
    return (str(candidate.resolve()),)
