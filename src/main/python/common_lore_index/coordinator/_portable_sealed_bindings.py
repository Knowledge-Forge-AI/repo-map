"""Project admitted manifest bindings onto their sealed semantic roots."""
from collections.abc import Mapping
from pathlib import Path

from common_lore_index.artifacts.manifest import PortableSnapshotManifest
from common_lore_index.graph.multi_source import SourceKind
from common_lore_index.graph.multi_source_pipeline import SealedSourceBinding


def sealed_bindings(
    manifest: PortableSnapshotManifest, roots: Mapping[str, Path],
) -> tuple[SealedSourceBinding, ...]:
    from common_lore_index.coordinator._portable_semantic_adapter import PortableExecutionError

    result = []
    for binding in manifest.bindings:
        if binding.alias is None:
            raise PortableExecutionError("unsupported_contract")
        result.append(
            SealedSourceBinding(
                binding_id=binding.binding_id,
                source_definition_id=binding.source_definition_id,
                alias=binding.alias,
                revision=binding.revision,
                source_kind=(
                    SourceKind.FOLDER
                    if binding.source_kind == "local-directory"
                    else SourceKind.GIT_WORKING_TREE
                ),
                root=roots[binding.binding_id],
                repository_scope=binding.repository_scope or "",
                logical_root=binding.logical_root or "",
                privacy=binding.privacy_policy,
                evidence_retention=binding.evidence_retention_policy or "",
                extractor_profile=binding.extractor_profile or "",
                selection_policy_id=binding.selection_policy_id,
                resolution_policy=binding.resolution_policy or "",
                role=binding.role,
                input_name=binding.input_name,
            )
        )
    return tuple(result)
