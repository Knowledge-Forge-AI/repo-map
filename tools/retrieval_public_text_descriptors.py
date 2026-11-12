"""Current accepted publication, capture, span correspondence and descriptor recomputation.

The caller injects the trusted publication readback adapter and fresh v1
representation/evidence/span readers. This module never imports test support
and never reaches into a pin's private adapter field.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from common_lore_index.artifacts._store_common import ArtifactIntegrityError
from common_lore_index.retrieval.projection_build import ProjectedFileRecord
from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy, ExclusionReason
from common_lore_index.retrieval.publication_binding import CorrespondenceRefusal, ProjectionInputs, check_correspondence
from common_lore_index.storage.semantic_candidates import digest_json
from retrieval_public_text_admission import AdmittedPair, admit_document_pair
from retrieval_public_text_capture import (
    ExcerptReadLedger, VerifiedRawObject, capture_projection, observed_inputs, read_verified_object,
)
from retrieval_public_text_contracts import (
    ADMISSION_POLICY_VERSION, AGGREGATE_BUDGET_EXCEEDED, ARTIFACT_INTEGRITY_REFUSED, DESCRIPTOR_CONSTRUCTION_REFUSED,
    DESCRIPTOR_SCHEMA, DESCRIPTOR_SET_CHANGED, DOCUMENT_CAP_EXCEEDED, MODEL_TEXT_VERSION, POLICY_DIGEST_MISMATCH,
    PRIVATE_MARKER_SCOPE_INVALID, PROJECTION_INPUTS_UNAVAILABLE, PROJECTION_RECORD_MISMATCH,
    PROJECTION_RECORD_MISSING, PROJECTION_SETUP_REFUSED, PROJECTION_TRUNCATED, PUBLICATION_MISMATCH,
    PUBLICATION_REVALIDATION_FAILED, REPRESENTATION_READBACK_REFUSED, REPRESENTATION_VERSION,
    SPAN_CORRESPONDENCE_REFUSED, SPAN_LINK_MISMATCH, PairExclusion, PrivateMarkerScope, PublicTextDescriptor,
    PublicTextRefusal, SpanRow, counter_mapping, maintained_reason, require_scope, validate_accepted_reference,
)
from retrieval_public_text_excerpt import encode_model_text, map_excerpt, model_text_input_digest
from retrieval_semantic_primitives import AcceptedEvidenceRecord
from retrieval_semantic_provenance import (
    AcceptedStoreReadback, VerifiedPublicationPin, verify_publication_provenance,
)
from retrieval_semantic_representation import RepresentationValidationReport

PREPARATION_SCHEMA = "cloe-public-text-preparation-v1"
MAX_DOCUMENTS = 500


def revalidate_publication_pin(pin: VerifiedPublicationPin) -> None:
    """Current-publication fence shared by preparation and census; failure is one closed refusal."""
    _revalidate(pin)


def _revalidate(pin: VerifiedPublicationPin) -> None:
    try:
        current = pin.revalidate_current()
    except Exception:
        raise PublicTextRefusal(PUBLICATION_REVALIDATION_FAILED) from None
    if current is not pin or not VerifiedPublicationPin.is_factory_issued(pin):
        raise PublicTextRefusal(PUBLICATION_REVALIDATION_FAILED)


def _capture_publication(
    pin: VerifiedPublicationPin, adapter: Callable[[], AcceptedStoreReadback], policy: BodyProjectionPolicy,
) -> ProjectionInputs:
    """Invoke the injected adapter once and bind that exact snapshot to the original pin."""
    if not callable(adapter):
        raise PublicTextRefusal(PUBLICATION_MISMATCH)
    try:
        captured = adapter()
    except Exception:
        raise PublicTextRefusal(PUBLICATION_MISMATCH) from None
    if not isinstance(captured, AcceptedStoreReadback):
        raise PublicTextRefusal(PUBLICATION_MISMATCH)
    try:  # bounded trusted reconstruction over the adapter's snapshot; any failure is the closed mismatch
        verified = verify_publication_provenance(
            graph_id=captured.graph_id, repository_identity=captured.repository_identity,
            backend=captured.backend, accepted_publication=captured.accepted_publication,
            receipt=captured.receipt, policy=policy, readback_adapter=lambda: captured,
        )
    except Exception:
        raise PublicTextRefusal(PUBLICATION_MISMATCH) from None
    if verified.to_dict() != pin.to_dict():
        raise PublicTextRefusal(PUBLICATION_MISMATCH)
    if captured.projection_inputs is None:
        raise PublicTextRefusal(PROJECTION_INPUTS_UNAVAILABLE)
    return captured.projection_inputs


def _reference_matches_pin(reference: Mapping[str, Any], pin: VerifiedPublicationPin) -> bool:
    return (
        reference["graph_id"] == pin.graph_id and reference["repository_id"] == pin.repository_identity
        and reference["backend"] == pin.backend and reference["run_id"] == pin.run_id
        and reference["accepted_generation"] == pin.generation
        and reference["publication_bundle_id"] == pin.publication_bundle_id
        and reference["job_id"] == str(pin.receipt.attempt.job_id)
        and reference["attempt"] == int(pin.receipt.attempt.attempt)
        and reference["snapshot_manifest_id"] == pin.snapshot_manifest_id
        and reference["extraction_receipt_id"] == pin.extraction_receipt_id
    )


def check_span_correspondence(
    evidence: Sequence[AcceptedEvidenceRecord], rows: Sequence[SpanRow],
) -> tuple[SpanRow, ...]:
    """Companion rows must equal the fresh v1 evidence row-key set with equal path/metadata."""
    v1: dict[tuple[str, str, str, int, int], AcceptedEvidenceRecord] = {}
    for record in evidence:
        if type(record) is not AcceptedEvidenceRecord:
            raise PublicTextRefusal(SPAN_CORRESPONDENCE_REFUSED)
        key = (record.canonical_key, record.evidence_key, record.link_kind, record.run_id, record.graph_key_version)
        if key in v1:
            raise PublicTextRefusal(SPAN_CORRESPONDENCE_REFUSED)
        v1[key] = record
    companion: dict[tuple[str, str, str, int, int], SpanRow] = {}
    for row in rows:
        if type(row) is not SpanRow or type(row.run_id) is not int or type(row.graph_key_version) is not int:
            raise PublicTextRefusal(SPAN_CORRESPONDENCE_REFUSED)
        if row.row_key in companion:
            raise PublicTextRefusal(SPAN_CORRESPONDENCE_REFUSED)
        companion[row.row_key] = row
    if set(v1) != set(companion):
        raise PublicTextRefusal(SPAN_CORRESPONDENCE_REFUSED)
    for key, record in v1.items():
        row = companion[key]
        if row.path != record.path or row.metadata_json != record.metadata_json:
            raise PublicTextRefusal(SPAN_CORRESPONDENCE_REFUSED)
    return tuple(rows)


def _read(reader: Callable[[], Any], code: str) -> Any:
    if not callable(reader):
        raise PublicTextRefusal(code)
    try:
        return reader()
    except Exception:
        raise PublicTextRefusal(code) from None


@dataclass(frozen=True)
class PublicTextDocument:
    descriptor: PublicTextDescriptor
    _model_text: str = field(repr=False, compare=False)

    @property
    def model_text(self) -> str:
        return self._model_text

    @property
    def identity(self) -> str:
        return self.descriptor.identity


@dataclass(frozen=True)
class PublicTextPreparation:
    """One prepared pass; public serialization carries no raw text, marker or private path."""

    graph_id: str
    backend: str
    run_id: int
    generation: int
    privacy_scope_id: str
    publication_identity: str
    accepted_reference: Mapping[str, Any]
    documents: tuple[PublicTextDocument, ...]
    exclusions: tuple[PairExclusion, ...]
    v1_verified_pair_count: int
    projection_invoked: bool
    measurements: Mapping[str, Any]
    _scope: PrivateMarkerScope = field(repr=False, compare=False)

    def comparable_state(self) -> dict[str, Any]:
        return {
            "publication_identity": self.publication_identity, "accepted_reference": dict(self.accepted_reference),
            "descriptor_identities": [doc.identity for doc in self.documents],
            "exclusions": [item.to_dict() for item in self.exclusions],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PREPARATION_SCHEMA, "admission_policy_version": ADMISSION_POLICY_VERSION,
            "descriptor_schema": DESCRIPTOR_SCHEMA, "model_text_version": MODEL_TEXT_VERSION,
            "representation_version": REPRESENTATION_VERSION, "graph_id": self.graph_id, "backend": self.backend,
            "run_id": self.run_id, "generation": self.generation, "privacy_scope_id": self.privacy_scope_id,
            **self.comparable_state(),
            "descriptors": [doc.descriptor.to_dict() for doc in self.documents],
            "exclusion_counts": counter_mapping([item.reason for item in self.exclusions]),
            "v1_verified_pair_count": self.v1_verified_pair_count, "document_count": len(self.documents),
            "projection_invoked": self.projection_invoked, "measurements": dict(self.measurements),
        }


def _membership(
    pair: AdmittedPair, projection: Any, reference: Mapping[str, Any],
) -> tuple[ProjectedFileRecord | None, str | None]:
    key = (pair.entry.binding_id, pair.source_relative_path)
    record = next((f for f in projection.projected_files if (f.binding_id, f.source_relative_path) == key), None)
    if record is None:
        excluded = next((f for f in projection.excluded_files if (f.binding_id, f.source_relative_path) == key), None)
        if excluded is None:
            return None, PROJECTION_RECORD_MISSING
        if excluded.reason is ExclusionReason.AGGREGATE_BUDGET_EXCEEDED:
            raise PublicTextRefusal(AGGREGATE_BUDGET_EXCEEDED)
        return None, maintained_reason("public_text_projection_excluded", excluded.reason)
    if record.truncated is not False:
        return None, PROJECTION_TRUNCATED
    if (
        record.accepted_reference.to_dict() != dict(reference)
        or record.original_content_digest != pair.entry.reference.content_digest
        or record.original_size_bytes != pair.entry.reference.size_bytes
    ):
        return None, PROJECTION_RECORD_MISMATCH
    row = pair.row
    linked = any(
        link.canonical_node_key == pair.representation.canonical_key and link.evidence_key == row.evidence_key
        and link.link_kind == row.link_kind and link.binding_id == pair.entry.binding_id
        and link.source_relative_path == pair.source_relative_path
        and type(link.start_line) is int and link.start_line == row.start_line
        and type(link.end_line) is int and link.end_line == row.end_line
        for link in record.evidence_links
    )
    return (record, None) if linked else (None, SPAN_LINK_MISMATCH)


def _document(
    pair: AdmittedPair, record: ProjectedFileRecord, raw: VerifiedRawObject, pin: VerifiedPublicationPin,
    reference: Mapping[str, Any], scope: PrivateMarkerScope, ledger: ExcerptReadLedger,
) -> PublicTextDocument | str:
    rep, row = pair.representation, pair.row
    span, reason = map_excerpt(
        raw.raw, row.start_line, row.end_line, projected_raw_line_count=record.raw_line_count,
        private_markers=scope.markers,
    )
    if span is None:
        return reason or ARTIFACT_INTEGRITY_REFUSED
    try:
        text = encode_model_text(
            rep.canonical_key, rep.kind, rep.display_name, pair.source_relative_path, span.excerpt,
            private_markers=scope.markers,
        )
    except PublicTextRefusal as error:
        return error.code
    try:
        descriptor = _descriptor(pair, reference, pin, scope, span, text)
    except PublicTextRefusal:
        raise
    except (ValueError, TypeError) as error:
        raise PublicTextRefusal(DESCRIPTOR_CONSTRUCTION_REFUSED) from error
    ledger.selected_excerpt_bytes += span.excerpt_bytes
    return PublicTextDocument(descriptor, text)


def _descriptor(
    pair: AdmittedPair, reference: Mapping[str, Any], pin: VerifiedPublicationPin, scope: PrivateMarkerScope,
    span: Any, text: str,
) -> PublicTextDescriptor:
    """B6: strict construction; ValueError/TypeError become one closed whole-preparation refusal."""
    rep, row, entry = pair.representation, pair.row, pair.entry
    return PublicTextDescriptor({
        "schema": DESCRIPTOR_SCHEMA, "representation_version": REPRESENTATION_VERSION,
        "model_text_version": MODEL_TEXT_VERSION, "admission_policy_version": ADMISSION_POLICY_VERSION,
        "graph_id": pin.graph_id, "repository_identity": pin.repository_identity, "backend": pin.backend,
        "run_id": pin.run_id, "generation": pin.generation, "receipt_identity": pin.receipt_identity,
        "policy_digest": pin.policy_digest, "privacy_scope_id": scope.scope_id, "accepted_reference": dict(reference),
        "publication_bundle_id": pin.publication_bundle_id, "snapshot_manifest_id": pin.snapshot_manifest_id,
        "extraction_receipt_id": pin.extraction_receipt_id, "candidate_id": pin.graph_candidate_id,
        "source_binding_id": rep.source_binding_id, "binding_revision": rep.binding_revision,
        "snapshot_id": rep.snapshot_id, "canonical_key": rep.canonical_key, "kind": rep.kind,
        "display_name": rep.display_name, "v1_input_digest": rep.input_digest, "evidence_key": row.evidence_key,
        "source_relative_path": pair.source_relative_path, "start_line": row.start_line, "end_line": row.end_line,
        "artifact_content_digest": entry.reference.content_digest, "artifact_size_bytes": entry.reference.size_bytes,
        "artifact_privacy": entry.reference.privacy.value, **span.public_fields(),
        "model_text_bytes": len(text.encode("utf-8")), "input_digest": model_text_input_digest(text),
    })


def prepare_public_text_generation(
    *,
    publication_pin: VerifiedPublicationPin,
    readback_adapter: Callable[[], AcceptedStoreReadback],
    policy: BodyProjectionPolicy,
    scope: PrivateMarkerScope,
    read_representations: Callable[[], RepresentationValidationReport],
    read_v1_evidence: Callable[[], Sequence[AcceptedEvidenceRecord]],
    read_span_rows: Callable[[], Sequence[SpanRow]],
) -> PublicTextPreparation:
    """Prepare one complete public-text pass from current accepted state; refusals are whole-pass."""
    scope = require_scope(scope)
    pin = publication_pin
    if type(pin) is not VerifiedPublicationPin or not VerifiedPublicationPin.is_factory_issued(pin):
        raise PublicTextRefusal(PUBLICATION_MISMATCH)
    _revalidate(pin)
    inputs = _capture_publication(pin, readback_adapter, policy)
    _revalidate(pin)
    corr_inputs, corr_observer = observed_inputs(inputs, "correspondence")
    try:
        accepted = check_correspondence(corr_inputs)
        reference = validate_accepted_reference(accepted.to_dict())
    except (CorrespondenceRefusal, ArtifactIntegrityError, ValueError, OSError) as error:
        raise PublicTextRefusal(PROJECTION_SETUP_REFUSED) from error
    _revalidate(pin)
    if policy.policy_digest() != pin.policy_digest:
        raise PublicTextRefusal(POLICY_DIGEST_MISMATCH)
    if not _reference_matches_pin(reference, pin):
        raise PublicTextRefusal(PUBLICATION_MISMATCH)
    report = _read(read_representations, REPRESENTATION_READBACK_REFUSED)
    if type(report) is not RepresentationValidationReport or report.status != "ok":
        raise PublicTextRefusal(REPRESENTATION_READBACK_REFUSED)
    if report.provenance.to_dict() != pin.to_dict():
        raise PublicTextRefusal(PUBLICATION_MISMATCH)
    _revalidate(pin)
    # Iterators are consumed inside the closed wrapper, so a generator failure cannot escape (F1-F2).
    evidence = _read(lambda: tuple(read_v1_evidence()), SPAN_CORRESPONDENCE_REFUSED)
    rows = check_span_correspondence(evidence, _read(lambda: tuple(read_span_rows()), SPAN_CORRESPONDENCE_REFUSED))
    _revalidate(pin)
    rows_by_node: dict[str, list[SpanRow]] = {}
    for row in rows:
        rows_by_node.setdefault(row.canonical_key, []).append(row)
    bindings = {binding.binding_id: binding for binding in inputs.manifest.bindings}
    entries = {(entry.binding_id, entry.source_relative_path): entry for entry in inputs.manifest.entries}
    admitted: list[AdmittedPair] = []
    exclusions: list[PairExclusion] = []
    for rep in report.verified_entries:
        outcome = admit_document_pair(
            rep, policy=policy, bindings_by_id=bindings, entries_by_key=entries,
            rows=rows_by_node.get(rep.canonical_key, ()), run_id=pin.run_id, private_markers=scope.markers,
        )
        if isinstance(outcome, AdmittedPair):
            admitted.append(outcome)
        else:
            exclusions.append(outcome)
    measurements: dict[str, Any] = {
        "correspondence": corr_observer.counters(),
        "provenance_verification_reads": "unmeasured", "excerpt_reads": None, "projection": None,
    }
    documents: list[PublicTextDocument] = []
    if admitted:
        documents = _capture_documents(admitted, exclusions, inputs, policy, pin, reference, scope, measurements)
    if len(documents) > MAX_DOCUMENTS:
        raise PublicTextRefusal(DOCUMENT_CAP_EXCEEDED)
    _revalidate(pin)
    ordered = sorted(exclusions, key=lambda item: (item.canonical_key.encode("utf-8"), item.source_binding_id.encode("utf-8")))
    return PublicTextPreparation(
        pin.graph_id, pin.backend, pin.run_id, pin.generation, scope.scope_id, str(digest_json(pin.to_dict())),
        dict(reference), tuple(documents), tuple(ordered), len(report.verified_entries), bool(admitted),
        measurements, scope,
    )


def _capture_documents(
    admitted: Sequence[AdmittedPair], exclusions: list[PairExclusion], inputs: ProjectionInputs,
    policy: BodyProjectionPolicy, pin: VerifiedPublicationPin, reference: Mapping[str, Any],
    scope: PrivateMarkerScope, measurements: dict[str, Any],
) -> list[PublicTextDocument]:
    capture = capture_projection(inputs, policy)
    _revalidate(pin)
    if capture.projection.accepted_reference.to_dict() != dict(reference):
        raise PublicTextRefusal(PUBLICATION_MISMATCH)
    groups: dict[str, list[tuple[AdmittedPair, ProjectedFileRecord]]] = {}
    for pair in admitted:
        record, reason = _membership(pair, capture.projection, reference)
        if record is None:
            exclusions.append(PairExclusion(pair.representation.canonical_key, pair.entry.binding_id, reason or PROJECTION_RECORD_MISSING))
            continue
        groups.setdefault(pair.entry.reference.content_digest, []).append((pair, record))
    _wrapped, observer = observed_inputs(inputs, "excerpt_reads")
    ledger = ExcerptReadLedger()
    documents: list[PublicTextDocument] = []
    for group in groups.values():
        _revalidate(pin)
        raw = read_verified_object(observer, group[0][0].entry, policy, ledger)
        _revalidate(pin)
        for pair, record in group:
            outcome: PublicTextDocument | str = (
                ARTIFACT_INTEGRITY_REFUSED if raw is None
                else _document(pair, record, raw, pin, reference, scope, ledger)
            )
            if isinstance(outcome, PublicTextDocument):
                documents.append(outcome)
            else:
                exclusions.append(PairExclusion(pair.representation.canonical_key, pair.entry.binding_id, outcome))
        del raw
    _revalidate(pin)
    measurements.update({
        "projection": capture.counters, "projection_authorized_openable_entries": capture.authorized_openable_entries,
        "projection_aggregate_input_bytes_read": capture.projection.aggregate_input_bytes_read,
        "excerpt_reads": observer.counters(), "excerpt_ledger": ledger.to_dict(),
    })
    return documents


def require_unchanged_recomputation(
    before: PublicTextPreparation, after: PublicTextPreparation, *, scope: PrivateMarkerScope,
) -> None:
    """Fresh recomputation must use the same frozen scope and reproduce every descriptor and exclusion."""
    scope = require_scope(scope)
    for prepared in (before, after):
        if (
            type(prepared) is not PublicTextPreparation or prepared._scope is not scope
            or prepared.privacy_scope_id != scope.scope_id
        ):
            raise PublicTextRefusal(PRIVATE_MARKER_SCOPE_INVALID)
    if before.comparable_state() != after.comparable_state():
        raise PublicTextRefusal(DESCRIPTOR_SET_CHANGED)
