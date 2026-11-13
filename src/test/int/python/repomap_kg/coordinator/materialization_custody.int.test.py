"""Real source IO and adapter error/cancellation categories in an isolated sandbox."""
from __future__ import annotations
import errno
import os
from dataclasses import replace
from pathlib import Path
import threading
from typing import BinaryIO, cast
import pytest
from common_lore_index.artifacts.store import ArtifactIntegrityError, FileSystemArtifactStore
from common_lore_index.artifacts.validator import PublisherBundleValidator
from common_lore_index.coordinator import _portable_semantic_adapter as adapter
from common_lore_index.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_test_support.materialization_fixtures import CHUNK_BYTES, FaultSource, SourceProbe, WitnessStore, patch_copy_os
from repomap_test_support.portable_spool_case import spool_case
from repomap_test_support.portable_worker_equivalence import reference_bytes, publication_expectation


def test_streamed_real_source_keeps_exact_reference_bundle_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, store, manifest, candidate_id, capability, sentinel = spool_case(tmp_path, functions=4201)
    reference = capture_multi_source_candidate(config)
    expected = reference_bytes(reference, manifest, capability, tmp_path / "reference-sort")
    witness = WitnessStore(store.root)
    witness.targets = {entry.reference.content_digest for entry in manifest.entries}
    monkeypatch.setattr(adapter, "FileSystemArtifactStore", lambda _root: witness)
    result = adapter.execute_portable_extraction(capability, emit_progress=lambda *_: None, cancel_event=threading.Event())
    assert store.read(result.bundle_reference) == expected
    validation = PublisherBundleValidator().validate_bundle(
        store=store, bundle_reference=result.bundle_reference, receipt_reference=result.receipt_reference,
        expectation=publication_expectation(manifest, capability, candidate_id),
    )
    assert validation.byte_integrity_valid and validation.semantic_authority_valid
    assert witness.whole_reads == [] and sum(witness.stream_reads) == manifest.total_bytes
    assert max(witness.stream_requests) <= CHUNK_BYTES
    assert all(probe.reader.closed for probe in witness.probes)
    assert tuple(capability.workspace_root.iterdir()) == (sentinel,)
    assert sentinel.read_bytes() == b"preserved"


class NonconformingSource(FaultSource):
    """A real file reader deliberately violating the store contract, for guards."""

    def __init__(self, reader, mode):
        super().__init__(reader)
        self.mode = mode
        self.calls = 0
        self.extra = False

    def read(self, size=-1):
        self.calls += 1
        if self.mode == "custom-invalid":
            return cast(bytes, None)
        if self.mode == "custom-over-read":
            return b"x" * (size + 1)
        if self.mode == "custom-short" and self.calls > 1:
            return b""
        chunk = self.reader.read(size)
        if self.mode == "custom-digest" and self.calls == 1:
            return b"!" + chunk[1:]
        if self.mode == "custom-excess" and not chunk and not self.extra:
            self.extra = True
            return b"!"
        return chunk


def _destination_fault(monkeypatch, fault, workspace, error):
    original_open, original_stat, original_read = os.open, os.fstat, os.read
    original_write, original_close = os.write, os.close
    closes: list[int] = []

    def opened(path, flags, mode=0o777, **kwargs):
        writer = bool(flags & os.O_WRONLY)
        if (fault == "destination-open" and writer) or (fault == "destination-readback-open" and not writer):
            raise error
        return original_open(path, flags, mode, **kwargs)

    def inspected(descriptor):
        if fault == "destination-stat":
            raise error
        return original_stat(descriptor)

    def read(descriptor, size):
        if fault == "destination-readback":
            raise error
        return original_read(descriptor, size)

    def write(descriptor, value):
        if fault in {"destination-write", "source-exit-and-destination-write"}:
            raise error
        if fault == "destination-zero":
            return 0
        return original_write(descriptor, value)

    def close(descriptor):
        original_close(descriptor)
        closes.append(descriptor)
        if (fault == "destination-close" and len(closes) == 1) or (fault == "destination-readback-close" and len(closes) == 2):
            raise error
        if fault == "destination-readback-corrupt" and len(closes) == 1:
            path = next(workspace.rglob("public.py"))
            path.write_bytes(b"!" * path.stat().st_size)

    patch_copy_os(monkeypatch, open=opened, fstat=inspected, read=read, write=write, close=close)
    return closes


