"""Pure capacity evidence, independent domains, and workload release contracts."""

import json
import io
import stat
import subprocess
from types import SimpleNamespace

import pytest
import test_sandbox_capacity as capacity


UPPER = "/var/lib/docker/overlay2/layer/diff"
TOKEN = "a" * 64
DIGEST = "b" * 64
GIB = capacity.GIB


def evidence(free=10 * GIB):
    return {
        "upper": UPPER,
        "mount_sha256": DIGEST,
        "free_bytes": free,
        "total_bytes": 100 * GIB,
        "free_percent": free * 100 // (100 * GIB),
    }




@pytest.fixture
def binding(monkeypatch, tmp_path):
    path = tmp_path / "capacity"
    owner = tmp_path / "owner"
    owner.write_text(TOKEN)
    monkeypatch.setattr(capacity, "BINDING_PATH", path)
    monkeypatch.setattr(capacity, "OWNER_PATH", owner)
    monkeypatch.setattr(capacity, "root_mount", lambda: (UPPER, DIGEST))
    monkeypatch.setattr(capacity.time, "time", lambda: 1000)
    monkeypatch.setattr(
        capacity.os,
        "fstat",
        lambda fd: SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o600),
    )
    value = {
        "schema": capacity.SCHEMA,
        "token": TOKEN,
        "mount_sha256": DIGEST,
        "issued_seconds": 1000,
    }
    path.write_text(json.dumps(value))
    return path, value


@pytest.mark.parametrize(
    "change",
    [
        {"free_bytes": True},
        {"total_bytes": 0},
        {"free_percent": 99},
        {"free_bytes": 2**64},
        {"extra": 1},
        {"upper": "/wrong"},
        {"mount_sha256": "malformed"},
    ],
)
def test_probe_rejects_malformed_contradictory_or_substituted_evidence(change, capsys):
    with pytest.raises(RuntimeError, match="sandbox_capacity_refused"):
        capacity.validate_probe(evidence() | change, upper=UPPER)
    record = json.loads(capsys.readouterr().err)
    assert set(record) == {"event", "stage", "decision", "reason"}
    assert record["decision"] == "refused"
    assert record["stage"] == "outer_overlay_backing"
    assert record["reason"] in {"malformed_backing_evidence", "unbound_backing_evidence"}


def test_image_materialization_crossing_floor_is_not_hidden_by_prebuild_reading():
    assert capacity.validate_probe(evidence(13 * GIB), upper=UPPER)
    with pytest.raises(RuntimeError, match="host_admission_refused: free_disk_reserve"):
        capacity.validate_probe(evidence(10 * GIB - 1), upper=UPPER)
    assert capacity.validate_probe(evidence(10 * GIB), upper=UPPER)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"issued_seconds": -1}, "stale_binding"),
        ({"issued_seconds": 1001}, "stale_binding"),
        ({"issued_seconds": True}, "stale_binding"),
        ({"token": "c" * 64}, "wrong_attempt_binding"),
        ({"mount_sha256": "c" * 64}, "substituted_backing_mapping"),
        ({"free_bytes": 100 * GIB}, "malformed_binding"),
    ],
)
def test_binding_is_closed_current_and_bound(binding, change, reason):
    path, value = binding
    path.write_text(json.dumps(value | change))
    with pytest.raises(RuntimeError, match=reason):
        capacity.read_binding()


def test_binding_uses_fresh_measurement_not_environment(binding, monkeypatch):
    monkeypatch.setenv("REPOMAP_TEST_FREE_DISK_BYTES", str(900 * GIB))
    monkeypatch.setattr(capacity, "space", lambda path: (10 * GIB, 100 * GIB))
    assert capacity.backing_space() == (10 * GIB, 10)


def test_binding_lasts_for_invocation_and_refreshes_measurement(binding, monkeypatch):
    readings = [(10 * GIB, 100 * GIB), (GIB, 100 * GIB)]
    paths = []

    def measured(path):
        paths.append(path)
        return readings.pop(0)

    monkeypatch.setattr(capacity, "space", measured)
    assert capacity.backing_space() == (10 * GIB, 10)
    monkeypatch.setattr(capacity.time, "time", lambda: 1121)
    assert capacity.backing_space() == (GIB, 1)
    assert paths == ["/", "/"]


def test_binding_revalidates_owner_token_after_initial_handoff(binding):
    _, _ = binding
    capacity.read_binding()
    capacity.OWNER_PATH.write_text("c" * 64)
    with pytest.raises(RuntimeError, match="wrong_attempt_binding"):
        capacity.read_binding()


def test_binding_revalidates_mount_after_initial_handoff(binding, monkeypatch):
    _, _ = binding
    capacity.read_binding()
    monkeypatch.setattr(capacity, "root_mount", lambda: (UPPER, "c" * 64))
    with pytest.raises(RuntimeError, match="substituted_backing_mapping"):
        capacity.read_binding()


@pytest.mark.parametrize("rendered", ["{", "[]", "x" * 4097, '{"schema":1,"schema":2}'])
def test_binding_rejects_malformed_duplicate_and_oversized_records(binding, rendered):
    path, _ = binding
    path.write_text(rendered)
    with pytest.raises(RuntimeError, match="binding"):
        capacity.read_binding()


