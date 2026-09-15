"""Zunit shell-family canonicalization handlers."""

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
from repomap_kg.canonicalization._shell_edge_helpers import (
    _append_two_node_edge as _append_zunit_two_node_edge,
)
from repomap_kg.canonicalization._shell_observation_helpers import (
    _append_graph_key_error as _append_zunit_graph_key_error,
    _filtered_evidence_metadata,
    _shell_evidence,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.edge_helpers import _upsert_config_edge
from repomap_kg.canonicalization.dispatch_helpers import ZUNIT_RAW_ONLY_KINDS
from repomap_kg.canonicalization.evidence_helpers import ZUNIT_EVIDENCE_OMIT_KEYS
from repomap_kg.canonicalization.metadata_helpers import _metadata_text
from repomap_kg.canonicalization.node_edge_helpers import _upsert_node
from repomap_kg.canonicalization.shell_zunit_metadata import (
    _zunit_assertion_edge_metadata,
    _zunit_assertion_node_metadata,
    _zunit_base_edge_metadata,
    _zunit_base_metadata,
    _zunit_command_edge_metadata,
    _zunit_command_node_metadata,
    _zunit_context_source,
    _zunit_expectation_edge_metadata,
    _zunit_expectation_node_metadata,
    _zunit_file_node_metadata,
    _zunit_fixture_edge_metadata,
    _zunit_helper_edge_metadata,
    _zunit_hook_node_metadata,
    _zunit_mock_or_stub_edge_metadata,
    _zunit_mock_or_stub_node_metadata,
    _zunit_static_suite_identity,
    _zunit_static_test_identity,
    _zunit_suite_node_metadata,
    _zunit_test_case_node_metadata,
    _zunit_test_owner,
)
from repomap_kg.graph.keys import (
    GraphKeyError,
    file_key,
    tool_key,
    zunit_assertion_key,
    zunit_command_under_test_key,
    zunit_expectation_key,
    zunit_file_key,
    zunit_hook_key,
    zunit_mock_key,
    zunit_stub_key,
    zunit_suite_key,
    zunit_test_case_key,
)
from repomap_kg.observations.raw import RawObservation

def _is_zunit_observation(observation: RawObservation) -> bool:
    return (
        observation.kind.startswith("zunit.")
        or observation.metadata.get("test_framework") == "zunit"
    )

def _zunit_evidence_from_observation(
    observation: RawObservation,
    ordinal: int,
) -> CanonicalEvidence:
    return _shell_evidence(observation, ordinal, ZUNIT_EVIDENCE_OMIT_KEYS)

def _zunit_evidence_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return _filtered_evidence_metadata(metadata, ZUNIT_EVIDENCE_OMIT_KEYS)

def _try_canonicalize_zunit_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> bool:
    if not _is_zunit_observation(observation):
        return False
    if observation.kind == "zunit.file":
        _canonicalize_zunit_file_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "zunit.suite":
        _canonicalize_zunit_suite_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "zunit.test_case":
        _canonicalize_zunit_test_case_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in (
        "zunit.setup",
        "zunit.teardown",
        "zunit.before_each",
        "zunit.after_each",
        "zunit.hook",
    ):
        _canonicalize_zunit_hook_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "zunit.helper":
        _canonicalize_zunit_helper_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "zunit.fixture_reference":
        _canonicalize_zunit_fixture_reference_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "zunit.command_under_test":
        _canonicalize_zunit_command_under_test_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "zunit.assertion":
        _canonicalize_zunit_assertion_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "zunit.expectation":
        _canonicalize_zunit_expectation_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in ("zunit.mock", "zunit.stub"):
        _canonicalize_zunit_mock_or_stub_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in ZUNIT_RAW_ONLY_KINDS:
        evidence.append(_zunit_evidence_from_observation(observation, ordinal))
        return True
    return False

def _canonicalize_zunit_file_observation(
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
        target_key = zunit_file_key(observation.path)
    except GraphKeyError as error:
        _append_zunit_graph_key_error(observation, ordinal, diagnostics, error)
        return

    evidence_record = _zunit_evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={"language": "zunit"},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind="zunit.file",
        display_name=observation.path,
        metadata=_zunit_file_node_metadata(observation.metadata),
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
    edge_key = _upsert_config_edge(
        edges,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
        metadata=_zunit_base_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_zunit_suite_observation(
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
    suite_identity = _zunit_static_suite_identity(observation)
    if suite_identity is None:
        evidence.append(_zunit_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zunit_file_key(observation.path)
        target_key = zunit_suite_key(observation.path, suite_identity)
    except GraphKeyError as error:
        _append_zunit_graph_key_error(observation, ordinal, diagnostics, error)
        return
    _append_zunit_two_node_edge(
        observation=observation,
        evidence_record=_zunit_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="zunit.file",
        source_display=observation.path,
        source_metadata=_zunit_file_node_metadata({}),
        target_key=target_key,
        target_kind="zunit.suite",
        target_display=suite_identity,
        target_metadata=_zunit_suite_node_metadata(observation.metadata),
        edge_kind="contains",
        edge_metadata=_zunit_base_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zunit_test_case_observation(
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
    test_identity = _zunit_static_test_identity(observation)
    if test_identity is None:
        evidence.append(_zunit_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key, source_kind, source_display, source_metadata = _zunit_test_owner(
            observation
        )
        target_key = zunit_test_case_key(observation.path, test_identity)
    except GraphKeyError as error:
        _append_zunit_graph_key_error(observation, ordinal, diagnostics, error)
        return
    edge_kind = "has_test_case" if source_kind == "zunit.suite" else "contains"
    _append_zunit_two_node_edge(
        observation=observation,
        evidence_record=_zunit_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind=source_kind,
        source_display=source_display,
        source_metadata=source_metadata,
        target_key=target_key,
        target_kind="zunit.test_case",
        target_display=test_identity,
        target_metadata=_zunit_test_case_node_metadata(observation.metadata),
        edge_kind=edge_kind,
        edge_metadata=_zunit_base_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zunit_hook_observation(
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
    hook_name = _metadata_text(observation.metadata, "hook_name") or observation.name
    if hook_name is None or hook_name == "[dynamic]":
        evidence.append(_zunit_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zunit_file_key(observation.path)
        target_key = zunit_hook_key(
            observation.path,
            hook_name,
            observation.start_line or 0,
        )
    except GraphKeyError as error:
        _append_zunit_graph_key_error(observation, ordinal, diagnostics, error)
        return
    _append_zunit_two_node_edge(
        observation=observation,
        evidence_record=_zunit_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="zunit.file",
        source_display=observation.path,
        source_metadata=_zunit_file_node_metadata({}),
        target_key=target_key,
        target_kind="zunit.hook",
        target_display=hook_name,
        target_metadata=_zunit_hook_node_metadata(observation.metadata),
        edge_kind="has_hook",
        edge_metadata=_zunit_base_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zunit_helper_observation(
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
    target_path = _metadata_text(observation.metadata, "resolved_path")
    if (
        _metadata_text(observation.metadata, "target_kind") != "static"
        or target_path is None
    ):
        evidence.append(_zunit_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zunit_file_key(observation.path)
        target_key = file_key(target_path)
    except GraphKeyError as error:
        _append_zunit_graph_key_error(observation, ordinal, diagnostics, error)
        return
    _append_zunit_two_node_edge(
        observation=observation,
        evidence_record=_zunit_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="zunit.file",
        source_display=observation.path,
        source_metadata=_zunit_file_node_metadata({}),
        target_key=target_key,
        target_kind="file",
        target_display=target_path,
        target_metadata={},
        edge_kind="uses_helper",
        edge_metadata=_zunit_helper_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zunit_fixture_reference_observation(
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
    target_path = _metadata_text(observation.metadata, "resolved_path")
    if (
        _metadata_text(observation.metadata, "target_kind") != "static"
        or target_path is None
    ):
        evidence.append(_zunit_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key, source_kind, source_display, source_metadata = _zunit_context_source(
            observation
        )
        target_key = file_key(target_path)
    except GraphKeyError as error:
        _append_zunit_graph_key_error(observation, ordinal, diagnostics, error)
        return
    _append_zunit_two_node_edge(
        observation=observation,
        evidence_record=_zunit_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind=source_kind,
        source_display=source_display,
        source_metadata=source_metadata,
        target_key=target_key,
        target_kind="file",
        target_display=target_path,
        target_metadata={},
        edge_kind="uses_fixture",
        edge_metadata=_zunit_fixture_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zunit_command_under_test_observation(
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
    command_name = _metadata_text(observation.metadata, "command_name") or observation.name
    if (
        command_name is None
        or command_name == "[dynamic]"
        or _metadata_text(observation.metadata, "target_kind") != "command"
    ):
        evidence.append(_zunit_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key, source_kind, source_display, source_metadata = _zunit_context_source(
            observation
        )
        command_key = zunit_command_under_test_key(
            observation.path,
            observation.start_line or 0,
            command_name,
        )
        tool_target_key = tool_key(command_name)
    except GraphKeyError as error:
        _append_zunit_graph_key_error(observation, ordinal, diagnostics, error)
        return

    evidence_record = _zunit_evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind=source_kind,
        display_name=source_display,
        metadata=source_metadata,
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=command_key,
        kind="zunit.command_under_test",
        display_name=command_name,
        metadata=_zunit_command_node_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=tool_target_key,
        kind="tool",
        display_name=command_name,
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
                canonical_key=command_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="observed",
            ),
            CanonicalNodeEvidenceLink(
                canonical_key=tool_target_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
        )
    )
    edge_key = _upsert_config_edge(
        edges,
        source_key=source_key,
        kind="command_under_test",
        target_key=tool_target_key,
        metadata=_zunit_command_edge_metadata(observation.metadata, command_name),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_zunit_assertion_observation(
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
    assertion_name = _metadata_text(observation.metadata, "assertion_name") or observation.name
    if assertion_name is None or assertion_name == "[dynamic]":
        evidence.append(_zunit_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key, source_kind, source_display, source_metadata = _zunit_context_source(
            observation
        )
        target_key = zunit_assertion_key(
            observation.path,
            observation.start_line or 0,
            assertion_name,
        )
    except GraphKeyError as error:
        _append_zunit_graph_key_error(observation, ordinal, diagnostics, error)
        return
    _append_zunit_two_node_edge(
        observation=observation,
        evidence_record=_zunit_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind=source_kind,
        source_display=source_display,
        source_metadata=source_metadata,
        target_key=target_key,
        target_kind="zunit.assertion",
        target_display=assertion_name,
        target_metadata=_zunit_assertion_node_metadata(observation.metadata),
        edge_kind="has_assertion",
        edge_metadata=_zunit_assertion_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zunit_expectation_observation(
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
    expectation_kind = _metadata_text(observation.metadata, "expectation_kind")
    if expectation_kind is None or expectation_kind in {"dynamic", "redacted"}:
        evidence.append(_zunit_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key, source_kind, source_display, source_metadata = _zunit_context_source(
            observation
        )
        target_key = zunit_expectation_key(
            observation.path,
            observation.start_line or 0,
            expectation_kind,
        )
    except GraphKeyError as error:
        _append_zunit_graph_key_error(observation, ordinal, diagnostics, error)
        return
    _append_zunit_two_node_edge(
        observation=observation,
        evidence_record=_zunit_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind=source_kind,
        source_display=source_display,
        source_metadata=source_metadata,
        target_key=target_key,
        target_kind="zunit.expectation",
        target_display=expectation_kind,
        target_metadata=_zunit_expectation_node_metadata(observation.metadata),
        edge_kind="expects",
        edge_metadata=_zunit_expectation_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_zunit_mock_or_stub_observation(
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
    command_name = (
        _metadata_text(observation.metadata, "target_command")
        or _metadata_text(observation.metadata, "command_name")
        or observation.name
    )
    if (
        command_name is None
        or _metadata_text(observation.metadata, "target_kind") != "command"
    ):
        evidence.append(_zunit_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = zunit_file_key(observation.path)
        if observation.kind == "zunit.mock":
            target_key = zunit_mock_key(
                observation.path,
                observation.start_line or 0,
                command_name,
            )
            target_kind = "zunit.mock"
            edge_kind = "uses_mock"
        else:
            target_key = zunit_stub_key(
                observation.path,
                observation.start_line or 0,
                command_name,
            )
            target_kind = "zunit.stub"
            edge_kind = "uses_stub"
    except GraphKeyError as error:
        _append_zunit_graph_key_error(observation, ordinal, diagnostics, error)
        return
    _append_zunit_two_node_edge(
        observation=observation,
        evidence_record=_zunit_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="zunit.file",
        source_display=observation.path,
        source_metadata=_zunit_file_node_metadata({}),
        target_key=target_key,
        target_kind=target_kind,
        target_display=command_name,
        target_metadata=_zunit_mock_or_stub_node_metadata(observation.metadata),
        edge_kind=edge_kind,
        edge_metadata=_zunit_mock_or_stub_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )
