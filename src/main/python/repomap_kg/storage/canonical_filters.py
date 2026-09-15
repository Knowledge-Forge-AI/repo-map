"""Canonical storage filter validation shared by CLI and MCP adapters."""

from __future__ import annotations

from repomap_kg.graph.edge_kinds import CANONICAL_EDGE_KINDS
from repomap_kg.graph.keys import GRAPH_KEY_VERSION, validate_key
from repomap_kg.storage.errors import StorageSchemaError


def canonical_node_kind_from_args(args) -> str | None:
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError("unsupported graph key version")
    if args.canonical_key is not None:
        validation = validate_key(args.canonical_key)
        if not validation.valid:
            detail = f": {validation.error}" if validation.error else ""
            raise StorageSchemaError(f"invalid canonical key{detail}")
    kind = args.kind
    if args.path_prefix is not None:
        if kind is not None and kind != "file":
            raise StorageSchemaError(
                "path-prefix only applies to file canonical nodes"
            )
        kind = "file"
    return kind


def canonical_edge_filters_from_args(args) -> None:
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError("unsupported graph key version")
    if args.kind is not None and args.kind not in CANONICAL_EDGE_KINDS:
        values = ", ".join(sorted(CANONICAL_EDGE_KINDS))
        raise StorageSchemaError(
            f"unsupported canonical edge kind: {args.kind}; expected one of {values}"
        )
    for option, value in (
        ("source", args.source_key),
        ("target", args.target_key),
    ):
        if value is None:
            continue
        validation = validate_key(value)
        if not validation.valid:
            detail = f": {validation.error}" if validation.error else ""
            raise StorageSchemaError(f"invalid {option} canonical key{detail}")


def canonical_neighborhood_filters_from_args(args) -> None:
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError("unsupported graph key version")
    if args.depth != 1:
        raise StorageSchemaError("storage neighborhood only supports depth 1")
    validation = validate_key(args.node)
    if not validation.valid:
        detail = f": {validation.error}" if validation.error else ""
        raise StorageSchemaError(f"invalid node canonical key{detail}")


__all__ = [
    "canonical_edge_filters_from_args",
    "canonical_neighborhood_filters_from_args",
    "canonical_node_kind_from_args",
]
