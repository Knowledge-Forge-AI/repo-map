"""Adversarial regression matrix for child coverage registration atomicity and diagnostics."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys

import coverage
import pytest

from runner_coverage import ChildCoverageSession
from runner_coverage_execution import (
    ShardDiagnosticSnapshot,
    create_shard_snapshot,
    read_registered_children,
    reconcile_child_manifests,
)
from runner_portable_coverage import validate_shard_directory_integrity
from runner_integration_obligations import (
    COV5G_OWNER_SHA256,
    MAINTAINED_INTENTIONAL_VICTIM_DECLARATIONS,
)


def _setup_session(tmp_path: Path, suite: str = "int") -> ChildCoverageSession:
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    (source / "mod.py").write_text("VALUE = 42\n", encoding="utf-8")
    return ChildCoverageSession(
        coverage_module=coverage,
        scratch_dir=tmp_path / "measure",
        source_root=source,
        suite=suite,
    )


def test_normal_registered_child_accepted(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            res = subprocess.run([sys.executable, "-c", "pass"], capture_output=True)
            assert res.returncode == 0
            runner.stop()
            runner.save()
            registered = read_registered_children(
                session.child_manifest_dir, session.session_dir.name, "int"
            )
            assert len(registered) == 1
            pid, record = next(iter(registered.items()))
            assert record["cov_start"] == 1 and record["exited"]
            assert record["strict"] is True
            combined = session.combine(runner)
            assert combined is not None
    finally:
        session.cleanup()


def test_missing_manifest_authority_fails_closed(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            env = dict(os.environ)
            env.pop("COVERAGE_CHILD_MANIFEST_DIR", None)
            res = subprocess.run([sys.executable, "-c", "pass"], env=env, capture_output=True)
            assert res.returncode == 0

            # No shard was written to data_dir by the un-manifested child
            shards_before_parent_save = [p for p in session.data_dir.iterdir() if p.name.startswith(".coverage.")]
            assert not shards_before_parent_save

            runner.stop()
            runner.save()

            # Diagnostic was written to fallback manifest directory
            diag_files = list(session.child_manifest_dir.glob("*.registration_failure"))
            assert len(diag_files) == 1
            diag_text = diag_files[0].read_text(encoding="utf-8")
            assert "failure_class=missing_manifest_authority" in diag_text
            assert "has_manifest=0" in diag_text

            registered = read_registered_children(
                session.child_manifest_dir, session.session_dir.name, "int"
            )
            assert len(registered) == 1
            rec = next(iter(registered.values()))
            assert rec["registration_failure"] is True
            assert rec["failure_class"] == "missing_manifest_authority"

            with pytest.raises(RuntimeError, match="missing_manifest_authority"):
                session.combine(runner)
            snap = session.diagnostic_snapshots[-1]
            assert snap.failure_class == "missing_manifest_authority"
            assert snap.termination_outcome == "registration_failed"
    finally:
        session.cleanup()


def test_marker_creation_collision_fails_closed(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            token = "f" * 32
            # Pre-create the start marker to force FileExistsError collision
            (session.child_manifest_dir / f"{token}.start").write_text("collision", encoding="utf-8")

            env = dict(os.environ, COVERAGE_CHILD_REGISTRATION_TOKEN=token)
            res = subprocess.run([sys.executable, "-c", "pass"], env=env, capture_output=True)
            assert res.returncode == 0
            runner.stop()
            runner.save()

            diag_files = list(session.child_manifest_dir.glob("*.registration_failure"))
            assert len(diag_files) == 1
            diag_text = diag_files[0].read_text(encoding="utf-8")
            assert "failure_class=token_reuse" in diag_text

            registered = read_registered_children(
                session.child_manifest_dir, session.session_dir.name, "int"
            )
            rec = next(iter(registered.values()))
            assert rec["registration_failure"] is True

            with pytest.raises(RuntimeError, match="token_reuse"):
                session.combine(runner)
    finally:
        session.cleanup()


def test_unregistered_valid_sqlite_shard_rejected(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            runner = session.create_coverage(coverage)
            orphan_path = session.data_dir / ".coverage.orphan"
            orphan_cov = coverage.Coverage(data_file=str(orphan_path))
            orphan_cov.start()
            orphan_cov.stop()
            orphan_cov.save()
            assert orphan_path.is_file() and orphan_path.stat().st_size > 0

            with pytest.raises(RuntimeError, match="unregistered coverage shard rejected: .coverage.orphan"):
                validate_shard_directory_integrity(
                    session.data_dir, set(), None,
                    session._create_snapshot, session._record_diagnostic, coverage,
                )
            snap = session.diagnostic_snapshots[-1]
            assert snap.reader_status == "unregistered_shard_rejected"
            assert snap.termination_outcome == "unregistered_child"
    finally:
        session.cleanup()


def test_zero_byte_unregistered_shard_rejected(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            zero_shard = session.data_dir / ".coverage.zero_byte"
            zero_shard.write_bytes(b"")
            with pytest.raises(RuntimeError, match="unregistered coverage shard rejected: .coverage.zero_byte"):
                validate_shard_directory_integrity(
                    session.data_dir, set(), None,
                    session._create_snapshot, session._record_diagnostic, coverage,
                )
            snap = session.diagnostic_snapshots[-1]
            assert snap.shard_name == ".coverage.zero_byte"
            assert snap.size_bytes == 0
            assert snap.reader_status == "unregistered_shard_rejected"
            assert snap.termination_outcome == "unregistered_child"
    finally:
        session.cleanup()


def test_unregistered_12hex_hostname_shard_rejected(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            # Simulate shard name from hosted run 12
            shard_name = ".coverage.398370f43f11.pid12161.XF1IuM5x.HNQIp837rWOh"
            shard_path = session.data_dir / shard_name
            c = coverage.Coverage(data_file=str(shard_path))
            c.start()
            c.stop()
            c.save()

            with pytest.raises(RuntimeError, match="unregistered coverage shard rejected"):
                validate_shard_directory_integrity(
                    session.data_dir, set(), None,
                    session._create_snapshot, session._record_diagnostic, coverage,
                )
            snap = session.diagnostic_snapshots[-1]
            assert snap.shard_name == shard_name
            assert snap.file_type == "unregistered"
            assert snap.reader_status == "unregistered_shard_rejected"
            assert snap.child_probe_id == "pid=12161"
    finally:
        session.cleanup()


def test_stale_cross_invocation_registration_rejected(tmp_path):
    manifest = tmp_path / "child_procs"
    manifest.mkdir()
    (manifest / "101.start").write_text(
        "pid=101\ninvocation=stale_inv\nsuite=int\nrevision=rev1\nrole=inherited-python\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="child invocation identity mismatch"):
        read_registered_children(manifest, expected_invocation="fresh_inv", expected_suite="int")

    (manifest / "101.start").write_text(
        "pid=101\ninvocation=fresh_inv\nsuite=staging\nrevision=rev1\nrole=inherited-python\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="child suite identity mismatch"):
        read_registered_children(manifest, expected_invocation="fresh_inv", expected_suite="int")

    (manifest / "101.start").write_text(
        "pid=101\ninvocation=fresh_inv\nsuite=int\nrevision=stale_rev\nrole=inherited-python\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="child source identity mismatch"):
        read_registered_children(
            manifest, expected_invocation="fresh_inv", expected_suite="int", expected_revision="fresh_rev"
        )


def test_stale_cross_invocation_registration_failure_rejected(tmp_path):
    manifest = tmp_path / "child_procs"
    manifest.mkdir()
    (manifest / "101.registration_failure").write_text(
        "pid=101\ninvocation=stale_inv\nsuite=int\nrevision=rev1\nfailure_class=marker_collision\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="child invocation identity mismatch"):
        read_registered_children(manifest, expected_invocation="fresh_inv", expected_suite="int")


def test_token_reuse_rejected(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            tok = "a" * 32
            # Simulate a pre-existing start marker for this token
            (session.child_manifest_dir / f"{tok}.start").write_text("prior_worker", encoding="utf-8")
            env = dict(os.environ, COVERAGE_CHILD_REGISTRATION_TOKEN=tok)
            subprocess.run([sys.executable, "-c", "pass"], env=env, capture_output=True)

            diag_files = list(session.child_manifest_dir.glob("*.registration_failure"))
            assert len(diag_files) == 1
            content = diag_files[0].read_text(encoding="utf-8")
            assert "failure_class=token_reuse" in content
            assert f"token_hash={hashlib.sha256(tok.encode()).hexdigest()}" in content
            assert tok not in content.split("token_hash=")[0]
    finally:
        session.cleanup()


def test_grandchild_token_inheritance_neutralized(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            token = "t" * 32
            child_shard = session.data_dir / f".coverage.{token}"
            env = dict(
                os.environ,
                COVERAGE_CHILD_REGISTRATION_TOKEN=token,
                COVERAGE_FILE=str(child_shard),
                COVERAGE_CHILD_LAUNCH_ROLE="portable",
            )
            # Child verifies that the token was consumed, then spawns a grandchild
            child_code = (
                "import subprocess, sys, os\n"
                "assert 'COVERAGE_CHILD_REGISTRATION_TOKEN' not in os.environ\n"
                "res = subprocess.run([sys.executable, '-c', "
                "'import os; assert \"COVERAGE_CHILD_REGISTRATION_TOKEN\" not in os.environ'], "
                "capture_output=True)\n"
                "sys.exit(res.returncode)\n"
            )
            res = subprocess.run([sys.executable, "-c", child_code], env=env, capture_output=True)
            assert res.returncode == 0, f"Child execution failed: {res.stderr.decode()}"
            runner.stop()
            runner.save()

            # No registration failure was logged
            fail_markers = list(session.child_manifest_dir.glob("*.registration_failure"))
            assert not fail_markers
    finally:
        session.cleanup()


def test_pid_identity_cannot_substitute_for_registration_authority(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            fake_shard = session.data_dir / ".coverage.host.pid8888.xxxx"
            fake_shard.write_bytes(b"SQLite format 3\x00data")
            with pytest.raises(RuntimeError, match="unregistered coverage shard rejected"):
                validate_shard_directory_integrity(
                    session.data_dir, set(), None,
                    session._create_snapshot, session._record_diagnostic, coverage,
                    registered_children={}, child_manifest_dir=session.child_manifest_dir,
                )
            snap = session.diagnostic_snapshots[-1]
            assert snap.child_probe_id == "pid=8888"
            assert snap.termination_outcome == "unregistered_child"
    finally:
        session.cleanup()


def test_fix1_intentional_victim_preserved(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            manifest = session.child_manifest_dir
            # Guarantee a dead PID by spawning and waiting for non-Python process termination
            dead_proc = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
            dead_proc.wait()
            pid = dead_proc.pid

            (manifest / f"{pid}.start").write_text(
                f"pid={pid}\ninvocation={session.session_dir.name}\nsuite=int\n"
                f"role=intentional-victim\nowner={COV5G_OWNER_SHA256}\ncov_start=1\n",
                encoding="utf-8",
            )
            (manifest / f"{pid}.victim").write_text(
                f"pid={pid}\nowner={COV5G_OWNER_SHA256}\ninvocation={session.session_dir.name}\n"
                f"backend_disappeared=1\ndescriptor_closed=1\nprocess_cleaned=1\nexitcode=-9\n",
                encoding="utf-8",
            )
            registered = read_registered_children(manifest, session.session_dir.name, "int")
            assert pid in registered
            assert registered[pid]["victim_receipt"] is not None

            consumed, shards = reconcile_child_manifests(
                registered_children=registered,
                shard_paths_set=set(),
                child_manifest_dir=manifest,
                parent_data_path=str(session.data_file),
                parent_pid=os.getpid(),
                snapshot_fn=session._create_snapshot,
                record_fn=session._record_diagnostic,
                cov_mod=coverage,
            )
            assert not shards
            snap = session.diagnostic_snapshots[-1]
            assert snap.file_type == "intentional_victim"
            assert snap.reader_status == "intentional_victim_receipt_verified"
            assert snap.termination_outcome == "intentional_victim_terminated"
            assert snap.launch_role == "intentional-victim"
            assert snap.test_owner == COV5G_OWNER_SHA256
    finally:
        session.cleanup()


def test_unregistered_lookalike_cannot_impersonate_victim(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            manifest = session.child_manifest_dir
            dead_proc = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
            dead_proc.wait()
            pid = dead_proc.pid

            # Foreign owner does not match maintained intentional victim declaration
            (manifest / f"{pid}.start").write_text(
                f"pid={pid}\ninvocation={session.session_dir.name}\nsuite=int\n"
                f"role=intentional-victim\nowner={'0'*64}\ncov_start=1\n",
                encoding="utf-8",
            )
            (manifest / f"{pid}.victim").write_text(
                f"pid={pid}\nowner={'0'*64}\nbackend_disappeared=1\n"
                f"descriptor_closed=1\nprocess_cleaned=1\nexitcode=-9\n",
                encoding="utf-8",
            )
            registered = read_registered_children(manifest, session.session_dir.name, "int")
            with pytest.raises(RuntimeError, match="terminal receipt is incomplete"):
                reconcile_child_manifests(
                    registered_children=registered,
                    shard_paths_set=set(),
                    child_manifest_dir=manifest,
                    parent_data_path=str(session.data_file),
                    parent_pid=os.getpid(),
                    snapshot_fn=session._create_snapshot,
                    record_fn=session._record_diagnostic,
                    cov_mod=coverage,
                )
    finally:
        session.cleanup()


def test_narrow_resource_tracker_boundary_preserved(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            lookalike = "from multiprocessing.resource_tracker import main; print('not tracker')"
            res = subprocess.run([sys.executable, "-c", lookalike], env=dict(os.environ), capture_output=True)
            assert res.returncode == 0
            runner.stop()
            runner.save()

            registered = read_registered_children(session.child_manifest_dir, session.session_dir.name, "int")
            rec = next(iter(registered.values()))
            assert rec["auxiliary"] is False
            assert rec["strict"] is True
            assert rec["role"] != "auxiliary-runtime"
    finally:
        session.cleanup()


def test_auxiliary_runtime_exempt_from_failure(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            tracker_cmd = "from multiprocessing.resource_tracker import main;main(42)"
            env = dict(os.environ)
            env.pop("COVERAGE_CHILD_MANIFEST_DIR", None)
            subprocess.run([sys.executable, "-c", tracker_cmd], env=env, capture_output=True)
            runner.stop()
            runner.save()

            # Auxiliary runtime must not log registration failure when unmanifested
            fail_markers = list(session.child_manifest_dir.glob("*.registration_failure"))
            assert not fail_markers
    finally:
        session.cleanup()


def test_registration_failure_precedence_over_stale_start(tmp_path):
    manifest = tmp_path / "child_procs"
    manifest.mkdir()
    pid = 4321
    # Pre-existing start marker with cov_start=1
    (manifest / f"{pid}.start").write_text(
        f"pid={pid}\ninvocation=fresh_inv\nsuite=int\nrevision=rev1\nrole=inherited-python\ncov_start=1\n",
        encoding="utf-8",
    )
    # Registration failure for the same PID and invocation
    (manifest / f"{pid}.registration_failure").write_text(
        f"pid={pid}\nppid=1\ninvocation=fresh_inv\nsuite=int\nrevision=rev1\n"
        f"role=inherited-python\nowner=\nlaunch_shape=script:test\n"
        f"has_config=1\nhas_manifest=1\nhas_token=0\ntoken_hash=\n"
        f"bootstrap_stage=marker_creation\nfailure_class=marker_collision\nfailure_reason=FileExistsError\n",
        encoding="utf-8",
    )
    registered = read_registered_children(manifest, expected_invocation="fresh_inv", expected_suite="int")
    assert pid in registered
    assert registered[pid].get("registration_failure") is True
    assert registered[pid].get("failure_class") == "marker_collision"


def test_multiple_registration_failures_all_recorded(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            registered = {
                1001: {
                    "registration_failure": True, "pid": 1001, "failure_class": "marker_collision",
                    "failure_reason": "FileExistsError", "invocation": "inv1", "suite": "int",
                    "role": "inherited-python",
                },
                1002: {
                    "registration_failure": True, "pid": 1002, "failure_class": "missing_manifest_authority",
                    "failure_reason": "manifest_not_found", "invocation": "inv1", "suite": "int",
                    "role": "inherited-python",
                },
            }
            with pytest.raises(RuntimeError, match="child coverage registration failed"):
                reconcile_child_manifests(
                    registered_children=registered,
                    shard_paths_set=set(),
                    child_manifest_dir=session.child_manifest_dir,
                    parent_data_path=str(session.data_file),
                    parent_pid=os.getpid(),
                    snapshot_fn=session._create_snapshot,
                    record_fn=session._record_diagnostic,
                    cov_mod=coverage,
                )
            snaps = [s for s in session.diagnostic_snapshots if s.termination_outcome == "registration_failed"]
            assert len(snaps) == 2
            assert {s.failure_class for s in snaps} == {"marker_collision", "missing_manifest_authority"}
    finally:
        session.cleanup()


def test_disarm_coverage_prevents_shard_on_failure(tmp_path):
    shard_file = tmp_path / "test.shard"
    script = f"""
