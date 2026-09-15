"""Versioned records and snapshot structures for multi-source graph configurations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
import re

from repomap_kg.graph._multi_source_identity import (
    HEX_PATTERN,
    MultiSourceIdentityError,
    TOKEN_PATTERN,
    bounded_ascii,
    digest,
    prefixed_digest,
    prefixed_token,
    token,
)


_GIT_OBJECT_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_MAX_LOGICAL_ROOT_BYTES = 256
_MAX_RELATIVE_PATH_BYTES = 1024
_ROLE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_INPUT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class SourceKind(StrEnum):
    FOLDER = "folder"
    GIT_WORKING_TREE = "git-working-tree"
    ARCHIVE = "archive"
    AUTHORIZED_REMOTE = "authorized-remote"


def source_definition_id(identifier: str) -> str:
    return "src1:" + token(identifier, "source definition identifier")


def _graph_id(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise MultiSourceIdentityError("graph identity is invalid")
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        raise MultiSourceIdentityError("graph identity is invalid") from None
    if TOKEN_PATTERN.fullmatch(value) is None:
        raise MultiSourceIdentityError("graph identity is invalid")
    return value


def graph_source_binding_id(graph_id: str, alias: str) -> str:
    graph = _graph_id(graph_id)
    role = token(alias, "binding alias")
    return "bind1:" + digest(
        "repomap-graph-source-binding-v1", {"alias": role, "graph_id": graph}
    )


def _logical_root(value: str) -> str:
    text = bounded_ascii(value, "logical root", _MAX_LOGICAL_ROOT_BYTES)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != text:
        raise MultiSourceIdentityError("logical root is invalid")
    return text


def source_binding_role(value: str) -> str:
    """Validate one extensible, public-safe source role token."""

    if not isinstance(value, str) or _ROLE_PATTERN.fullmatch(value) is None:
        raise MultiSourceIdentityError("binding role is invalid")
    return value


def source_binding_input_name(value: str) -> str:
    """Validate one bounded Nix-compatible input-name token."""

    if not isinstance(value, str) or _INPUT_NAME_PATTERN.fullmatch(value) is None:
        raise MultiSourceIdentityError("binding input name is invalid")
    return value


@dataclass(frozen=True)
class SourceDefinition:
    source_definition_id: str
    kind: SourceKind

    def __post_init__(self) -> None:
        prefixed_token(self.source_definition_id, "src1:", "source definition identity")
        if not isinstance(self.kind, SourceKind):
            raise MultiSourceIdentityError("source kind is invalid")

    @classmethod
    def create(cls, identifier: str, kind: SourceKind) -> "SourceDefinition":
        return cls(source_definition_id(identifier), kind)


@dataclass(frozen=True)
class GraphSourceBinding:
    binding_id: str
    graph_id: str
    alias: str
    source_definition: SourceDefinition
    revision: int
    logical_root: str
    privacy_policy: str
    evidence_retention_policy: str
    extractor_profile: str
    selection_policy_id: str
    resolution_policy: str
    role: str = "source"
    input_name: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        prefixed_digest(self.binding_id, "bind1:", "graph source binding identity")
        graph = _graph_id(self.graph_id)
        alias = token(self.alias, "binding alias")
        if self.binding_id != graph_source_binding_id(graph, alias):
            raise MultiSourceIdentityError("graph source binding identity is invalid")
        if not isinstance(self.source_definition, SourceDefinition):
            raise MultiSourceIdentityError("source definition is invalid")
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 1
        ):
            raise MultiSourceIdentityError("binding revision is invalid")
        _logical_root(self.logical_root)
        if self.privacy_policy not in {
            "public-dev", "private-ops", "private-memory", "private-config",
            "sensitive-local", "inherit",
        }:
            raise MultiSourceIdentityError("binding privacy policy is invalid")
        if self.evidence_retention_policy not in {
            "inherit", "metadata-only", "full-authorized", "ephemeral",
        }:
            raise MultiSourceIdentityError("evidence retention policy is invalid")
        token(self.extractor_profile, "extractor profile")
        prefixed_digest(self.selection_policy_id, "select1:", "selection policy identity")
        if self.resolution_policy not in {"isolated", "allow-declared", "inherit"}:
            raise MultiSourceIdentityError("resolution policy is invalid")
        source_binding_role(self.role)
        if self.input_name is not None:
            source_binding_input_name(self.input_name)
        if not isinstance(self.enabled, bool):
            raise MultiSourceIdentityError("binding enabled state is invalid")

    @classmethod
    def create(
        cls,
        *,
        graph_id: str,
        alias: str,
        source_definition: SourceDefinition,
        revision: int,
        logical_root: str,
        privacy_policy: str,
        evidence_retention_policy: str,
        extractor_profile: str,
        selection_policy_id: str,
        resolution_policy: str,
        role: str = "source",
        input_name: str | None = None,
        enabled: bool = True,
    ) -> "GraphSourceBinding":
        return cls(
            graph_source_binding_id(graph_id, alias),
            graph_id,
            alias,
            source_definition,
            revision,
            logical_root,
            privacy_policy,
            evidence_retention_policy,
            extractor_profile,
            selection_policy_id,
            resolution_policy,
            role,
            input_name,
            enabled,
        )


def multi_source_configuration_id(
    graph_id: str, bindings: Sequence[GraphSourceBinding]
) -> str:
    graph = _graph_id(graph_id)
    ordered = sorted(bindings, key=lambda item: item.binding_id)
    if not ordered or len({item.binding_id for item in ordered}) != len(ordered):
        raise MultiSourceIdentityError("configuration binding inventory is invalid")
    payload = {
        "graph_id": graph,
        "bindings": [
            {
                "alias": item.alias,
                "binding_id": item.binding_id,
                "evidence_retention_policy": item.evidence_retention_policy,
                "enabled": item.enabled,
                "extractor_profile": item.extractor_profile,
                "logical_root": item.logical_root,
                "privacy_policy": item.privacy_policy,
                "resolution_policy": item.resolution_policy,
                "role": item.role,
                "input_name": item.input_name,
                "revision": item.revision,
                "selection_policy_id": item.selection_policy_id,
                "source_definition_id": item.source_definition.source_definition_id,
                "source_kind": item.source_definition.kind.value,
            }
            for item in ordered
        ],
    }
    return "msc1:" + digest("repomap-multi-source-configuration-v1", payload)


def _manifest_path(value: str) -> str:
    text = bounded_ascii(value, "manifest path", _MAX_RELATIVE_PATH_BYTES)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != text or text == ".":
        raise MultiSourceIdentityError("manifest path is invalid")
    return text


@dataclass(frozen=True, order=True)
class SnapshotManifestEntry:
    relative_path: str
    content_sha256: str
    size_bytes: int
    executable: bool = False

    def __post_init__(self) -> None:
        _manifest_path(self.relative_path)
        if HEX_PATTERN.fullmatch(self.content_sha256) is None:
            raise MultiSourceIdentityError("manifest content digest is invalid")
        if (
            not isinstance(self.size_bytes, int)
            or isinstance(self.size_bytes, bool)
            or not 0 <= self.size_bytes < 2**63
        ):
            raise MultiSourceIdentityError("manifest size is invalid")
        if not isinstance(self.executable, bool):
            raise MultiSourceIdentityError("manifest mode is invalid")


def _manifest_identity(entries: Sequence[SnapshotManifestEntry]) -> str:
    payload = {
        "entries": [
            [item.relative_path, item.content_sha256, item.size_bytes, item.executable]
            for item in entries
        ]
    }
    return "manifest1:" + digest("repomap-selected-content-manifest-v1", payload)


def _snapshot_identity(
    binding: GraphSourceBinding,
    manifest_digest: str,
    git_commit: str | None,
    git_tree: str | None,
    ignore_policy_id: str,
    metadata_identity: str,
) -> str:
    payload = {
        "binding_id": binding.binding_id,
        "binding_revision": binding.revision,
        "git_commit": git_commit,
        "git_tree": git_tree,
        "ignore_policy_id": ignore_policy_id,
        "manifest_digest": manifest_digest,
        "metadata_identity": metadata_identity,
        "selection_policy_id": binding.selection_policy_id,
        "source_definition_id": binding.source_definition.source_definition_id,
    }
    return "snap1:" + digest("repomap-source-snapshot-v1", payload)


@dataclass(frozen=True)
class SourceSnapshot:
    snapshot_id: str
    binding: GraphSourceBinding
    manifest_entries: tuple[SnapshotManifestEntry, ...]
    manifest_digest: str
    git_commit: str | None
    git_tree: str | None
    ignore_policy_id: str
    metadata_identity: str

    def __post_init__(self) -> None:
        prefixed_digest(self.snapshot_id, "snap1:", "snapshot identity")
        if not isinstance(self.binding, GraphSourceBinding):
            raise MultiSourceIdentityError("snapshot binding is invalid")
        prefixed_digest(self.manifest_digest, "manifest1:", "manifest identity")
        prefixed_token(self.ignore_policy_id, "ignore1:", "ignore policy identity")
        prefixed_token(self.metadata_identity, "meta1:", "source metadata identity")
        for value in (self.git_commit, self.git_tree):
            if value is not None and _GIT_OBJECT_PATTERN.fullmatch(value) is None:
                raise MultiSourceIdentityError("Git object identity is invalid")
        if tuple(sorted(self.manifest_entries)) != self.manifest_entries:
            raise MultiSourceIdentityError("manifest ordering is invalid")
        if self.manifest_digest != _manifest_identity(self.manifest_entries):
            raise MultiSourceIdentityError("manifest identity is invalid")
        if self.snapshot_id != _snapshot_identity(
            self.binding, self.manifest_digest, self.git_commit, self.git_tree,
            self.ignore_policy_id, self.metadata_identity,
        ):
            raise MultiSourceIdentityError("snapshot identity is invalid")

    @classmethod
    def create(
        cls,
        binding: GraphSourceBinding,
        *,
        manifest_entries: Sequence[SnapshotManifestEntry],
        git_commit: str | None,
        git_tree: str | None,
        ignore_policy_id: str,
        metadata_identity: str,
    ) -> "SourceSnapshot":
        entries = tuple(sorted(manifest_entries))
        paths = [item.relative_path for item in entries]
        if len(paths) != len(set(paths)):
            raise MultiSourceIdentityError("duplicate manifest path")
        if not entries and git_tree is None:
            raise MultiSourceIdentityError("snapshot content identity is missing")
        manifest_digest = _manifest_identity(entries)
        return cls(
            _snapshot_identity(
                binding, manifest_digest, git_commit, git_tree,
                ignore_policy_id, metadata_identity,
            ),
            binding, entries, manifest_digest, git_commit, git_tree,
            ignore_policy_id, metadata_identity,
        )


__all__ = [
    "GraphSourceBinding",
    "SnapshotManifestEntry",
    "SourceDefinition",
    "SourceKind",
    "SourceSnapshot",
    "_graph_id",
    "graph_source_binding_id",
    "multi_source_configuration_id",
    "source_binding_input_name",
    "source_binding_role",
    "source_definition_id",
]
