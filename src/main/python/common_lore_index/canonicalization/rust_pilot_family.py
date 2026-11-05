"""Witness-only Rust canonicalization; no offline positive path exists."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from common_lore_index.canonicalization.diagnostics import CanonicalizationDiagnostic
from common_lore_index.canonicalization.evidence_helpers import _evidence_from_observation
from common_lore_index.canonicalization.main import canonicalize_observations
from common_lore_index.canonicalization.node_edge_helpers import _node_kind_from_key, _upsert_edge, _upsert_node
from common_lore_index.canonicalization.records import (
    CanonicalEdgeEvidenceLink, CanonicalGraph, CanonicalNodeEvidenceLink,
    CanonicalizationResult, canonical_edge_key,
)
from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot.component_lock import LOCK_SHA256
from common_lore_index.extractors.rust_pilot.controller import RustPilotController
from common_lore_index.extractors.rust_pilot.witness_state import Admission, Unserializable
from common_lore_index.graph.keys import GRAPH_KEY_VERSION, GraphKeyError, file_key
from common_lore_index.graph.rust_keys import rust_item_key, rust_source_file_key
from common_lore_index.observations.raw import RawObservation

RUST_RAW_KINDS = frozenset({"rust.parse", "rust.item", "rust.unsupported"})
_ITEM_NAMESPACES = frozenset(
    {"rust.module", "rust.function", "rust.type", "rust.trait", "rust.impl", "rust.macro"}
)
_KIND_NAMESPACE = {
    "mod": "rust.module", "fn": "rust.function", "struct": "rust.type",
    "enum": "rust.type", "union": "rust.type", "type": "rust.type",
    "trait": "rust.trait", "impl": "rust.impl", "macro": "rust.macro",
}
_CONTAINER_NAMESPACES = frozenset({"rust.module", "rust.trait", "rust.impl"})
_CONSTRUCTION_TOKEN = object()


def _diag(
    severity: str, category: str, message: str, obs: RawObservation | None = None,
    ordinal: int | None = None, field: str | None = None, value: object | None = None,
) -> CanonicalizationDiagnostic:
    return CanonicalizationDiagnostic(
        severity=severity, category=category, message=message,
        raw_observation_ordinal=ordinal, raw_source_id=None if obs is None else obs.source_id,
        path=None if obs is None else obs.path, field=field, value=value,
    )


def _admit(run: RustPilotController) -> tuple[dict[str, tuple[RawObservation, ...]], tuple[CanonicalizationDiagnostic, ...]]:
    admitted: dict[str, tuple[RawObservation, ...]] = {}
    diagnostics: list[CanonicalizationDiagnostic] = []
    for path in run.selected_paths():
        result = run.admit(path)
        if type(result) is not Admission:
            raise ContractError("rust_pilot_admission_type")
        if result.refused_bindings:
            diagnostics.extend(
                _diag("warning", "rust_pilot_binding_refused",
                      "Rust claims refused because a live binding did not hold",
                      field="binding", value=name)
                for name in result.refused_bindings
            )
            continue
        if type(result.observations) is not tuple:
            raise ContractError("rust_pilot_observation_tuple")
        admitted[path] = result.observations
    return admitted, tuple(diagnostics)


class WitnessedCanonicalization(Unserializable):
    """A merged result bound to one open controller and tuple identities."""

    __slots__ = ("_run", "_by_path", "_observations", "_result", "_integrity")

    def __init__(self, run: RustPilotController, by_path: Mapping[str, tuple[RawObservation, ...]],
                 observations: tuple[RawObservation, ...], result: CanonicalizationResult, *,
                 _token: object) -> None:
        if _token is not _CONSTRUCTION_TOKEN:
            raise ContractError("rust_pilot_witness_private_constructor")
        if type(run) is not RustPilotController:
            raise ContractError("rust_pilot_controller_required")
        self._run, self._by_path, self._observations, self._result = run, dict(by_path), observations, result
        self._integrity = self._content_digest()

    def _content_digest(self) -> bytes:
        # Per-instance mutation guard only. A digest never substitutes for
        # the exact open controller and fresh admission checks below.
        digest = hashlib.sha256()
        for observation in self._observations:
            digest.update(observation.to_json_line().encode("utf-8") + b"\n")
        for chunk in json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False).iterencode(
                self._result.to_dict()):
            digest.update(chunk.encode("utf-8"))
        return digest.digest()

    @property
    def observations(self) -> tuple[RawObservation, ...]:
        return self._observations

    @property
    def result(self) -> CanonicalizationResult:
        return self._result

    @property
    def lock_sha256(self) -> str:
        return LOCK_SHA256

    @property
    def helper_closure_sha256(self) -> str:
        value = getattr(self._run, "helper_closure_sha256", None)
        if type(value) is not str:
            raise ContractError("rust_pilot_helper_identity_unavailable")
        return value

    def verify_live(self) -> bool:
        try:
            if (type(self._run) is not RustPilotController or not self._run.verify_live()
                    or self._content_digest() != self._integrity):
                return False
            current, _ = _admit(self._run)
            return (
                set(current) == set(self._by_path)
                and all(current[path] is self._by_path[path] for path in current)
                and self._run.verify_live()
                and self._content_digest() == self._integrity
            )
        except (ContractError, AttributeError, TypeError, ValueError, RecursionError):
            return False


def _edge(edges: dict[str, Any], links: list[CanonicalEdgeEvidenceLink], source: str,
          kind: str, target: str, evidence: str, metadata: Mapping[str, Any],
          confidence: str) -> None:
    identity: dict[str, Any] = {}
    key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION, source_key=source, kind=kind,
        target_key=target, identity_metadata=identity,
    )
    _upsert_edge(
        edges, edge_key=key, source_key=source, kind=kind, target_key=target,
        identity_metadata=identity, metadata=metadata, confidence=confidence,
    )
    links.append(CanonicalEdgeEvidenceLink(edge_key=key, evidence_key=evidence, link_kind="supports"))


def _build(
    legacy: CanonicalizationResult, merged: tuple[RawObservation, ...],
    by_path: Mapping[str, tuple[RawObservation, ...]],
    admission_diagnostics: Sequence[CanonicalizationDiagnostic],
) -> CanonicalizationResult:
    nodes = {x.canonical_key: x for x in legacy.graph.nodes}
    edges = {x.edge_key: x for x in legacy.graph.edges}
    evidence = list(legacy.graph.evidence)
    node_links = list(legacy.graph.node_evidence_links)
    edge_links = list(legacy.graph.edge_evidence_links)
    diagnostics = list(legacy.diagnostics) + list(admission_diagnostics)
    ordinal = {id(item): index for index, item in enumerate(merged)}
    raw = [item for rows in by_path.values() for item in rows]
    evidence_by_id: dict[int, Any] = {}
    for item in raw:
        if item.kind not in RUST_RAW_KINDS:
            diagnostics.append(_diag("error", "rust_pilot_raw_kind", "unknown live Rust raw kind",
                                      item, ordinal[id(item)], "kind"))
            continue
        record = _evidence_from_observation(item, ordinal[id(item)])
        evidence.append(record)
        evidence_by_id[id(item)] = record

    grouped: dict[str, list[RawObservation]] = defaultdict(list)
    for item in raw:
        grouped[item.path].append(item)
    source_keys: dict[str, str] = {}
    item_keys: dict[tuple[str, str], str] = {}
    item_ns: dict[str, str] = {}
    pending: list[tuple[str, RawObservation, str, str]] = []

    for path, items in grouped.items():
        parses = [item for item in items if item.kind == "rust.parse"]
        if len(parses) != 1:
            diagnostics.append(_diag("error", "rust_pilot_parse_cardinality",
                                      "one live rust.parse is required per path",
                                      parses[0] if parses else None,
                                      ordinal.get(id(parses[0])) if parses else None, "rust.parse"))
            continue
        parse = parses[0]
        completeness = parse.metadata.get("completeness")
        if parse.metadata.get("outcome") == "succeeded" and completeness in {"complete", "partial", "truncated"}:
            basis = "complete_tree" if completeness == "complete" else "partial_tree_usable_scope"
        else:
            basis = None
        try:
            source = file_key(path)
            source_rust = rust_source_file_key(path)
        except GraphKeyError:
            diagnostics.append(_diag("error", "rust_pilot_key_invalid",
                                      "Rust source path cannot produce a key", parse, ordinal[id(parse)], "path"))
            continue
        if source not in nodes:
            diagnostics.append(_diag("error", "rust_pilot_legacy_file_missing",
                                      "Rust source claim requires the legacy file node",
                                      parse, ordinal[id(parse)], "path"))
            continue
        parse_evidence = evidence_by_id[id(parse)]
        if basis is not None:
            metadata = dict(parse.metadata)
            metadata["completeness_basis"] = basis
            _upsert_node(nodes, canonical_key=source_rust, kind="rust.source_file",
                         display_name=path, metadata=metadata, confidence=parse.confidence)
            source_keys[path] = source_rust
            node_links.append(CanonicalNodeEvidenceLink(source_rust, parse_evidence.evidence_key, "observed"))
            _edge(edges, edge_links, source, "contains", source_rust, parse_evidence.evidence_key,
                  {"completeness_basis": basis}, parse.confidence)
        for item in (x for x in items if x.kind == "rust.item"):
            if basis is None or (basis != "complete_tree" and item.metadata.get("usable_scope") is not True):
                continue
            metadata = dict(item.metadata)
            namespace, item_kind, pointer = metadata.get("namespace"), metadata.get("item_kind"), metadata.get("pointer")
            if (type(namespace) is not str or namespace not in _ITEM_NAMESPACES
                    or type(item_kind) is not str or _KIND_NAMESPACE.get(item_kind) != namespace
                    or type(pointer) is not str):
                diagnostics.append(_diag("error", "rust_pilot_item_contract",
                                          "Rust item metadata is outside the closed vocabulary",
                                          item, ordinal[id(item)], "metadata"))
                continue
            try:
                key = rust_item_key(namespace, path, pointer)
            except GraphKeyError:
                diagnostics.append(_diag("error", "rust_pilot_key_invalid",
                                          "Rust item pointer cannot produce a key",
                                          item, ordinal[id(item)], "pointer"))
                continue
            if (path, pointer) in item_keys or key in nodes:
                diagnostics.append(_diag("error", "rust_pilot_duplicate_key",
                                          "duplicate Rust syntax pointer refused",
                                          item, ordinal[id(item)], "pointer"))
                continue
            item_keys[(path, pointer)], item_ns[key] = key, namespace
            pending.append((path, item, key, basis))

    for path, item, key, basis in pending:
        parent = item.metadata.get("parent_pointer")
        if parent == "/":
            parent_source = source_keys.get(path)
            edge_kind = "defines"
        else:
            parent_source = item_keys.get((path, parent)) if type(parent) is str else None
            edge_kind = "contains"
        if parent_source is None:
            diagnostics.append(_diag("error", "rust_pilot_parent_missing",
                                      "Rust item parent pointer has no admitted container",
                                      item, ordinal[id(item)], "parent_pointer"))
            continue
        if edge_kind == "contains" and item_ns.get(parent_source) not in _CONTAINER_NAMESPACES:
            diagnostics.append(_diag("error", "rust_pilot_parent_invalid",
                                      "Rust contains parent is not a Rust container",
                                      item, ordinal[id(item)], "parent_pointer"))
            continue
        metadata = dict(item.metadata)
        metadata["completeness_basis"] = basis
        _upsert_node(nodes, canonical_key=key, kind=_node_kind_from_key(key),
                     display_name=item.name or str(metadata.get("pointer", "")).rsplit("/", 1)[-1],
                     metadata=metadata, confidence=item.confidence)
        item_evidence = evidence_by_id[id(item)]
        node_links.append(CanonicalNodeEvidenceLink(key, item_evidence.evidence_key, "observed"))
        _edge(edges, edge_links, parent_source, edge_kind, key, item_evidence.evidence_key,
              {"completeness_basis": basis}, item.confidence)
        node_links.append(CanonicalNodeEvidenceLink(parent_source, item_evidence.evidence_key, "inferred_from_edge"))

    return CanonicalizationResult(
        graph=CanonicalGraph(
            graph_key_version=legacy.graph.graph_key_version, nodes=tuple(nodes.values()),
            edges=tuple(edges.values()), evidence=tuple(evidence),
            node_evidence_links=tuple(node_links), edge_evidence_links=tuple(edge_links),
            raw_observation_count=len(merged),
        ),
        diagnostics=tuple(diagnostics),
    )


def canonicalize_rust_pilot(
    run: RustPilotController, legacy_observations: Sequence[RawObservation], *,
    repository_scope: str | None = None,
) -> WitnessedCanonicalization:
    if type(run) is not RustPilotController:
        raise ContractError("rust_pilot_controller_required")
    legacy_observations = tuple(legacy_observations)
    if any(item.kind in RUST_RAW_KINDS for item in legacy_observations):
        raise ContractError("legacy_rust_observation_not_allowed")
    if not run.verify_live():
        raise ContractError("rust_pilot_witness_unavailable")
    by_path, admission_diagnostics = _admit(run)
    rust = tuple(item for rows in by_path.values() for item in rows)
    merged = legacy_observations + rust
    result = _build(
        canonicalize_observations(legacy_observations, repository_scope=repository_scope),
        merged, by_path, admission_diagnostics,
    )
    witnessed = WitnessedCanonicalization(
        run, by_path, merged, result, _token=_CONSTRUCTION_TOKEN
    )
    if not witnessed.verify_live():
        raise ContractError("rust_pilot_witness_changed")
    return witnessed


__all__ = ("WitnessedCanonicalization", "canonicalize_rust_pilot")
