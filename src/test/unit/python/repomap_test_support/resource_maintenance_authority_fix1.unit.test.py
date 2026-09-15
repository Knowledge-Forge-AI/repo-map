"""TEST-HYGIENE3B1-FIX1 provider and real maintenance wiring contracts."""

from __future__ import annotations

import repomap_test_support.resource_protection_authority as resource_protection_authority_owner

import hashlib
import json
from pathlib import Path


import test_hygiene_maintenance as maintenance_tool
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_index import AdvisoryIndex, ReconciledBound
from repomap_test_support.resource_ledger import (
    ResourceKind,
    ResourceLedger,
    RetainedReason,
    RunIdentity,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimPurpose,
    ClaimRegistry,
    register_protection,
)
from repomap_test_support.resource_quarantine_gc import quarantine_batch
from repomap_test_support.resource_receipts import (
    verify_appended_report_packet,
    write_close_receipt,
)
from repomap_test_support.resource_scratch_history import discover_historical_gc


NOW = 2_000_000


def _root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    (tmp_path / "r").mkdir(mode=0o700)
    return tmp_path


def _run(
    root: Path,
    run_id: str,
    *,
    phase: str = "TEST-HYGIENE3B1-FIX1",
    report_source: bool = False,
) -> Path:
    run = root / "r" / run_id
    run.mkdir(mode=0o700)
    monitoring = root / "index" / "repo-map_dev" / phase / run_id
    manifest = {
        "schema": "repomap-test-scratch-manifest-v1",
        "project": "repo-map_dev",
        "phase": phase,
        "run_kind": "test",
        "run_id": run_id,
        "pid": 999_999,
        "physical_run_root": str(run),
        "monitoring_index_path": str(monitoring),
        "state": "passed",
        "retention_policy": "operator_review",
        "exit_status": 0,
        "live_runtime_residue": False,
    }
    (run / "manifest.json").write_text(json.dumps(manifest))
    (run / "manifest.json").chmod(0o600)
    ledger = ResourceLedger.create(
        run / "resource-ledger.json",
        RunIdentity("repo-map_dev", phase, run_id),
        now_seconds=0,
    )
    if report_source:
        evidence = run / "report-source.txt"
        evidence.write_text("public-safe")
        evidence.chmod(0o600)
        ledger.register(
            ResourceKind.SCRATCH_EVIDENCE_GROUP,
            str(evidence),
            creation_owner="phase",
            created_before_run=False,
            creation_observed=True,
            cleanup_required=False,
            retained=True,
            retained_reason=RetainedReason.REPORT_SOURCE,
            size_bytes=11,
            inode_count=1,
        )
    ledger.stamp_terminal("passed", 1, report_source_pending=report_source)
    return run


def _packet(report_id: str) -> bytes:
    boundary = b"=" * 80
    payload = b"public-safe operational payload\n"
    fields = (
        b"ENVELOPE-FORMAT: agent-report-record\n"
        b"ENVELOPE-VERSION: 1\n"
        b"RECORD-TYPE: operational-report\n"
        b"RECORD-FORMAT-VERSION: 1\n"
        + f"RECORD-ID: {report_id}\n".encode()
        + b"PROJECT: repo-map_dev\n"
        + b"PHASE: TEST-HYGIENE3B1-FIX1\n"
    )
    return b"".join(
        (
            boundary, b"\nBEGIN AGENT-REPORT-RECORD\n", fields,
            b"PAYLOAD-SHA256: " + hashlib.sha256(payload).hexdigest().encode() + b"\n",
            b"PAYLOAD-SIZE-BYTES: " + str(len(payload)).encode() + b"\n",
            boundary, b"\n", payload, boundary, b"\nEND AGENT-REPORT-RECORD\n",
            fields, b"RECORD-COMPLETE: true\n", boundary, b"\n",
        )
    )


def _monitor(root: Path, run: Path, phase: str = "TEST-HYGIENE3B1-FIX1") -> Path:
    link = root / "index" / "repo-map_dev" / phase / run.name
    link.parent.mkdir(mode=0o700, parents=True)
    depth = len(link.relative_to(root).parts) - 1
    link.symlink_to(Path(*([".."] * depth)) / "r" / run.name)
    return link


