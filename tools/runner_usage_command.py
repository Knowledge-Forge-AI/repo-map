"""Closed command and probe admission for measured usage-worker launches."""

from __future__ import annotations

from pathlib import Path
import os
from typing import Any

from runner_coverage_capability import (
    CapabilityContainmentError, CapabilityRefusalError, CapabilityValidationError,
)

USAGE_COMMAND = ("-m", "repomap_test_support.usage_worker")
MEASURED_CASES = frozenset({
    "nominal", "burn", "rss", "grandchild-waited", "grandchild-remaining",
})
ALL_CASES = MEASURED_CASES | {"sigkill", "block"}
PROBE_CASES = frozenset({"grandchild-waited", "grandchild-remaining", "block"})
_FIXED_PREFIX = ("--capability", "--job-id", "--attempt")


def _canonical(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise CapabilityContainmentError(f"{label} must not be a symlink")
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise CapabilityContainmentError(f"{label} cannot be resolved") from exc
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise CapabilityContainmentError(f"{label} has a symlinked parent")
    return resolved


def _inside(path: Path, root: Path, label: str) -> bool:
    try:
        return path.is_relative_to(root.resolve())
    except (OSError, ValueError):
        raise CapabilityContainmentError(f"{label} path is invalid")


def validate_usage_probe(
    probe: str | Path,
    *,
    case: str,
    session_dir: Path | None = None,
    child_manifest_dir: Path | None = None,
    data_dir: Path | None = None,
) -> Path:
    """Validate a private absent probe leaf without creating or truncating it."""
    if case not in PROBE_CASES:
        raise CapabilityValidationError("usage probe is forbidden for this case")
    raw = Path(probe)
    if not raw.is_absolute() or raw.name in {"", ".", ".."}:
        raise CapabilityContainmentError("usage probe must be an absolute leaf path")
    parent = _canonical(raw.parent, "usage probe parent")
    leaf = _canonical(raw, "usage probe")
    if raw != leaf or leaf != parent / raw.name or raw.name in {".", ".."}:
        raise CapabilityContainmentError("usage probe is not a canonical leaf")
    roots = tuple(_canonical(root, "usage boundary") for root in (session_dir, child_manifest_dir, data_dir) if root is not None)
    if any(_inside(parent, root, "usage probe") for root in roots):
        raise CapabilityContainmentError("usage probe overlaps a runner-owned directory")
    if not parent.exists() or not parent.is_dir():
        raise CapabilityContainmentError("usage probe parent must be a private directory")
    try:
        details = parent.stat()
    except OSError as exc:
        raise CapabilityContainmentError("usage probe parent cannot be inspected") from exc
    if not (details.st_mode & 0o077 == 0
            and details.st_uid == os.getuid()):
        raise CapabilityContainmentError("usage probe parent must be a private directory")
    if raw.exists() or raw.is_symlink():
        raise CapabilityContainmentError("usage probe leaf must be absent")
    return leaf


def validate_usage_arguments(
    arguments: tuple[str, ...],
    *,
    capability: Any = None,
    measured_only: bool = True,
    session_dir: Path | None = None,
    child_manifest_dir: Path | None = None,
    data_dir: Path | None = None,
) -> tuple[str, Path | None]:
    """Validate fixed usage-worker arguments after the module name.

    The portable launch chain appends capability/job/attempt after the case and
    optional probe. This parser accepts exactly that ordered shape and no
    ambient options or arbitrary script roots.
    """
    args = list(arguments)
    if len(args) < 2 or args.pop(0) != "--case":
        raise CapabilityValidationError("usage worker requires --case")
    case = args.pop(0)
    allowed = MEASURED_CASES if measured_only else ALL_CASES
    if case not in allowed:
        raise CapabilityValidationError("usage worker case is not admitted")
    probe: Path | None = None
    if args and args[0] == "--probe-path":
        if len(args) < 2 or not args[1] or args[1].startswith("--"):
            raise CapabilityValidationError("usage probe argument is malformed")
        probe = Path(args[1])
        del args[:2]
    if case in PROBE_CASES and probe is None:
        raise CapabilityValidationError("usage worker probe is required")
    if case not in PROBE_CASES and probe is not None:
        raise CapabilityValidationError("usage probe is forbidden for this case")
    if len(args) != 6 or tuple(args[::2]) != _FIXED_PREFIX or not all(args[1::2]):
        raise CapabilityValidationError("usage worker capability arguments are not closed")
    if not args[-1].isdigit() or int(args[-1]) <= 0:
        raise CapabilityValidationError("usage worker attempt is invalid")
    if capability is not None:
        validate_usage_probe(
            probe, case=case, session_dir=capability.session_dir,
            child_manifest_dir=capability.child_manifest_dir, data_dir=capability.data_dir,
        ) if probe is not None else None
    elif probe is not None:
        validate_usage_probe(
            probe, case=case, session_dir=session_dir,
            child_manifest_dir=child_manifest_dir, data_dir=data_dir,
        )
    return case, probe


def permitted_worker_paths(capability: Any, command: tuple[str, ...]) -> tuple[Path, ...]:
    """Select one exact launch identity without widening production paths."""
    from runner_coverage_capability import compute_source_commitment
    if command == capability.portable_command:
        return capability.permitted_python_paths
    if command == USAGE_COMMAND:
        if capability.conformance_root is None:
            raise CapabilityRefusalError("usage worker requires test-conformance authority")
        expected_root = Path(__file__).resolve().parents[1] / "src/test/support/python"
        product_root = Path(__file__).resolve().parents[1] / "src/main/python"
        if capability.conformance_root != expected_root or capability.conformance_commitment is None:
            raise CapabilityContainmentError("usage worker support root is not the committed conformance root")
        if compute_source_commitment(capability.conformance_root) != capability.conformance_commitment:
            raise CapabilityValidationError("usage worker source commitment mismatch")
        if tuple(capability.permitted_python_paths) != (product_root,):
            raise CapabilityContainmentError("usage worker product source root is not exact")
        if any(path.is_symlink() or not path.is_dir() for path in (expected_root, product_root)):
            raise CapabilityContainmentError("usage worker source roots are unavailable")
        return (expected_root, product_root)
    from runner_coverage_conformance import CONFORMANCE_COMMAND

    if command != CONFORMANCE_COMMAND or capability.conformance_root is None:
        raise CapabilityValidationError("invalid worker command identity")
    expected_root = Path(__file__).resolve().parents[1] / "src/test/support/python"
    if capability.conformance_root != expected_root:
        raise CapabilityContainmentError("conformance source root mismatch")
    if compute_source_commitment(capability.conformance_root) != capability.conformance_commitment:
        raise CapabilityValidationError("conformance source commitment mismatch")
    return (capability.conformance_root, *capability.permitted_python_paths)


def usage_python_paths(repo_root: Path) -> tuple[Path, Path]:
    """Return the only ordered source roots permitted to the usage helper."""
    root = repo_root.resolve()
    return (root / "src/test/support/python", root / "src/main/python")


__all__ = (
    "ALL_CASES", "MEASURED_CASES", "PROBE_CASES", "USAGE_COMMAND",
    "usage_python_paths", "validate_usage_arguments", "validate_usage_probe",
)
