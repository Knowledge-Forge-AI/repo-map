"""Source-language canonicalization handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
    canonical_edge_key,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.diagnostic_helpers import (
    _append_raw_target_diagnostic,
    _graph_key_error_category,
)
from repomap_kg.canonicalization.edge_helpers import _upsert_css_edge
from repomap_kg.canonicalization.evidence_helpers import _evidence_from_observation
from repomap_kg.canonicalization.language_javascript_family import (
    _canonicalize_js_definition_observation,
    _canonicalize_js_reference_observation,
    _js_define_edge_metadata,
    _js_definition_source_key,
    _js_definition_target_key,
    _js_display_name,
    _js_node_metadata,
    _js_reference_edge_metadata,
    _js_reference_source_key,
    _js_reference_target_key,
)
from repomap_kg.canonicalization.metadata_helpers import (
    _append_metadata_text,
    _metadata_text,
)
from repomap_kg.canonicalization.node_edge_helpers import (
    _display_name_from_key,
    _node_kind_from_key,
    _upsert_edge,
    _upsert_node,
)
from repomap_kg.graph.keys import (
    GRAPH_KEY_VERSION,
    GraphKeyError,
    external_key,
    file_key,
    parse_key,
    python_class_key,
    python_function_key,
    python_method_key,
    python_module_key,
    ruby_class_key,
    ruby_constant_key,
    ruby_file_key,
    ruby_method_key,
    ruby_module_key,
    ruby_route_key,
    ruby_singleton_method_key,
    ruby_test_case_key,
    ruby_test_method_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


def _canonicalize_python_definition_observation(
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
        source_key = file_key(observation.path)
        target_key, target_display_name, edge_metadata = _python_definition_target(
            observation
        )
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
        kind="file",
        display_name=observation.path,
        metadata={},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=target_display_name,
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
                link_kind="observed",
            ),
        )
    )

    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=edge_metadata,
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_ruby_definition_observation(
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
        source_key = _ruby_definition_source_key(observation)
        target_key = _ruby_definition_target_key(observation)
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
        display_name=_ruby_display_name(source_key, observation),
        metadata=_ruby_node_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=_ruby_display_name(target_key, observation),
        metadata=_ruby_node_metadata(observation.metadata),
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
        metadata=_ruby_define_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_ruby_reference_observation(
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
        source_key = _ruby_reference_source_key(observation)
        target_key = _ruby_reference_target_key(observation, ordinal, diagnostics)
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
        metadata=_ruby_node_metadata(observation.metadata),
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
        metadata=_ruby_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_python_import_observation(
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
    source_module = _metadata_text(observation.metadata, "module")
    if source_module is None:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="python.import observation requires module metadata",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.module",
                value=source_module,
            )
        )
        return
    try:
        source_key = python_module_key(source_module)
        target_key = _python_import_target_key(observation, ordinal, diagnostics)
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
        kind="python.module",
        display_name=source_module,
        metadata={},
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

    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind="imports",
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind="imports",
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=_python_import_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _python_definition_target(
    observation: RawObservation,
) -> tuple[str, str, dict[str, Any]]:
    module = _metadata_text(observation.metadata, "module")
    name = observation.name
    if observation.kind == "python.module":
        module_name = module or name
        if not isinstance(module_name, str) or not module_name.strip():
            raise GraphKeyError("python.module observation requires module name")
        return python_module_key(module_name), module_name, {"modules": [module_name]}
    if not isinstance(module, str) or not module.strip():
        raise GraphKeyError(f"{observation.kind} observation requires module metadata")
    if not isinstance(name, str) or not name.strip():
        raise GraphKeyError(f"{observation.kind} observation requires name")
    if observation.kind == "python.class":
        return python_class_key(module, name), name, {"classes": [name]}
    if observation.kind == "python.function":
        return python_function_key(module, name), name, {"functions": [name]}
    if observation.kind == "python.method":
        class_name = _metadata_text(observation.metadata, "class")
        if class_name is None:
            raise GraphKeyError("python.method observation requires class metadata")
        return (
            python_method_key(module, class_name, name),
            f"{class_name}.{name}",
            {"methods": [f"{class_name}.{name}"]},
        )
    raise GraphKeyError(f"unsupported Python definition kind: {observation.kind}")

def _ruby_definition_source_key(observation: RawObservation) -> str:
    if observation.kind == "ruby.file":
        return file_key(observation.path)
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is not None:
        parsed = parse_key(source_key)
        if parsed.namespace in {
            "file",
            "ruby.file",
            "ruby.module",
            "ruby.class",
            "ruby.method",
            "ruby.singleton_method",
            "ruby.test_case",
            "ruby.route",
        }:
            return source_key
        raise GraphKeyError(f"{observation.kind} source_key has unsupported namespace")
    if observation.kind in ("ruby.module", "ruby.class", "ruby.test_case", "ruby.route"):
        return ruby_file_key(observation.path)
    if observation.kind == "ruby.test_method":
        test_case_key = _metadata_text(observation.metadata, "test_case_key")
        if test_case_key is not None:
            parsed = parse_key(test_case_key)
            if parsed.namespace == "ruby.test_case":
                return test_case_key
        raise GraphKeyError("ruby.test_method observation requires test_case_key")
    if observation.kind in ("ruby.method", "ruby.singleton_method", "ruby.constant"):
        owner = _metadata_text(observation.metadata, "owner")
        if owner is None:
            raise GraphKeyError(f"{observation.kind} observation requires owner metadata")
        owner_kind = _metadata_text(observation.metadata, "owner_kind") or "ruby.class"
        if owner_kind == "ruby.module":
            return ruby_module_key(owner)
        if owner_kind == "ruby.class":
            return ruby_class_key(owner)
        raise GraphKeyError(f"{observation.kind} owner_kind has unsupported namespace")
    raise GraphKeyError(f"unsupported Ruby definition kind: {observation.kind}")

def _ruby_definition_target_key(observation: RawObservation) -> str:
    if observation.target is not None:
        parse_key(observation.target)
        return observation.target
    name = observation.name
    if not isinstance(name, str) or not name.strip():
        raise GraphKeyError(f"{observation.kind} observation requires name or target")
    if observation.kind == "ruby.file":
        return ruby_file_key(observation.path)
    if observation.kind == "ruby.module":
        return ruby_module_key(name)
    if observation.kind == "ruby.class":
        return ruby_class_key(name)
    if observation.kind == "ruby.method":
        owner = _metadata_text(observation.metadata, "owner")
        if owner is None:
            raise GraphKeyError("ruby.method observation requires owner metadata")
        return ruby_method_key(owner, name)
    if observation.kind == "ruby.singleton_method":
        owner = _metadata_text(observation.metadata, "owner")
        if owner is None:
            raise GraphKeyError("ruby.singleton_method observation requires owner metadata")
        return ruby_singleton_method_key(owner, name)
    if observation.kind == "ruby.constant":
        owner = _metadata_text(observation.metadata, "owner")
        if owner is None:
            raise GraphKeyError("ruby.constant observation requires owner metadata")
        return ruby_constant_key(owner, name)
    if observation.kind == "ruby.test_case":
        return ruby_test_case_key(observation.path, name)
    if observation.kind == "ruby.test_method":
        test_case_key = _metadata_text(observation.metadata, "test_case_key")
        if test_case_key is None:
            raise GraphKeyError("ruby.test_method observation requires test_case_key")
        return ruby_test_method_key(test_case_key, name)
    if observation.kind == "ruby.route":
        route_pointer = _metadata_text(observation.metadata, "route_pointer")
        if route_pointer is None:
            raise GraphKeyError("ruby.route observation requires route_pointer metadata")
        return ruby_route_key(observation.path, route_pointer)
    raise GraphKeyError(f"unsupported Ruby definition kind: {observation.kind}")

def _ruby_reference_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is None:
        return ruby_file_key(observation.path)
    parsed = parse_key(source_key)
    if parsed.namespace in {
        "ruby.file",
        "ruby.module",
        "ruby.class",
        "ruby.method",
        "ruby.singleton_method",
        "ruby.test_case",
        "ruby.test_method",
        "ruby.route",
    }:
        return source_key
    raise GraphKeyError("ruby.reference source_key has unsupported namespace")

def _ruby_reference_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    target = observation.target or _metadata_text(observation.metadata, "target_key")
    if target is None:
        placeholder_key = unknown_key("ruby.reference", "missing-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="ruby.reference observation requires target",
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
        placeholder_key = unknown_key("ruby.reference", "malformed-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category=_graph_key_error_category(error),
                message=f"ruby.reference target is not a canonical key: {error}",
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

def _ruby_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "profile",
        "parser",
        "qualified_name",
        "owner",
        "method_name",
        "superclass",
        "constant_name",
        "test_framework",
        "route_method",
        "route_pattern",
        "redacted",
        "redaction_reason",
        "dynamic",
        "dynamic_reason",
        "identity_strength",
    ):
        value = metadata.get(key)
        if value is not None:
            summary[key] = value
    return summary

def _ruby_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    profile = _metadata_text(metadata, "profile")
    if profile:
        summary["profiles"] = [profile]
    for source_key, target_key in (
        ("qualified_name", "qualified_names"),
        ("owner", "owners"),
        ("method_name", "methods"),
        ("constant_name", "constants"),
        ("test_framework", "test_frameworks"),
        ("route_method", "route_methods"),
        ("route_pattern", "route_patterns"),
    ):
        value = _metadata_text(metadata, source_key)
        if value:
            summary[target_key] = [value]
    return summary

def _ruby_reference_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, target_key in (
        ("profile", "profiles"),
        ("raw_value_summary", "raw_value_summaries"),
        ("reference_kind", "reference_kinds"),
        ("resolution_reason", "resolution_reasons"),
    ):
        value = _metadata_text(metadata, source_key)
        if value:
            summary[target_key] = [value]
    return summary

def _ruby_display_name(canonical_key: str, observation: RawObservation) -> str:
    for key in ("qualified_name", "method_name", "constant_name", "route_pattern"):
        value = _metadata_text(observation.metadata, key)
        if value is not None:
            return value
    if observation.name:
        return observation.name
    return _display_name_from_key(canonical_key)

def _python_import_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    resolution = _metadata_text(observation.metadata, "resolution")
    imported_module = _metadata_text(observation.metadata, "imported_module")
    if resolution == "local" and imported_module is not None:
        return python_module_key(imported_module)
    if resolution == "external" and imported_module is not None:
        return external_key("python.module", imported_module)
    if resolution == "unknown":
        if observation.target is not None:
            try:
                parsed = parse_key(observation.target)
            except GraphKeyError as error:
                diagnostics.append(
                    CanonicalizationDiagnostic(
                        severity="warning",
                        category=_graph_key_error_category(error),
                        message=f"raw target is not a valid canonical key: {error}",
                        raw_observation_ordinal=ordinal,
                        raw_source_id=observation.source_id,
                        path=observation.path,
                        field="target",
                        value=observation.target,
                    )
                )
            else:
                if parsed.namespace in ("unknown", "dynamic"):
                    return observation.target
        return unknown_key("python.module", "missing-module")
    if imported_module is not None:
        return external_key("python.module", imported_module)
    return unknown_key("python.module", "missing-module")

def _python_import_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    imported_module = _metadata_text(metadata, "imported_module")
    if imported_module is not None:
        summary["imported_modules"] = [imported_module]
    resolution = _metadata_text(metadata, "resolution")
    if resolution is not None:
        summary["resolutions"] = [resolution]
    return summary
