"""Parent-owned source sealing for portable semantic attempts."""

from __future__ import annotations

from pathlib import Path
import re

from common_lore_index.artifacts.manifest import (
    DEFAULT_ARTIFACT_LIMITS,
    ManifestArtifact,
    ManifestBinding,
    PortableSnapshotManifest,
)
from common_lore_index.artifacts._manifest_records import (
    ArtifactLimits,
    _validate_inventory_shape,
    _validate_limits,
)
from common_lore_index.artifacts.references import ArtifactReference
from common_lore_index.artifacts.store import FileSystemArtifactStore
from common_lore_index.artifacts._source_sealing_io import (
    SourceUnsealableError,
    open_source_body,
)
from common_lore_index.artifacts._store_common import (
    ArtifactErrorCode,
    ArtifactIntegrityError,
)
from common_lore_index.graph.multi_source import (
    GraphCandidate,
    SourceKind,
    multi_source_configuration_id,
)
from common_lore_index.graph.multi_source_pipeline import (
    multi_source_semantic_identities,
    scan_multi_source_generations,
)
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig
from common_lore_index.storage.staging_family_contracts import PrivacyClassification


def seal_configured_sources(
    graph: OpsGraphConfig,
    store: FileSystemArtifactStore,
    *,
    extractor_generation: str,
    canonicalizer_generation: str,
    limits: ArtifactLimits = DEFAULT_ARTIFACT_LIMITS,
) -> tuple[PortableSnapshotManifest, ArtifactReference, str]:
    """Seal one stable configured inventory without running semantic extraction."""

    _validate_limits(limits)
    first = scan_multi_source_generations(graph)
    snapshots = {item.binding.binding_id: item for item in first.snapshots}
    configured_bindings = tuple(
        sorted(graph.effective_source_bindings, key=lambda item: item.binding_id)
    )
    bindings = [
        _manifest_binding(
            graph,
            configured,
            snapshots[configured.binding_id].ignore_policy_id,
            snapshots[configured.binding_id].snapshot_id,
        )
        for configured in configured_bindings
    ]
    inventory = [
        (configured.binding_id, item.relative_path, item.size_bytes)
        for configured in configured_bindings
        for item in snapshots[configured.binding_id].manifest_entries
    ]
    _validate_inventory_shape(
        [item.binding_id for item in bindings], inventory, limits
    )
    entries: list[ManifestArtifact] = []
    for configured in configured_bindings:
        snapshot = snapshots[configured.binding_id]
        root = Path(configured.root_path_expanded).resolve(strict=True)
        for item in snapshot.manifest_entries:
            try:
                with open_source_body(
                    root,
                    item.relative_path,
                    expected_size=item.size_bytes,
                    expected_digest=item.content_sha256,
                    expected_executable=item.executable,
                ) as body:
                    reference = store.put(
                        body,
                        content_digest="sha256:" + item.content_sha256,
                        max_bytes=item.size_bytes,
                        media_type="application/octet-stream",
                        record_format="bytes-v1",
                        privacy=PrivacyClassification.RAW_SOURCE,
                    )
            except SourceUnsealableError:
                raise
            except ArtifactIntegrityError as error:
                if (
                    error.code is ArtifactErrorCode.ARTIFACT_BOUNDS
                    or str(error) == "artifact digest does not match supplied digest"
                ):
                    raise ValueError("source changed while sealing") from None
                raise
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
        limits=limits,
    )
    reference = store.put(
        manifest.canonical_bytes(),
        media_type="application/x-repomap-snapshot-manifest-v1+json",
        record_format="canonical-json-v1",
        privacy=manifest.effective_privacy,
        max_bytes=limits.max_manifest_bytes,
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