def _maintenance(root: Path):
    registry = ClaimRegistry(root)
    handle = registry.acquire_maintenance("quarantine", now_seconds=NOW)
    ledger = GcLedger.create(
        root,
        project="repo-map_dev",
        pass_id="pass1",
        trigger="operator_requested",
        configuration_digest="d" * 64,
        maintenance_owner_token=handle.owner_token,
        now_seconds=NOW,
    )
    return registry, handle, ledger


def test_r10_real_path_refuses_when_protection_authority_unavailable(
    tmp_path: Path, monkeypatch, capsys
):
    root = _root(tmp_path)
    AdvisoryIndex.initialize_empty(
        root / ".index" / "repo-map_dev",
        scratch_root=root,
        requesting_run_id=None,
        initialized_at_seconds=0,
    )
    _run(root, "eligible")
    monkeypatch.setattr(maintenance_tool, "select_scratch_root", lambda environ: root)

    def unavailable(*args, **kwargs):
        raise RuntimeError("injected unavailable authority")

    result = maintenance_tool.main(
        ["quarantine"], protection_provider_factory=unavailable
    )
    output = capsys.readouterr().out

    assert result == 2
    assert "historical_gc_refused" in output
    assert "protection_authority_unavailable" in output
    assert (root / "r" / "eligible").is_dir()
    assert not (root / ".quarantine" / "repo-map_dev" / "eligible").exists()


def test_r11_authoritative_report_monitoring_and_pin_observation(tmp_path: Path):
    subject = resource_protection_authority_owner
    root = _root(tmp_path)
    report = _run(root, "report-held")
    monitored = _run(root, "monitoring-held")
    pinned = _run(root, "pinned")
    register_protection(
        root,
        "repo-map_dev",
        report.name,
        ClaimPurpose.REPORT_SOURCE_REGISTRATION,
        now_seconds=NOW,
    )
    register_protection(
        root,
        "repo-map_dev",
        monitored.name,
        ClaimPurpose.MONITORING_REGISTRATION,
        now_seconds=NOW,
    )
    register_protection(
        root,
        "repo-map_dev",
        pinned.name,
        ClaimPurpose.OPERATOR_PIN_REGISTRATION,
        now_seconds=NOW,
    )
    monitoring_link = _monitor(root, monitored)

    observation = subject.observe_protections(
        root, project="repo-map_dev", now_seconds=NOW + 1
    )
    public = subject.public_protection_projection(observation)

    assert observation.observed_at_seconds == NOW + 1
    assert observation.provider_record_id
    assert observation.report_run_ids == frozenset({report.name})
    assert observation.monitoring_run_ids == frozenset({monitored.name})
    assert observation.pin_run_ids == frozenset({pinned.name})
    assert public == {"report_protections": 1, "monitoring_protections": 1, "pins": 1}
    assert report.name not in repr(public)
    assert monitored.name not in repr(public)
    assert pinned.name not in repr(public)
    assert monitoring_link.resolve() == monitored.resolve()


def test_r11_report_source_pending_append_and_closed_grace_authority(tmp_path: Path):
    subject = resource_protection_authority_owner
    root = _root(tmp_path)
    pending = _run(root, "pending", report_source=True)
    released = _run(root, "released", report_source=True)

    pending_observation = subject.observe_protections(
        root, project="repo-map_dev", now_seconds=NOW
    )
    assert pending_observation.report_run_ids == frozenset({pending.name, released.name})

    reports = released / "reports"
    reports.mkdir(mode=0o700, parents=True)
    report_id = "OPERATIONAL-REPORT-" + "a" * 64
    packet = reports / "packet.txt"
    packet.write_bytes(_packet(report_id))
    packet.chmod(0o600)
    append = verify_appended_report_packet(
        reports / "append-v2.json",
        packet_path=packet,
        phase="TEST-HYGIENE3B1-FIX1",
        run_id="released",
        expected_report_id=report_id,
        append_verified_at_seconds=100,
    )
    write_close_receipt(
        reports / "close-receipt-v2.json",
        phase="TEST-HYGIENE3B1-FIX1",
        run_id="released",
        commit="b" * 40,
        commit_verified_at_seconds=150,
        append=append,
        closed_at_seconds=200,
    )

    grace = subject.observe_protections(
        root, project="repo-map_dev", now_seconds=200 + 86_399
    )
    after_grace = subject.observe_protections(
        root, project="repo-map_dev", now_seconds=200 + 86_400
    )

    assert grace.report_run_ids == frozenset({"pending", "released"})
    assert after_grace.report_run_ids == frozenset({"pending"})


