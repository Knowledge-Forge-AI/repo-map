"""Parent-owned source sealing for portable semantic attempts."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import stat

from repomap_kg.artifacts.manifest import (
    ManifestArtifact,
    ManifestBinding,
    PortableSnapshotManifest,
)
from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.graph.multi_source import (
    GraphCandidate,
    SourceKind,
    multi_source_configuration_id,
)
from repomap_kg.graph.multi_source_pipeline import (
    multi_source_semantic_identities,
    scan_multi_source_generations,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


def seal_configured_sources(
    graph: OpsGraphConfig,
    store: FileSystemArtifactStore,
    *,
    extractor_generation: str,
    canonicalizer_generation: str,
) -> tuple[PortableSnapshotManifest, ArtifactReference, str]:
    """Seal one stable configured inventory without running semantic extraction."""

    first = scan_multi_source_generations(graph)
    snapshots = {item.binding.binding_id: item for item in first.snapshots}
    bindings: list[ManifestBinding] = []
    entries: list[ManifestArtifact] = []
    for configured in sorted(
        graph.effective_source_bindings, key=lambda item: item.binding_id
    ):
        snapshot = snapshots[configured.binding_id]
        bindings.append(_manifest_binding(graph, configured, snapshot.ignore_policy_id, snapshot.snapshot_id))
        root = Path(configured.root_path_expanded).resolve(strict=True)
        for item in snapshot.manifest_entries:
            source = root.joinpath(*item.relative_path.split("/"))
            details = source.lstat()
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_nlink != 1
                or source.is_symlink()
                or not source.resolve(strict=True).is_relative_to(root)
            ):
                raise ValueError("source inventory is not sealable")
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != item.content_sha256:
                raise ValueError("source changed while sealing")
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
    second = scan_multi_source_generations(graph)
    if second.source_generation != first.source_generation or second.snapshots != first.snapshots:
        raise ValueError("source changed while sealing")
    identities = multi_source_semantic_identities(graph)
    candidate = GraphCandidate.create(
        graph.id,
        first.snapshots,
        configuration_identity=multi_source_configuration_id(
            graph.id,
            tuple(item.binding for item in first.snapshots),
        ),
        extractor_capability_identity=identities[0],
        resolver_identity=identities[1],
        canonicalizer_identity=identities[2],
        semantic_contract_identity=identities[3],
        quality_rule_identity=identities[4],
    )
    manifest = PortableSnapshotManifest.create(
        graph_id=graph.id,
        bindings=bindings,
        entries=entries,
        source_generation=first.source_generation,
        config_generation=first.config_generation,
        extractor_generation=extractor_generation,
        canonicalizer_generation=canonicalizer_generation,
        extractor_capability_identity=identities[0],
        resolver_identity=identities[1],
        canonicalizer_identity=identities[2],
        semantic_contract_identity=identities[3],
        quality_rule_identity=identities[4],
    )
    reference = store.put(
        manifest.canonical_bytes(),
        media_type="application/x-repomap-snapshot-manifest-v1+json",
        record_format="canonical-json-v1",
        privacy=manifest.effective_privacy,
    )
    return manifest, reference, candidate.candidate_id


def _manifest_binding(
    graph: OpsGraphConfig,
    configured: OpsGraphSourceBindingConfig,
    ignore_policy_id: str,
    snapshot_id: str,
) -> ManifestBinding:
    scope = (
        graph.repository_name
        if graph.repository_name and re.fullmatch(r"[A-Za-z0-9._-]+", graph.repository_name)
        else graph.id
    )
    return ManifestBinding(
        binding_id=configured.binding_id,
        revision=configured.revision,
        snapshot_id=snapshot_id,
        source_definition_id=configured.source_definition_id,
        source_kind=(
            "local-directory"
            if configured.source_kind is SourceKind.FOLDER
            else "git-tree"
        ),
        acquisition_method="sealed-local-copy",
        selection_policy_id=configured.selection_policy_id,
        ignore_policy_id=ignore_policy_id,
        privacy_policy=configured.privacy,
        role=configured.role,
        input_name=configured.input_name,
        alias=configured.alias,
        logical_root=configured.logical_root,
        evidence_retention_policy=configured.evidence_retention,
        extractor_profile=configured.extractor_profile,
        resolution_policy=configured.resolution_policy,
        repository_scope=scope,
    )


__all__ = ("seal_configured_sources",)
