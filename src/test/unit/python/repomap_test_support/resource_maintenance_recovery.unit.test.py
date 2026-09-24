"""Dead-owner recovery uses test-owned roots and never acquires dead authority."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from repomap_test_support import resource_maintenance_recovery as recovery
from repomap_test_support.resource_index_records import LOCK_SCHEMA
from repomap_test_support.resource_ledger_io import write_private_json_exclusive
from repomap_test_support.resource_lifecycle_claim import ClaimError, ClaimRegistry, ProcessLiveness
from repomap_test_support.resource_lifecycle_claim_operations import _record_id


def _owner(tmp_path, *, pid=None, start="a" * 64, barrier=False):
    tmp_path.chmod(0o700)
    registry = ClaimRegistry(tmp_path)
    handle = registry.acquire_maintenance("recover-index", now_seconds=1)
    payload = json.loads(handle.path.read_text())
    payload.update(process_id=os.getpid() if pid is None else pid, process_start_evidence=start)
    payload.pop("maintenance_record_id")
    payload["maintenance_record_id"] = _record_id(payload)
    handle.path.write_text(json.dumps(payload))
    if barrier:
        path = tmp_path / ".index" / "repo-map_dev" / "admission.lock"
        path.parent.mkdir(parents=True, mode=0o700)
        write_private_json_exclusive(path, {
            "schema": LOCK_SCHEMA, **{key: payload[key] for key in (
                "owner_token", "process_id", "process_start_evidence", "created_at_seconds",
            )},
        })
    return registry, payload


def _recover(root, payload, **kwargs):
    return recovery.recover_maintenance_owner(
        root, expected_record_id=payload["maintenance_record_id"],
        confirmation=recovery.CONFIRM_RECOVERY, now_seconds=4000, **kwargs,
    )


@pytest.mark.parametrize("barrier", [False, True])
def test_actual_dead_process_recovery_preserves_records_and_all_run_bytes(tmp_path, barrier):
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)
    registry, payload = _owner(tmp_path, pid=child.pid, barrier=barrier)
    run = tmp_path / "r" / "retained"
    run.mkdir(parents=True)
    (run / "evidence").write_text("retained")
    result = _recover(tmp_path, payload)
    assert result == {"outcome": "recovered", "maintenance_records": 1, "paired_barriers": int(barrier)}
    assert not (registry.maintenance_root / "maintenance.lock").exists()
    assert not (tmp_path / ".index/repo-map_dev/admission.lock").exists()
    intent = json.loads(next((registry.maintenance_root / "recovery-records").glob("*.intent.json")).read_text())
    assert intent["maintenance"] == payload and intent["liveness"] == "dead"
    assert (run / "evidence").read_text() == "retained"
    handle = registry.acquire_maintenance("inventory")
    registry.release_maintenance(handle)


def test_live_owner_refused_and_actual_reused_pid_start_distinguished(tmp_path):
    import psutil
    pid = os.getpid()
    start = hashlib.sha256(f"repomap-process-start-v1\0{pid}\0{psutil.Process(pid).create_time():.6f}".encode()).hexdigest()
    registry, payload = _owner(tmp_path, start=start)
    with pytest.raises(ClaimError, match="not provably dead"):
        _recover(tmp_path, payload)
    assert (registry.maintenance_root / "maintenance.lock").exists()
    # Same live PID, different creation identity means the recorded owner is dead.
    payload["process_start_evidence"] = "b" * 64
    payload.pop("maintenance_record_id")
    payload["maintenance_record_id"] = _record_id(payload)
    (registry.maintenance_root / "maintenance.lock").write_text(json.dumps(payload))
    assert _recover(tmp_path, payload)["outcome"] == "recovered"


@pytest.mark.parametrize("liveness", [ProcessLiveness.LIVE, ProcessLiveness.UNKNOWN, None])
def test_unknown_or_live_never_retired(tmp_path, liveness):
    registry, payload = _owner(tmp_path, barrier=True)
    before = (registry.maintenance_root / "maintenance.lock").read_bytes()
    with pytest.raises(ClaimError, match="not provably dead"):
        _recover(tmp_path, payload, owner_is_live=lambda *_: liveness)
    assert (registry.maintenance_root / "maintenance.lock").read_bytes() == before
    assert (tmp_path / ".index/repo-map_dev/admission.lock").exists()


def test_competing_recovery_cannot_pass_same_inode_lock(tmp_path):
    registry, payload = _owner(tmp_path)
    calls = []

    def probe(*_):
        with pytest.raises(BlockingIOError):
            _recover(tmp_path, payload)
        calls.append(True)
        return ProcessLiveness.DEAD

    assert _recover(tmp_path, payload, owner_is_live=probe)["outcome"] == "recovered"
    assert len(calls) == 2


@pytest.mark.parametrize("change", ["replacement", "corrupt", "symlink", "foreign_barrier"])
def test_changed_or_unsafe_records_are_preserved(tmp_path, change):
    registry, payload = _owner(tmp_path, barrier=True)
    path = registry.maintenance_root / "maintenance.lock"
    if change == "corrupt":
        path.write_text("not json")
    elif change == "symlink":
        saved = path.with_name("saved")
        path.rename(saved)
        path.symlink_to(saved)
    elif change == "foreign_barrier":
        barrier = tmp_path / ".index/repo-map_dev/admission.lock"
        value = json.loads(barrier.read_text())
        value["owner_token"] = "f" * 32
        barrier.write_text(json.dumps(value))

    def probe(*_):
        if change == "replacement":
            path.unlink()
            write_private_json_exclusive(path, payload)
        return ProcessLiveness.DEAD

    with pytest.raises((ClaimError, ValueError, RuntimeError)):
        _recover(tmp_path, payload, owner_is_live=probe)
    assert path.exists()
    assert (tmp_path / ".index/repo-map_dev/admission.lock").exists()


def test_interruption_releases_recovery_serialization_without_new_lock(tmp_path, monkeypatch):
    registry, payload = _owner(tmp_path, barrier=True)
    real = Path.unlink

    def interrupted(path, *args, **kwargs):
        if path.name == "maintenance.lock":
            raise KeyboardInterrupt("test interruption")
        return real(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", interrupted)
        with pytest.raises(KeyboardInterrupt):
            _recover(tmp_path, payload)
    assert (registry.maintenance_root / "maintenance.lock").exists()
    assert not (tmp_path / ".index/repo-map_dev/admission.lock").exists()
    interrupted_record = next((registry.maintenance_root / "recovery-records").glob("*.interrupted.json"))
    assert json.loads(interrupted_record.read_text())["removed_records"] == 1
    assert _recover(tmp_path, payload)["outcome"] == "recovered"


@pytest.mark.parametrize("field,value", [("expected_record_id", "c" * 64), ("confirmation", "yes"), ("now_seconds", 2)])
def test_exact_authority_and_lease_required(tmp_path, field, value):
    registry, payload = _owner(tmp_path)
    kwargs = dict(expected_record_id=payload["maintenance_record_id"],
                  confirmation=recovery.CONFIRM_RECOVERY, now_seconds=4000)
    kwargs[field] = value
    with pytest.raises(ClaimError):
        recovery.recover_maintenance_owner(tmp_path, **kwargs)
    assert (registry.maintenance_root / "maintenance.lock").exists()


def test_cli_routes_recovery_before_maintenance_acquisition(tmp_path, monkeypatch, capsys):
    import test_hygiene_maintenance as tool
    registry, payload = _owner(tmp_path)
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(tmp_path))
    result = tool.main(["recover-maintenance-owner", "--record-id", payload["maintenance_record_id"],
                        "--confirm", recovery.CONFIRM_RECOVERY])
    assert result == 0 and "recovered" in capsys.readouterr().out
    assert not (registry.maintenance_root / "maintenance.lock").exists()
    result = tool.main(["recover-maintenance-owner", "--record-id", payload["maintenance_record_id"],
                        "--confirm", recovery.CONFIRM_RECOVERY])
    assert result == 2 and "refused" in capsys.readouterr().out
