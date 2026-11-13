"""All copy-local releases are attempted once, preserving the actual primary."""
from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO, cast

import pytest

from common_lore_index._temporary import OwnedDirectoryIdentity
from common_lore_index.artifacts.store import ArtifactIntegrityError
from common_lore_index.coordinator import _portable_materialization as module
from repomap_test_support.materialization_fixtures import FaultSource, copy_case, patch_copy_os


def _inject_release_faults(monkeypatch, source, body_failure, primary, secondary):
    events: list[str] = []
    original_close = os.close

    def close(descriptor: int) -> None:
        events.append("destination-close")
        assert source.reader.closed
        original_close(descriptor)
        raise secondary

    def write(_descriptor, _data):
        raise primary

    changes: dict[str, object] = {"close": close}
    if body_failure:
        changes["write"] = write
    patch_copy_os(monkeypatch, **changes)
    return events


@pytest.mark.parametrize("body_failure", [False, True])
def test_source_exit_and_destination_close_are_both_attempted_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body_failure: bool,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public")
    source_error = OSError("source close fixture")
    primary = OSError("destination body fixture")
    secondary = OSError("destination close fixture")
    source = FaultSource(store.open_stream(manifest.entries[0].reference, max_bytes=6), {"exit": source_error})
    events = _inject_release_faults(monkeypatch, source, body_failure, primary, secondary)
    monkeypatch.setattr(store, "open_stream", lambda *_args, **_kwargs: cast(BinaryIO, source))
    try:
        with pytest.raises((OSError, ArtifactIntegrityError)) as caught:
            with module.MaterializedWorkspace(store, manifest, workspace, job_id="job-close", attempt=1):
                pytest.fail("release failure returned a view")
        assert caught.value is primary if body_failure else caught.value.__cause__ is source_error
        assert events == ["destination-close"]
        exits = [error for name, error in source.events if name == "exit"]
        assert exits == [primary if body_failure else None]
        assert source.reader.closed and not tuple(workspace.iterdir())
    finally:
        source.reader.close()


@pytest.mark.parametrize("uncertain_close", [False, True])
def test_failed_enter_closes_once_and_does_not_retry_an_uncertain_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uncertain_close: bool,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public")
    primary = RuntimeError("enter fixture")
    close_error = OSError("close fixture")
    source = FaultSource(
        store.open_stream(manifest.entries[0].reference, max_bytes=6),
        {"enter": primary, "close_before" if uncertain_close else "close": close_error},
    )
    descriptor = source.reader.fileno()
    monkeypatch.setattr(store, "open_stream", lambda *_args, **_kwargs: cast(BinaryIO, source))
    try:
        with pytest.raises(RuntimeError) as caught:
            with module.MaterializedWorkspace(store, manifest, workspace, job_id="job-enter", attempt=1):
                pytest.fail("failed enter returned a view")
        assert caught.value is primary
        assert source.events == [("enter", None), ("close", None)]
        assert source.reader.closed is not uncertain_close
        if uncertain_close:
            assert os.fstat(descriptor).st_size == 6
        assert not tuple(workspace.iterdir())
    finally:
        # Fixture-owned reclamation follows the no-retry observation; it is not
        # a second subject release or a claim that refusal closed this resource.
        source.reader.close()
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_legacy_root_cleanup_refusal_still_replaces_the_body_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public")
    original_cleanup = module._remove_materialized_root
    body = ValueError("copy callback fixture")
    cleanup = RuntimeError("root cleanup fixture")
    owned: list[tuple[Path, OwnedDirectoryIdentity]] = []

    def refuse(root, identity):
        owned.append((root, identity))
        raise cleanup

    def cancel() -> None:
        raise body

    monkeypatch.setattr(module, "_remove_materialized_root", refuse)
    try:
        with pytest.raises(RuntimeError) as caught:
            with module.MaterializedWorkspace(
                store, manifest, workspace, job_id="job-root", attempt=1, io_cancel_check=cancel,
            ):
                pytest.fail("copy cancellation returned a view")
        assert caught.value is cleanup and caught.value.__context__ is body
        assert len(owned) == 1 and owned[0][0].exists()
    finally:
        for root, identity in owned:
            original_cleanup(root, identity)
    assert not tuple(workspace.iterdir())


@pytest.mark.parametrize("window", ["write-open", "write-stat", "read-open"])
def test_destination_acquisition_failures_release_every_previously_acquired_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, window: str,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public")
    marker = PermissionError("destination acquisition fixture")
    original_open, original_stat, original_close = os.open, os.fstat, os.close
    acquired: list[int] = []
    closed: list[int] = []

    def opened(path, flags, mode=0o777, **kwargs):
        writer = bool(flags & os.O_WRONLY)
        if (window == "write-open" and writer) or (window == "read-open" and not writer):
            raise marker
        descriptor = original_open(path, flags, mode, **kwargs)
        acquired.append(descriptor)
        return descriptor

    def inspected(descriptor):
        if window == "write-stat":
            raise marker
        return original_stat(descriptor)

    def close(descriptor):
        original_close(descriptor)
        closed.append(descriptor)

    patch_copy_os(monkeypatch, open=opened, fstat=inspected, close=close)
    with pytest.raises(PermissionError) as caught:
        with module.MaterializedWorkspace(store, manifest, workspace, job_id="job-acquire", attempt=1):
            pytest.fail("acquisition failure returned a view")
    assert caught.value is marker and acquired == closed
    assert store.probes[0].reader.closed
    assert store.probes[0].exits == [None if window == "read-open" else marker]
    assert not tuple(workspace.iterdir())


def test_truthy_source_exit_cannot_suppress_a_copy_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public")
    marker = OSError("copy failure fixture")

    class SuppressingSource(FaultSource):
        def __exit__(self, kind, error, traceback):
            super().__exit__(kind, error, traceback)
            return True

    source = SuppressingSource(store.open_stream(manifest.entries[0].reference, max_bytes=6))

    def write(_descriptor, _data):
        raise marker

    monkeypatch.setattr(store, "open_stream", lambda *_args, **_kwargs: cast(BinaryIO, source))
    patch_copy_os(monkeypatch, write=write)
    with pytest.raises(OSError) as caught:
        with module.MaterializedWorkspace(store, manifest, workspace, job_id="job-suppress", attempt=1):
            pytest.fail("truthy exit suppressed a copy failure")
    assert caught.value is marker and source.events[-1] == ("exit", marker)
    assert source.reader.closed and not tuple(workspace.iterdir())
