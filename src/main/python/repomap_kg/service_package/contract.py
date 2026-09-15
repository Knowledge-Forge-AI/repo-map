"""Platform-neutral coordinator service-package contract."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from repomap_kg.service_package.environment import (
    SERVICE_ENVIRONMENT_ALLOWLIST,
    apply_service_environment,
)
from repomap_kg.coordinator.windows_security import (
    WindowsSecurityError,
    reject_reparse_path,
    validate_supported_windows_path,
)


@dataclass(frozen=True)
class ServicePackageSpec:
    """Normalized semantics shared by every native user-service adapter."""

    service_identity: str
    foreground_argv: tuple[str, ...]
    environment_source: str
    environment_allowlist: tuple[str, ...]
    repo_map_home: Path
    config_source: str
    psql_path: Path | None
    python_sha256: str | None
    psql_sha256: str | None
    runtime_directory: Path
    working_directory: Path
    stdout_path: Path
    stderr_path: Path
    startup_policy: str
    restart_policy: str
    restart_delay_seconds: int
    shutdown_policy: str
    shutdown_timeout_seconds: int
    readiness_contract: str
    log_ownership: str
    resource_policy: str
    install_target: str
    generated_artifact_ownership: str
    status_inspection: str
    uninstall_behavior: str
    upgrade_behavior: str
    rollback_behavior: str
    privacy_classification: str
    architectural_targets: tuple[str, ...]
    native_adapter_targets: tuple[str, ...]


def build_service_package_spec(repo_map_home: str | Path) -> ServicePackageSpec:
    """Build the single approved service specification for one RepoMap home."""

    normalized_home = _normalize_home(repo_map_home)
    executable = Path(os.path.realpath(sys.executable))
    if not is_approved_python_executable(executable):
        raise RuntimeError("service_foreground_executable_invalid")
    psql_path = _resolve_psql_dependency()
    return _build_spec(
        normalized_home,
        foreground_argv=(
            str(executable),
            "-m",
            "repomap_kg",
            "ops",
            "coordinator-serve",
            "--repo-map-home",
            str(normalized_home),
            "--service-package-environment",
            "--service-package-psql",
            str(psql_path),
            "--json",
        ),
        psql_path=psql_path,
        python_sha256=_executable_sha256(executable),
        psql_sha256=_executable_sha256(psql_path),
    )


def build_service_inspection_spec(repo_map_home: str | Path) -> ServicePackageSpec:
    """Build the dependency-free subset used only for status and uninstall."""

    return _build_spec(
        _normalize_home(repo_map_home),
        foreground_argv=(),
        psql_path=None,
        python_sha256=None,
        psql_sha256=None,
    )


def _normalize_home(repo_map_home: str | Path) -> Path:
    try:
        raw_home = os.fspath(repo_map_home)
        if "\x00" in raw_home:
            raise ValueError
        home = Path(raw_home)
    except (TypeError, ValueError):
        raise ValueError("service_repo_map_home_invalid") from None
    if not home.is_absolute():
        raise ValueError("service_repo_map_home_invalid")
    if os.name == "nt":  # pragma: no cover - native Windows runner
        try:
            validate_supported_windows_path(raw_home)
        except (TypeError, ValueError):
            raise ValueError("service_repo_map_home_invalid") from None
    return home.resolve(strict=False)


def _build_spec(
    normalized_home: Path,
    *,
    foreground_argv: tuple[str, ...],
    psql_path: Path | None,
    python_sha256: str | None,
    psql_sha256: str | None,
) -> ServicePackageSpec:
    runtime_directory = normalized_home / "coordinator"
    return ServicePackageSpec(
        service_identity="org.repomap.coordinator",
        foreground_argv=foreground_argv,
        environment_source="allowlisted_native_manager_environment",
        environment_allowlist=SERVICE_ENVIRONMENT_ALLOWLIST,
        repo_map_home=normalized_home,
        config_source="repo_map_home",
        psql_path=psql_path,
        python_sha256=python_sha256,
        psql_sha256=psql_sha256,
        runtime_directory=runtime_directory,
        working_directory=normalized_home,
        stdout_path=runtime_directory / "service.stdout.log",
        stderr_path=runtime_directory / "service.stderr.log",
        startup_policy="explicit_user_session",
        restart_policy="on_failure_rate_limited",
        restart_delay_seconds=10,
        shutdown_policy="sigterm_then_kill",
        shutdown_timeout_seconds=30,
        readiness_contract="authenticated_health_v1",
        log_ownership="owner_private_files",
        resource_policy="native_user_default",
        install_target="current_user",
        generated_artifact_ownership="repomap_owned_private_regular_file_v1",
        status_inspection="manager_state_plus_authenticated_health",
        uninstall_behavior="recognized_owner_file_only",
        upgrade_behavior="preserve_native_state_or_rollback",
        rollback_behavior="restore_prior_known_good",
        privacy_classification="owner_private",
        architectural_targets=("darwin", "linux", "win32"),
        native_adapter_targets=("darwin", "linux"),
    )


def service_semantics(spec: ServicePackageSpec) -> dict[str, object]:
    """Return adapter-neutral values used for compatibility validation."""

    return {
        "service_identity": spec.service_identity,
        "foreground_argv": spec.foreground_argv,
        "environment_source": spec.environment_source,
        "environment_allowlist": spec.environment_allowlist,
        "repo_map_home": spec.repo_map_home,
        "config_source": spec.config_source,
        "psql_path": spec.psql_path,
        "runtime_directory": spec.runtime_directory,
        "working_directory": spec.working_directory,
        "startup_policy": spec.startup_policy,
        "restart_policy": spec.restart_policy,
        "restart_delay_seconds": spec.restart_delay_seconds,
        "shutdown_policy": spec.shutdown_policy,
        "shutdown_timeout_seconds": spec.shutdown_timeout_seconds,
        "readiness_contract": spec.readiness_contract,
        "log_ownership": spec.log_ownership,
        "resource_policy": spec.resource_policy,
        "install_target": spec.install_target,
        "generated_artifact_ownership": spec.generated_artifact_ownership,
        "status_inspection": spec.status_inspection,
        "uninstall_behavior": spec.uninstall_behavior,
        "upgrade_behavior": spec.upgrade_behavior,
        "rollback_behavior": spec.rollback_behavior,
        "privacy_classification": spec.privacy_classification,
    }


_PYTHON_EXECUTABLE = re.compile(r"python(?:\d+(?:\.\d+)*)?")


def is_approved_python_executable(path: str | Path) -> bool:
    """Recognize a fixed, executable, non-writable Python interpreter path."""

    return _matches_current_executable(path, Path(os.path.realpath(sys.executable)))


def is_approved_psql_executable(path: str | Path) -> bool:
    """Recognize the fixed PostgreSQL client dependency used by the coordinator.

    The approved name is required of the invoked path, not of the target it
    resolves to: Debian and Ubuntu ship ``/usr/bin/psql`` as a link to
    ``pg_wrapper``, which selects the cluster binary from its own argv[0].
    Target integrity is still taken from the resolved file, matching
    ``coordinator._refresh_capability_io.validate_psql``.
    """

    value = shutil.which("psql")
    if value is None:
        return False
    if not _has_invocation_name(path, _psql_name()):
        return False
    candidate = _safe_resolved_executable(path)
    expected = _safe_resolved_executable(Path(value))
    return candidate is not None and expected is not None and candidate == expected


def is_recognizable_python_reference(path: str | Path, digest: str) -> bool:
    """Recognize current Python authority or a closed stale interpreter reference."""

    return _recognizes_executable_reference(
        path,
        digest,
        name_pattern=_PYTHON_EXECUTABLE,
    )


def is_recognizable_psql_reference(path: str | Path, digest: str) -> bool:
    """Recognize current psql authority or a closed stale dependency reference."""

    return _recognizes_executable_reference(
        path, digest, exact_name=_psql_name()
    )


def _recognizes_executable_reference(
    path: str | Path,
    digest: str,
    *,
    name_pattern: re.Pattern[str] | None = None,
    exact_name: str | None = None,
) -> bool:
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return False
    if exact_name is not None and not _has_invocation_name(path, exact_name):
        return False
    resolved = _safe_resolved_executable(path)
    if resolved is not None:
        if name_pattern is not None and name_pattern.fullmatch(resolved.name) is None:
            return False
        try:
            return _executable_sha256(resolved) == digest
        except RuntimeError:
            return False
    return _is_missing_executable_reference(
        path,
        name_pattern=name_pattern,
        exact_name=exact_name,
    )


def _matches_current_executable(path: str | Path, expected: Path) -> bool:
    candidate = _safe_resolved_executable(path)
    approved = _safe_resolved_executable(expected)
    return candidate is not None and approved is not None and candidate == approved


def _safe_resolved_executable(path: str | Path) -> Path | None:
    try:
        raw = os.fspath(path)
        candidate = Path(raw)
        if "\x00" in raw or not candidate.is_absolute():
            return None
        if os.name == "nt":  # pragma: no cover - native Windows runner
            reject_reparse_path(candidate)
        resolved = candidate.resolve(strict=True)
        details = resolved.stat()
    except (OSError, TypeError, ValueError, WindowsSecurityError):
        return None
    if (
        not stat.S_ISREG(details.st_mode)
        or (os.name != "nt" and stat.S_IMODE(details.st_mode) & 0o022)
        or (os.name == "nt" and os.access(resolved, os.W_OK))
        or not os.access(resolved, os.X_OK)
    ):
        return None
    return resolved


def _is_missing_executable_reference(
    path: str | Path,
    *,
    name_pattern: re.Pattern[str] | None = None,
    exact_name: str | None = None,
) -> bool:
    try:
        raw = os.fspath(path)
        candidate = Path(raw)
        if "\x00" in raw or not candidate.is_absolute():
            return False
        if candidate.exists() or candidate.is_symlink():
            return False
    except (OSError, TypeError, ValueError):
        return False
    if exact_name is not None and not _same_filename(candidate.name, exact_name):
        return False
    if name_pattern is not None and name_pattern.fullmatch(candidate.name) is None:
        return False
    return True


def _resolve_psql_dependency() -> Path:
    # The lexical path is what gets recorded and executed; resolving it here
    # would strip the argv[0] a wrapper needs to select its cluster binary.
    value = shutil.which("psql")
    if value is None:
        raise RuntimeError("service_psql_unavailable")
    invoked = Path(value)
    if not invoked.is_absolute() or not is_approved_psql_executable(invoked):
        raise RuntimeError("service_psql_unavailable")
    return invoked


def _psql_name(platform_name: str | None = None) -> str:
    return "psql.exe" if (platform_name or os.name) == "nt" else "psql"


def _has_invocation_name(path: str | Path, expected: str) -> bool:
    try:
        raw = os.fspath(path)
    except TypeError:
        return False
    return "\x00" not in raw and _same_filename(Path(raw).name, expected)


def _same_filename(left: str, right: str) -> bool:
    return left.casefold() == right.casefold() if os.name == "nt" else left == right


def _executable_sha256(path: Path) -> str:
    try:
        details = path.stat()
        if not 0 < details.st_size <= 128 * 1024 * 1024:
            raise OSError
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        raise RuntimeError("service_foreground_executable_invalid") from None
    return digest.hexdigest()


__all__ = [
    "SERVICE_ENVIRONMENT_ALLOWLIST",
    "ServicePackageSpec",
    "apply_service_environment",
    "build_service_inspection_spec",
    "build_service_package_spec",
    "is_approved_psql_executable",
    "is_approved_python_executable",
    "is_recognizable_psql_reference",
    "is_recognizable_python_reference",
    "service_semantics",
]