@pytest.mark.parametrize(
    "row,valid",
    [
        (f"1 2 0:3 / / rw - overlay overlay rw,upperdir={UPPER},workdir=/work", True),
        ("1 2 0:3 / / rw - tmpfs tmpfs rw", False),
        ("1 2 0:3 / / rw - overlay overlay rw,lowerdir=/lower", False),
        (f"1 2 0:3 / / ro - overlay overlay ro,upperdir={UPPER}", False),
    ],
)
def test_root_mapping_requires_writable_overlay(monkeypatch, row, valid):
    monkeypatch.setattr(capacity.Path, "open", lambda *a, **k: io.StringIO(row))
    if valid:
        assert capacity.root_mount()[0] == UPPER
    else:
        with pytest.raises(RuntimeError, match="unsupported_backing_mapping"):
            capacity.root_mount()


def test_root_mount_translates_filesystem_failures(monkeypatch):
    def unavailable(*args, **kwargs):
        raise PermissionError("/private/mountinfo")

    monkeypatch.setattr(capacity.Path, "open", unavailable)
    with pytest.raises(
        RuntimeError, match="sandbox_capacity_refused: mount_measurement_unavailable"
    ) as raised:
        capacity.root_mount()
    assert isinstance(raised.value.__cause__, PermissionError)
    assert "/private/mountinfo" not in str(raised.value)


def test_space_translates_filesystem_failures(monkeypatch):
    def unavailable(path):
        raise PermissionError("/private/backing")

    monkeypatch.setattr(capacity.os, "statvfs", unavailable)
    with pytest.raises(
        RuntimeError,
        match="sandbox_capacity_refused: filesystem_measurement_unavailable",
    ) as raised:
        capacity.space("/private/backing")
    assert isinstance(raised.value.__cause__, PermissionError)
    assert "/private/backing" not in str(raised.value)


def test_binding_translates_mount_revalidation_failures(binding, monkeypatch):
    def unavailable():
        raise OSError("/private/mountinfo")

    monkeypatch.setattr(capacity, "root_mount", unavailable)
    with pytest.raises(
        RuntimeError, match="sandbox_capacity_refused: mount_measurement_unavailable"
    ) as raised:
        capacity.read_binding()
    assert isinstance(raised.value.__cause__, OSError)
    assert "/private/mountinfo" not in str(raised.value)


def test_checkpoint_observes_pressure_from_all_tmpfs_consumers(monkeypatch):
    monkeypatch.setattr(
        capacity,
        "space",
        lambda path: (
            (GIB - 1, 8 * GIB) if path == "/sandbox-scratch" else (GIB, 4 * GIB)
        ),
    )
    with pytest.raises(RuntimeError, match="scratch_headroom_insufficient"):
        capacity.validate_scratch_capacity()


@pytest.mark.parametrize(
    "scratch_free,docker_free,reason",
    [
        (8 * GIB, GIB, None),
        (GIB, GIB, None),
        (GIB - 1, GIB, "scratch_headroom_insufficient"),
        (8 * GIB, 0, "inner_docker_capacity_refused: exhausted"),
    ],
)
def test_scratch_and_inner_docker_are_independent(
    monkeypatch, scratch_free, docker_free, reason
):
    monkeypatch.setattr(
        capacity,
        "space",
        lambda path: (
            (scratch_free, 8 * GIB)
            if path == "/sandbox-scratch"
            else (docker_free, 4 * GIB)
        ),
    )
    if reason:
        with pytest.raises(RuntimeError, match=reason):
            capacity.validate_scratch_capacity()
    else:
        capacity.validate_scratch_capacity()


def test_parent_binds_only_daemon_layer_after_measuring(monkeypatch):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        output = ""
        if command[1] == "info":
            output = json.dumps(
                "overlay2" if "Driver" in command[-1] else "/var/lib/docker"
            )
        elif command[1] == "inspect":
            output = json.dumps({"Name": "overlay2", "Data": {"UpperDir": UPPER}})
        elif command[-1] == "probe":
            output = json.dumps(evidence())
        return subprocess.CompletedProcess(command, 0, output, "")

    capacity.bind_backing_capacity(runner, "d" * 64, TOKEN)
    assert calls[-2][0][-1] == "probe"
    binding = json.loads(calls[-1][1]["input"])
    assert binding == {
        "schema": capacity.SCHEMA,
        "token": TOKEN,
        "mount_sha256": DIGEST,
    }
    assert TOKEN not in " ".join(calls[-1][0])




@pytest.mark.parametrize(
    "free,total,byte_ok,percent_ok",
    [(10 * GIB, 200 * GIB, True, True),
     (10 * GIB - 1, 100 * GIB, False, True),
     (10 * GIB, 200 * GIB + 1, True, False),
     (10 * GIB - 1, 200 * GIB, False, False)],
)
def test_reserve_evidence_distinguishes_exact_independent_boundaries(
    free, total, byte_ok, percent_ok, capsys
):
    value = evidence(free) | {"total_bytes": total, "free_percent": free * 100 // total}
    if byte_ok and percent_ok:
        assert capacity.validate_probe(value, upper=UPPER) == value
    else:
        with pytest.raises(RuntimeError, match="^host_admission_refused: free_disk_reserve$"):
            capacity.validate_probe(value, upper=UPPER)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "event": "repomap-sandbox-capacity-v1", "stage": "outer_overlay_backing",
        "free_bytes": free, "total_bytes": total, "free_percent": free * 100 // total,
        "required_free_bytes": 10737418240, "required_free_percent": 5,
        "byte_floor_passed": byte_ok, "percentage_floor_passed": percent_ok,
        "decision": "admitted" if byte_ok and percent_ok else "refused",
    }
