"""TEST-HYGIENE3A immutable index and prospective-admission contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path

import pytest

from typing import TypedDict

from repomap_test_support.resource_hygiene_policy import GIB, HygieneProfile
from repomap_test_support.resource_ledger_io import write_private_json_exclusive
from repomap_test_support.resource_retention import TerminalOutcome
from repomap_test_support.resource_index import (
    AdvisoryIndex,
    HostAdmissionRefused,
    IndexError,
)


def _index(tmp_path: Path) -> AdvisoryIndex:
    return AdvisoryIndex.initialize_empty(
        tmp_path / ".index" / "repo-map_dev",
        scratch_root=tmp_path,
        requesting_run_id=None,
        initialized_at_seconds=1,
    )


class OwnerKwargs(TypedDict):
    process_id: int
    process_start_evidence: str
    owner_token: str
    configuration_sha256: str


def _owner() -> OwnerKwargs:
    return {
        "process_id": os.getpid(),
        "process_start_evidence": "a" * 64,
        "owner_token": "b" * 32,
        "configuration_sha256": "c" * 64,
    }


def test_admission_and_close_records_are_private_and_immutable(tmp_path: Path):
    index = _index(tmp_path)
    record = index.admit(
        run_id="run1",
        phase="TEST-HYGIENE3A",
        profile=HygieneProfile.ORDINARY,
        hard_watermark_bytes=80 * GIB,
        hard_watermark_inodes=3_000_000,
        admitted_at_seconds=100,
        **_owner(),
    )
    assert record.path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(IndexError, match="already exists"):
        index.admit(
            run_id="run1",
            phase="TEST-HYGIENE3A",
            profile=HygieneProfile.ORDINARY,
            hard_watermark_bytes=80 * GIB,
            hard_watermark_inodes=3_000_000,
            admitted_at_seconds=101,
            **_owner(),
        )
    close = index.close(
        run_id="run1",
        phase="TEST-HYGIENE3A",
        terminal_outcome=TerminalOutcome.PASSED,
        allocated_bytes=1,
        inode_count=1,
        retained_evidence_bytes=1,
        retention_class="successful-evidence",
        closed_at_seconds=200,
        owner_token="b" * 32,
    )
    assert close.path.stat().st_mode & 0o777 == 0o600


def test_concurrent_prospective_admission_includes_requester_quota(tmp_path: Path):
    index = _index(tmp_path)

    def request(run_id: str) -> str:
        try:
            index.admit(
                run_id=run_id,
                phase="TEST-HYGIENE3A",
                profile=HygieneProfile.INTEGRATION,
                hard_watermark_bytes=8 * GIB,
                hard_watermark_inodes=200_000,
                admitted_at_seconds=100,
                **_owner(),
            )
        except HostAdmissionRefused:
            return "refused"
        return "admitted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request, ["run1", "run2"]))
    assert sorted(results) == ["admitted", "refused"]


def test_stale_lock_and_malformed_summary_fail_closed(tmp_path: Path):
    index = _index(tmp_path)
    index.lock_path.write_text("stale")
    with pytest.raises(HostAdmissionRefused, match="lock"):
        index.admit(
            run_id="run1",
            phase="TEST-HYGIENE3A",
            profile=HygieneProfile.ORDINARY,
            hard_watermark_bytes=80 * GIB,
            hard_watermark_inodes=3_000_000,
            admitted_at_seconds=100,
            **_owner(),
        )
    assert index.lock_path.read_text() == "stale"


def test_record_cap_refuses_without_walking_run_roots(tmp_path: Path):
    index = _index(tmp_path)
    for number in range(513):
        (index.records_path / f"opaque-{number}.json").write_text("{}")
    with pytest.raises(HostAdmissionRefused, match="record cap"):
        index.reconcile()


def test_active_reservation_is_counted_even_when_summary_is_zero(tmp_path: Path):
    index = _index(tmp_path)
    index.admit(
        run_id="run1",
        phase="TEST-HYGIENE3A",
        profile=HygieneProfile.INTEGRATION,
        hard_watermark_bytes=16 * GIB,
        hard_watermark_inodes=400_000,
        admitted_at_seconds=100,
        **_owner(),
    )
    with pytest.raises(HostAdmissionRefused, match="hard_byte_watermark"):
        index.admit(
            run_id="run2",
            phase="TEST-HYGIENE3A",
            profile=HygieneProfile.INTEGRATION,
            hard_watermark_bytes=15 * GIB,
            hard_watermark_inodes=399_999,
            admitted_at_seconds=101,
            **_owner(),
        )


def test_close_for_another_phase_is_refused(tmp_path: Path):
    index = _index(tmp_path)
    index.admit(
        run_id="run1",
        phase="TEST-HYGIENE3A",
        profile=HygieneProfile.ORDINARY,
        hard_watermark_bytes=80 * GIB,
        hard_watermark_inodes=3_000_000,
        admitted_at_seconds=100,
        **_owner(),
    )
    with pytest.raises(IndexError, match="owner"):
        index.close(
            run_id="run1",
            phase="FOREIGN",
            terminal_outcome=TerminalOutcome.PASSED,
            allocated_bytes=1,
            inode_count=1,
            retained_evidence_bytes=1,
            retention_class="successful-evidence",
            closed_at_seconds=200,
            owner_token="b" * 32,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("generation", True), ("allocated_bytes", -1), ("inode_count", "0")],
)
def test_malformed_summary_numeric_values_refuse_admission(tmp_path: Path, field, value):
    index = _index(tmp_path)
    payload = json.loads(index.summary_path.read_text())
    payload[field] = value
    index.summary_path.write_text(json.dumps(payload))
    with pytest.raises(HostAdmissionRefused, match="summary"):
        index.reconcile()


def test_reconciliation_never_walks_historical_run_trees(tmp_path: Path):
    index = _index(tmp_path)
    historical = tmp_path / "r" / "opaque"
    historical.mkdir(parents=True)
    historical.chmod(0)
    try:
        assert index.reconcile().record_count == 0
    finally:
        historical.chmod(0o700)


def test_index_root_symlink_is_refused(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    index_parent = tmp_path / ".index"
    index_parent.mkdir()
    linked = index_parent / "repo-map_dev"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(IndexError, match="unsafe"):
        AdvisoryIndex.open(linked, scratch_root=tmp_path)


def test_lock_release_requires_exact_owner_record(tmp_path: Path):
    index = _index(tmp_path)
    token = index._acquire_lock(100)
    payload = json.loads(index.lock_path.read_text())
    payload["schema"] = "foreign-lock"
    index.lock_path.write_text(json.dumps(payload))

    with pytest.raises(IndexError, match="release failed"):
        index._release_lock(token)
    assert index.lock_path.exists()


def test_reconciliation_rejects_record_filename_alias(tmp_path: Path):
    index = _index(tmp_path)
    write_private_json_exclusive(
        index.records_path / "alias.admitted.json",
        {
            "schema": "repomap-test-hygiene-admission-v2",
            "run_id": "run1",
            "phase": "TEST-HYGIENE3A",
            "profile": "ordinary",
            "byte_quota": 2 * GIB,
            "inode_quota": 50_000,
            "process_id": os.getpid(),
            "process_start_evidence": "a" * 64,
            "owner_token": "b" * 32,
            "configuration_sha256": "c" * 64,
            "admitted_at_seconds": 100,
        },
    )
    with pytest.raises(HostAdmissionRefused, match="identity"):
        index.reconcile()


def test_reconciliation_rejects_close_without_admission(tmp_path: Path):
    index = _index(tmp_path)
    write_private_json_exclusive(
        index.records_path / "run1.closed.json",
        {
            "schema": "repomap-test-hygiene-close-v2",
            "run_id": "run1",
            "phase": "TEST-HYGIENE3A",
            "terminal_outcome": "passed",
            "allocated_bytes": 1,
            "inode_count": 1,
            "retained_evidence_bytes": 1,
            "retention_class": "successful-evidence",
            "closed_at_seconds": 200,
        },
    )
    with pytest.raises(HostAdmissionRefused, match="lacks its admission"):
        index.reconcile()


def test_v1_index_record_is_lower_authority_and_never_rewritten(tmp_path: Path):
    index = _index(tmp_path)
    legacy = index.records_path / "run1.admitted.json"
    payload = {
        "schema": "repomap-test-hygiene-admission-v1",
        "run_id": "run1",
        "phase": "TEST-HYGIENE3A",
        "profile": "ordinary",
        "byte_quota": 2 * GIB,
        "inode_quota": 50_000,
        "admitted_at_seconds": 100,
    }
    write_private_json_exclusive(legacy, payload)

    with pytest.raises(HostAdmissionRefused, match="invalid"):
        index.reconcile()

    assert json.loads(legacy.read_text()) == payload
