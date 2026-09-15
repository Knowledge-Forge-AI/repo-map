"""TEST-HYGIENE3A-FIX1 index authority regressions."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from repomap_test_support import resource_index, resource_index_bootstrap
from repomap_test_support.resource_hygiene_policy import GIB, HygieneProfile
from repomap_test_support.resource_index import AdvisoryIndex, HostAdmissionRefused
from repomap_test_support.resource_ledger_io import PrivateJsonError
from repomap_test_support.resource_retention import TerminalOutcome


def _index_root(tmp_path: Path) -> Path:
    return tmp_path / ".index" / "repo-map_dev"


def _admit(index: AdvisoryIndex, run_id: str = "run1"):
    return index.admit(
        run_id=run_id,
        phase="TEST-HYGIENE3A-FIX1",
        profile=HygieneProfile.ORDINARY,
        hard_watermark_bytes=80 * GIB,
        hard_watermark_inodes=3_000_000,
        admitted_at_seconds=100,
        process_id=os.getpid(),
        process_start_evidence="b" * 64,
        owner_token="c" * 32,
        configuration_sha256="a" * 64,
    )


def test_nonempty_population_cannot_bootstrap_a_zero_summary(tmp_path: Path):
    historical = tmp_path / "r" / "preexisting-run"
    historical.mkdir(parents=True)

    with pytest.raises(HostAdmissionRefused, match="maintenance_required"):
        AdvisoryIndex.initialize_empty(
            _index_root(tmp_path),
            scratch_root=tmp_path,
            requesting_run_id=None,
            initialized_at_seconds=100,
        )


def test_same_filesystem_decoy_root_cannot_bootstrap_live_index(tmp_path: Path):
    live = tmp_path / "live"
    decoy = tmp_path / "decoy"
    (live / "r" / "preexisting-run").mkdir(parents=True)
    decoy.mkdir()

    with pytest.raises(HostAdmissionRefused, match="maintenance_required"):
        AdvisoryIndex.initialize_empty(
            _index_root(live),
            scratch_root=decoy,
            requesting_run_id=None,
            initialized_at_seconds=100,
        )

    assert not (_index_root(live) / "summary.json").exists()


def test_explicit_open_refuses_mismatched_same_filesystem_root(tmp_path: Path):
    live = tmp_path / "live"
    decoy = tmp_path / "decoy"
    live.mkdir()
    decoy.mkdir()
    index = AdvisoryIndex.initialize_empty(
        _index_root(live),
        scratch_root=live,
        requesting_run_id=None,
        initialized_at_seconds=100,
    )

    with pytest.raises(HostAdmissionRefused, match="maintenance_required"):
        AdvisoryIndex.open(index.root, scratch_root=decoy)


def test_admission_write_failure_releases_exact_lock(tmp_path: Path, monkeypatch):
    index = AdvisoryIndex.initialize_empty(
        _index_root(tmp_path),
        scratch_root=tmp_path,
        requesting_run_id=None,
        initialized_at_seconds=100,
    )
    write = resource_index.write_private_json_exclusive

    def fail_admission(path, payload):
        if Path(path).name.endswith(".admitted.json"):
            raise PrivateJsonError("injected admission write failure")
        return write(path, payload)

    monkeypatch.setattr(
        resource_index, "write_private_json_exclusive", fail_admission
    )

    with pytest.raises(resource_index.IndexError, match="creation failed"):
        _admit(index)

    assert not index.lock_path.exists()


def test_bootstrap_release_failure_preserves_maintenance_refusal(
    tmp_path: Path, monkeypatch
):
    (tmp_path / "r" / "preexisting-run").mkdir(parents=True)

    def fail_release(path, token):
        raise resource_index_bootstrap.IndexBootstrapError(
            "injected bootstrap release failure"
        )

    monkeypatch.setattr(resource_index_bootstrap, "_release_lock", fail_release)

    with pytest.raises(HostAdmissionRefused) as raised:
        AdvisoryIndex.initialize_empty(
            _index_root(tmp_path),
            scratch_root=tmp_path,
            requesting_run_id=None,
            initialized_at_seconds=100,
        )

    assert raised.value.maintenance_required is True


def test_summary_binds_filesystem_and_bootstrap_provenance(tmp_path: Path):
    index = AdvisoryIndex.initialize_empty(
        _index_root(tmp_path),
        scratch_root=tmp_path,
        requesting_run_id=None,
        initialized_at_seconds=100,
    )
    payload = json.loads(index.summary_path.read_text())

    assert payload["scratch_filesystem_id"]
    assert payload["initialization_mode"] == "safe_empty_bootstrap"
    assert payload["inventory_at_seconds"] == 100
    assert payload["provenance_record_id"]


def test_safe_empty_bootstrap_allows_only_exact_requesting_run(tmp_path: Path):
    current = tmp_path / "r" / "current-run"
    current.mkdir(parents=True)

    index = AdvisoryIndex.initialize_empty(
        _index_root(tmp_path),
        scratch_root=tmp_path,
        requesting_run_id="current-run",
        initialized_at_seconds=100,
    )

    assert index.reconcile().allocated_bytes == 0
    bootstrap = json.loads(index.bootstrap_path.read_text())
    assert bootstrap["population_entry_count"] == 1
    assert bootstrap["requesting_run_id"] == "current-run"


def test_summary_from_another_filesystem_identity_fails_closed(tmp_path: Path):
    index = AdvisoryIndex.initialize_empty(
        _index_root(tmp_path),
        scratch_root=tmp_path,
        requesting_run_id=None,
        initialized_at_seconds=100,
    )
    payload = json.loads(index.summary_path.read_text())
    payload["scratch_filesystem_id"] = "f" * 64
    index.summary_path.write_text(json.dumps(payload))

    with pytest.raises(HostAdmissionRefused, match="maintenance_required"):
        AdvisoryIndex.open(index.root, scratch_root=tmp_path)


def test_summary_impossible_against_filesystem_fails_closed(tmp_path: Path):
    index = AdvisoryIndex.initialize_empty(
        _index_root(tmp_path),
        scratch_root=tmp_path,
        requesting_run_id=None,
        initialized_at_seconds=100,
    )
    payload = json.loads(index.summary_path.read_text())
    payload["allocated_bytes"] = os.statvfs(tmp_path).f_blocks * os.statvfs(
        tmp_path
    ).f_frsize + 1
    index.summary_path.write_text(json.dumps(payload))

    with pytest.raises(HostAdmissionRefused, match="impossible"):
        index.reconcile()


def test_admission_record_contains_exact_owner_and_configuration(tmp_path: Path):
    index = AdvisoryIndex.initialize_empty(
        _index_root(tmp_path),
        scratch_root=tmp_path,
        requesting_run_id=None,
        initialized_at_seconds=100,
    )
    record = _admit(index)
    payload = json.loads(record.path.read_text())

    assert payload["schema"] == "repomap-test-hygiene-admission-v2"
    assert payload["process_id"] == os.getpid()
    assert payload["process_start_evidence"]
    assert payload["owner_token"]
    assert payload["configuration_sha256"] == "a" * 64


def test_close_record_contains_terminal_and_retained_facts(tmp_path: Path):
    index = AdvisoryIndex.initialize_empty(
        _index_root(tmp_path),
        scratch_root=tmp_path,
        requesting_run_id=None,
        initialized_at_seconds=100,
    )
    _admit(index)
    record = index.close(
        run_id="run1",
        phase="TEST-HYGIENE3A-FIX1",
        terminal_outcome=TerminalOutcome.FAILED,
        allocated_bytes=2,
        inode_count=2,
        retained_evidence_bytes=2,
        retention_class="failed-evidence",
        closed_at_seconds=200,
        owner_token="c" * 32,
    )
    payload = json.loads(record.path.read_text())

    assert payload["schema"] == "repomap-test-hygiene-close-v2"
    assert payload["terminal_outcome"] == "failed"
    assert payload["retained_evidence_bytes"] == 2


def test_qualification_requires_pre_request_bound_below_soft(tmp_path: Path):
    index = AdvisoryIndex.initialize_empty(
        _index_root(tmp_path),
        scratch_root=tmp_path,
        requesting_run_id=None,
        initialized_at_seconds=100,
    )
    summary = json.loads(index.summary_path.read_text())
    summary["allocated_bytes"] = 40 * GIB
    index.summary_path.write_text(json.dumps(summary))

    with pytest.raises(HostAdmissionRefused, match="soft_byte_watermark"):
        index.admit(
            run_id="qualification-run",
            phase="TEST-HYGIENE3A-FIX1",
            profile=HygieneProfile.QUALIFICATION,
            hard_watermark_bytes=120 * GIB,
            hard_watermark_inodes=3_000_000,
            admitted_at_seconds=100,
            process_id=os.getpid(),
            process_start_evidence="b" * 64,
            owner_token="c" * 32,
            configuration_sha256="a" * 64,
        )


def test_qualification_reports_soft_inode_watermark_separately(tmp_path: Path):
    index = AdvisoryIndex.initialize_empty(
        _index_root(tmp_path),
        scratch_root=tmp_path,
        requesting_run_id=None,
        initialized_at_seconds=100,
    )
    summary = json.loads(index.summary_path.read_text())
    summary["inode_count"] = 1_500_000
    index.summary_path.write_text(json.dumps(summary))

    with pytest.raises(HostAdmissionRefused, match="soft_inode_watermark"):
        index.admit(
            run_id="qualification-run",
            phase="TEST-HYGIENE3A-FIX1",
            profile=HygieneProfile.QUALIFICATION,
            hard_watermark_bytes=120 * GIB,
            hard_watermark_inodes=3_000_000,
            admitted_at_seconds=100,
            process_id=os.getpid(),
            process_start_evidence="b" * 64,
            owner_token="c" * 32,
            configuration_sha256="a" * 64,
        )
