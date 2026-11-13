"""Preserve artifact refusal categories and independently verify custom streams."""
from __future__ import annotations

from dataclasses import replace
import io
from pathlib import Path
from typing import BinaryIO, cast

import pytest

from common_lore_index.artifacts import PortableSnapshotManifest
from common_lore_index.artifacts._store_stream import VerifyingArtifactStream
from common_lore_index.artifacts.store import (
    ArtifactErrorCode, ArtifactIntegrityError, FileSystemArtifactStore, MemoryArtifactStore,
)
from common_lore_index.coordinator._portable_materialization import MaterializedWorkspace
from repomap_test_support.materialization_fixtures import (
    BINDING_ID, CHUNK_BYTES, FaultSource, copy_case, manifest_for,
)


@pytest.mark.parametrize("fault,code", [
    ("short", ArtifactErrorCode.ARTIFACT_CORRUPT),
    ("excess", ArtifactErrorCode.ARTIFACT_BOUNDS),
    ("digest", ArtifactErrorCode.ARTIFACT_CORRUPT),
    ("stale", ArtifactErrorCode.ARTIFACT_STALE),
])
def test_filesystem_source_refusals_keep_their_existing_codes(
    tmp_path: Path, fault: str, code: ArtifactErrorCode,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public")
    entry = manifest.entries[0]
    if fault == "stale":
        changed = replace(entry, reference=entry.reference.with_store_version("filesystem-v1-stale"))
        manifest = PortableSnapshotManifest.create_from(manifest, entries=(changed,))
    else:
        content = {"short": b"pub", "excess": b"public!", "digest": b"PUBLIC"}[fault]
        store.object_path(entry.reference).write_bytes(content)
    with pytest.raises(ArtifactIntegrityError) as caught:
        with MaterializedWorkspace(store, manifest, workspace, job_id="job-corrupt", attempt=1):
            pytest.fail("invalid source returned a view")
    assert caught.value.code == code
    assert not tuple(workspace.iterdir())
    assert all(probe.reader.closed for probe in store.probes)


@pytest.mark.parametrize("stage", ["open", "enter", "read", "exit"])
def test_each_source_oserror_is_normalized_with_its_original_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public")
    original = store.open_stream
    marker = PermissionError("source permission fixture")
    sources: list[FaultSource] = []

    def opened(reference, max_bytes=None):
        if stage == "open":
            raise marker
        source = FaultSource(original(reference, max_bytes), {stage: marker})
        sources.append(source)
        return cast(BinaryIO, source)

    monkeypatch.setattr(store, "open_stream", opened)
    with pytest.raises(ArtifactIntegrityError) as caught:
        with MaterializedWorkspace(store, manifest, workspace, job_id="job-source", attempt=1):
            pytest.fail("source failure returned a view")
    assert caught.value.code == ArtifactErrorCode.ARTIFACT_CORRUPT
    assert caught.value.__cause__ is marker
    assert not tuple(workspace.iterdir())
    assert all(source.reader.closed for source in sources)
    if sources:
        names = [name for name, _ in sources[0].events]
        assert names.count("close" if stage == "enter" else "exit") == 1


@pytest.mark.parametrize("fault", ["short", "excess", "digest", "oversized-read", "non-bytes"])
def test_nonconforming_custom_streams_cannot_return_an_unverified_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public")
    raw = io.BytesIO({"short": b"pub", "excess": b"public!"}.get(fault, b"PUBLIC"))

    class Reader:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            raw.close()

        def read(self, size):
            if fault == "oversized-read":
                return b"x" * (size + 1)
            if fault == "non-bytes":
                return None
            return raw.read(size)

    monkeypatch.setattr(store, "open_stream", lambda *_args, **_kwargs: Reader())
    with pytest.raises(ArtifactIntegrityError) as caught:
        with MaterializedWorkspace(store, manifest, workspace, job_id="job-custom", attempt=1):
            pytest.fail("nonconforming stream returned a view")
    assert caught.value.code == ArtifactErrorCode.ARTIFACT_CORRUPT
    assert raw.closed and not tuple(workspace.iterdir())


def test_a_custom_store_cannot_bypass_the_already_selected_artifact_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, workspace = copy_case(tmp_path, b"public")
    raw = io.BytesIO(b"public")
    monkeypatch.setattr(store, "open_stream", lambda *_args, **_kwargs: raw)
    with pytest.raises(ArtifactIntegrityError) as caught:
        with MaterializedWorkspace(
            store, manifest, workspace, job_id="job-custom-bounds", attempt=1, max_artifact_bytes=3,
        ):
            pytest.fail("ignored source bound returned a view")
    assert caught.value.code == ArtifactErrorCode.ARTIFACT_BOUNDS
    assert raw.closed and not tuple(workspace.iterdir())


@pytest.mark.parametrize("backend,versioned", [
    ("filesystem", True), ("memory", True), ("filesystem", False), ("memory", False),
])
def test_both_supported_stores_accept_versioned_and_portable_versionless_references(
    tmp_path: Path, backend: str, versioned: bool,
) -> None:
    store = FileSystemArtifactStore(tmp_path / "store") if backend == "filesystem" else MemoryArtifactStore()
    data = b"public\x00artifact"
    manifest = manifest_for(store, data)
    if not versioned:
        manifest = PortableSnapshotManifest.from_bytes(manifest.canonical_bytes())
        assert manifest.entries[0].reference.store_version is None
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    with MaterializedWorkspace(store, manifest, workspace, job_id="job-stores", attempt=1) as view:
        assert (view.binding_roots[BINDING_ID] / "src/payload.bin").read_bytes() == data
        assert view.materialized_bytes == len(data)
    assert store.read(manifest.entries[0].reference) == data
    assert not tuple(workspace.iterdir())


def test_a_legitimate_short_read_stream_is_consumed_through_actual_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"public" * CHUNK_BYTES
    store, manifest, workspace = copy_case(tmp_path, data)
    original = FileSystemArtifactStore.open_stream
    sources: list[FaultSource] = []

    class ShortReader(FaultSource):
        def read(self, size: int = -1) -> bytes:
            return super().read(min(size, 37))

    def opened(reference, max_bytes=None):
        source = ShortReader(original(store, reference, max_bytes))
        sources.append(source)
        return cast(BinaryIO, source)

    monkeypatch.setattr(store, "open_stream", opened)
    with MaterializedWorkspace(store, manifest, workspace, job_id="job-short", attempt=1) as view:
        assert view.materialized_bytes == len(data)
    assert len([name for name, _ in sources[0].events if name == "read"]) > 2
    assert isinstance(sources[0].reader, VerifyingArtifactStream)
    assert sources[0].reader.verified and sources[0].reader.closed
    assert sources[0].events[-1] == ("exit", None)
    assert not tuple(workspace.iterdir())
