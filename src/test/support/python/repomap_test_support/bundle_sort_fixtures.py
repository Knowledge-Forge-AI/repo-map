"""Public fixture metadata for real streaming-sort resource witnesses."""
from __future__ import annotations

from collections.abc import Iterable
import builtins
from pathlib import Path
import tempfile
from typing import Any, BinaryIO, Literal

import pytest

from common_lore_index._temporary import OwnedTemporaryDirectory
from common_lore_index.artifacts._bundle_stream_encode import StreamingBundleEncoder
from common_lore_index.artifacts.bundle import PublicationBundle
from common_lore_index.storage.staging_family_rows import StageFamily
from repomap_test_support.portable_publication_fixtures import _bundle


class SortIOWitness:
    """Observe actual input/output handles without replacing their IO."""

    def __init__(self) -> None:
        self.inputs: list[BinaryIO] = []
        self.outputs: list[Any] = []
        self.merge_paths: list[Path] = []
        self.peak_inputs = 0
        self.peak_handles = 0
        self._temporary = tempfile.NamedTemporaryFile

    def _sample(self) -> None:
        self.peak_inputs = max(self.peak_inputs, sum(not handle.closed for handle in self.inputs))
        self.peak_handles = max(self.peak_handles, sum(not handle.closed for handle in self.inputs + self.outputs))

    def open_run(self, path: Path, mode: Literal["rb"]) -> BinaryIO:
        handle = builtins.open(path, mode)
        self.inputs.append(handle)
        self._sample()
        return handle

    def temporary(self, **kwargs: Any) -> Any:
        handle = self._temporary(**kwargs)
        self.outputs.append(handle)
        if kwargs["prefix"] == "merge_":
            self.merge_paths.append(Path(handle.name))
        self._sample()
        return handle

    @property
    def all_closed(self) -> bool:
        return all(handle.closed for handle in self.inputs + self.outputs)


def observe_sort_directory_cleanup(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Observe remaining runs before the real fallback removes its directory."""
    remaining: list[int] = []
    original = OwnedTemporaryDirectory.cleanup

    def cleanup(directory: OwnedTemporaryDirectory) -> None:
        if Path(directory.name).name.startswith("repomap_sort_"):
            remaining.append(len(tuple(Path(directory.name).iterdir())))
        original(directory)

    monkeypatch.setattr(OwnedTemporaryDirectory, "cleanup", cleanup)
    return remaining


def encoder_for_rows(
    root: Path, rows: Iterable[dict[str, object]], **options: Any,
) -> StreamingBundleEncoder:
    bundle = _bundle()
    families: dict[StageFamily, Iterable[dict[str, object]]] = {
        family: () for family in bundle.families
    }
    families["files"] = rows
    return encoder_for_bundle(root, bundle, family_rows=families, **options)


def encoder_for_bundle(
    root: Path, bundle: PublicationBundle, **options: Any,
) -> StreamingBundleEncoder:
    options.setdefault("family_rows", bundle.families)
    return StreamingBundleEncoder(
        request_id=bundle.request_id, job_id=bundle.job_id, attempt=bundle.attempt,
        graph_id=bundle.graph_id, candidate_id=bundle.candidate_id,
        snapshot_manifest_id=bundle.snapshot_manifest_id, snapshot_vector=bundle.snapshot_vector,
        source_generation=bundle.source_generation, config_generation=bundle.config_generation,
        extractor_generation=bundle.extractor_generation, canonicalizer_generation=bundle.canonicalizer_generation,
        extractor_capability_identity=bundle.extractor_capability_identity, resolver_identity=bundle.resolver_identity,
        canonicalizer_identity=bundle.canonicalizer_identity, semantic_contract_identity=bundle.semantic_contract_identity,
        quality_rule_identity=bundle.quality_rule_identity, privacy=bundle.privacy,
        row_stage_contract=bundle.row_stage_contract, spool_dir=root, **options,
    )
