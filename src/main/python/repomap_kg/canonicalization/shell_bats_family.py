"""Bats shell-family canonicalization handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization._shell_edge_helpers import (
    _append_two_node_edge as _append_bats_two_node_edge,
)
from repomap_kg.canonicalization._shell_observation_helpers import (
    _append_graph_key_error as _append_bats_graph_key_error,
    _filtered_evidence_metadata,
    _shell_evidence,
)
from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.edge_helpers import _upsert_config_edge
from repomap_kg.canonicalization.dispatch_helpers import BATS_RAW_ONLY_KINDS
from repomap_kg.canonicalization.evidence_helpers import BATS_EVIDENCE_OMIT_KEYS
from repomap_kg.canonicalization.metadata_helpers import (
    _append_metadata_text,
    _metadata_text,
)
from repomap_kg.canonicalization.node_edge_helpers import (
    _display_name_from_key,
    _upsert_node,
)
from repomap_kg.graph.keys import (
    GraphKeyError,
    bats_expectation_key,
    bats_file_key,
    bats_test_case_key,
    external_key,
    file_key,
    parse_key,
    tool_key,
)
from repomap_kg.observations.raw import RawObservation

def _is_bats_observation(observation: RawObservation) -> bool:
    return observation.kind.startswith("bats.") or observation.metadata.get("dialect") == "bats"

def _bats_evidence_from_observation(
    observation: RawObservation,
    ordinal: int,
) -> CanonicalEvidence:
    return _shell_evidence(observation, ordinal, BATS_EVIDENCE_OMIT_KEYS)

def _bats_evidence_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return _filtered_evidence_metadata(metadata, BATS_EVIDENCE_OMIT_KEYS)

def _try_canonicalize_bats_observation(
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
    if not _is_bats_observation(observation):
        return False
    if observation.kind == "bats.file":
        _canonicalize_bats_file_observation(
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
    if observation.kind == "bats.test_case":
        _canonicalize_bats_test_case_observation(
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
    if observation.kind == "bats.load":
        _canonicalize_bats_load_observation(
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
    if observation.kind == "bats.library_load":
        _canonicalize_bats_library_load_observation(
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
    if observation.kind == "bats.run":
        _canonicalize_bats_run_observation(
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
    if observation.kind in ("bats.assertion", "bats.refutation"):
        _canonicalize_bats_assertion_observation(
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
    if observation.kind == "bats.fixture_reference":
        _canonicalize_bats_fixture_reference_observation(
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
    if observation.kind == "bats.helper_reference":
        _canonicalize_bats_helper_reference_observation(
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
    if observation.kind in BATS_RAW_ONLY_KINDS:
        evidence.append(_bats_evidence_from_observation(observation, ordinal))
        return True
    return False

def _canonicalize_bats_file_observation(
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
        target_key = bats_file_key(observation.path)
    except GraphKeyError as error:
        _append_bats_graph_key_error(observation, ordinal, diagnostics, error)
        return

    evidence_record = _bats_evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={"language": "bats"},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind="bats.file",
        display_name=observation.path,
        metadata=_bats_file_node_metadata(observation.metadata),
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
        metadata=_bats_base_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_bats_test_case_observation(
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
    test_identity = _bats_static_test_identity(observation)
    if test_identity is None:
        evidence.append(_bats_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = bats_file_key(observation.path)
        target_key = bats_test_case_key(observation.path, test_identity)
    except GraphKeyError as error:
        _append_bats_graph_key_error(observation, ordinal, diagnostics, error)
        return

    _append_bats_two_node_edge(
        observation=observation,
        evidence_record=_bats_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="bats.file",
        source_display=observation.path,
        source_metadata=_bats_file_node_metadata({}),
        target_key=target_key,
        target_kind="bats.test_case",
        target_display=test_identity,
        target_metadata=_bats_test_case_node_metadata(observation.metadata),
        edge_kind="contains",
        edge_metadata=_bats_base_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_bats_load_observation(
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
    if observation.target is None or not observation.target.startswith("file:"):
        evidence.append(_bats_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = bats_file_key(observation.path)
        parse_key(observation.target)
    except GraphKeyError as error:
        _append_bats_graph_key_error(observation, ordinal, diagnostics, error)
        return
    _append_bats_two_node_edge(
        observation=observation,
        evidence_record=_bats_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="bats.file",
        source_display=observation.path,
        source_metadata=_bats_file_node_metadata({}),
        target_key=observation.target,
        target_kind="file",
        target_display=_display_name_from_key(observation.target),
        target_metadata={},
        edge_kind="loads",
        edge_metadata=_bats_load_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_bats_library_load_observation(
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
    library_name = _metadata_text(observation.metadata, "library_name")
    if (
        library_name is None
        or _metadata_text(observation.metadata, "target_kind") != "static"
    ):
        evidence.append(_bats_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key = bats_file_key(observation.path)
        target_key = external_key("bats.library", library_name)
    except GraphKeyError as error:
        _append_bats_graph_key_error(observation, ordinal, diagnostics, error)
        return
    _append_bats_two_node_edge(
        observation=observation,
        evidence_record=_bats_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind="bats.file",
        source_display=observation.path,
        source_metadata=_bats_file_node_metadata({}),
        target_key=target_key,
        target_kind="external",
        target_display=library_name,
        target_metadata={"domain": "bats.library"},
        edge_kind="depends_on",
        edge_metadata=_bats_library_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_bats_run_observation(
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
    command_name = _metadata_text(observation.metadata, "command_token") or observation.name
    if (
        command_name is None
        or command_name == "[dynamic]"
        or _metadata_text(observation.metadata, "command_kind") != "static"
    ):
        evidence.append(_bats_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key, source_kind, source_display, source_metadata = _bats_context_source(
            observation
        )
        target_key = tool_key(command_name)
    except GraphKeyError as error:
        _append_bats_graph_key_error(observation, ordinal, diagnostics, error)
        return
    _append_bats_two_node_edge(
        observation=observation,
        evidence_record=_bats_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind=source_kind,
        source_display=source_display,
        source_metadata=source_metadata,
        target_key=target_key,
        target_kind="tool",
        target_display=command_name,
        target_metadata={},
        edge_kind="tests_command",
        edge_metadata=_bats_run_edge_metadata(observation.metadata, command_name),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_bats_assertion_observation(
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
    test_identity = _metadata_text(observation.metadata, "test_case_name")
    if assertion_name is None or test_identity is None:
        evidence.append(_bats_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key, source_kind, source_display, source_metadata = _bats_context_source(
            observation
        )
        target_key = bats_expectation_key(
            observation.path,
            test_identity,
            observation.start_line or 0,
            assertion_name,
        )
    except GraphKeyError as error:
        _append_bats_graph_key_error(observation, ordinal, diagnostics, error)
        return
    edge_kind = "asserts" if observation.kind == "bats.assertion" else "refutes"
    _append_bats_two_node_edge(
        observation=observation,
        evidence_record=_bats_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind=source_kind,
        source_display=source_display,
        source_metadata=source_metadata,
        target_key=target_key,
        target_kind="bats.expectation",
        target_display=assertion_name,
        target_metadata=_bats_expectation_node_metadata(observation.metadata),
        edge_kind=edge_kind,
        edge_metadata=_bats_assertion_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_bats_fixture_reference_observation(
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
    if (
        observation.target is None
        or not observation.target.startswith("file:")
        or _metadata_text(observation.metadata, "fixture_kind") != "repo_fixture"
    ):
        evidence.append(_bats_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key, source_kind, source_display, source_metadata = _bats_context_source(
            observation
        )
        parse_key(observation.target)
    except GraphKeyError as error:
        _append_bats_graph_key_error(observation, ordinal, diagnostics, error)
        return
    _append_bats_two_node_edge(
        observation=observation,
        evidence_record=_bats_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind=source_kind,
        source_display=source_display,
        source_metadata=source_metadata,
        target_key=observation.target,
        target_kind="file",
        target_display=_display_name_from_key(observation.target),
        target_metadata={},
        edge_kind="references",
        edge_metadata=_bats_fixture_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _canonicalize_bats_helper_reference_observation(
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
    helper_name = _metadata_text(observation.metadata, "helper_name") or observation.name
    if helper_name is None:
        evidence.append(_bats_evidence_from_observation(observation, ordinal))
        return
    try:
        source_key, source_kind, source_display, source_metadata = _bats_context_source(
            observation
        )
        target_key = external_key("bats.helper", helper_name)
    except GraphKeyError as error:
        _append_bats_graph_key_error(observation, ordinal, diagnostics, error)
        return
    _append_bats_two_node_edge(
        observation=observation,
        evidence_record=_bats_evidence_from_observation(observation, ordinal),
        source_key=source_key,
        source_kind=source_kind,
        source_display=source_display,
        source_metadata=source_metadata,
        target_key=target_key,
        target_kind="external",
        target_display=helper_name,
        target_metadata={"domain": "bats.helper"},
        edge_kind="references",
        edge_metadata=_bats_helper_edge_metadata(observation.metadata),
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        node_evidence_links=node_evidence_links,
        edge_evidence_links=edge_evidence_links,
    )

def _bats_static_test_identity(observation: RawObservation) -> str | None:
    if _metadata_text(observation.metadata, "test_name_kind") != "static":
        return None
    if bool(observation.metadata.get("test_name_redacted")):
        return None
    return _metadata_text(observation.metadata, "test_name") or observation.name

def _bats_context_source(
    observation: RawObservation,
) -> tuple[str, str, str, dict[str, Any]]:
    test_name = _metadata_text(observation.metadata, "test_case_name")
    if (
        _metadata_text(observation.metadata, "test_context") == "test_case"
        and test_name is not None
        and not bool(observation.metadata.get("test_case_name_redacted"))
    ):
        return (
            bats_test_case_key(observation.path, test_name),
            "bats.test_case",
            test_name,
            _bats_test_case_node_metadata({"test_name": test_name}),
        )
    return (
        bats_file_key(observation.path),
        "bats.file",
        observation.path,
        _bats_file_node_metadata({}),
    )

def _bats_file_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _bats_base_metadata()
    summary["language"] = "bats"
    for key in ("file_type", "classification_evidence"):
        if key in metadata:
            summary[key] = metadata[key]
    summary["shebang_present"] = bool(_metadata_text(metadata, "shebang"))
    return summary

def _bats_test_case_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _bats_base_metadata()
    summary["node_role"] = "test_case"
    summary["body_modeled"] = False
    _append_metadata_text(summary, metadata, "test_name_kind", "test_name_kinds")
    command_count = metadata.get("command_count")
    if isinstance(command_count, int):
        summary["command_counts"] = [command_count]
    return summary

def _bats_expectation_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _bats_base_metadata()
    summary["node_role"] = "expectation"
    for source_key, target_key in (
        ("assertion_name", "assertion_names"),
        ("assertion_family", "assertion_families"),
        ("mode", "modes"),
        ("expected_value_kind", "expected_value_kinds"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    summary["assertion_executed"] = False
    return summary

def _bats_base_metadata() -> dict[str, Any]:
    return {
        "dialect": "bats",
        "test_framework": "bats",
        "static_only": True,
        "shell_executed": False,
        "bats_executed": False,
    }

def _bats_base_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _bats_base_metadata()
    if isinstance(metadata.get("test_intent"), bool):
        summary["test_intent"] = bool(metadata["test_intent"])
    if isinstance(metadata.get("command_executed"), bool):
        summary["command_executed"] = bool(metadata["command_executed"])
    return summary

def _bats_load_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _bats_base_edge_metadata(metadata)
    summary["helper_executed"] = False
    _append_metadata_text(summary, metadata, "resolution", "resolutions")
    _append_metadata_text(summary, metadata, "target_kind", "target_kinds")
    return summary

def _bats_library_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _bats_base_edge_metadata(metadata)
    summary["library_executed"] = False
    _append_metadata_text(summary, metadata, "library_name", "libraries")
    _append_metadata_text(summary, metadata, "resolution", "resolutions")
    return summary

def _bats_run_edge_metadata(
    metadata: Mapping[str, Any],
    command_name: str,
) -> dict[str, Any]:
    summary = _bats_base_edge_metadata(metadata)
    summary.update(
        {
            "commands": [command_name],
            "test_intent": True,
            "command_under_test": True,
            "command_executed": False,
        }
    )
    for source_key, target_key in (
        ("command_kind", "command_kinds"),
        ("test_context", "test_contexts"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    for source_key, target_key in (
        ("argument_count", "argument_counts"),
        ("expected_status", "expected_statuses"),
    ):
        value = metadata.get(source_key)
        if isinstance(value, int):
            summary[target_key] = [value]
    for source_key, target_key in (
        ("negated", "negated_observed"),
        ("separate_stderr", "separate_stderr_observed"),
    ):
        value = metadata.get(source_key)
        if isinstance(value, bool):
            summary[target_key] = value
    return summary

def _bats_assertion_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _bats_base_edge_metadata(metadata)
    summary["assertion_executed"] = False
    for source_key, target_key in (
        ("assertion_name", "assertion_names"),
        ("assertion_family", "assertion_families"),
        ("mode", "modes"),
        ("expected_value_kind", "expected_value_kinds"),
    ):
        _append_metadata_text(summary, metadata, source_key, target_key)
    argument_count = metadata.get("argument_count")
    if isinstance(argument_count, int):
        summary["argument_counts"] = [argument_count]
    return summary

def _bats_fixture_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _bats_base_edge_metadata(metadata)
    summary["filesystem_checked"] = False
    summary["file_created"] = False
    _append_metadata_text(summary, metadata, "fixture_kind", "fixture_kinds")
    _append_metadata_text(summary, metadata, "resolution", "resolutions")
    _append_metadata_text(summary, metadata, "source_kind", "source_kinds")
    return summary

def _bats_helper_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _bats_base_edge_metadata(metadata)
    summary["helper_executed"] = False
    _append_metadata_text(summary, metadata, "reference_kind", "reference_kinds")
    _append_metadata_text(summary, metadata, "resolution", "resolutions")
    return summary