def test_r11_revalidation_refreshes_provider_while_claim_is_held(tmp_path: Path):
    subject = resource_protection_authority_owner
    root = _root(tmp_path)
    run = _run(root, "eligible")
    candidate = discover_historical_gc(
        root,
        current_run_id="current",
        now_seconds=NOW,
        process_is_live=lambda pid: False,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
    ).eligible[0]
    registry, maintenance, ledger = _maintenance(root)
    calls: list[bool] = []

    def provider(now_seconds: int):
        calls.append((registry.root / "eligible.claim.json").is_file())
        return subject.ProtectionObservation.create(
            project="repo-map_dev",
            observed_at_seconds=now_seconds,
            report_run_ids={"eligible"},
            monitoring_run_ids=set(),
            pin_run_ids=set(),
        )

    result = quarantine_batch(
        root,
        registry,
        maintenance,
        ledger,
        (candidate,),
        now_seconds=NOW,
        process_is_live=lambda pid: False,
        active_report_run_ids=set(),
        active_monitoring_run_ids=set(),
        protection_provider=provider,
    )

    assert calls == [True]
    assert result.quarantined == ()
    assert result.active_or_protected == 1
    assert run.is_dir()


def test_monitoring_link_is_active_protection_and_never_dangles(tmp_path: Path):
    subject = resource_protection_authority_owner
    root = _root(tmp_path)
    run = _run(root, "monitored")
    link = _monitor(root, run)
    observation = subject.observe_protections(
        root, project="repo-map_dev", now_seconds=NOW
    )
    discovery = discover_historical_gc(
        root,
        current_run_id="current",
        now_seconds=NOW,
        process_is_live=lambda pid: False,
        active_report_run_ids=set(observation.report_run_ids),
        active_monitoring_run_ids=set(observation.monitoring_run_ids),
    )

    assert discovery.monitoring_held_count == 1
    assert discovery.eligible == ()
    assert link.is_symlink() and link.resolve() == run.resolve()
    assert not (root / ".quarantine" / "repo-map_dev" / run.name).exists()


def test_r12_real_command_stops_after_index_drops_below_soft(
    tmp_path: Path, monkeypatch, capsys
):
    subject = resource_protection_authority_owner
    root = _root(tmp_path)
    actual = AdvisoryIndex.initialize_empty(
        root / ".index" / "repo-map_dev",
        scratch_root=root,
        requesting_run_id=None,
        initialized_at_seconds=0,
    )
    _run(root, "eligible-a")
    _run(root, "eligible-b")
    bounds = iter(
        [
            ReconciledBound(50 * 1024**3, 2_000_000, 0, 0, 0),
            ReconciledBound(1, 1, 0, 0, 0),
        ]
    )
    monkeypatch.setattr(actual, "reconcile", lambda: next(bounds))
    monkeypatch.setattr(
        maintenance_tool.AdvisoryIndex,
        "open",
        lambda root, scratch_root: actual,
    )
    monkeypatch.setattr(maintenance_tool, "select_scratch_root", lambda environ: root)

    def factory(*args, **kwargs):
        return lambda now_seconds: subject.ProtectionObservation.create(
            project="repo-map_dev",
            observed_at_seconds=now_seconds,
            report_run_ids=set(),
            monitoring_run_ids=set(),
            pin_run_ids=set(),
        )

    result = maintenance_tool.main(
        ["quarantine"], protection_provider_factory=factory
    )
    output = capsys.readouterr().out
    remaining = sorted(path.name for path in (root / "r").iterdir())
    quarantined = sorted(
        path.name for path in (root / ".quarantine" / "repo-map_dev").iterdir()
    )

    assert result == 0
    assert len(remaining) == 1
    assert len(quarantined) == 1
    assert "'stop_reason': 'below_soft'" in output
