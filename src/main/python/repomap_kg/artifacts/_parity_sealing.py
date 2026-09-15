"""Public-safe offline parity graph sealing and source environment management."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
from pathlib import Path
import shutil
import stat
from typing import Iterator

from repomap_kg.artifacts.manifest import (
    ManifestArtifact,
    ManifestBinding,
    PortableSnapshotManifest,
)
from repomap_kg.artifacts.store import ArtifactStore
from repomap_kg.graph.multi_source import SourceKind
from repomap_kg.graph.multi_source_pipeline import MultiSourceCandidateBundle
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


@contextmanager
def _harness_owned_source_graph(
    graph: OpsGraphConfig,
    owned_root: Path,
) -> Iterator[tuple[OpsGraphConfig, tuple[Path, ...]]]:
    if owned_root.exists():
        raise ValueError("parity harness source-copy root already exists")
    owned_root.mkdir(mode=0o700)
    try:
        copied_bindings = []
        copied_roots = []
        for index, binding in enumerate(graph.effective_source_bindings):
            source = Path(binding.root_path_expanded)
            destination = owned_root / f"binding-{index:04d}"
            shutil.copytree(source, destination, copy_function=shutil.copy2)
            copied_roots.append(destination)
            copied_bindings.append(
                replace(
                    binding,
                    root_path=str(destination),
                    root_path_expanded=str(destination),
                )
            )
        yield (
            replace(
                graph,
                root_path="",
                root_path_expanded="",
                source_bindings=tuple(copied_bindings),
                explicit_source_bindings=True,
            ),
            tuple(copied_roots),
        )
    finally:
        if owned_root.exists():
            shutil.rmtree(owned_root)


def _source_signature(graph: OpsGraphConfig) -> tuple[tuple[object, ...], ...]:
    records: list[tuple[object, ...]] = []
    for binding in graph.effective_source_bindings:
        root = Path(binding.root_path_expanded)
        records.append((binding.binding_id, ".", root.stat().st_ino, root.stat().st_mode))
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            metadata = path.lstat()
            content = path.read_bytes() if stat.S_ISREG(metadata.st_mode) else None
            records.append(
                (
                    binding.binding_id,
                    relative,
                    metadata.st_ino,
                    metadata.st_mode,
                    content,
                )
            )
    return tuple(records)


def _seal_graph(
    graph: OpsGraphConfig,
    incumbent: MultiSourceCandidateBundle,
    store: ArtifactStore,
) -> PortableSnapshotManifest:
    snapshots = {
        item.binding.binding_id: item for item in incumbent.candidate.snapshots
    }
    bindings: list[ManifestBinding] = []
    entries: list[ManifestArtifact] = []
    for configured in sorted(graph.effective_source_bindings, key=lambda item: item.binding_id):
        snapshot = snapshots[configured.binding_id]
        bindings.append(
            ManifestBinding(
                binding_id=configured.binding_id,
                revision=configured.revision,
                snapshot_id=snapshot.snapshot_id,
                source_definition_id=configured.source_definition_id,
                source_kind=(
                    "local-directory"
                    if configured.source_kind is SourceKind.FOLDER
                    else "git-tree"
                ),
                acquisition_method="sealed-local-copy",
                selection_policy_id=configured.selection_policy_id,
                ignore_policy_id=snapshot.ignore_policy_id,
                privacy_policy=configured.privacy,
                role=configured.role,
                input_name=configured.input_name,
                alias=configured.alias,
                logical_root=configured.logical_root,
                evidence_retention_policy=configured.evidence_retention,
                extractor_profile=configured.extractor_profile,
                resolution_policy=configured.resolution_policy,
                repository_scope=graph.repository_name,
            )
        )
        root = Path(configured.root_path_expanded)
        for item in snapshot.manifest_entries:
            data = root.joinpath(*item.relative_path.split("/")).read_bytes()
            if hashlib.sha256(data).hexdigest() != item.content_sha256:
                raise ValueError("source changed while sealing parity fixture")
            reference = store.put(
                data,
                media_type="application/octet-stream",
                record_format="bytes-v1",
                privacy=PrivacyClassification.RAW_SOURCE,
            )
            entries.append(
                ManifestArtifact(
                    configured.binding_id,
                    item.relative_path,
                    reference,
                    item.executable,
                )
            )
    candidate = incumbent.candidate
    return PortableSnapshotManifest.create(
        graph_id=graph.id,
        bindings=bindings,
        entries=entries,
        source_generation=incumbent.source_generation,
        config_generation=incumbent.config_generation,
        extractor_generation="eg1:portable-python-static-v1",
        canonicalizer_generation="kg1:portable-canonicalizer-v1",
        extractor_capability_identity=candidate.extractor_capability_identity,
        resolver_identity=candidate.resolver_identity,
        canonicalizer_identity=candidate.canonicalizer_identity,
        semantic_contract_identity=candidate.semantic_contract_identity,
        quality_rule_identity=candidate.quality_rule_identity,
    )


seal_graph = _seal_graph


__all__ = [
    "_harness_owned_source_graph",
    "_seal_graph",
    "_source_signature",
    "seal_graph",
]
