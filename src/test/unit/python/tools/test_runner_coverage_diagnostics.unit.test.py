"""Diagnostic and forensic tests for child coverage shards and anomaly recording."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
from typing import Any

import coverage
import pytest

from runner_coverage import ChildCoverageSession
from runner_coverage_diagnostics import (
    create_shard_snapshot,
    extract_child_probe_id,
    extract_pid_match,
    record_diagnostic,
    validate_shard_file,
)
from runner_coverage_execution import (
    read_registered_children,
    reconcile_child_manifests,
)
from runner_integration_obligations import COV5G_OWNER_SHA256
from runner_portable_coverage import validate_shard_directory_integrity


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


def test_unregistered_valid_sqlite_shard_rejected(tmp_path):
    with _setup_session(tmp_path) as session:
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
        assert snap.sha256 is not None
        assert snap.size_bytes > 0


def test_zero_byte_unregistered_shard_rejected(tmp_path):
    with _setup_session(tmp_path) as session:
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


def test_unregistered_12hex_hostname_shard_rejected(tmp_path):
    with _setup_session(tmp_path) as session:
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
        assert snap.child_probe_id == "pid=12161"


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
            dead_proc = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
            dead_proc.wait()
            pid = dead_proc.pid
            (manifest / f"{pid}.start").write_text(
                f"pid={pid}\ninvocation={session.session_dir.name}\nsuite=int\n"
                f"role=intentional-victim\nowner={COV5G_OWNER_SHA256}\ncov_start=1\n", encoding="utf-8",
            )
            (manifest / f"{pid}.victim").write_text(
                f"pid={pid}\nowner={COV5G_OWNER_SHA256}\ninvocation={session.session_dir.name}\n"
                f"backend_disappeared=1\ndescriptor_closed=1\nprocess_cleaned=1\nexitcode=-9\n", encoding="utf-8",
            )
            registered = read_registered_children(manifest, session.session_dir.name, "int")
            consumed, shards = reconcile_child_manifests(
                registered_children=registered, shard_paths_set=set(), child_manifest_dir=manifest,
                parent_data_path=str(session.data_file), parent_pid=os.getpid(),
                snapshot_fn=session._create_snapshot, record_fn=session._record_diagnostic, cov_mod=coverage,
            )
            assert not shards
            snap = session.diagnostic_snapshots[-1]
            assert snap.file_type == "intentional_victim"
            assert snap.reader_status == "intentional_victim_receipt_verified"
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
            (manifest / f"{pid}.start").write_text(
                f"pid={pid}\ninvocation={session.session_dir.name}\nsuite=int\n"
                f"role=intentional-victim\nowner={'0'*64}\ncov_start=1\n", encoding="utf-8",
            )
            (manifest / f"{pid}.victim").write_text(
                f"pid={pid}\nowner={'0'*64}\nbackend_disappeared=1\n"
                f"descriptor_closed=1\nprocess_cleaned=1\nexitcode=-9\n", encoding="utf-8",
            )
            registered = read_registered_children(manifest, session.session_dir.name, "int")
            with pytest.raises(RuntimeError, match="terminal receipt is incomplete"):
                reconcile_child_manifests(
                    registered_children=registered, shard_paths_set=set(), child_manifest_dir=manifest,
                    parent_data_path=str(session.data_file), parent_pid=os.getpid(),
                    snapshot_fn=session._create_snapshot, record_fn=session._record_diagnostic, cov_mod=coverage,
                )
    finally:
        session.cleanup()


def test_shard_diagnostic_snapshot_fields():
    snap = create_shard_snapshot(
        session_name="test_session", shard_name=".coverage.sample",
        file_type="registration_failure", size_bytes=0, sha256=None,
        reader_status="registration_failed:marker_collision:FileExistsError", stage="pre_combine",
        child_probe_id="pid=555", termination_outcome="registration_failed", launch_role="inherited-python",
        test_owner="test_user", ppid=1, launch_shape="script:test", invocation_id="inv-xyz",
        suite="int", source_revision="rev-abc", has_config=True, has_manifest=True, has_token=False,
        bootstrap_stage="marker_creation", failure_class="marker_collision", failure_reason="FileExistsError",
        measured_files_count=5, measured_classification={"inside_source_root": 5},
    )
    d = snap.to_dict()
    assert d["invocation_id"] == "inv-xyz" and d["has_config"] is True
    assert d["measured_files_count"] == 5
    assert d["measured_classification"] == {"inside_source_root": 5}


def test_extract_pid_and_probe_helpers():
    assert extract_pid_match(".coverage.host.pid1234.rand") == 1234
    assert extract_pid_match("unrelated_file") is None
    assert extract_child_probe_id(".coverage.host.pid5678.rand") == "pid=5678"


def test_validate_shard_file_rejects_zero_byte(tmp_path):
    zfile = tmp_path / ".coverage.zero"
    zfile.write_bytes(b"")
    snaps: list[Any] = []
    with pytest.raises(RuntimeError, match="zero-byte file"):
        validate_shard_file(
            str(zfile), {}, create_shard_snapshot,
            lambda s: record_diagnostic(snaps, s, tmp_path),
        )
    assert len(snaps) == 1 and snaps[0].reader_status == "rejected_zero_byte"


def test_multiple_registration_failures_all_recorded(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            registered = {
                1001: {"registration_failure": True, "pid": 1001, "failure_class": "marker_collision",
                       "failure_reason": "FileExistsError", "invocation": "inv1", "suite": "int", "role": "inherited-python"},
                1002: {"registration_failure": True, "pid": 1002, "failure_class": "missing_manifest_authority",
                       "failure_reason": "manifest_not_found", "invocation": "inv1", "suite": "int", "role": "inherited-python"},
            }
            with pytest.raises(RuntimeError, match="child coverage registration failed"):
                reconcile_child_manifests(
                    registered_children=registered, shard_paths_set=set(), child_manifest_dir=session.child_manifest_dir,
                    parent_data_path=str(session.data_file), parent_pid=os.getpid(),
                    snapshot_fn=session._create_snapshot, record_fn=session._record_diagnostic, cov_mod=coverage,
                )
            snaps = [s for s in session.diagnostic_snapshots if s.termination_outcome == "registration_failed"]
            assert len(snaps) == 2
            assert {s.failure_class for s in snaps} == {"marker_collision", "missing_manifest_authority"}
    finally:
        session.cleanup()


def test_unknown_launch_family_fails_closed():
    """Matrix Item 11: Unknown or typo launch families fail closed."""
    from runner_coverage_execution import prepare_child_coverage_environment

    with pytest.raises(ValueError, match="unknown coverage launch family"):
        prepare_child_coverage_environment(
            {"COVERAGE_PROCESS_START": "/path/to/rc"},
            family="unknown_random_family",
        )


def test_unmeasured_family_scrubbed_and_extra_env_cannot_override(tmp_path):
    """Matrix Item 13: Unmeasured family loses capability and extra_env cannot override."""
    from runner_coverage_bootstrap import install_bootstrap_directory
    from runner_coverage_execution import prepare_child_coverage_environment

    bdir = tmp_path / "bootstrap"
    install_bootstrap_directory(bdir)

    base_env = {
        "COVERAGE_PROCESS_START": "/path/to/rc",
        "COVERAGE_FILE": "/path/to/shard",
        "PYTHONPATH": f"/user/code:{bdir}",
    }
    # Caller attempts to smuggle coverage back via extra_env with reserved key
    hostile_extra = {
        "COVERAGE_PROCESS_START": "/hacked/rc",
        "PYTHONPATH": f"{bdir}:/extra/lib",
    }
    with pytest.raises(ValueError, match="runner-reserved coverage key"):
        prepare_child_coverage_environment(
            base_env,
            family="arch7f_probe",
            extra_env=hostile_extra,
        )

    # Benign extra_env without reserved keys succeeds and unmeasured family is scrubbed
    benign_extra = {
        "PYTHONPATH": f"{bdir}:/extra/lib",
    }
    cleaned = prepare_child_coverage_environment(
        base_env,
        family="arch7f_probe",
        extra_env=benign_extra,
    )
    assert not any(k.startswith("COVERAGE_") for k in cleaned)
    assert str(bdir) not in cleaned.get("PYTHONPATH", "")
    assert "/user/code" in cleaned.get("PYTHONPATH", "")
    assert "/extra/lib" in cleaned.get("PYTHONPATH", "")


def test_streaming_hash_and_corrupt_shard_rejection(tmp_path):
    from runner_coverage_diagnostics import compute_streaming_sha256
    corrupt_file = tmp_path / "corrupt.shard"
    corrupt_file.write_bytes(b"NOT_SQLITE_HEADER" + b"\x00" * 100)
    sha, sz, hdr = compute_streaming_sha256(corrupt_file)
    assert sz == 117 and sha is not None and not hdr.startswith(b"SQLite format 3")
    snaps: list[Any] = []
    with pytest.raises(RuntimeError, match="invalid SQLite header"):
        validate_shard_file(
            str(corrupt_file), {}, create_shard_snapshot,
            lambda s: record_diagnostic(snaps, s, tmp_path),
        )
    assert len(snaps) == 1 and snaps[0].reader_status == "invalid_sqlite_header"




def test_integration_population_remains_explicit(tmp_path):
    from runner_coverage_execution import prepare_child_coverage_environment
    scrubbed = prepare_child_coverage_environment(
        {"COVERAGE_PROCESS_START": "/rc", "PYTHONPATH": "/usr/lib"}, family="arch7f_probe",
    )
    assert "COVERAGE_PROCESS_START" not in scrubbed
    assert scrubbed.get("PYTHONPATH") == "/usr/lib"

    fail_closed = prepare_child_coverage_environment(
        {"COVERAGE_PROCESS_START": "/rc", "PYTHONPATH": "/usr/lib"}, family="cli_module",
    )
    assert "COVERAGE_PROCESS_START" not in fail_closed

    bdir = tmp_path / "bootstrap"
    bdir.mkdir()
    (bdir / "sitecustomize.py").write_text("# Runner-owned bootstrap: no product authority hooks are replaced.\n")
    measured = prepare_child_coverage_environment(
        {"COVERAGE_PROCESS_START": "/rc", "PYTHONPATH": f"{bdir}:/usr/lib:{bdir}"},
        family="cli_module", bootstrap_dir=bdir,
    )
    assert measured.get("COVERAGE_PROCESS_START") == "/rc"
    parts = measured["PYTHONPATH"].split(os.pathsep)
    assert len(parts) == len(set(parts))
    assert str(bdir) in parts


def test_shard_forensics_containment_and_malformed_sqlite(tmp_path):
    session = _setup_session(tmp_path)
    from runner_coverage_forensics import read_anomalous_shard_forensics
    from runner_coverage_diagnostics import merge_diagnostic_snapshot

    # 1. Containment rejection
    outside_shard = tmp_path / "outside.shard"
    outside_shard.write_bytes(b"SQLite format 3\x00" + b"\x00" * 96)
    valid, cnt, info, verdict = read_anomalous_shard_forensics(outside_shard, session.data_dir)
    assert not valid and verdict == "unauthorized_shard_location"

    # 2. Malformed SQLite through validate_shard_directory_integrity
    corrupt = session.data_dir / ".coverage.corrupt"
    corrupt.write_bytes(b"SQLite format 3\x00" + b"CORRUPT_SQLITE_DATA" * 5)
    with pytest.raises(RuntimeError, match="unregistered coverage shard rejected"):
        validate_shard_directory_integrity(
            session.data_dir, set(), None, session._create_snapshot,
            session._record_diagnostic, coverage, source_root=session.source_root,
        )
    assert len(session.diagnostic_snapshots) == 1
    snap = session.diagnostic_snapshots[0]
    assert snap.failure_class == "sqlite_error" and snap.measured_files_count is None
    assert snap.to_dict()["measured_files_count"] is None
    assert "sqlite_valid=False:measured_files=unknown" in (snap.failure_reason or "")
    assert snap.forensic_verdict is not None and snap.forensic_verdict.startswith("sqlite_error:")
    snap_json = session.session_dir / "coverage_anomaly_snapshot.json"
    assert snap_json.is_file()
    jdata = json.loads(snap_json.read_text(encoding="utf-8"))
    assert jdata[0]["measured_files_count"] is None
    assert jdata[0]["forensic_verdict"] == snap.forensic_verdict

    # 3. Forensic verdict preserved when child_info supplies failure_class/reason (B5)
    c_info = {"failure_class": "registration_failure", "failure_reason": "missing_marker"}
    merged = merge_diagnostic_snapshot(snap, child_info=c_info, forensic_verdict=snap.forensic_verdict)
    assert merged.failure_class == "registration_failure"
    assert merged.forensic_verdict == snap.forensic_verdict
    assert f"forensic_verdict={snap.forensic_verdict}" in (merged.failure_reason or "")


def test_empty_coverage_db_pins_measured_files_zero(tmp_path):
    session = _setup_session(tmp_path)
    try:
        from coverage.sqldata import SCHEMA_VERSION as EXPECTED_SCHEMA
    except ImportError:
        EXPECTED_SCHEMA = getattr(coverage.CoverageData, "SCHEMA_VERSION", 7)

    empty_shard = session.data_dir / ".coverage.empty_db"
    conn = sqlite3.connect(empty_shard)
    conn.execute("CREATE TABLE coverage_schema (version INTEGER)")
    conn.execute("INSERT INTO coverage_schema VALUES (?)", (EXPECTED_SCHEMA,))
    conn.execute("CREATE TABLE file (id INTEGER PRIMARY KEY, path TEXT)")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="unregistered coverage shard rejected"):
        validate_shard_directory_integrity(
            session.data_dir, set(), None, session._create_snapshot,
            session._record_diagnostic, coverage, source_root=session.source_root,
        )
    snap = session.diagnostic_snapshots[0]
    assert snap.measured_files_count == 0
    assert snap.to_dict()["measured_files_count"] == 0
    assert "sqlite_valid=True:measured_files=0" in (snap.failure_reason or "")
    assert snap.forensic_verdict is None
    snap_json = session.session_dir / "coverage_anomaly_snapshot.json"
    assert snap_json.is_file()
    jdata = json.loads(snap_json.read_text(encoding="utf-8"))
    assert jdata[0]["measured_files_count"] == 0

