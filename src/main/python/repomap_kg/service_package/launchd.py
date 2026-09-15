"""macOS launchd per-user adapter for the portable service contract."""

from __future__ import annotations

import os
import plistlib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from repomap_kg.service_package.contract import (
    ServicePackageSpec,
    is_recognizable_psql_reference,
    is_recognizable_python_reference,
    service_semantics,
)


_MAX_DEFINITION_BYTES = 1024 * 1024
_LABEL = "org.repomap.coordinator"


@dataclass(frozen=True)
class LaunchdUserAdapter:
    """Translate one common specification into a user LaunchAgent."""

    user_home: Path
    uid: int
    platform_name: str = "darwin"
    artifact_kind: str = "launchd_plist"

    @property
    def target_path(self) -> Path:
        return (
            self.user_home
            / "Library"
            / "LaunchAgents"
            / "org.repomap.coordinator.plist"
        )

    @property
    def service_target(self) -> str:
        return f"gui/{self.uid}/{_LABEL}"

    def render(self, spec: ServicePackageSpec) -> bytes:
        payload = {
            "Disabled": True,
            "ExitTimeOut": spec.shutdown_timeout_seconds,
            "KeepAlive": {"SuccessfulExit": False},
            "Label": spec.service_identity,
            "ProcessType": "Background",
            "ProgramArguments": list(spec.foreground_argv),
            "RunAtLoad": True,
            "StandardErrorPath": str(spec.stderr_path),
            "StandardOutPath": str(spec.stdout_path),
            "ThrottleInterval": spec.restart_delay_seconds,
            "Umask": 0o077,
            "WorkingDirectory": str(spec.working_directory),
            "X-RepoMap-Psql-SHA256": spec.psql_sha256,
            "X-RepoMap-Python-SHA256": spec.python_sha256,
        }
        return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True)

    def validate(self, content: bytes, spec: ServicePackageSpec) -> None:
        if not self.recognizes(content):
            raise ValueError("service_definition_invalid")
        try:
            actual = plistlib.loads(content)
            expected = plistlib.loads(self.render(spec))
        except (ValueError, plistlib.InvalidFileException):
            raise ValueError("service_definition_invalid") from None
        if actual != expected:
            raise ValueError("service_definition_invalid")

    def recognizes(self, content: bytes) -> bool:
        if not isinstance(content, bytes) or len(content) > _MAX_DEFINITION_BYTES:
            return False
        try:
            payload = plistlib.loads(content)
        except (ValueError, plistlib.InvalidFileException, TypeError, OverflowError):
            return False
        if not isinstance(payload, dict) or payload.get("Label") != _LABEL:
            return False
        if "EnvironmentVariables" in payload or "Program" in payload:
            return False
        argv = payload.get("ProgramArguments")
        python_sha256 = payload.get("X-RepoMap-Python-SHA256")
        psql_sha256 = payload.get("X-RepoMap-Psql-SHA256")
        if not _recognized_foreground_argv(argv, python_sha256, psql_sha256):
            return False
        argv = cast(list[str], argv)
        expected_keys = {
            "Disabled",
            "ExitTimeOut",
            "KeepAlive",
            "Label",
            "ProcessType",
            "ProgramArguments",
            "RunAtLoad",
            "StandardErrorPath",
            "StandardOutPath",
            "ThrottleInterval",
            "Umask",
            "WorkingDirectory",
            "X-RepoMap-Psql-SHA256",
            "X-RepoMap-Python-SHA256",
        }
        if set(payload) != expected_keys:
            return False
        home = Path(argv[6])
        runtime_directory = home / "coordinator"
        return payload == {
            "Disabled": True,
            "ExitTimeOut": 30,
            "KeepAlive": {"SuccessfulExit": False},
            "Label": _LABEL,
            "ProcessType": "Background",
            "ProgramArguments": argv,
            "RunAtLoad": True,
            "StandardErrorPath": str(runtime_directory / "service.stderr.log"),
            "StandardOutPath": str(runtime_directory / "service.stdout.log"),
            "ThrottleInterval": 10,
            "Umask": 0o077,
            "WorkingDirectory": str(home),
            "X-RepoMap-Psql-SHA256": psql_sha256,
            "X-RepoMap-Python-SHA256": python_sha256,
        }

    def semantic_values(self, spec: ServicePackageSpec) -> dict[str, object]:
        return service_semantics(spec)

    def active_probe_argv(self) -> tuple[str, ...]:
        return ("/bin/launchctl", "print", self.service_target)

    def manager_probe_argv(self) -> tuple[str, ...]:
        return ("/bin/launchctl", "print", f"gui/{self.uid}")

    def inactive_return_codes(self) -> frozenset[int]:
        return frozenset({113})

    def disabled_return_codes(self) -> frozenset[int]:
        return frozenset()

    def enabled_probe_argv(self) -> None:
        return None

    def reload_commands(self) -> tuple[tuple[str, ...], ...]:
        return ()

    def enable_commands(self) -> tuple[tuple[str, ...], ...]:
        return (("/bin/launchctl", "enable", self.service_target),)

    def disable_commands(self) -> tuple[tuple[str, ...], ...]:
        return (("/bin/launchctl", "disable", self.service_target),)

    def start_commands(self) -> tuple[tuple[str, ...], ...]:
        return (("/bin/launchctl", "bootstrap", f"gui/{self.uid}", str(self.target_path)),)

    def stop_commands(self) -> tuple[tuple[str, ...], ...]:
        return (("/bin/launchctl", "bootout", self.service_target),)

    def restart_commands(self) -> tuple[tuple[str, ...], ...]:
        return (("/bin/launchctl", "kickstart", "-k", self.service_target),)


def _recognized_foreground_argv(
    value: object,
    python_sha256: object,
    psql_sha256: object,
) -> bool:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return False
    if (
        len(value) != 11
        or not isinstance(python_sha256, str)
        or not isinstance(psql_sha256, str)
        or not is_recognizable_python_reference(value[0], python_sha256)
    ):
        return False
    if value[1:6] != [
        "-m",
        "repomap_kg",
        "ops",
        "coordinator-serve",
        "--repo-map-home",
    ]:
        return False
    return (
        os.path.isabs(value[6])
        and value[7:9]
        == ["--service-package-environment", "--service-package-psql"]
        and is_recognizable_psql_reference(value[9], psql_sha256)
        and value[10] == "--json"
        and all("\x00" not in item and "\n" not in item for item in value)
    )


__all__ = ["LaunchdUserAdapter"]
