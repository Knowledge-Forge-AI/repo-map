"""Portable, locator-independent sealed snapshot manifest contract."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import ClassVar, Sequence

from repomap_kg.artifacts._canonical import (
    canonical_json,
    decode_canonical_json,
    prefixed_digest,
)
from repomap_kg.artifacts._manifest_records import (
    DEFAULT_ARTIFACT_LIMITS,
    _GRAPH,
    ArtifactLimits,
    ManifestArtifact,
    ManifestBinding,
    _binding_from_mapping,
    _effective_privacy,
    _entry_from_mapping,
    _identity,
    _list,
    _str,
    _validate_inventory,
)
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


@dataclass(frozen=True)
class PortableSnapshotManifest:
    """Exact semantic inventory; artifact locators remain execution material."""

    SCHEMA_VERSION: ClassVar[int] = 1
    CANONICALIZATION_VERSION: ClassVar[str] = "repomap-snapshot-manifest-json-v1"
    graph_id: str
    bindings: tuple[ManifestBinding, ...]
    entries: tuple[ManifestArtifact, ...]
    source_generation: str
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str
    extractor_capability_identity: str
    resolver_identity: str
    canonicalizer_identity: str
    semantic_contract_identity: str
    quality_rule_identity: str
    effective_privacy: PrivacyClassification
    total_files: int
    total_bytes: int
    manifest_id: str

    @property
    def snapshot_vector(self) -> tuple[tuple[str, int, str], ...]:
        return tuple((item.binding_id, item.revision, item.snapshot_id) for item in self.bindings)

    def canonical_mapping(self) -> dict[str, object]:
        return {
            "bindings": [item.mapping() for item in self.bindings],
            "canonicalization_version": self.CANONICALIZATION_VERSION,
            "canonicalizer_generation": self.canonicalizer_generation,
            "canonicalizer_identity": self.canonicalizer_identity,
            "config_generation": self.config_generation,
            "effective_privacy": self.effective_privacy.value,
            "entries": [item.semantic_mapping() for item in self.entries],
            "extractor_capability_identity": self.extractor_capability_identity,
            "extractor_generation": self.extractor_generation,
            "graph_id": self.graph_id,
            "quality_rule_identity": self.quality_rule_identity,
            "resolver_identity": self.resolver_identity,
            "schema_version": self.SCHEMA_VERSION,
            "semantic_contract_identity": self.semantic_contract_identity,
            "source_generation": self.source_generation,
            "total_bytes": self.total_bytes,
            "total_files": self.total_files,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.canonical_mapping())

    @classmethod
    def create(
        cls,
        *,
        graph_id: str,
        bindings: Sequence[ManifestBinding],
        entries: Sequence[ManifestArtifact],
        source_generation: str,
        config_generation: str,
        extractor_generation: str,
        canonicalizer_generation: str,
        extractor_capability_identity: str,
        resolver_identity: str,
        canonicalizer_identity: str,
        semantic_contract_identity: str,
        quality_rule_identity: str,
        limits: ArtifactLimits = DEFAULT_ARTIFACT_LIMITS,
    ) -> "PortableSnapshotManifest":
        if not _GRAPH.fullmatch(graph_id):
            raise ValueError("graph identity is invalid")
        ordered_bindings = tuple(sorted(bindings))
        ordered_entries = tuple(sorted(entries))
        _validate_inventory(ordered_bindings, ordered_entries, limits)
        for value, prefix, label in (
            (source_generation, "sg1:", "source generation"),
            (config_generation, "cg1:", "configuration generation"),
            (extractor_generation, "eg1:", "extractor generation"),
            (canonicalizer_generation, "kg1:", "canonicalizer generation"),
            (extractor_capability_identity, "cap1:", "extractor capability"),
            (resolver_identity, "resolver1:", "resolver identity"),
            (canonicalizer_identity, "canon1:", "canonicalizer identity"),
            (semantic_contract_identity, "semantic1:", "semantic identity"),
            (quality_rule_identity, "quality1:", "quality identity"),
        ):
            _identity(value, prefix, label)
        total_bytes = sum(item.reference.size_bytes for item in ordered_entries)
        privacy = _effective_privacy(ordered_bindings, ordered_entries)
        manifest_instance = cls(
            graph_id,
            ordered_bindings,
            ordered_entries,
            source_generation,
            config_generation,
            extractor_generation,
            canonicalizer_generation,
            extractor_capability_identity,
            resolver_identity,
            canonicalizer_identity,
            semantic_contract_identity,
            quality_rule_identity,
            privacy,
            len(ordered_entries),
            total_bytes,
            "",
        )
        encoded = manifest_instance.canonical_bytes()
        if len(encoded) > limits.max_manifest_bytes:
            raise ValueError("manifest byte bounds exceeded")
        return replace(
            manifest_instance,
            manifest_id=prefixed_digest(
                "snapmanifest1:", b"repomap-snapshot-manifest-v1", encoded
            ),
        )

    @classmethod
    def create_from(
        cls,
        source: "PortableSnapshotManifest",
        *,
        entries: Sequence[ManifestArtifact] | None = None,
        limits: ArtifactLimits = DEFAULT_ARTIFACT_LIMITS,
        **changes: object,
    ) -> "PortableSnapshotManifest":
        values = {
            name: getattr(source, name)
            for name in (
                "graph_id", "bindings", "source_generation", "config_generation",
                "extractor_generation", "canonicalizer_generation",
                "extractor_capability_identity", "resolver_identity",
                "canonicalizer_identity", "semantic_contract_identity",
                "quality_rule_identity",
            )
        }
        values.update(changes)
        return cls.create(
            **values,
            entries=source.entries if entries is None else entries,
            limits=limits,
        )

    @classmethod
    def from_bytes(cls, data: bytes, *, limits: ArtifactLimits = DEFAULT_ARTIFACT_LIMITS) -> "PortableSnapshotManifest":
        if len(data) > limits.max_manifest_bytes:
            raise ValueError("manifest byte bounds exceeded")
        payload = decode_canonical_json(data)
        expected = {
            "bindings", "canonicalization_version", "canonicalizer_generation",
            "canonicalizer_identity", "config_generation", "effective_privacy",
            "entries", "extractor_capability_identity", "extractor_generation",
            "graph_id", "quality_rule_identity", "resolver_identity",
            "schema_version", "semantic_contract_identity", "source_generation",
            "total_bytes", "total_files",
        }
        if set(payload) != expected or payload["schema_version"] != 1 or payload["canonicalization_version"] != cls.CANONICALIZATION_VERSION:
            raise ValueError("unsupported snapshot manifest schema")
        bindings = tuple(_binding_from_mapping(item) for item in _list(payload["bindings"], "bindings"))
        entries = tuple(_entry_from_mapping(item) for item in _list(payload["entries"], "entries"))
        value = cls.create(
            graph_id=_str(payload["graph_id"]), bindings=bindings, entries=entries,
            source_generation=_str(payload["source_generation"]),
            config_generation=_str(payload["config_generation"]),
            extractor_generation=_str(payload["extractor_generation"]),
            canonicalizer_generation=_str(payload["canonicalizer_generation"]),
            extractor_capability_identity=_str(payload["extractor_capability_identity"]),
            resolver_identity=_str(payload["resolver_identity"]),
            canonicalizer_identity=_str(payload["canonicalizer_identity"]),
            semantic_contract_identity=_str(payload["semantic_contract_identity"]),
            quality_rule_identity=_str(payload["quality_rule_identity"]), limits=limits,
        )
        if payload["total_files"] != value.total_files or payload["total_bytes"] != value.total_bytes or payload["effective_privacy"] != value.effective_privacy.value:
            raise ValueError("snapshot manifest summary is inconsistent")
        return value


__all__ = [
    "ArtifactLimits",
    "DEFAULT_ARTIFACT_LIMITS",
    "ManifestArtifact",
    "ManifestBinding",
    "PortableSnapshotManifest",
]
