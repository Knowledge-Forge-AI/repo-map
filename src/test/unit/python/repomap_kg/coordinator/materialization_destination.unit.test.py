"""Partial destination IO, readback integrity and first-reached failure semantics."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import threading

import pytest

from common_lore_index.artifacts.store import ArtifactIntegrityError
from common_lore_index.coordinator._portable_materialization import MaterializedWorkspace
from repomap_test_support.materialization_fixtures import BINDING_ID, CHUNK_BYTES, copy_case, patch_copy_os


class StopCopy(BaseException):
    """Deterministic cooperative control without native process signals."""


def test_legitimate_partial_destination_writes_produce_the_exact_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"public-payload"
    store, manifest, workspace = copy_case(tmp_path, data)
    original = os.write
    written: list[int] = []

    def write(descriptor, value):
        count = original(descriptor, value[:5])
        written.append(count)
        return count

    patch_copy_os(monkeypatch, write=write)
    with MaterializedWorkspace(store, manifest, workspace, job_id="job-partial", attempt=1) as view:
        assert (view.binding_roots[BINDING_ID] / "src/payload.bin").read_bytes() == data
    assert written == [5, 5, 4]
    assert store.probes[0].reader.closed and not tuple(workspace.iterdir())


@pytest.mark.parametrize("fault", [0, -1, OSError(errno.ENOSPC, "write fixture"), PermissionError("write fixture")])
def test_zero_failed_and_denied_writes_never_return_a_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: int | OSError,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public")

    def write(_descriptor, _value):
        if isinstance(fault, OSError):
            raise fault
        return fault

    patch_copy_os(monkeypatch, write=write)
    with pytest.raises(OSError) as caught:
        with MaterializedWorkspace(store, manifest, workspace, job_id="job-write", attempt=1):
            pytest.fail("failed write returned a view")
    if isinstance(fault, OSError):
        assert caught.value is fault
    else:
        assert str(caught.value) == "artifact write failed"
    assert store.probes[0].exits == [caught.value]
    assert store.probes[0].reader.closed and not tuple(workspace.iterdir())


def test_cancellation_between_actual_partial_writes_keeps_the_original_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public-payload")
    marker = StopCopy()
    event = threading.Event()
    written: list[int] = []
    original = os.write

    def write(descriptor, value):
        count = original(descriptor, value[:3])
        written.append(count)
        event.set()
        return count

    def check() -> None:
        if event.is_set():
            raise marker

    patch_copy_os(monkeypatch, write=write)
    with pytest.raises(StopCopy) as caught:
        with MaterializedWorkspace(store, manifest, workspace, job_id="job-cancel", attempt=1, io_cancel_check=check):
            pytest.fail("cancelled write returned a view")
    assert caught.value is marker and written == [3]
    assert store.probes[0].exits == [marker]
    assert store.probes[0].reader.closed and not tuple(workspace.iterdir())


def test_cancellation_during_bounded_readback_stops_before_the_next_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"x" * (CHUNK_BYTES + 1))
    marker = StopCopy()
    event = threading.Event()
    read_lengths: list[int] = []
    original = os.read

    def read(descriptor, size):
        data = original(descriptor, size)
        read_lengths.append(len(data))
        event.set()
        return data

    def check() -> None:
        if event.is_set():
            raise marker

    patch_copy_os(monkeypatch, read=read)
    with pytest.raises(StopCopy) as caught:
        with MaterializedWorkspace(store, manifest, workspace, job_id="job-readback", attempt=1, io_cancel_check=check):
            pytest.fail("cancelled verification returned a view")
    assert caught.value is marker and read_lengths == [CHUNK_BYTES]
    assert store.probes[0].reader.closed and store.probes[0].exits == [None]
    assert not tuple(workspace.iterdir())


def test_reached_destination_failure_precedes_a_later_corrupt_source_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public")
    store.object_path(manifest.entries[0].reference).write_bytes(b"PUBLIC")
    marker = OSError(errno.ENOSPC, "destination fixture")

    def write(_descriptor, _value):
        raise marker

    with monkeypatch.context() as patch:
        patch_copy_os(patch, write=write)
        with pytest.raises(OSError) as caught:
            with MaterializedWorkspace(store, manifest, workspace, job_id="job-precedence", attempt=1):
                pytest.fail("failed write returned a view")
        assert caught.value is marker
    with pytest.raises(ArtifactIntegrityError, match="digest"):
        with MaterializedWorkspace(store, manifest, workspace, job_id="job-corrupt", attempt=2):
            pytest.fail("corrupt source returned a view")
    assert all(probe.reader.closed for probe in store.probes)
    assert not tuple(workspace.iterdir())


@pytest.mark.parametrize("fault", ["digest", "short", "tail", "replacement"])
def test_destination_readback_refuses_content_or_identity_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public")
    closed: list[int] = []
    original = os.close

    def close(descriptor):
        original(descriptor)
        closed.append(descriptor)
        if len(closed) == 1:
            path = next(workspace.rglob("payload.bin"))
            if fault == "replacement":
                replacement = path.with_suffix(".replacement")
                replacement.write_bytes(b"public")
                os.replace(replacement, path)
            else:
                path.write_bytes({"digest": b"PUBLIC", "short": b"pub", "tail": b"public!"}[fault])

    patch_copy_os(monkeypatch, close=close)
    with pytest.raises(OSError, match="artifact verification failed"):
        with MaterializedWorkspace(store, manifest, workspace, job_id="job-readback", attempt=1):
            pytest.fail("changed destination returned a view")
    assert len(closed) == 2
    assert store.probes[0].reader.closed and not tuple(workspace.iterdir())


@pytest.mark.parametrize("body_failure", [False, True])
def test_readback_close_failure_is_visible_normally_and_preserves_an_active_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body_failure: bool,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public")
    primary = PermissionError("readback fixture")
    close_error = OSError("readback close fixture")
    closed: list[int] = []
    original_read, original_close = os.read, os.close

    def close(descriptor):
        original_close(descriptor)
        closed.append(descriptor)
        if len(closed) == 2:
            raise close_error

    def read(descriptor, size):
        if body_failure:
            raise primary
        return original_read(descriptor, size)

    patch_copy_os(monkeypatch, close=close, read=read)
    with pytest.raises(OSError) as caught:
        with MaterializedWorkspace(store, manifest, workspace, job_id="job-readback-close", attempt=1):
            pytest.fail("close failure returned a view")
    assert caught.value is (primary if body_failure else close_error)
    assert len(closed) == 2 and not tuple(workspace.iterdir())
