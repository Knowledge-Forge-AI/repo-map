"""Path-free multi-source semantic identities, moved without algorithm changes."""
from __future__ import annotations
from collections.abc import Sequence
import hashlib
import json
from common_lore_index.graph.multi_source import SourceSnapshot, multi_source_configuration_id
from common_lore_index.graph.multi_source_capture import MultiSourceCaptureError
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig

_MULTI_SOURCE_EXTRACTOR_IDENTITY = "cap1:python-static-v1"

_MULTI_SOURCE_CANONICALIZER_IDENTITY = "canon1:graph-key-v1-binding-path"

_MULTI_SOURCE_SEMANTIC_IDENTITY = "semantic1:multi-source-config-binary64-v1"

_MULTI_SOURCE_QUALITY_IDENTITY = "quality1:default"

_MULTI_SOURCE_RESOLVER_VERSION = "nix-static-v2"

def _resolver_identity(bindings: Sequence[OpsGraphSourceBindingConfig]) -> str:
    payload = [
        [
            item.binding_id,
            item.role,
            item.input_name,
            item.resolution_policy,
            item.selection_policy_id,
        ]
        for item in sorted(bindings, key=lambda binding: binding.binding_id)
    ]
    encoded = json.dumps(
        {"resolver_version": _MULTI_SOURCE_RESOLVER_VERSION, "bindings": payload},
        separators=(",", ":"),
        ensure_ascii=True,
        sort_keys=True,
    ).encode()
    return "resolver1:" + _MULTI_SOURCE_RESOLVER_VERSION + "-" + hashlib.sha256(
        encoded
    ).hexdigest()[:24]

def _multi_source_source_generation(
    snapshots: Sequence[SourceSnapshot],
) -> str:
    ordered = tuple(sorted(snapshots, key=lambda item: item.binding.binding_id))
    if not ordered:
        raise MultiSourceCaptureError(
            "source binding inventory is unsupported", category="source_invalid"
        )
    graph_ids = {item.binding.graph_id for item in ordered}
    if len(graph_ids) != 1:
        raise MultiSourceCaptureError(
            "source binding inventory is invalid", category="source_invalid"
        )
    vector = []
    for snapshot in ordered:
        vector.append({
            "binding_id": snapshot.binding.binding_id,
            "binding_revision": snapshot.binding.revision,
            "snapshot_id": snapshot.snapshot_id,
        })
    payload = {
        "algorithm": "multi-source-snapshot-vector-v1",
        "graph_id": next(iter(graph_ids)),
        "snapshot_vector": vector,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sg1:" + hashlib.sha256(encoded).hexdigest()

def multi_source_config_generation(graph: OpsGraphConfig) -> str:
    """Bind semantic configuration without reading physical source locations."""

    configured = tuple(
        sorted(graph.effective_source_bindings, key=lambda item: item.binding_id)
    )
    bindings = tuple(item.domain_binding(graph.id) for item in configured)
    configuration_identity = multi_source_configuration_id(graph.id, bindings)
    resolver_identity = _resolver_identity(configured)
    payload = {
        "algorithm": "multi-source-semantic-configuration-v1",
        "graph_id": graph.id,
        "configuration_identity": configuration_identity,
        "extractor_capability_identity": _MULTI_SOURCE_EXTRACTOR_IDENTITY,
        "resolver_identity": resolver_identity,
        "canonicalizer_identity": _MULTI_SOURCE_CANONICALIZER_IDENTITY,
        "semantic_contract_identity": _MULTI_SOURCE_SEMANTIC_IDENTITY,
        "quality_rule_identity": _MULTI_SOURCE_QUALITY_IDENTITY,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "cg1:" + hashlib.sha256(encoded).hexdigest()

def multi_source_semantic_identities(
    graph: OpsGraphConfig,
) -> tuple[str, str, str, str, str]:
    """Return the path-free semantic identities bound by a portable manifest."""

    configured = tuple(
        sorted(graph.effective_source_bindings, key=lambda item: item.binding_id)
    )
    return (
        _MULTI_SOURCE_EXTRACTOR_IDENTITY,
        _resolver_identity(configured),
        _MULTI_SOURCE_CANONICALIZER_IDENTITY,
        _MULTI_SOURCE_SEMANTIC_IDENTITY,
        _MULTI_SOURCE_QUALITY_IDENTITY,
    )
