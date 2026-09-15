"""One isolated TEST-HYGIENE3B3 synthetic destructive-path proof."""

from __future__ import annotations

import json
import os
import socket
import stat
from pathlib import Path

import pytest

import test_hygiene_maintenance as maintenance_tool
from repomap_test_support.resource_hygiene_policy import HygieneProfile
from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.resource_interruption import (
    InterruptionOutcome,
    classify_interruption,
    operator_marker_path,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimPurpose,
    ProcessLiveness,
    register_protection,
)
from repomap_test_support.resource_operator_reclamation import CONFIRMATION_LITERAL
from repomap_test_support.resource_operator_reclamation_test_support import (
    PHASE,
    PROJECT,
    add_monitoring_link,
    add_run,
    private_root,
)
from repomap_test_support.resource_protection_authority import observe_protections
from repomap_test_support.resource_retention import RetentionClass, TerminalOutcome


@pytest.mark.skipif(
    os.environ.get("REPOMAP_TEST_HYGIENE3B3_FIX1_PROOF") != "1",
    reason="single TEST-HYGIENE3B3-FIX1 destructive proof requires exact opt-in",
)
def test_isolated_operator_reclamation_destructive_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    request: pytest.FixtureRequest,
) -> None:
    proof = tmp_path / "operator-proof"
    proof.mkdir(mode=0o700)
    root = private_root(proof)
    sentinel = tmp_path / "external-sentinel"
    sentinel.write_text("must survive", encoding="utf-8")

    terminal = add_run(root, "valid-terminal")
    report_pending = add_run(root, "report-pending")
    add_run(root, "ambiguous", exact=False)
    add_run(root, "foreign", project="other-project")
    live_run = add_run(root, "synthetic-live", state="running", pid=os.getpid())
    (root / "r" / "opaque.bin").write_bytes(b"opaque")
    (root / "r" / "external-link").symlink_to(sentinel)
    os.mkfifo(root / "r" / "co-tenant-fifo", mode=0o600)
    socket_path = root / "r" / "co-tenant.socket"
    original_cwd = os.getcwd()
    cwd_fd = os.open(".", os.O_RDONLY)
    bound_socket = socket.socket(socket.AF_UNIX)
    request.addfinalizer(bound_socket.close)
    try:
        os.chdir(root / "r")
        bound_socket.bind("co-tenant.socket")
    finally:
        try:
            os.fchdir(cwd_fd)
        finally:
            os.close(cwd_fd)

    assert os.getcwd() == original_cwd
    assert stat.S_ISSOCK(socket_path.lstat().st_mode)

    for name in (".gc", ".quarantine"):
        (root / name).mkdir(mode=0o700)
    quarantined = root / ".quarantine" / PROJECT / "retained-run"
    quarantined.mkdir(mode=0o700, parents=True)
    terminal_link = add_monitoring_link(root, terminal.name)
    live_link = add_monitoring_link(root, live_run.name)
    register_protection(
        root,
        PROJECT,
        report_pending.name,
        ClaimPurpose.REPORT_SOURCE_REGISTRATION,
        now_seconds=2,
    )
    register_protection(
        root,
        PROJECT,
        terminal.name,
        ClaimPurpose.OPERATOR_PIN_REGISTRATION,
        now_seconds=2,
    )

    index = AdvisoryIndex.open(root / ".index" / PROJECT, scratch_root=root)
    _admit(index, terminal.name, "a" * 32)
    index.close(
        run_id=terminal.name,
        phase=PHASE,
        terminal_outcome=TerminalOutcome.PASSED,
        retention_class=RetentionClass.SUCCESSFUL_EVIDENCE.value,
        allocated_bytes=terminal.stat().st_size,
        inode_count=2,
        retained_evidence_bytes=0,
        closed_at_seconds=3,
        owner_token="a" * 32,
    )
    _admit(index, live_run.name, "b" * 32)
    _admit(index, quarantined.name, "e" * 32)
    index.close(
        run_id=quarantined.name,
        phase=PHASE,
        terminal_outcome=TerminalOutcome.PASSED,
        retention_class=RetentionClass.SUCCESSFUL_EVIDENCE.value,
        allocated_bytes=10,
        inode_count=2,
        retained_evidence_bytes=10,
        closed_at_seconds=3,
        owner_token="e" * 32,
    )
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))

    try:
        assert os.getcwd() == original_cwd
        assert maintenance_tool.main(["operator-reclaim"]) == 2
        assert terminal.exists()
        capsys.readouterr()
        assert maintenance_tool.main(
            ["operator-reclaim", "--confirm", CONFIRMATION_LITERAL]
        ) == 2
        assert live_run.exists()
        capsys.readouterr()
        assert maintenance_tool.main(
            [
                "operator-reclaim",
                "--confirm",
                CONFIRMATION_LITERAL,
                "--force-live",
            ]
        ) == 2
        assert terminal.exists()
        capsys.readouterr()

        exit_code = maintenance_tool.main(
            [
                "operator-reclaim",
                "--confirm",
                CONFIRMATION_LITERAL,
                "--force-live",
                "--override-pins",
            ]
        )
    finally:
        bound_socket.close()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["outcome"] == "completed"
    assert output["barrier_released"] is True
    assert output["entry_count"] == 9
    assert tuple((root / "r").iterdir()) == ()
    assert sentinel.read_text(encoding="utf-8") == "must survive"
    assert not terminal_link.exists() and not terminal_link.is_symlink()
    assert not live_link.exists() and not live_link.is_symlink()
    for name in ("r", ".gc", ".quarantine", ".index", ".operator-reclamation"):
        assert (root / name).is_dir()

    marker = operator_marker_path(root, project=PROJECT, run_id=live_run.name)
    assert classify_interruption(
        marker,
        project=PROJECT,
        phase=PHASE,
        run_id=live_run.name,
        state_changed=True,
    ) is InterruptionOutcome.OPERATOR_INTERRUPTED
    assert quarantined.exists()
    assert {
        path.name for path in (root / ".index" / PROJECT / "runs").iterdir()
    } == {"retained-run.admitted.json", "retained-run.closed.json"}
    reconciled = AdvisoryIndex.open(
        root / ".index" / PROJECT, scratch_root=root
    ).reconcile()
    assert (reconciled.active_runs, reconciled.allocated_bytes, reconciled.inode_count) == (
        0,
        10,
        2,
    )
    protections = observe_protections(
        root, project=PROJECT, now_seconds=4
    )
    assert not protections.report_run_ids
    assert not protections.monitoring_run_ids
    assert not protections.pin_run_ids
    log = root / ".operator-reclamation" / "log" / "operator-reclamation.jsonl"
    public_text = log.read_text(encoding="utf-8")
    for private in (str(root), terminal.name, live_run.name):
        assert private not in public_text
    assert all(
        os.getpid() not in json.loads(line).values()
        for line in public_text.splitlines()
    )


