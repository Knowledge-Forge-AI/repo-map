"""Synthetic TEST-HYGIENE3B3 fixtures; never select shared scratch."""

from __future__ import annotations

import json
from pathlib import Path

from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.resource_ledger_io import write_private_json_exclusive
from repomap_test_support.resource_lifecycle_claim import ProcessLiveness


PROJECT = "repo-map_dev"
PHASE = "TEST-HYGIENE3B3"


def private_root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    (tmp_path / "r").mkdir(mode=0o700)
    AdvisoryIndex.initialize_empty(
        tmp_path / ".index" / PROJECT,
        scratch_root=tmp_path,
        requesting_run_id=None,
        initialized_at_seconds=1,
    )
    return tmp_path


def add_run(
    root: Path,
    run_id: str,
    *,
    state: str = "passed",
    pid: int | None = 999_999,
    project: str = PROJECT,
    exact: bool = True,
    payload: bytes = b"fixture",
) -> Path:
    run = root / "r" / run_id
    run.mkdir(mode=0o700)
    (run / "payload.bin").write_bytes(payload)
    manifest = {
        "schema": "repomap-test-scratch-manifest-v1",
        "project": project,
        "phase": PHASE,
        "run_kind": "test",
        "run_id": run_id,
        "pid": pid,
        "physical_run_root": str(run),
        "monitoring_index_path": str(
            root / "index" / PROJECT / PHASE / run_id
        ),
        "state": state,
        "retention_policy": "operator_review",
    }
    if state != "running":
        manifest.update(
            exit_status=0,
            live_runtime_residue=False,
        )
    if not exact:
        manifest.pop("run_kind")
    path = run / "manifest.json"
    path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return run


def add_monitoring_link(root: Path, run_id: str, *, phase: str = PHASE) -> Path:
    directory = root / "index" / PROJECT / phase
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    link = directory / run_id
    link.symlink_to(root / "r" / run_id)
    return link


def add_pin(root: Path, run_id: str, *, valid: bool = True) -> Path:
    directory = root / ".protections" / PROJECT / "pins"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    (root / ".protections").chmod(0o700)
    (root / ".protections" / PROJECT).chmod(0o700)
    directory.chmod(0o700)
    path = directory / f"{run_id}.json"
    payload = (
        {
            "schema": "repomap-test-run-protection-v1",
            "project": PROJECT,
            "run_id": run_id,
            "purpose": "operator_pin_registration",
            "claim_record_id": "a" * 64,
            "registered_at_seconds": 1,
        }
        if valid
        else {"schema": "malformed"}
    )
    write_private_json_exclusive(path, payload)
    return path


def dead(_pid: int) -> ProcessLiveness:
    return ProcessLiveness.DEAD


def live(_pid: int) -> ProcessLiveness:
    return ProcessLiveness.LIVE


def unknown(_pid: int) -> ProcessLiveness:
    return ProcessLiveness.UNKNOWN