import coverage
cov = coverage.Coverage(data_file={repr(str(shard_file))})
cov.start()
cov._auto_save = False
cov.stop()
"""
    res = subprocess.run([sys.executable, "-c", script], capture_output=True)
    assert res.returncode == 0
    assert not shard_file.exists()


def test_registration_diagnostics_sanitized_and_bounded(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            raw_token = "secrettoken123456789012345678901"
            (session.child_manifest_dir / f"{raw_token}.start").write_text("collision", encoding="utf-8")
            env = dict(
                os.environ,
                COVERAGE_CHILD_REGISTRATION_TOKEN=raw_token,
                SUPER_SECRET="my_password_123",
            )
            subprocess.run([sys.executable, "-c", "pass"], env=env, capture_output=True)

            diag_files = list(session.child_manifest_dir.glob("*.registration_failure"))
            assert len(diag_files) == 1
            content = diag_files[0].read_text(encoding="utf-8")

            # Check bounded required fields
            assert "pid=" in content
            assert "ppid=" in content
            assert "invocation=" in content
            assert "suite=" in content
            assert "role=" in content
            assert "has_token=1" in content
            assert "failure_class=token_reuse" in content

            # Verify no secrets or raw tokens leaked
            assert raw_token not in content
            assert "my_password_123" not in content
            assert "SUPER_SECRET" not in content
            assert hashlib.sha256(raw_token.encode()).hexdigest() in content
    finally:
        session.cleanup()


def test_shard_diagnostic_snapshot_fields(tmp_path):
    snap = create_shard_snapshot(
        session_name="test_session",
        shard_name=".coverage.sample",
        file_type="registration_failure",
        size_bytes=0,
        sha256=None,
        reader_status="registration_failed:marker_collision:FileExistsError",
        stage="pre_combine",
        child_probe_id="pid=555",
        termination_outcome="registration_failed",
        launch_role="inherited-python",
        test_owner="test_user",
        ppid=1,
        launch_shape="script:test",
        invocation_id="inv-xyz",
        suite="int",
        source_revision="rev-abc",
        has_config=True,
        has_manifest=True,
        has_token=False,
        bootstrap_stage="marker_creation",
        failure_class="marker_collision",
        failure_reason="FileExistsError",
    )
    d = snap.to_dict()
    assert d["invocation_id"] == "inv-xyz"
    assert d["suite"] == "int"
    assert d["source_revision"] == "rev-abc"
    assert d["has_config"] is True
    assert d["has_manifest"] is True
    assert d["has_token"] is False
    assert d["bootstrap_stage"] == "marker_creation"
    assert d["failure_class"] == "marker_collision"
    assert d["failure_reason"] == "FileExistsError"
    assert d["child_probe_id"] == "pid=555"
    assert d["termination_outcome"] == "registration_failed"