def _observe_fault(monkeypatch, targets, event, fault, workspace):
    source_error = PermissionError("source IO fixture")
    destination_error = PermissionError(errno.EACCES, "destination IO fixture")
    original_stream = FileSystemArtifactStore.open_stream
    sources: list[FaultSource | SourceProbe] = []
    consumed: list[int] = []
    requests: list[int] = []
    source_faults = {"source-enter": "enter", "source-read": "read", "source-exit": "exit", "source-exit-and-destination-write": "exit"}

    class CorruptWithCancel(FaultSource):
        def read(self, size=-1):
            event.set()
            raise ArtifactIntegrityError("cancelled")

    def opened(self, ref, max_bytes=None):
        if ref.content_digest not in targets:
            return original_stream(self, ref, max_bytes)
        source: FaultSource | SourceProbe
        if fault.startswith("custom-"):
            source = NonconformingSource(self.object_path(ref).open("rb"), fault)
        elif fault in source_faults:
            source = FaultSource(original_stream(self, ref, max_bytes), {source_faults[fault]: source_error})
        elif fault == "source-error-with-cancel":
            source = CorruptWithCancel(original_stream(self, ref, max_bytes))
        else:
            source = SourceProbe(original_stream(self, ref, max_bytes), consumed, requests, event.set if fault == "cancel-after-chunk" else None)
        sources.append(source)
        return cast(BinaryIO, source)

    monkeypatch.setattr(FileSystemArtifactStore, "open_stream", opened)
    closes = _destination_fault(monkeypatch, fault, workspace, destination_error)
    return destination_error, sources, consumed, closes


def _execute_fault(monkeypatch, manifest, capability, fault):
    targets = {entry.reference.content_digest for entry in manifest.entries}
    event = threading.Event()
    if fault == "custom-bounds":
        capability = replace(capability, max_artifact_bytes=capability.manifest_reference.size_bytes)
    destination_error, sources, consumed, closes = _observe_fault(monkeypatch, targets, event, fault, capability.workspace_root)
    with pytest.raises((adapter.PortableExecutionError, OSError)) as caught:
        adapter.execute_portable_extraction(capability, emit_progress=lambda *_: None, cancel_event=event)
    if fault in {"destination-zero", "destination-readback-corrupt"}:
        assert isinstance(caught.value, OSError)
        assert str(caught.value) == ("artifact write failed" if fault == "destination-zero" else "artifact verification failed")
    elif fault.startswith("destination-") or fault == "source-exit-and-destination-write":
        assert caught.value is destination_error
    else:
        assert isinstance(caught.value, adapter.PortableExecutionError)
        expected = {"cancel-after-chunk": "cancelled", "custom-bounds": "artifact_bounds"}.get(fault, "artifact_corrupt")
        assert caught.value.category == expected
    return sources, consumed, closes


@pytest.mark.parametrize("fault", [
    "source-enter", "source-read", "source-exit", "source-error-with-cancel",
    "source-exit-and-destination-write", "cancel-after-chunk",
    "destination-open", "destination-stat", "destination-write", "destination-zero",
    "destination-close", "destination-readback-open", "destination-readback",
    "destination-readback-close", "destination-readback-corrupt",
    "custom-short", "custom-excess", "custom-digest", "custom-invalid",
    "custom-over-read", "custom-bounds",
])
def test_reached_materialization_faults_keep_adapter_categories_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    _, store, manifest, _, capability, sentinel = spool_case(tmp_path, functions=4201)
    before = {p.name: p.read_bytes() for p in store._objects.iterdir()}
    sources, consumed, closes = _execute_fault(monkeypatch, manifest, capability, fault)
    if fault == "cancel-after-chunk":
        assert 0 < sum(consumed) <= CHUNK_BYTES
    if fault.startswith("destination-") and fault != "destination-open":
        assert closes
    assert sources and all(source.reader.closed for source in sources)
    assert {p.name: p.read_bytes() for p in store._objects.iterdir()} == before
    assert not tuple(store._temporary.iterdir())
    assert tuple(capability.workspace_root.iterdir()) == (sentinel,)
    assert sentinel.read_bytes() == b"preserved"
