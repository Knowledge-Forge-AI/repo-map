"""Historical scratch GC discovery and mutation revalidation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from repomap_test_support.resource_ledger import (
    ResourceLedger,
    ResourceLedgerError,
    RunIdentity,
)
from repomap_test_support.resource_ledger_io import PrivateJsonError, read_private_json
from repomap_test_support.resource_receipts import (
    read_append_record,
    read_close_receipt,
    read_operator_release,
    report_source_release,
)
from repomap_test_support.resource_retention import RetentionClass, RetentionError
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    exact_object,
    nonnegative_int,
    sha256_hex,
)
from repomap_test_support.test_scratch import MANIFEST_SCHEMA

if TYPE_CHECKING:
    from repomap_test_support.resource_lifecycle_claim import ProcessLiveness
    from repomap_test_support.resource_scratch_history import (
        HistoricalGcCandidate,
        HistoricalGcDiscovery,
    )


def _history_owner():
    from repomap_test_support import resource_scratch_history

    return resource_scratch_history


def _lifecycle_owner():
    from repomap_test_support import resource_lifecycle_claim

    return resource_lifecycle_claim


def discover_historical_gc(
    scratch_root: Path,
    *,
    current_run_id: str,
    now_seconds: int,
    process_is_live: Callable[[int], ProcessLiveness | bool],
    active_report_run_ids: set[str],
    active_monitoring_run_ids: set[str],
    project: str = "repo-map_dev",
) -> HistoricalGcDiscovery:
    """Discover v2 ledger-era candidates; return advice, never mutation authority."""
    history = _history_owner()
    from repomap_test_support.resource_scratch import (
        ScratchAccountingError,
        measure_scratch,
    )

    runs = Path(scratch_root) / "r"
    protection_root = Path(scratch_root) / ".protections" / project
    eligible = []
    active = ambiguous = unexpired = pinned = report_held = monitoring_held = 0
    if not runs.exists():
        return history.HistoricalGcDiscovery((), 0, 0, 0, 0, 0, 0)
    if runs.is_symlink() or not runs.is_dir():
        return history.HistoricalGcDiscovery((), 0, 1, 0, 0, 0, 0)
    for run_root in sorted(runs.iterdir(), key=lambda item: item.name):
        if run_root.name == current_run_id:
            continue
        try:
            manifest = history._strict_manifest(run_root, project)
        except (OSError, ValueError):
            ambiguous += 1
            continue
        pid = manifest["pid"]
        if manifest["state"] == "running" or history._process_protects(process_is_live(pid)):
            active += 1
            continue
        if manifest["state"] not in {"passed", "failed", "stopped"}:
            ambiguous += 1
            continue
        if run_root.name in active_monitoring_run_ids:
            monitoring_held += 1
            continue
        if run_root.name in active_report_run_ids:
            report_held += 1
            continue
        try:
            monitoring_protected = history._valid_protection(
                protection_root / "monitoring" / f"{run_root.name}.json",
                project,
                run_root.name,
                "monitoring_registration",
            )
            pinned_protected = history._valid_protection(
                protection_root / "pins" / f"{run_root.name}.json",
                project,
                run_root.name,
                "operator_pin_registration",
            )
            report_protected = history._valid_protection(
                protection_root / "reports" / f"{run_root.name}.json",
                project,
                run_root.name,
                "report_source_registration",
            )
        except (PrivateJsonError, HygieneValidationError):
            ambiguous += 1
            continue
        if monitoring_protected:
            monitoring_held += 1
            continue
        if pinned_protected:
            pinned += 1
            continue
        try:
            ledger = ResourceLedger.open(
                run_root / "resource-ledger.json",
                RunIdentity(project, manifest["phase"], run_root.name),
            )
        except ResourceLedgerError:
            ambiguous += 1
            continue
        lifecycle = ledger.lifecycle
        terminal_at = lifecycle.terminal_at_seconds
        retention = lifecycle.retention_class
        if terminal_at is None:
            ambiguous += 1
            continue
        released_report_source = False
        if retention is RetentionClass.REPORT_SOURCE_PENDING_APPEND:
            released_report_source = history._report_source_released(run_root, now_seconds)
            if not released_report_source:
                report_held += 1
                continue
            retention = RetentionClass.HISTORICAL_GC_CANDIDATE
        elif retention.ttl_seconds is None:
            ambiguous += 1
            continue
        if (
            not released_report_source
            and (
                ledger.has_report_source()
                or report_protected
            )
        ):
            report_held += 1
            continue
        if retention.ttl_seconds is not None and now_seconds < terminal_at + retention.ttl_seconds:
            unexpired += 1
            continue
        try:
            measurement = measure_scratch(run_root, reject_unsafe_links=True)
            metadata = run_root.stat(follow_symlinks=False)
        except (OSError, ScratchAccountingError):
            ambiguous += 1
            continue
        eligible.append(
            history.HistoricalGcCandidate(
                run_root.name,
                manifest["phase"],
                run_root,
                metadata.st_dev,
                metadata.st_ino,
                measurement.allocated_bytes,
                measurement.inode_count,
                terminal_at,
                retention,
                not released_report_source
                and retention.over_retention_seconds is not None
                and now_seconds >= terminal_at + retention.over_retention_seconds,
            )
        )
    return history.HistoricalGcDiscovery(
        tuple(eligible), active, ambiguous, unexpired, pinned,
        report_held, monitoring_held,
    )


def revalidate_historical_candidate(
    candidate: HistoricalGcCandidate,
    *,
    scratch_root: Path,
    now_seconds: int,
    process_is_live: Callable[[int], ProcessLiveness | bool],
    active_report_run_ids: set[str],
    active_monitoring_run_ids: set[str],
    project: str = "repo-map_dev",
) -> HistoricalGcCandidate:
    history = _history_owner()
    discovery = history.discover_historical_gc(
        scratch_root,
        current_run_id="__maintenance__",
        now_seconds=now_seconds,
        process_is_live=process_is_live,
        active_report_run_ids=active_report_run_ids,
        active_monitoring_run_ids=active_monitoring_run_ids,
        project=project,
    )
    refreshed = next((item for item in discovery.eligible if item.run_id == candidate.run_id), None)
    if refreshed is None:
        protection_root = Path(scratch_root) / ".protections" / project
        protected = (
            candidate.run_id in active_report_run_ids
            or candidate.run_id in active_monitoring_run_ids
            or any(
                (protection_root / kind / f"{candidate.run_id}.json").exists()
                for kind in ("pins", "reports", "monitoring")
            )
        )
        try:
            manifest = history._strict_manifest(candidate.run_root, project)
            protected = (
                protected
                or manifest["state"] == "running"
                or history._process_protects(process_is_live(manifest["pid"]))
            )
        except (OSError, ValueError):
            pass
        raise history.HistoricalRevalidationError(
            "historical candidate is no longer eligible",
            category="active" if protected else "ambiguous",
        )
    if (
        refreshed.run_root != candidate.run_root
        or refreshed.device != candidate.device
        or refreshed.inode != candidate.inode
        or refreshed.phase != candidate.phase
        or refreshed.retention_class is not candidate.retention_class
        or refreshed.terminal_at_seconds != candidate.terminal_at_seconds
    ):
        raise history.HistoricalRevalidationError(
            "historical candidate identity changed", category="ambiguous"
        )
    return refreshed


def _strict_manifest(run_root: Path, project: str) -> dict:
    manifest_path = run_root / "manifest.json"
    ledger_path = run_root / "resource-ledger.json"
    if run_root.is_symlink() or not run_root.is_dir():
        raise ValueError("run root is unsafe")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("manifest is unsafe")
    if run_root.stat().st_uid != os.getuid() or manifest_path.stat().st_uid != os.getuid():
        raise ValueError("run ownership is foreign")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "schema", "project", "phase", "run_kind", "run_id", "pid",
        "physical_run_root", "monitoring_index_path", "state", "retention_policy",
    }
    if manifest.get("state") in {"passed", "failed", "stopped"}:
        required |= {"exit_status", "live_runtime_residue"}
    if type(manifest) is not dict or set(manifest) != required:
        raise ValueError("manifest fields are not exact")
    if (
        manifest["schema"] != MANIFEST_SCHEMA
        or manifest["project"] != project
        or manifest["run_kind"] != "test"
        or manifest["run_id"] != run_root.name
        or type(manifest["pid"]) is not int
        or Path(manifest["physical_run_root"]) != run_root
        or Path(manifest["physical_run_root"]).resolve() != run_root.resolve()
    ):
        raise ValueError("manifest identity is invalid")
    if ledger_path.is_symlink() or not ledger_path.is_file():
        raise ValueError("resource ledger identity is unsafe")
    if ledger_path.stat(follow_symlinks=False).st_uid != os.getuid():
        raise ValueError("resource ledger ownership is foreign")
    return manifest


def _report_source_released(run_root: Path, now_seconds: int) -> bool:
    reports = run_root / "reports"
    try:
        append = read_append_record(reports / "append-v2.json")
        receipt_path = reports / "close-receipt-v2.json"
        receipt = read_close_receipt(receipt_path) if receipt_path.is_file() else None
        release_path = reports / "operator-release.json"
        operator_release = (
            read_operator_release(release_path) if release_path.is_file() else None
        )
        return report_source_release(
            append,
            receipt,
            now_seconds=now_seconds,
            operator_release=operator_release,
        ).released
    except RetentionError:
        return False


def _valid_protection(
    path: Path, project: str, run_id: str, purpose: str
) -> bool:
    lifecycle = _lifecycle_owner()
    if not path.exists() and not path.is_symlink():
        return False
    payload = exact_object(
        read_private_json(path),
        {
            "schema", "project", "run_id", "purpose", "claim_record_id",
            "registered_at_seconds",
        },
        "run protection",
    )
    if (
        payload["schema"] != lifecycle.PROTECTION_SCHEMA
        or payload["project"] != project
        or payload["run_id"] != run_id
        or payload["purpose"] != purpose
    ):
        raise HygieneValidationError("run protection identity is invalid")
    sha256_hex(payload["claim_record_id"], "claim record id")
    nonnegative_int(payload["registered_at_seconds"], "registration timestamp")
    return True


def _process_protects(value: ProcessLiveness | bool) -> bool:
    lifecycle = _lifecycle_owner()
    return lifecycle.coerce_process_liveness(value) is not lifecycle.ProcessLiveness.DEAD
