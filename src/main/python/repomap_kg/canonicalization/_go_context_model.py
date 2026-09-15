"""Records and pure helpers for Go canonical context construction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.graph.go_source_keys import (
    go_source_const_key,
    go_source_function_key,
    go_source_method_key,
    go_source_type_key,
    go_source_var_key,
)
from repomap_kg.graph.keys import GraphKeyError
from repomap_kg.observations.raw import RawObservation


MAX_GO_CANONICAL_DIAGNOSTICS = 64
GO_DECLARATION_KINDS = frozenset(
    {"go.type", "go.type_alias", "go.function", "go.method", "go.const", "go.var"}
)
GO_SUPPORTING_KINDS = frozenset(
    {"go.struct", "go.interface", "go.test", "go.benchmark", "go.fuzz", "go.example", "go.test_main"}
)
GO_UNRESOLVED_RELATIONSHIP_KINDS = frozenset(
    {
        "go.reference",
        "go.selector",
        "go.select",
        "go.call",
        "go.dynamic",
        "go.method_expression",
        "go.construct",
        "go.instantiation",
        "go.embedded_field",
        "go.goroutine",
        "go.defer",
        "go.send",
        "go.receive",
        "go.panic",
        "go.recover",
        "go.return",
    }
)


@dataclass(frozen=True)
class GoModuleIdentity:
    root: str
    module_path: str
    semantic_key: str
    source_key: str
    repository_scope: str


@dataclass(frozen=True)
class GoPackageIdentity:
    directory: str
    import_path: str | None
    package_name: str
    canonical_key: str
    source_module_key: str | None
    semantic_module_key: str | None
    module_path: str | None
    module_root: str | None
    repository_scope: str
    identity_source: str
    external_test_package: bool
    vendor: bool


@dataclass(frozen=True)
class GoNodeClaim:
    canonical_key: str
    kind: str
    display_name: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class GoEdgeClaim:
    source_key: str
    kind: str
    target_key: str
    identity_metadata: Mapping[str, Any]
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class GoCanonicalContext:
    node_claims: Mapping[str, GoNodeClaim]
    node_keys_by_source_id: Mapping[str, tuple[str, ...]]
    edge_claims_by_source_id: Mapping[str, tuple[GoEdgeClaim, ...]]
    diagnostics: tuple[CanonicalizationDiagnostic, ...]
    duplicate_declaration_evidence: int
    identity_collisions: int
    unresolved_relationships: int
    invalid_source_ids: frozenset[str]


@dataclass(frozen=True)
class GoNodeClaimInput:
    kind: str
    display_name: str
    metadata: Mapping[str, Any]
    source_id: str
    primary: bool


def declaration_identity(
    item: RawObservation,
    package: GoPackageIdentity,
) -> tuple[str, str, str]:
    if item.name is None:
        raise GraphKeyError("Go declaration name is required")
    if item.kind in {"go.type", "go.type_alias"}:
        node_kind = "go.source_type" if item.kind == "go.type" else "go.source_type_alias"
        return go_source_type_key(package.canonical_key, item.name), node_kind, item.name
    if item.kind == "go.function":
        return (
            go_source_function_key(package.canonical_key, item.name),
            "go.source_function",
            item.name,
        )
    if item.kind == "go.method":
        receiver = item.metadata.get("receiver_base")
        if not isinstance(receiver, str) or not receiver:
            raise GraphKeyError("Go method receiver base is required")
        return (
            go_source_method_key(package.canonical_key, receiver, item.name),
            "go.source_method",
            f"{receiver}.{item.name}",
        )
    if item.kind == "go.const":
        return go_source_const_key(package.canonical_key, item.name), "go.source_const", item.name
    if item.kind == "go.var":
        return go_source_var_key(package.canonical_key, item.name), "go.source_var", item.name
    raise GraphKeyError("unsupported Go declaration kind")


def location_key(item: RawObservation) -> tuple[Any, ...]:
    return (
        item.path,
        item.name,
        item.metadata.get("start_offset"),
        item.metadata.get("end_offset"),
    )


def parent(path: str) -> str:
    result = str(PurePosixPath(path).parent)
    return result if result else "."


def is_repository_relative_path(path: str) -> bool:
    parsed = PurePosixPath(path)
    windows = PureWindowsPath(path)
    return (
        bool(path)
        and "\x00" not in path
        and "\\" not in path
        and not parsed.is_absolute()
        and not windows.drive
        and ".." not in parsed.parts
        and str(parsed) == path
    )


def is_vendor_path(path: str) -> bool:
    return "vendor" in PurePosixPath(path).parts


def normalize_directory(path: str) -> str:
    normalized = str(PurePosixPath(path))
    return normalized if normalized else "."


def is_directory_ancestor(root: str, directory: str) -> bool:
    root_parts = () if root == "." else PurePosixPath(root).parts
    directory_parts = () if directory == "." else PurePosixPath(directory).parts
    return directory_parts[: len(root_parts)] == root_parts


def relative_directory(directory: str, root: str) -> str:
    directory_parts = () if directory == "." else PurePosixPath(directory).parts
    root_parts = () if root == "." else PurePosixPath(root).parts
    relative = directory_parts[len(root_parts) :]
    return "/".join(relative) if relative else "."
