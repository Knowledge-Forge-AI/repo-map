"""Email canonicalization handlers."""

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
from repomap_kg.canonicalization.diagnostic_helpers import _graph_key_error_category
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
    email_address_key,
    email_attachment_stub_key,
    email_mailbox_key,
    email_message_key,
    email_part_key,
    email_thread_hint_key,
    file_key,
    parse_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


def _canonicalize_email_definition_observation(
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
        source_key = _email_definition_source_key(observation)
        target_key = _email_definition_target_key(observation)
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
        metadata={},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=_email_display_name(target_key, observation),
        metadata=_email_node_metadata(observation.kind, observation.metadata),
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
        metadata=_email_define_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_email_address_observation(
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
        source_key = _email_reference_source_key(observation)
        target_key = _email_address_target_key(observation)
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
        metadata={},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind="email.address",
        display_name=_email_display_name(target_key, observation),
        metadata=_email_node_metadata(observation.kind, observation.metadata),
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
        kind="references",
        target_key=target_key,
        metadata=_email_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_email_reference_observation(
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
        source_key = _email_reference_source_key(observation)
        target_key = _email_reference_target_key(observation, ordinal, diagnostics)
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
    edge_key = _upsert_css_edge(
        edges,
        source_key=source_key,
        kind="references",
        target_key=target_key,
        metadata=_email_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _email_definition_source_key(observation: RawObservation) -> str:
    if observation.kind == "email.mailbox":
        return file_key(observation.path)
    if observation.kind == "email.message":
        source_key = _metadata_text(observation.metadata, "source_key")
        if source_key is not None:
            parsed = parse_key(source_key)
            if parsed.namespace == "email.mailbox":
                return source_key
            raise GraphKeyError("email.message source_key must be email.mailbox")
        return file_key(observation.path)
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is None:
        raise GraphKeyError(f"{observation.kind} observation requires source_key")
    parsed = parse_key(source_key)
    if parsed.namespace == "email.message":
        return source_key
    raise GraphKeyError(f"{observation.kind} source_key must be email.message")

def _email_definition_target_key(observation: RawObservation) -> str:
    if observation.target is not None:
        parsed = parse_key(observation.target)
        if parsed.namespace in (
            "email.mailbox",
            "email.message",
            "email.part",
            "email.attachment_stub",
            "email.thread_hint",
        ):
            return observation.target
        raise GraphKeyError(f"{observation.kind} target has unsupported namespace")
    if observation.kind == "email.mailbox":
        return email_mailbox_key(observation.path)
    if observation.kind == "email.message":
        message_id_hash = _metadata_text(observation.metadata, "message_id_hash")
        identity_strength = _metadata_text(observation.metadata, "identity_strength")
        identity = f"{identity_strength or 'structural'}:{message_id_hash or observation.source_id}"
        return email_message_key(observation.path, identity)
    source_key = _email_definition_source_key(observation)
    pointer = (
        _metadata_text(observation.metadata, "part_path")
        or _metadata_text(observation.metadata, "thread_hint_kind")
        or observation.name
    )
    if not isinstance(pointer, str) or not pointer.strip():
        raise GraphKeyError(f"{observation.kind} observation requires pointer metadata")
    if observation.kind == "email.part":
        return email_part_key(source_key, pointer)
    if observation.kind == "email.attachment_stub":
        return email_attachment_stub_key(source_key, pointer)
    if observation.kind == "email.thread_hint":
        return email_thread_hint_key(source_key, pointer)
    raise GraphKeyError(f"unsupported email definition kind: {observation.kind}")

def _email_address_target_key(observation: RawObservation) -> str:
    if observation.target is not None:
        parsed = parse_key(observation.target)
        if parsed.namespace == "email.address":
            return observation.target
        raise GraphKeyError("email.address target must be email.address")
    address_hash = _metadata_text(observation.metadata, "address_hash")
    if address_hash is None:
        raise GraphKeyError("email.address observation requires address_hash")
    return email_address_key(f"addrhash:{address_hash}")

def _email_reference_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is None:
        raise GraphKeyError(f"{observation.kind} observation requires source_key")
    parsed = parse_key(source_key)
    if parsed.namespace in ("email.message", "email.part", "email.attachment_stub"):
        return source_key
    raise GraphKeyError(f"{observation.kind} source_key has unsupported namespace")

def _email_reference_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    target = observation.target or _metadata_text(observation.metadata, "target_key")
    if target is None:
        placeholder_key = unknown_key("email.reference", "missing-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="email.reference observation requires target",
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
        placeholder_key = unknown_key("email.reference", "malformed-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category=_graph_key_error_category(error),
                message=f"email.reference target is not a canonical key: {error}",
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

def _email_node_metadata(kind: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
    keys_by_kind = {
        "email.mailbox": (
            "format",
            "parser",
            "mailbox_message_count",
            "mailbox_message_count_limited",
            "mailbox_byte_count",
            "mailbox_parse_status",
            "mailbox_limit_reason",
            "mailbox_digest",
            "identity_strength",
        ),
        "email.message": (
            "format",
            "parser",
            "mailbox_file_key",
            "mbox_message_ordinal",
            "mbox_message_identity",
            "message_id_hash",
            "message_id_present",
            "message_id_valid",
            "date",
            "date_parse_status",
            "subject_present",
            "subject_hash",
            "subject_preview_redacted",
            "from_count",
            "to_count",
            "cc_count",
            "bcc_count",
            "reply_to_count",
            "sender_count",
            "return_path_count",
            "text_plain_part_count",
            "text_html_part_count",
            "attachment_count",
            "has_text_plain",
            "has_text_html",
            "has_attachments",
            "has_remote_references",
            "redacted",
            "redaction_reason",
            "identity_strength",
        ),
        "email.address": (
            "format",
            "parser",
            "address_role",
            "address_domain",
            "address_hash",
            "address_display_name_redacted",
            "redacted",
            "redaction_reason",
        ),
        "email.part": (
            "format",
            "parser",
            "mime_type",
            "content_type",
            "content_disposition",
            "charset",
            "transfer_encoding",
            "part_index",
            "part_path",
            "part_depth",
            "part_byte_count",
            "inline",
            "content_id_present",
            "redacted",
            "redaction_reason",
        ),
        "email.attachment_stub": (
            "format",
            "parser",
            "part_path",
            "content_disposition",
            "attachment_filename_redacted",
            "attachment_filename_hash",
            "attachment_mime_type",
            "attachment_byte_count",
            "inline",
            "content_id_present",
            "redacted",
            "redaction_reason",
        ),
        "email.thread_hint": (
            "format",
            "parser",
            "thread_hint_kind",
            "reference_kind",
            "referenced_message_id_hash",
            "not_fetched",
            "identity_strength",
        ),
    }
    summary: dict[str, Any] = {}
    for key in keys_by_kind.get(kind, ()):
        value = metadata.get(key)
        if value is not None:
            summary[key] = value
    return summary

def _email_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, target_key in (
        ("format", "formats"),
        ("mailbox_parse_status", "mailbox_parse_statuses"),
        ("mailbox_limit_reason", "mailbox_limit_reasons"),
        ("content_type", "content_types"),
        ("content_disposition", "content_dispositions"),
        ("part_path", "part_paths"),
        ("thread_hint_kind", "thread_hint_kinds"),
        ("identity_strength", "identity_strengths"),
    ):
        value = _metadata_text(metadata, source_key)
        if value:
            summary[target_key] = [value]
    return summary

def _email_reference_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, target_key in (
        ("format", "formats"),
        ("address_role", "address_roles"),
        ("address_domain", "address_domains"),
        ("reference_kind", "reference_kinds"),
        ("thread_hint_kind", "thread_hint_kinds"),
        ("raw_value_summary", "raw_value_summaries"),
        ("redaction_reason", "redaction_reasons"),
    ):
        value = _metadata_text(metadata, source_key)
        if value:
            summary[target_key] = [value]
    for source_key, target_key in (
        ("not_fetched", "not_fetched"),
        ("redacted", "redacted_observed"),
    ):
        value = metadata.get(source_key)
        if isinstance(value, bool):
            summary[target_key] = value
    return summary

def _email_display_name(canonical_key: str, observation: RawObservation) -> str:
    if observation.kind == "email.mailbox":
        count = observation.metadata.get("mailbox_message_count")
        if isinstance(count, int):
            return f"email mailbox ({count} messages)"
        return "email mailbox"
    for key in (
        "address_domain",
        "part_path",
        "attachment_filename_redacted",
        "thread_hint_kind",
    ):
        value = _metadata_text(observation.metadata, key)
        if value is not None:
            return value
    if observation.kind == "email.message":
        digest = _metadata_text(observation.metadata, "message_id_hash")
        if digest is not None:
            return f"email message {digest[:12]}"
        return "email message"
    if observation.name:
        return observation.name
    return _display_name_from_key(canonical_key)
