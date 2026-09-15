"""Exact report, monitoring, and pin protection observations for GC."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from repomap_test_support.resource_index_bootstrap import canonical_json
from repomap_test_support.resource_ledger import (
    ResourceLedger,
    ResourceLedgerError,
    RunIdentity,
)
from repomap_test_support.resource_ledger_io import PrivateJsonError
from repomap_test_support.resource_lifecycle_claim import ClaimPurpose
from repomap_test_support.resource_retention import RetentionClass
from repomap_test_support.resource_scratch_history import (
    _report_source_released,
    _strict_manifest,
    _valid_protection,
)
from repomap_test_support.resource_validation import HygieneValidationError
from repomap_test_support.resource_validation import exact_object
from repomap_test_support.test_scratch import MANIFEST_SCHEMA


PROTECTION_OBSERVATION_SCHEMA = "repomap-test-protection-observation-v1"


class ProtectionAuthorityError(RuntimeError):
    """Protection evidence is unavailable, malformed, or ambiguous."""


@dataclass(frozen=True)
class ProtectionObservation:
    schema: str
    project: str
    observed_at_seconds: int
    report_run_ids: frozenset[str]
    monitoring_run_ids: frozenset[str]
    pin_run_ids: frozenset[str]
    provider_record_id: str

    @classmethod
    def create(
        cls,
        *,
        project: str,
        observed_at_seconds: int,
        report_run_ids: Iterable[str],
        monitoring_run_ids: Iterable[str],
        pin_run_ids: Iterable[str],
    ) -> "ProtectionObservation":
        reports = frozenset(report_run_ids)
        monitoring = frozenset(monitoring_run_ids)
        pins = frozenset(pin_run_ids)
        seed = {
            "schema": PROTECTION_OBSERVATION_SCHEMA,
            "project": project,
            "observed_at_seconds": observed_at_seconds,
            "report_run_ids": sorted(reports),
            "monitoring_run_ids": sorted(monitoring),
            "pin_run_ids": sorted(pins),
        }
        return cls(
            PROTECTION_OBSERVATION_SCHEMA,
            project,
            observed_at_seconds,
            reports,
            monitoring,
            pins,
            hashlib.sha256(canonical_json(seed)).hexdigest(),
        )


def observe_protections(
    scratch_root: Path,
    *,
    project: str,
    now_seconds: int,
    include_quarantine: bool = False,
) -> ProtectionObservation:
    """Return one bounded authoritative observation or fail closed."""
    root = Path(scratch_root)
    runs_root = root / "r"
    reports: set[str] = set()
    monitoring: set[str] = set()
    pins: set[str] = set()
    try:
        runs = _run_manifests(runs_root, project)
        if include_quarantine:
            quarantined = _quarantined_manifests(root, project)
            if set(runs).intersection(quarantined):
                raise ValueError("run identity exists in two lifecycle locations")
            runs.update(quarantined)
        _registered_protections(root, project, runs, reports, monitoring, pins)
        _report_source_protections(runs, reports, now_seconds)
        _monitoring_index_protections(root, project, runs, monitoring)
    except (
        OSError,
        ValueError,
        PrivateJsonError,
        HygieneValidationError,
        ResourceLedgerError,
    ) as error:
        raise ProtectionAuthorityError("protection authority is invalid") from error
    return ProtectionObservation.create(
        project=project,
        observed_at_seconds=now_seconds,
        report_run_ids=reports,
        monitoring_run_ids=monitoring,
        pin_run_ids=pins,
    )


def public_protection_projection(
    observation: ProtectionObservation,
) -> dict[str, int]:
    return {
        "report_protections": len(observation.report_run_ids),
        "monitoring_protections": len(observation.monitoring_run_ids),
        "pins": len(observation.pin_run_ids),
    }


def _run_manifests(runs_root: Path, project: str) -> dict[str, tuple[Path, dict]]:
    if not runs_root.exists():
        return {}
    if runs_root.is_symlink() or not runs_root.is_dir():
        raise ValueError("run authority root is unsafe")
    result = {}
    for run_root in runs_root.iterdir():
        manifest = _strict_manifest(run_root, project)
        result[run_root.name] = (run_root, manifest)
    return result


def _quarantined_manifests(
    root: Path, project: str
) -> dict[str, tuple[Path, dict]]:
    quarantine_root = root / ".quarantine" / project
    if not quarantine_root.exists():
        return {}
    if quarantine_root.is_symlink() or not quarantine_root.is_dir():
        raise ValueError("quarantine authority root is unsafe")
    result = {}
    for run_root in quarantine_root.iterdir():
        try:
            manifest_path = run_root / "manifest.json"
            if (
                run_root.is_symlink()
                or not run_root.is_dir()
                or run_root.stat(follow_symlinks=False).st_uid != os.getuid()
                or manifest_path.is_symlink()
                or not manifest_path.is_file()
            ):
                raise ValueError("quarantined run identity is unsafe")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            required = {
                "schema", "project", "phase", "run_kind", "run_id", "pid",
                "physical_run_root", "monitoring_index_path", "state",
                "retention_policy", "exit_status", "live_runtime_residue",
            }
            manifest = exact_object(manifest, required, "quarantined run manifest")
            if (
                manifest["schema"] != MANIFEST_SCHEMA
                or manifest["project"] != project
                or manifest["run_kind"] != "test"
                or manifest["run_id"] != run_root.name
                or type(manifest["pid"]) is not int
                or Path(manifest["physical_run_root"])
                != root / "r" / run_root.name
                or manifest["state"] not in {"passed", "failed", "stopped"}
            ):
                raise ValueError("quarantined run manifest identity is invalid")
        except (OSError, ValueError, HygieneValidationError):
            continue
        result[run_root.name] = (run_root, manifest)
    return result


def _registered_protections(
    root: Path,
    project: str,
    runs: dict[str, tuple[Path, dict]],
    reports: set[str],
    monitoring: set[str],
    pins: set[str],
) -> None:
    protection_root = root / ".protections" / project
    specifications = (
        ("reports", ClaimPurpose.REPORT_SOURCE_REGISTRATION, reports),
        ("monitoring", ClaimPurpose.MONITORING_REGISTRATION, monitoring),
        ("pins", ClaimPurpose.OPERATOR_PIN_REGISTRATION, pins),
    )
    for kind, purpose, target in specifications:
        directory = protection_root / kind
        if not directory.exists():
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("protection directory is unsafe")
        for path in directory.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise ValueError("protection record path is unsafe")
            run_id = path.stem
            if run_id not in runs:
                raise ValueError("protection record has no exact run")
            if not _valid_protection(path, project, run_id, purpose.value):
                raise ValueError("protection record did not validate")
            target.add(run_id)


def _report_source_protections(
    runs: dict[str, tuple[Path, dict]],
    reports: set[str],
    now_seconds: int,
) -> None:
    for run_id, (run_root, manifest) in runs.items():
        ledger = ResourceLedger.open(
            run_root / "resource-ledger.json",
            RunIdentity(manifest["project"], manifest["phase"], run_id),
        )
        if not ledger.has_report_source():
            continue
        lifecycle = ledger.lifecycle
        released = (
            lifecycle.retention_class is RetentionClass.REPORT_SOURCE_PENDING_APPEND
            and _report_source_released(run_root, now_seconds)
        )
        if not released:
            reports.add(run_id)


def _monitoring_index_protections(
    root: Path,
    project: str,
    runs: dict[str, tuple[Path, dict]],
    monitoring: set[str],
) -> None:
    project_index = root / "index" / project
    if not project_index.exists():
        return
    if project_index.is_symlink() or not project_index.is_dir():
        raise ValueError("monitoring project index is unsafe")
    for phase_dir in project_index.iterdir():
        if phase_dir.is_symlink() or not phase_dir.is_dir():
            raise ValueError("monitoring phase index is unsafe")
        for link in phase_dir.iterdir():
            if not link.is_symlink():
                raise ValueError("monitoring entry is not an exact live link")
            run_id = link.name
            if run_id not in runs:
                raise ValueError("monitoring entry has no exact run")
            _, manifest = runs[run_id]
            expected_target = Path(manifest["physical_run_root"])
            if (
                link.resolve(strict=False) != expected_target
                or phase_dir.name != manifest["phase"]
                or Path(manifest["monitoring_index_path"]) != link
            ):
                raise ValueError("monitoring entry identity is invalid")
            monitoring.add(run_id)


__all__ = [
    "PROTECTION_OBSERVATION_SCHEMA",
    "ProtectionAuthorityError",
    "ProtectionObservation",
    "observe_protections",
    "public_protection_projection",
]