@pytest.mark.skipif(
    os.environ.get("REPOMAP_TEST_HYGIENE3B3_FIX3_PROOF") != "1",
    reason="single TEST-HYGIENE3B3-FIX3 broad proof requires exact opt-in",
)
def test_fix3_exact_valid_liveness_scope_broad_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proof = tmp_path / "fix3-operator-proof"
    proof.mkdir(mode=0o700)
    root = private_root(proof)
    sentinel = tmp_path / "fix3-external-sentinel"
    sentinel.write_text("must survive", encoding="utf-8")

    terminal = add_run(root, "valid-terminal")
    valid_dead = add_run(root, "valid-dead", state="running", pid=888)
    add_run(
        root,
        "foreign-missing",
        project="other-project",
        state="running",
        pid=None,
    )
    add_run(
        root,
        "foreign-live",
        project="other-project",
        state="running",
        pid=777,
    )
    add_run(root, "ambiguous-running", exact=False, state="running", pid=None)
    (root / "r" / "opaque.bin").write_bytes(b"opaque")
    (root / "r" / "external-link").symlink_to(sentinel)
    os.mkfifo(root / "r" / "co-tenant-fifo", mode=0o600)
    socket_path = root / "r" / "co-tenant.socket"
    bound_socket = socket.socket(socket.AF_UNIX)
    original_cwd = os.getcwd()
    cwd_fd = os.open(".", os.O_RDONLY)
    try:
        os.chdir(root / "r")
        bound_socket.bind("co-tenant.socket")
    finally:
        try:
            os.fchdir(cwd_fd)
        finally:
            os.close(cwd_fd)
    assert os.getcwd() == original_cwd
    assert socket_path.is_socket()

    for name in (".gc", ".quarantine"):
        (root / name).mkdir(mode=0o700)
    terminal_link = add_monitoring_link(root, terminal.name)
    dead_link = add_monitoring_link(root, valid_dead.name)
    register_protection(
        root,
        PROJECT,
        terminal.name,
        ClaimPurpose.REPORT_SOURCE_REGISTRATION,
        now_seconds=2,
    )
    index = AdvisoryIndex.open(root / ".index" / PROJECT, scratch_root=root)
    _admit(index, terminal.name, "f" * 32)
    index.close(
        run_id=terminal.name,
        phase=PHASE,
        terminal_outcome=TerminalOutcome.PASSED,
        retention_class=RetentionClass.SUCCESSFUL_EVIDENCE.value,
        allocated_bytes=terminal.stat().st_size,
        inode_count=2,
        retained_evidence_bytes=0,
        closed_at_seconds=3,
        owner_token="f" * 32,
    )
    _admit(index, valid_dead.name, "1" * 32)
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))
    monkeypatch.setattr(
        maintenance_tool,
        "_process_is_live",
        lambda pid: (
            ProcessLiveness.LIVE if pid == 777 else ProcessLiveness.DEAD
        ),
    )

    try:
        exit_code = maintenance_tool.main(
            ["operator-reclaim", "--confirm", CONFIRMATION_LITERAL]
        )
    finally:
        bound_socket.close()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["outcome"] == "completed"
    assert output["force_live"] is False
    assert output["override_pins"] is False
    assert output["entry_count"] == 9
    assert (output["live_count"], output["unknown_count"]) == (0, 0)
    assert output["barrier_released"] is True
    assert tuple((root / "r").iterdir()) == ()
    assert sentinel.read_text(encoding="utf-8") == "must survive"
    assert not terminal_link.exists() and not terminal_link.is_symlink()
    assert not dead_link.exists() and not dead_link.is_symlink()
    for name in ("r", ".gc", ".quarantine", ".index", ".operator-reclamation"):
        assert (root / name).is_dir()
    assert not (root / ".index" / PROJECT / "admission.lock").exists()
    maintenance = root / ".maintenance" / PROJECT
    assert not tuple(maintenance.iterdir())
    assert not tuple((root / ".index" / PROJECT / "runs").iterdir())
    reconciled = AdvisoryIndex.open(
        root / ".index" / PROJECT, scratch_root=root
    ).reconcile()
    assert (reconciled.active_runs, reconciled.allocated_bytes) == (0, 0)
    protections = observe_protections(root, project=PROJECT, now_seconds=4)
    assert not protections.report_run_ids
    assert not protections.monitoring_run_ids
    assert not protections.pin_run_ids


def _admit(index: AdvisoryIndex, run_id: str, owner_token: str) -> None:
    index.admit(
        run_id=run_id,
        phase=PHASE,
        profile=HygieneProfile.ORDINARY,
        hard_watermark_bytes=10**12,
        hard_watermark_inodes=10**9,
        admitted_at_seconds=2,
        process_id=os.getpid(),
        process_start_evidence="c" * 64,
        owner_token=owner_token,
        configuration_sha256="d" * 64,
    )
