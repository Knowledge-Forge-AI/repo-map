"""Real owned artifact fixtures and bounded source observations for copy tests."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
import os
import sys
from types import SimpleNamespace, TracebackType
from typing import BinaryIO, cast

import pytest

from common_lore_index.artifacts import ManifestArtifact, ManifestBinding, PortableSnapshotManifest
from common_lore_index.artifacts.references import ArtifactReference
from common_lore_index.artifacts.store import ArtifactStore, FileSystemArtifactStore
from common_lore_index.artifacts._store_stream import VerifyingArtifactStream
from common_lore_index.coordinator._portable_capability import PortableExecutionCapability
from common_lore_index.storage.staging_family_contracts import PrivacyClassification

BINDING_ID = "bind1:" + "1" * 64
CHUNK_BYTES = 65536


@dataclass
class SourceProbe:
    reader: BinaryIO
    observed: list[int]
    requests: list[int]
    on_chunk: Callable[[], None] | None
    exits: list[BaseException | None] = field(default_factory=list)

    @property
    def closed(self) -> bool:
        return self.reader.closed

    @property
    def verified(self) -> bool:
        return isinstance(self.reader, VerifyingArtifactStream) and self.reader.verified

    def fileno(self) -> int:
        return self.reader.fileno()

    def __enter__(self) -> SourceProbe:
        self.reader.__enter__()
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> bool | None:
        self.exits.append(error)
        return self.reader.__exit__(kind, error, traceback)

    def close(self) -> None:
        self.reader.close()

    def read(self, size: int = -1) -> bytes:
        self.requests.append(size)
        chunk = self.reader.read(size)
        self.observed.append(len(chunk))
        if chunk and self.on_chunk is not None:
            self.on_chunk()
        return chunk


@dataclass
class FaultSource:
    """Inject named failures around a real owned and verifiable file stream."""

    reader: BinaryIO
    faults: Mapping[str, BaseException] = field(default_factory=dict)
    events: list[tuple[str, BaseException | None]] = field(default_factory=list)

    def _fail(self, name: str) -> None:
        error = self.faults.get(name)
        if error is not None:
            raise error

    def __enter__(self) -> FaultSource:
        self.events.append(("enter", None))
        self.reader.__enter__()
        self._fail("enter")
        return self

    def read(self, size: int = -1) -> bytes:
        self.events.append(("read", None))
        self._fail("read")
        return self.reader.read(size)

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> bool | None:
        self.events.append(("exit", error))
        result = self.reader.__exit__(kind, error, traceback)
        self._fail("exit")
        return result

    def close(self) -> None:
        self.events.append(("close", None))
        self._fail("close_before")
        self.reader.close()
        self._fail("close")


class WitnessStore(FileSystemArtifactStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.targets: set[str] = set()
        self.whole_reads: list[int] = []
        self.stream_reads: list[int] = []
        self.stream_requests: list[int] = []
        self.probes: list[SourceProbe] = []
        self.on_chunk: Callable[[], None] | None = None

    def read(self, reference: ArtifactReference, max_bytes: int | None = None) -> bytes:
        data = super().read(reference, max_bytes)
        if reference.content_digest in self.targets:
            self.whole_reads.append(len(data))
            if self.on_chunk is not None:
                self.on_chunk()
        return data

    def open_stream(self, reference: ArtifactReference, max_bytes: int | None = None) -> BinaryIO:
        stream = super().open_stream(reference, max_bytes)
        if reference.content_digest not in self.targets:
            return stream
        probe = SourceProbe(stream, self.stream_reads, self.stream_requests, self.on_chunk)
        self.probes.append(probe)
        return cast(BinaryIO, probe)


def manifest_for(store: ArtifactStore, content: bytes, *, executable: bool = False,
                 path: str = "src/payload.bin") -> PortableSnapshotManifest:
    binding = ManifestBinding(
        BINDING_ID, 1, "snap1:" + "2" * 64, "src1:fixture", "local-directory",
        "sealed-local-copy", "select1:" + "3" * 64, "ignore1:fixture",
        "public-dev", "source", None,
    )
    reference = store.put(content, privacy=PrivacyClassification.RAW_SOURCE)
    return PortableSnapshotManifest.create(
        graph_id="graph-copy", bindings=(binding,),
        entries=(ManifestArtifact(BINDING_ID, path, reference, executable),),
        source_generation="sg1:" + "4" * 64, config_generation="cg1:" + "5" * 64,
        extractor_generation="eg1:" + "6" * 64, canonicalizer_generation="kg1:" + "7" * 64,
        extractor_capability_identity="cap1:python-static-v1", resolver_identity="resolver1:nix-v1",
        canonicalizer_identity="canon1:graph-v1", semantic_contract_identity="semantic1:graph-key-v1",
        quality_rule_identity="quality1:accepted-v1",
    )


def copy_case(root: Path, content: bytes) -> tuple[WitnessStore, PortableSnapshotManifest, Path]:
    store = WitnessStore(root / "store")
    manifest = manifest_for(store, content)
    store.targets = {entry.reference.content_digest for entry in manifest.entries}
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    return store, manifest, workspace


def capability_for(store: WitnessStore, manifest: PortableSnapshotManifest,
                   workspace: Path) -> PortableExecutionCapability:
    reference = store.put(
        manifest.canonical_bytes(), media_type="application/x-repomap-snapshot-manifest-v1+json",
        record_format="canonical-json-v1", privacy=manifest.effective_privacy,
    )
    return PortableExecutionCapability(
        schema_version=1, job_id="job-copy", attempt=1, graph_id=manifest.graph_id,
        store_root=store.root, workspace_root=workspace, manifest_reference=reference,
        source_generation=manifest.source_generation, config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation, canonicalizer_generation=manifest.canonicalizer_generation,
        max_artifact_bytes=64 * 1024 * 1024, max_bundle_bytes=64 * 1024 * 1024,
    )


def patch_copy_os(monkeypatch: pytest.MonkeyPatch, **changes: object) -> None:
    """Patch only copy owners' os bindings; source/store/host OS stays real."""
    facade = SimpleNamespace(**(vars(os) | changes))
    for name in ("_portable_materialization", "_portable_materialization_copy", "_portable_materialization_io"):
        module = sys.modules.get("common_lore_index.coordinator." + name)
        if module is not None and hasattr(module, "os"):
            monkeypatch.setattr(module, "os", facade)


def observe_copy_writes(
    monkeypatch: pytest.MonkeyPatch, *, after_write: Callable[[], None] | None = None,
) -> list[int]:
    counts: list[int] = []
    original = os.write

    def write(descriptor: int, value: bytes | memoryview) -> int:
        count = original(descriptor, value)
        counts.append(count)
        if after_write is not None:
            after_write()
        return count

    patch_copy_os(monkeypatch, write=write)
    return counts
