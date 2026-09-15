"""Records for graph-local source-binding configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from repomap_kg.graph.multi_source import (
    GraphSourceBinding,
    SourceDefinition,
    SourceKind,
)
from repomap_kg.ops.config_helpers import (
    PRIVATE_PATH_DISPLAY,
    PRIVATE_PRIVACY,
    PRIVATE_ROOT_DISPLAY,
    PRIVATE_SOURCE_DISPLAY,
    redact_text,
)


@dataclass(frozen=True)
class OpsGraphSourceBindingConfig:
    schema_version: int
    binding_id: str
    source_definition_id: str
    alias: str
    revision: int
    source_kind: SourceKind
    root_path: str
    root_path_expanded: str
    repository_name: str
    logical_root: str
    privacy: str
    evidence_retention: str
    extractor_profile: str
    include_paths: tuple[str, ...]
    exclude_paths: tuple[str, ...]
    selection_policy_id: str
    resolution_policy: str
    enabled: bool = True
    role: str = "source"
    input_name: str | None = None

    def domain_binding(self, graph_id: str) -> GraphSourceBinding:
        return GraphSourceBinding(
            binding_id=self.binding_id,
            graph_id=graph_id,
            alias=self.alias,
            source_definition=SourceDefinition(
                self.source_definition_id, self.source_kind
            ),
            revision=self.revision,
            logical_root=self.logical_root,
            privacy_policy=self.privacy,
            evidence_retention_policy=self.evidence_retention,
            extractor_profile=self.extractor_profile,
            selection_policy_id=self.selection_policy_id,
            resolution_policy=self.resolution_policy,
            role=self.role,
            input_name=self.input_name,
            enabled=self.enabled,
        )

    def to_jsonable(self, *, graph_privacy: str | None = None) -> dict[str, Any]:
        private = (
            self.privacy in PRIVATE_PRIVACY
            or graph_privacy in PRIVATE_PRIVACY
        )
        return {
            "schema_version": self.schema_version,
            "binding_id": self.binding_id,
            "source_definition_id": self.source_definition_id,
            "alias": self.alias,
            "revision": self.revision,
            "source_kind": self.source_kind.value,
            "root_path": PRIVATE_ROOT_DISPLAY if private else self.root_path,
            "root_path_expanded": (
                PRIVATE_ROOT_DISPLAY if private else self.root_path_expanded
            ),
            "repository_name": (
                PRIVATE_SOURCE_DISPLAY if private else self.repository_name
            ),
            "logical_root": PRIVATE_PATH_DISPLAY if private else self.logical_root,
            "privacy": self.privacy,
            "evidence_retention": self.evidence_retention,
            "extractor_profile": self.extractor_profile,
            "include_paths": [
                PRIVATE_PATH_DISPLAY if private else redact_text(path)
                for path in self.include_paths
            ],
            "exclude_paths": [
                PRIVATE_PATH_DISPLAY if private else redact_text(path)
                for path in self.exclude_paths
            ],
            "selection_policy_id": self.selection_policy_id,
            "resolution_policy": self.resolution_policy,
            "enabled": self.enabled,
            "role": self.role,
            "input_name": (
                PRIVATE_SOURCE_DISPLAY if private and self.input_name else self.input_name
            ),
            "private": private,
        }


__all__ = ["OpsGraphSourceBindingConfig"]
