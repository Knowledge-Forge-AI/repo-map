"""JavaScript source-language canonicalization handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.diagnostic_helpers import (
    _graph_key_error_category,
)
from repomap_kg.canonicalization.edge_helpers import _upsert_css_edge
from repomap_kg.canonicalization.evidence_helpers import _evidence_from_observation
from repomap_kg.canonicalization.metadata_helpers import _metadata_text
from repomap_kg.canonicalization.node_edge_helpers import (
    _display_name_from_key,
    _node_kind_from_key,
    _upsert_node,
)
from repomap_kg.graph.keys import (
    GraphKeyError,
    file_key,
    js_class_key,
    js_component_key,
    js_file_key,
    js_function_key,
    js_method_key,
    js_module_key,
    js_route_key,
    js_test_case_key,
    js_test_suite_key,
    js_variable_key,
    parse_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


def _canonicalize_js_definition_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        source_key = _js_definition_source_key(observation)
        target_key = _js_definition_target_key(observation)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=observation.target,
            )
        )
        return

    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind=_node_kind_from_key(source_key),
        display_name=_js_display_name(source_key, observation),
        metadata=_js_node_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=_js_display_name(target_key, observation),
        metadata=_js_node_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    node_evidence_links.extend(
        (
            CanonicalNodeEvidenceLink(
                canonical_key=source_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
            CanonicalNodeEvidenceLink(
                canonical_key=target_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="observed",
            ),
        )
    )
    edge_key = _upsert_css_edge(
        edges,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
        metadata=_js_define_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_js_reference_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        source_key = _js_reference_source_key(observation)
        target_key = _js_reference_target_key(observation, ordinal, diagnostics)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=observation.target,
            )
        )
        return

    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind=_node_kind_from_key(source_key),
        display_name=_display_name_from_key(source_key),
        metadata=_js_node_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=_display_name_from_key(target_key),
        metadata={},
        confidence=observation.confidence,
    )
    node_evidence_links.extend(
        (
            CanonicalNodeEvidenceLink(
                canonical_key=source_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
            CanonicalNodeEvidenceLink(
                canonical_key=target_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
        )
    )
    edge_key = _upsert_css_edge(
        edges,
        source_key=source_key,
        kind="references",
        target_key=target_key,
        metadata=_js_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _js_definition_source_key(observation: RawObservation) -> str:
    if observation.kind == "js.file":
        return file_key(observation.path)
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is not None:
        parsed = parse_key(source_key)
        if parsed.namespace in {
            "file",
            "js.file",
            "js.module",
            "js.function",
            "js.class",
            "js.method",
            "js.component",
            "js.test_suite",
            "js.test_case",
            "js.route",
        }:
            return source_key
        raise GraphKeyError(f"{observation.kind} source_key has unsupported namespace")
    if observation.kind == "js.module":
        return js_file_key(observation.path)
    if observation.kind in (
        "js.function",
        "js.class",
        "js.variable",
        "js.component",
        "js.test_suite",
        "js.route",
    ):
        return js_module_key(observation.path)
    if observation.kind == "js.method":
        class_key = _metadata_text(observation.metadata, "class_key")
        if class_key is not None and parse_key(class_key).namespace == "js.class":
            return class_key
        class_name = _metadata_text(observation.metadata, "class_name")
        if class_name is not None:
            return js_class_key(observation.path, class_name)
        raise GraphKeyError("js.method observation requires class metadata")
    if observation.kind == "js.test_case":
        suite_key = _metadata_text(observation.metadata, "test_suite_key")
        if suite_key is not None and parse_key(suite_key).namespace == "js.test_suite":
            return suite_key
        return js_file_key(observation.path)
    raise GraphKeyError(f"unsupported JavaScript definition kind: {observation.kind}")


def _js_definition_target_key(observation: RawObservation) -> str:
    if observation.target is not None:
        parse_key(observation.target)
        return observation.target
    name = observation.name
    if not isinstance(name, str) or not name.strip():
        raise GraphKeyError(f"{observation.kind} observation requires name or target")
    if observation.kind == "js.file":
        return js_file_key(observation.path)
    if observation.kind == "js.module":
        return js_module_key(observation.path)
    if observation.kind == "js.function":
        return js_function_key(observation.path, name)
    if observation.kind == "js.class":
        return js_class_key(observation.path, name)
    if observation.kind == "js.method":
        class_key = _js_definition_source_key(observation)
        return js_method_key(class_key, name)
    if observation.kind == "js.variable":
        return js_variable_key(observation.path, name)
    if observation.kind == "js.component":
        return js_component_key(observation.path, name)
    if observation.kind == "js.test_suite":
        pointer = _metadata_text(observation.metadata, "test_pointer") or f"/tests/{name}"
        return js_test_suite_key(observation.path, pointer)
    if observation.kind == "js.test_case":
        owner_key = _js_definition_source_key(observation)
        pointer = _metadata_text(observation.metadata, "test_pointer") or f"/tests/{name}"
        return js_test_case_key(owner_key, pointer)
    if observation.kind == "js.route":
        route_pointer = _metadata_text(observation.metadata, "route_pointer")
        if route_pointer is None:
            raise GraphKeyError("js.route observation requires route_pointer metadata")
        return js_route_key(observation.path, route_pointer)
    raise GraphKeyError(f"unsupported JavaScript definition kind: {observation.kind}")


def _js_reference_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is None:
        return js_module_key(observation.path)
    parsed = parse_key(source_key)
    if parsed.namespace in {
        "js.file",
        "js.module",
        "js.function",
        "js.class",
        "js.method",
        "js.variable",
        "js.component",
        "js.test_suite",
        "js.test_case",
        "js.route",
    }:
        return source_key
    raise GraphKeyError("js.reference source_key has unsupported namespace")


def _js_reference_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    target = observation.target or _metadata_text(observation.metadata, "target_key")
    if target is None:
        placeholder_key = unknown_key("js.reference", "missing-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="js.reference observation requires target",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=target,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key
    try:
        parse_key(target)
    except GraphKeyError as error:
        placeholder_key = unknown_key("js.reference", "malformed-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category=_graph_key_error_category(error),
                message=f"js.reference target is not a canonical key: {error}",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=target,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key
    return target


def _js_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "profile",
        "parser",
        "module_system",
        "export_kind",
        "import_kind",
        "local_name",
        "exported_name",
        "qualified_name",
        "function_name",
        "class_name",
        "method_name",
        "component_name",
        "test_framework",
        "route_method",
        "route_pattern",
        "literal_type",
        "dynamic",
        "dynamic_reason",
        "redacted",
        "redaction_reason",
        "identity_strength",
    ):
        value = metadata.get(key)
        if value is not None:
            summary[key] = value
    return summary


def _js_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    profile = _metadata_text(metadata, "profile")
    if profile:
        summary["profiles"] = [profile]
    for source_key, target_key in (
        ("module_system", "module_systems"),
        ("function_name", "functions"),
        ("class_name", "classes"),
        ("method_name", "methods"),
        ("local_name", "locals"),
        ("component_name", "components"),
        ("test_framework", "test_frameworks"),
        ("route_method", "route_methods"),
        ("route_pattern", "route_patterns"),
    ):
        value = _metadata_text(metadata, source_key)
        if value:
            summary[target_key] = [value]
    return summary


def _js_reference_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, target_key in (
        ("profile", "profiles"),
        ("raw_value_summary", "raw_value_summaries"),
        ("reference_kind", "reference_kinds"),
        ("import_kind", "import_kinds"),
        ("export_kind", "export_kinds"),
        ("resolution_reason", "resolution_reasons"),
        ("dynamic_reason", "dynamic_reasons"),
    ):
        value = _metadata_text(metadata, source_key)
        if value:
            summary[target_key] = [value]
    not_fetched = metadata.get("not_fetched")
    if isinstance(not_fetched, bool):
        summary["not_fetched"] = not_fetched
    dynamic = metadata.get("dynamic")
    if isinstance(dynamic, bool):
        summary["dynamic_observed"] = dynamic
    return summary


def _js_display_name(canonical_key: str, observation: RawObservation) -> str:
    for key in (
        "qualified_name",
        "function_name",
        "class_name",
        "method_name",
        "component_name",
        "route_pattern",
        "local_name",
    ):
        value = _metadata_text(observation.metadata, key)
        if value is not None:
            return value
    if observation.name:
        return observation.name
    return _display_name_from_key(canonical_key)
