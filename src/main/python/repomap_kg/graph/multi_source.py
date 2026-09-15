"""Versioned deployment-neutral identities for multi-source graph candidates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re

from repomap_kg.graph._multi_source_identity import (
    MultiSourceIdentityError,
    bounded_ascii,
    digest,
    prefixed_digest,
    prefixed_token,
    token,
)
from repomap_kg.graph.multi_source_records import (
    GraphSourceBinding as GraphSourceBinding,
    SnapshotManifestEntry as SnapshotManifestEntry,
    SourceDefinition as SourceDefinition,
    SourceKind as SourceKind,
    SourceSnapshot as SourceSnapshot,
    _graph_id,
    graph_source_binding_id as graph_source_binding_id,
    multi_source_configuration_id as multi_source_configuration_id,
    source_binding_input_name as source_binding_input_name,
    source_binding_role as source_binding_role,
    source_definition_id as source_definition_id,
)


_MAX_SELECTION_PATTERN_BYTES = 512
_COMPATIBILITY_EXTRACTOR_PROFILE_PATTERN = re.compile(
    r"^(?:legacy-[0-9a-f]{32}|legacy-strict-v1-[0-9a-f]{64})$"
)


def compatibility_source_definition_id(graph_id: str) -> str:
    graph = _graph_id(graph_id)
    return "src1:legacy-" + hashlib.sha256(graph.encode("ascii")).hexdigest()


def _selection_patterns(values: Sequence[str], label: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        text = bounded_ascii(value, label, _MAX_SELECTION_PATTERN_BYTES)
        path = PurePosixPath(text)
        if path.is_absolute() or ".." in path.parts or text in {"", "."}:
            raise MultiSourceIdentityError(f"{label} is invalid")
        normalized.append(text)
    if len(normalized) != len(set(normalized)):
        raise MultiSourceIdentityError(f"duplicate {label}")
    return tuple(sorted(normalized))


def source_selection_policy_id(
    include_paths: Sequence[str], exclude_paths: Sequence[str]
) -> str:
    payload = {
        "exclude_paths": _selection_patterns(exclude_paths, "exclude path"),
        "include_paths": _selection_patterns(include_paths, "include path"),
    }
    return "select1:" + digest("repomap-source-selection-v1", payload)


def compatibility_source_selection_policy_id(exclude_paths: Sequence[str]) -> str:
    """Bind predecessor-accepted legacy exclusions without new-syntax validation."""

    values = tuple(exclude_paths)
    if any(not isinstance(value, str) or not value for value in values):
        raise MultiSourceIdentityError("legacy exclude path is invalid")
    return "select1:" + digest(
        "repomap-legacy-source-selection-v1",
        {"exclude_paths": values, "include_paths": ()},
    )


def compatibility_extractor_profile(value: str) -> str:
    """Project a legacy profile into the strict binding token domain."""

    if not isinstance(value, str) or not value:
        raise MultiSourceIdentityError("legacy extractor profile is invalid")
    try:
        strict_profile = token(value, "extractor profile")
    except MultiSourceIdentityError:
        return "legacy-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    if is_reserved_compatibility_extractor_profile(strict_profile):
        return "legacy-strict-v1-" + hashlib.sha256(
            strict_profile.encode("ascii")
        ).hexdigest()
    return strict_profile


def is_reserved_compatibility_extractor_profile(value: str) -> bool:
    """Return whether a token occupies the reserved compatibility domain."""

    return _COMPATIBILITY_EXTRACTOR_PROFILE_PATTERN.fullmatch(value) is not None


@dataclass(frozen=True)
class GraphCandidate:
    candidate_id: str
    graph_id: str
    snapshots: tuple[SourceSnapshot, ...]
    configuration_identity: str
    extractor_capability_identity: str
    resolver_identity: str
    canonicalizer_identity: str
    semantic_contract_identity: str
    quality_rule_identity: str

    def __post_init__(self) -> None:
        prefixed_digest(self.candidate_id, "cand1:", "candidate identity")
        graph = _graph_id(self.graph_id)
        prefixed_digest(self.configuration_identity, "msc1:", "configuration identity")
        for value, prefix, label in (
            (self.extractor_capability_identity, "cap1:", "extractor capability identity"),
            (self.resolver_identity, "resolver1:", "resolver identity"),
            (self.canonicalizer_identity, "canon1:", "canonicalizer identity"),
            (self.semantic_contract_identity, "semantic1:", "semantic contract identity"),
            (self.quality_rule_identity, "quality1:", "quality rule identity"),
        ):
            prefixed_token(value, prefix, label)
        if tuple(sorted(self.snapshots, key=lambda item: item.binding.binding_id)) != self.snapshots:
            raise MultiSourceIdentityError("candidate snapshot ordering is invalid")
        binding_ids = [item.binding.binding_id for item in self.snapshots]
        if not self.snapshots or len(binding_ids) != len(set(binding_ids)):
            raise MultiSourceIdentityError("duplicate candidate binding")
        if any(item.binding.graph_id != graph for item in self.snapshots):
            raise MultiSourceIdentityError("candidate graph binding is invalid")
        if self.configuration_identity != multi_source_configuration_id(
            graph, tuple(item.binding for item in self.snapshots)
        ):
            raise MultiSourceIdentityError("candidate configuration identity is invalid")
        payload = self._identity_payload()
        if self.candidate_id != "cand1:" + digest(
            "repomap-graph-candidate-v1", payload
        ):
            raise MultiSourceIdentityError("candidate identity is invalid")

    @property
    def snapshot_vector(self) -> tuple[tuple[str, int, str], ...]:
        return tuple(
            (item.binding.binding_id, item.binding.revision, item.snapshot_id)
            for item in self.snapshots
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "canonicalizer_identity": self.canonicalizer_identity,
            "configuration_identity": self.configuration_identity,
            "extractor_capability_identity": self.extractor_capability_identity,
            "graph_id": self.graph_id,
            "quality_rule_identity": self.quality_rule_identity,
            "resolver_identity": self.resolver_identity,
            "semantic_contract_identity": self.semantic_contract_identity,
            "snapshot_vector": [list(item) for item in self.snapshot_vector],
        }

    @classmethod
    def create(
        cls,
        graph_id: str,
        snapshots: Sequence[SourceSnapshot],
        *,
        configuration_identity: str,
        extractor_capability_identity: str,
        resolver_identity: str,
        canonicalizer_identity: str,
        semantic_contract_identity: str,
        quality_rule_identity: str,
    ) -> "GraphCandidate":
        graph = _graph_id(graph_id)
        ordered = tuple(sorted(snapshots, key=lambda item: item.binding.binding_id))
        binding_ids = [item.binding.binding_id for item in ordered]
        if not ordered or len(binding_ids) != len(set(binding_ids)):
            raise MultiSourceIdentityError("duplicate candidate binding")
        if any(item.binding.graph_id != graph for item in ordered):
            raise MultiSourceIdentityError("candidate graph binding is invalid")
        snapshot_vector = [
            [item.binding.binding_id, item.binding.revision, item.snapshot_id]
            for item in ordered
        ]
        payload = {
            "canonicalizer_identity": canonicalizer_identity,
            "configuration_identity": configuration_identity,
            "extractor_capability_identity": extractor_capability_identity,
            "graph_id": graph,
            "quality_rule_identity": quality_rule_identity,
            "resolver_identity": resolver_identity,
            "semantic_contract_identity": semantic_contract_identity,
            "snapshot_vector": snapshot_vector,
        }
        return cls(
            "cand1:" + digest("repomap-graph-candidate-v1", payload),
            graph, ordered, configuration_identity, extractor_capability_identity,
            resolver_identity, canonicalizer_identity, semantic_contract_identity,
            quality_rule_identity,
        )


__all__ = [
    "GraphCandidate",
    "GraphSourceBinding",
    "MultiSourceIdentityError",
    "SnapshotManifestEntry",
    "SourceDefinition",
    "SourceKind",
    "SourceSnapshot",
    "compatibility_extractor_profile",
    "compatibility_source_definition_id",
    "compatibility_source_selection_policy_id",
    "graph_source_binding_id",
    "is_reserved_compatibility_extractor_profile",
    "multi_source_configuration_id",
    "source_binding_input_name",
    "source_binding_role",
    "source_definition_id",
    "source_selection_policy_id",
]
