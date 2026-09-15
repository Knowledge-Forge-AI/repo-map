"""Exact cleanup and aborted-admission closure for allocating test runs."""

from __future__ import annotations

import hashlib
import os
import shutil

from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.resource_ledger import ResourceLedger
from repomap_test_support.resource_ledger_io import write_private_json_exclusive
from repomap_test_support.resource_retention import TerminalOutcome
from repomap_test_support.resource_scratch import ScratchRunOwner, measure_scratch
from repomap_test_support.test_scratch import TestScratchLayout


def cleanup_unadmitted_layout(layout: TestScratchLayout) -> None:
    """Remove only exact transient groups of a refused, never-admitted request."""

    if not layout.allocated:
        raise RuntimeError("borrowed scratch cannot be cleaned by a borrower")
    roots = {
        layout.run_root / directory.relative_to(layout.run_root).parts[0]
        for directory in layout.directories()
    }
    for root in sorted(roots, key=lambda item: item.name):
        if root.is_symlink():
            raise RuntimeError("unadmitted transient scratch path is a symlink")
        if root.exists():
            shutil.rmtree(root)
        if root.exists() or root.is_symlink():
            raise RuntimeError("unadmitted transient scratch cleanup failed")


def process_start_evidence() -> str:
    try:
        import psutil

        started = psutil.Process(os.getpid()).create_time()
    except (ImportError, OSError) as error:
        raise RuntimeError("process start evidence is unavailable") from error
    seed = f"repomap-process-start-v1\0{os.getpid()}\0{started:.6f}".encode()
    return hashlib.sha256(seed).hexdigest()


def abort_admitted_start(
    layout: TestScratchLayout,
    index: AdvisoryIndex,
    *,
    now_seconds: int,
    stage: str,
    owner_token: str,
    ledger: ResourceLedger | None,
    scratch: ScratchRunOwner | None,
) -> None:
    if scratch is not None:
        try:
            scratch.cleanup_transient(record_boundaries=False)
        except RuntimeError:
            # Registration itself may be the injected failure. The exact layout
            # cleanup below remains authoritative for this aborted setup.
            pass
    cleanup_unadmitted_layout(layout)
    configuration = layout.run_root / "hygiene-configuration.json"
    if configuration.is_symlink():
        raise RuntimeError("aborted configuration evidence is unsafe")
    if configuration.exists():
        configuration.unlink()
    if ledger is not None:
        try:
            ledger.stamp_terminal(TerminalOutcome.FAILED, now_seconds)
        except RuntimeError:
            pass
    abort_path = layout.run_root / "admission-abort.json"
    write_private_json_exclusive(
        abort_path,
        {
            "schema": "repomap-test-hygiene-admission-abort-v1",
            "project": layout.project,
            "phase": layout.phase,
            "run_id": layout.run_root.name,
            "setup_stage": stage,
            "terminal_outcome": TerminalOutcome.FAILED.value,
            "closed_at_seconds": now_seconds,
        },
    )
    retained = [layout.manifest, abort_path]
    if ledger is not None and ledger.path.exists():
        retained.append(ledger.path)
    measurement = measure_scratch(layout.run_root, retained_paths=retained)
    index.close(
        run_id=layout.run_root.name,
        phase=layout.phase,
        terminal_outcome=TerminalOutcome.FAILED,
        retention_class="failed-evidence",
        allocated_bytes=measurement.allocated_bytes,
        inode_count=measurement.inode_count,
        retained_evidence_bytes=measurement.allocated_bytes,
        closed_at_seconds=now_seconds,
        owner_token=owner_token,
    )


__all__ = ["abort_admitted_start", "cleanup_unadmitted_layout", "process_start_evidence"]
