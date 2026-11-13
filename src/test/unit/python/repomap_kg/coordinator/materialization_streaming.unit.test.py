"""Actual copy and readback work is bounded without changing artifact checkpoints."""
from __future__ import annotations

from pathlib import Path
import threading

import pytest

from common_lore_index.coordinator import _portable_semantic_adapter as adapter
from common_lore_index.artifacts._store_stream import VerifyingArtifactStream
from common_lore_index.coordinator._portable_materialization import MaterializedWorkspace
from repomap_test_support.materialization_fixtures import (
    BINDING_ID, CHUNK_BYTES, capability_for, copy_case, manifest_for, observe_copy_writes,
)


def test_source_copy_uses_stream_and_bounded_readback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"public\x00" * (3 * CHUNK_BYTES // 7 + 1)
    store, manifest, workspace = copy_case(tmp_path, data)
    whole_readbacks: list[int] = []
    original = Path.read_bytes

    def readback(path: Path) -> bytes:
        result = original(path)
        if path.is_relative_to(workspace):
            whole_readbacks.append(len(result))
        return result

    monkeypatch.setattr(Path, "read_bytes", readback)
    with MaterializedWorkspace(store, manifest, workspace, job_id="job-copy", attempt=1) as view:
        target = view.binding_roots[BINDING_ID] / "src/payload.bin"
        with target.open("rb") as reader:
            assert reader.read() == data
        assert view.materialized_bytes == len(data)
    assert (store.whole_reads, whole_readbacks) == ([], []), {
        "whole_source_reads": store.whole_reads, "whole_destination_reads": whole_readbacks,
    }
    assert sum(store.stream_reads) == len(data)
    assert all(0 < size <= CHUNK_BYTES for size in store.stream_requests)
    assert all(probe.reader.closed for probe in store.probes)
    assert not tuple(workspace.iterdir())


def test_mid_materialization_cancel_has_a_bounded_consumed_and_written_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"public\n" * (3 * CHUNK_BYTES // 7 + 1)
    store, manifest, workspace = copy_case(tmp_path, data)
    cap = capability_for(store, manifest, workspace)
    before = {p.name: p.read_bytes() for p in store._objects.iterdir()}
    sentinel = workspace / "unrelated"
    sentinel.write_bytes(b"preserved")
    event = threading.Event()
    store.on_chunk = event.set
    writes = observe_copy_writes(monkeypatch)
    monkeypatch.setattr(adapter, "FileSystemArtifactStore", lambda _root: store)
    with pytest.raises(adapter.PortableExecutionError) as caught:
        adapter.execute_portable_extraction(cap, emit_progress=lambda *_: None, cancel_event=event)
    assert caught.value.category == "cancelled"
    assert event.is_set()
    consumed = sum(store.whole_reads) + sum(store.stream_reads)
    assert (consumed <= CHUNK_BYTES, sum(writes)) == (True, 0), {
        "source_bytes_consumed": consumed, "destination_bytes_written": sum(writes),
    }
    assert {p.name: p.read_bytes() for p in store._objects.iterdir()} == before
    assert not tuple(store._temporary.iterdir())
    assert tuple(workspace.iterdir()) == (sentinel,)
    assert sentinel.read_bytes() == b"preserved"
    assert all(probe.reader.closed for probe in store.probes)


def test_default_artifact_checkpoint_callback_keeps_one_call_per_entry(tmp_path: Path) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public" * CHUNK_BYTES)
    checks: list[str] = []
    with MaterializedWorkspace(
        store, manifest, workspace, job_id="job-copy", attempt=1,
        cancel_check=lambda: checks.append("artifact"),
    ) as view:
        assert view.materialized_bytes == 6 * CHUNK_BYTES
    assert checks == ["artifact"]
    assert not tuple(workspace.iterdir())


@pytest.mark.parametrize("size,executable,reads", [
    (0, False, [1]), (1, True, [2, 1]),
    (CHUNK_BYTES, False, [CHUNK_BYTES, 1]),
    (CHUNK_BYTES + 1, True, [CHUNK_BYTES, 2, 1]),
])
def test_exact_content_eof_modes_and_byte_totals(
    tmp_path: Path, size: int, executable: bool, reads: list[int],
) -> None:
    data = bytes(index % 251 for index in range(size))
    store, _, workspace = copy_case(tmp_path, data)
    manifest = manifest_for(store, data, executable=executable)
    with MaterializedWorkspace(store, manifest, workspace, job_id="job-boundary", attempt=1) as view:
        path = view.binding_roots[BINDING_ID] / "src/payload.bin"
        assert path.read_bytes() == data and view.materialized_bytes == size
        assert path.stat().st_mode & 0o777 == (0o500 if executable else 0o400)
    assert store.whole_reads == [] and store.stream_requests == reads
    assert isinstance(store.probes[0].reader, VerifyingArtifactStream)
    assert store.probes[0].reader.verified
    assert store.probes[0].reader.closed and store.probes[0].exits == [None]
    assert not tuple(workspace.iterdir())
