"""Stored-node similarity MCP tool and payload builder for RepoMap."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

from common_lore_index import __version__
from common_lore_index.server._ops_records import McpOpsError
from common_lore_index.server._ops_sanitization import safety_markers, sanitize_jsonable
from common_lore_index.server.mcp_core import (
    RepoMapMcpError,
    public_storage_error_message,
)
from common_lore_index.server.ops import configured_graph, graph_payload
from common_lore_index.storage import StorageSchemaError
from common_lore_index.storage.semantic_seed import SimilarNodesQuery
from common_lore_index.storage.semantic_candidates import (
    EmbeddingProfilesQuery,
    profiles_unavailable,
    unavailable,
)


def similar_nodes_payload(
    graph_id: str,
    canonical_key: str,
    rebuild_id: str,
    profile_identity: str,
    dimensions: int,
    *,
    selected: bool = False,
    limit: int = 20,
    evidence_limit: int = 5,
    source_binding_id: str | None = None,
    kind: str | None = None,
    path: str | None = None,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    target = configured_graph(graph_id, config_path=config_path)
    query = SimilarNodesQuery(
        canonical_key=canonical_key,
        rebuild_id=rebuild_id,
        profile_identity=profile_identity,
        dimensions=dimensions,
        selected=selected,
        limit=limit,
        evidence_limit=evidence_limit,
        source_binding_id=source_binding_id,
        kind=kind,
        path=path,
    ).validate()
    selection = target.selection
    store = target.stores.investigation_store()
    result_data = store.similar_nodes(selection.graph_id, query).to_jsonable()
    if _profiles_need_redaction(result_data, selection.path_markers):
        result_data = unavailable("privacy_refused").to_jsonable()
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": graph_payload(
            selection.graph,
            database=target.stores.storage_label(selection),
        ),
        **result_data,
        "safety": safety_markers(),
    }


def repomap_similar_nodes(
    *,
    graph_id: str,
    canonical_key: str,
    rebuild_id: str,
    profile_identity: str,
    dimensions: int,
    selected: bool = False,
    limit: int = 20,
    evidence_limit: int = 5,
    source_binding_id: str | None = None,
    kind: str | None = None,
    path: str | None = None,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    try:
        return similar_nodes_payload(
            graph_id,
            canonical_key,
            rebuild_id,
            profile_identity,
            dimensions,
            selected=selected,
            limit=limit,
            evidence_limit=evidence_limit,
            source_binding_id=source_binding_id,
            kind=kind,
            path=path,
            config_path=config_path,
        )
    except McpOpsError as error:
        raise RepoMapMcpError(str(error)) from error
    except StorageSchemaError as error:
        raise RepoMapMcpError(public_storage_error_message(error)) from error
    except ValueError as error:
        raise RepoMapMcpError(str(error)) from error


__all__ = (
    "SimilarNodesQuery",
    "embedding_profiles_payload",
    "repomap_embedding_profiles",
    "repomap_similar_nodes",
    "similar_nodes_payload",
)


def embedding_profiles_payload(
    graph_id: str, *, selected: bool = False, limit: int = 20,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    query = EmbeddingProfilesQuery(selected=selected, limit=limit).validate()
    target = configured_graph(graph_id, config_path=config_path)
    selection = target.selection
    result = (target.stores.investigation_store().embedding_profiles(selection.graph_id, query)
              if query.selected else profiles_unavailable("disabled"))
    result_data = result.to_jsonable()
    if _profiles_need_redaction(result_data, selection.path_markers):
        # Redacting a tuple in place would invalidate its profile digest or IDs.
        result_data = profiles_unavailable("privacy_refused").to_jsonable()
    return {
        "server": "repomap-kg", "version": __version__, "read_only": True,
        "graph": graph_payload(selection.graph, database=target.stores.storage_label(selection)),
        **result_data, "safety": safety_markers(),
    }


_OPAQUE_DIGEST_PATHS: dict[tuple[str | None, ...], re.Pattern[str]] = {
    ("profiles", None, "profile_identity"): re.compile(r"sha256:[0-9a-f]{64}\Z"),
    ("profiles", None, "source_scope", None, "source_binding_id"): re.compile(r"bind1:[0-9a-f]{64}\Z"),
    ("profiles", None, "source_scope", None, "snapshot_id"): re.compile(r"snap1:[0-9a-f]{64}\Z"),
    ("provenance", "profile_identity"): re.compile(r"sha256:[0-9a-f]{64}\Z"),
    ("provenance", "receipt_identity"): re.compile(r"sha256:[0-9a-f]{64}\Z"),
    ("provenance", "seed", "source_binding_id"): re.compile(r"bind1:[0-9a-f]{64}\Z"),
    ("provenance", "seed", "snapshot_id"): re.compile(r"snap1:[0-9a-f]{64}\Z"),
    ("provenance", "generations", "source_generation"): re.compile(r"sg1:[0-9a-f]{64}\Z"),
    ("provenance", "generations", "config_generation"): re.compile(r"cg1:[0-9a-f]{64}\Z"),
    ("provenance", "generations", "extractor_generation"): re.compile(r"eg1:[0-9a-f]{64}\Z"),
    ("provenance", "generations", "canonicalizer_generation"): re.compile(r"kg1:[0-9a-f]{64}\Z"),
    ("provenance", "publication", "snapshot_manifest_id"): re.compile(r"snapmanifest1:[0-9a-f]{64}\Z"),
    ("provenance", "publication", "extraction_receipt_id"): re.compile(r"receipt1:[0-9a-f]{64}\Z"),
    ("provenance", "publication", "publication_bundle_id"): re.compile(r"bundle1:[0-9a-f]{64}\Z"),
    ("provenance", "publication", "graph_candidate_id"): re.compile(r"cand1:[0-9a-f]{64}\Z"),
}

_FIXED_PROTOCOL_PATHS: dict[tuple[str | None, ...], tuple[str, ...]] = {
    ("profiles", None, "representation_version"): ("canonical-node-v1",),
    ("profiles", None, "normalization"): ("l2-unit",),
    ("profiles", None, "metric"): ("cosine",),
    ("profiles", None, "privacy_class"): ("public",),
    ("provenance", "profile", "representation_version"): ("canonical-node-v1",),
    ("provenance", "profile", "normalization"): ("l2-unit",),
    ("provenance", "profile", "metric"): ("cosine",),
    ("provenance", "profile", "privacy_class"): ("public",),
    ("provenance", "privacy_class"): ("public",),
    ("provenance", "pgvector_version"): ("0.8.7",),
    ("provenance", "search"): ("exact",),
    ("provenance", "input_digest_validation"): ("enrichment_principal_assertion",),
    ("provenance", "snapshot_contract"): (
        "receipt-fenced metadata and source evidence in one SQL statement",
        "receipt-fenced seed and candidates in one SQL statement",
    ),
}


def _sanitized_payload(payload: dict[str, Any], path_markers: tuple[str, ...]) -> dict[str, Any]:
    sanitized = sanitize_jsonable(payload, private_markers=path_markers)
    for cand, san_cand in zip(payload.get("candidates") or (), sanitized.get("candidates") or ()):
        if isinstance(cand, dict) and isinstance(san_cand, dict):
            for ev, san_ev in zip(cand.get("evidence") or (), san_cand.get("evidence") or ()):
                if isinstance(ev, dict) and isinstance(san_ev, dict) and "evidence_key" in ev:
                    san_ev["evidence_key"] = sanitize_jsonable({"v": ev["evidence_key"]}, private_markers=path_markers)["v"]
    return sanitized


def _profiles_need_redaction(payload: dict[str, Any], markers: tuple[str, ...]) -> bool:
    username = Path.home().name
    path_markers = tuple(marker for marker in markers if marker != username)
    if _sanitized_payload(payload, path_markers) != payload:
        return True
    if not username:
        return False
    # Deliberately public validated opaque identities at exact structured paths
    # bypass username token matching if and only if they match their exact prefix
    # and form. Generic model, generator, and nested provenance are always scrutinized.
    pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(username) + r"(?![A-Za-z0-9])")

    def contains_username(value: Any, path: tuple[str | None, ...]) -> bool:
        if isinstance(value, dict):
            return any(contains_username(item, (*path, str(key))) for key, item in value.items())
        if isinstance(value, list):
            return any(contains_username(item, (*path, None)) for item in value)
        if isinstance(value, str):
            if path == ("provenance", "seed", "canonical_key"):
                return False
            digest_pattern = _OPAQUE_DIGEST_PATHS.get(path)
            if digest_pattern is not None and digest_pattern.fullmatch(value) is not None:
                return False
            expected_fixed = _FIXED_PROTOCOL_PATHS.get(path)
            if expected_fixed is not None and value in expected_fixed:
                return False
            return bool(pattern.search(value))
        return False

    return any(contains_username(payload.get(field), (field,)) for field in ("profiles", "provenance"))


def repomap_embedding_profiles(
    *, graph_id: str, selected: bool = False, limit: int = 20,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    try:
        return embedding_profiles_payload(graph_id, selected=selected, limit=limit, config_path=config_path)
    except McpOpsError as error:
        raise RepoMapMcpError(str(error)) from error
    except StorageSchemaError as error:
        raise RepoMapMcpError(public_storage_error_message(error)) from error
    except ValueError as error:
        raise RepoMapMcpError(str(error)) from error


def embedding_profiles_tool_definition() -> dict[str, Any]:
    return {
        "name": "repomap_embedding_profiles",
        "description": "Read current public-safe precomputed profile tuples; explicitly choose one for similar_nodes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_id": {"type": "string"},
                "selected": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
            "required": ["graph_id"],
            "additionalProperties": False,
        },
    }
