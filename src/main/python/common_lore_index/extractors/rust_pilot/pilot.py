"""Explicit Rust-pilot facade; it forwards no test runner or callback."""

from __future__ import annotations

from pathlib import Path

from common_lore_index.extractors.rust_pilot.controller import RustPilotController
from common_lore_index.extractors.rust_pilot.selection import select_inputs


class RustPilotRun:
    """Namespace facade whose open method returns the exact live controller."""

    @classmethod
    def open(cls, *, docker_cli: str, sdk_image_id: str, profile_dir: Path | str,
             platform: str, audit_dir: Path | str | None = None) -> RustPilotController:
        return RustPilotController(
            docker_cli=docker_cli, sdk_image_id=sdk_image_id, profile_dir=profile_dir,
            platform=platform, audit_dir=audit_dir,
        )


def open_rust_pilot(*, docker_cli: str, sdk_image_id: str, profile_dir: Path | str,
                    platform: str, audit_dir: Path | str | None = None) -> RustPilotController:
    return RustPilotRun.open(
        docker_cli=docker_cli, sdk_image_id=sdk_image_id, profile_dir=profile_dir,
        platform=platform, audit_dir=audit_dir,
    )


__all__ = ("RustPilotController", "RustPilotRun", "open_rust_pilot", "select_inputs")
