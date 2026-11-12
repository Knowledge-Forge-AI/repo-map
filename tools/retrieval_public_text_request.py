"""One unchanged-schema dual-arm generation request (study section 4).

Four ordered partitions share one combined request: ``v1.document``,
``ptx.document``, ``v1.query`` and ``ptx.query``. v1 records keep their
original text and mode byte-for-byte under ``v1.<original id>``. Public-text
documents are ``ptx.d.NNNN`` in preparation order; public-text queries are
``ptx.q.<task_id>`` for census-admitted tasks and reuse the v1 query text.
Generation 2 is document-only. Every cap applies to the combined request and a
breach refuses; nothing is split, filtered or hidden. The generic request
schema, worker, kernel and source closure are unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from common_lore_index.storage.semantic_candidates import digest_json
from retrieval_public_text_census import PublicTextCensus, retained_task_sha256, task_sha256
from retrieval_public_text_contracts import (
    ADMISSION_POLICY_VERSION, DESCRIPTOR_SCHEMA, MODEL_TEXT_VERSION, REPRESENTATION_VERSION, counter_mapping,
)
from retrieval_public_text_descriptors import PublicTextPreparation
from retrieval_public_text_tasks import SelectedTaskSet
from retrieval_semantic_generator_inputs import PublicGenerationInput
from retrieval_semantic_generator_inputs import _digest as v1_utf8_digest  # original v1 scheme, unchanged
from retrieval_semantic_generator_kernel import SemanticMode, SemanticText
from retrieval_semantic_generator_kernel_contracts import (
    MAX_BATCH_SIZE, MAX_RECORD_ID_BYTES, MAX_RECORD_TEXT_BYTES, MAX_TOTAL_TEXT_BYTES,
)
from retrieval_semantic_generator_worker_contracts import (
    ATTEMPT_ID_PATTERN, MAX_REQUEST_BYTES, REQUEST_SCHEMA, SHA256_PATTERN, WorkerRequestError,
)
from retrieval_semantic_generator_worker_protocol import parse_worker_request
from retrieval_semantic_primitives import CANONICAL_NODE_REPRESENTATION_VERSION
from retrieval_semantic_provenance import VerifiedPublicationPin

DUAL_ARM_INPUT_SCHEMA = "cloe-public-text-dual-arm-input-v1"
STUDY_PHASE = "REPOMAP-CLOE-PUBLIC-TEXT1"
ARM_V1, ARM_PTX = CANONICAL_NODE_REPRESENTATION_VERSION, REPRESENTATION_VERSION
PARTITIONS = ("v1.document", "ptx.document", "v1.query", "ptx.query")

REQUEST_INPUT_INVALID = "request_input_invalid"
REQUEST_CURRENT_MISMATCH = "request_current_mismatch"
REQUEST_CORRESPONDENCE_MISMATCH = "request_correspondence_mismatch"
REQUEST_CAP_EXCEEDED = "request_cap_exceeded"
REQUEST_WORKER_REFUSED = "request_worker_validation_refused"
REQUEST_ROUNDTRIP_MISMATCH = "request_roundtrip_mismatch"
REQUEST_CODES = frozenset({
    REQUEST_INPUT_INVALID, REQUEST_CURRENT_MISMATCH, REQUEST_CORRESPONDENCE_MISMATCH, REQUEST_CAP_EXCEEDED,
    REQUEST_WORKER_REFUSED, REQUEST_ROUNDTRIP_MISMATCH,
})
_V1_QUERY_PREFIX = "query:"


class DualArmRequestRefusal(ValueError):
    """Closed refusal before any reservation; the message is the code only."""

    def __init__(self, code: str) -> None:
        if code not in REQUEST_CODES:
            raise ValueError("unknown dual-arm request code")
        super().__init__(code)
        self.code = code


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise DualArmRequestRefusal(code)


@dataclass(frozen=True)
class DualArmRecord:
    """Public layout row; it carries no text."""

    record_id: str
    arm: str
    mode: SemanticMode
    partition: str
    source_identity: str  # v1 doc: v1 input_digest; ptx doc: descriptor identity; query: retained_task_sha256
    v1_record_id: str | None
    task_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id, "arm": self.arm, "mode": self.mode.value, "partition": self.partition,
            "source_identity": self.source_identity, "v1_record_id": self.v1_record_id, "task_id": self.task_id,
        }


@dataclass(frozen=True)
class DualArmInput:
    """Frozen combined request input; texts and owner objects are private (repr=False)."""

    generation: int
    attempt_id: str
    study_identity: str
    v1: PublicGenerationInput = field(repr=False)
    preparation: PublicTextPreparation = field(repr=False)
    census: PublicTextCensus = field(repr=False)
    tasks: SelectedTaskSet = field(repr=False)
    pin: VerifiedPublicationPin = field(repr=False)
    records: tuple[SemanticText, ...] = field(repr=False)
    layout: tuple[DualArmRecord, ...]
    input_identity: str
    representation_report_identity: str
    publication_identity: str
    artifact_profile_identity: str
    _manifest: Mapping[str, Any] = field(repr=False, compare=False)

    def manifest(self) -> dict[str, Any]:
        """Public identity manifest (a fresh copy); it contains text digests, never text."""
        return dict(json.loads(json.dumps(self._manifest)))


def _text_sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def plan_records(
    *,
    generation: int,
    v1_records: Sequence[SemanticText],
    v1_document_sources: Mapping[str, str],
    ptx_documents: Sequence[tuple[str, str]],
    ptx_query_task_ids: Sequence[str],
    task_sources: Mapping[str, str],
) -> tuple[tuple[SemanticText, ...], tuple[DualArmRecord, ...]]:
    """Pure partition planner over (identity, text) inputs; ordering and correspondence only."""
    planned: dict[str, list[tuple[SemanticText, DualArmRecord]]] = {name: [] for name in PARTITIONS}
    v1_query_texts: dict[str, str] = {}
    for record in v1_records:
        try:
            mode = SemanticMode(record.mode)
        except ValueError as error:
            raise DualArmRequestRefusal(REQUEST_CORRESPONDENCE_MISMATCH) from error
        task_id = None
        if mode is SemanticMode.DOCUMENT:
            source = v1_document_sources.get(record.record_id)
        else:
            _require(record.record_id.startswith(_V1_QUERY_PREFIX), REQUEST_CORRESPONDENCE_MISMATCH)
            task_id = record.record_id[len(_V1_QUERY_PREFIX):]
            source = task_sources.get(task_id)
            v1_query_texts[task_id] = record.text
        _require(type(source) is str, REQUEST_CORRESPONDENCE_MISMATCH)
        assert isinstance(source, str)
        partition = "v1.document" if mode is SemanticMode.DOCUMENT else "v1.query"
        study_id = "v1." + record.record_id
        planned[partition].append((SemanticText(study_id, record.text, mode),
                                   DualArmRecord(study_id, ARM_V1, mode, partition, source, record.record_id, task_id)))
    _require(generation != 2 or not (v1_query_texts or ptx_query_task_ids), REQUEST_CORRESPONDENCE_MISMATCH)
    for ordinal, (identity, text) in enumerate(ptx_documents, start=1):
        study_id = f"ptx.d.{ordinal:04d}"
        planned["ptx.document"].append((SemanticText(study_id, text, SemanticMode.DOCUMENT), DualArmRecord(
            study_id, ARM_PTX, SemanticMode.DOCUMENT, "ptx.document", identity, None, None)))
    for task_id in ptx_query_task_ids:
        query_text, source = v1_query_texts.get(task_id), task_sources.get(task_id)
        _require(type(query_text) is str and type(source) is str, REQUEST_CORRESPONDENCE_MISMATCH)
        assert isinstance(query_text, str) and isinstance(source, str)
        study_id = "ptx.q." + task_id
        planned["ptx.query"].append((SemanticText(study_id, query_text, SemanticMode.QUERY), DualArmRecord(
            study_id, ARM_PTX, SemanticMode.QUERY, "ptx.query", source, None, task_id)))
    ordered = [item for name in PARTITIONS for item in planned[name]]
    return tuple(item[0] for item in ordered), tuple(item[1] for item in ordered)


def check_request_caps(records: Sequence[SemanticText], *, request_bytes: int) -> None:
    """The combined request stays within every existing worker and kernel ceiling."""
    _require(1 <= len(records) <= MAX_BATCH_SIZE, REQUEST_CAP_EXCEEDED)
    total = 0
    for record in records:
        try:
            id_bytes, text_bytes = len(record.record_id.encode("utf-8")), len(record.text.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise DualArmRequestRefusal(REQUEST_INPUT_INVALID) from error
        _require(id_bytes <= MAX_RECORD_ID_BYTES and text_bytes <= MAX_RECORD_TEXT_BYTES, REQUEST_CAP_EXCEEDED)
        total += text_bytes
    _require(total <= MAX_TOTAL_TEXT_BYTES, REQUEST_CAP_EXCEEDED)
    _require(type(request_bytes) is int and 0 < request_bytes <= MAX_REQUEST_BYTES, REQUEST_CAP_EXCEEDED)


def encode_dual_arm_request(value: DualArmInput) -> bytes:
    """Canonical request bytes, cap-checked and round-tripped through the unchanged worker parser."""
    request = {
        "schema": REQUEST_SCHEMA, "attempt_id": value.attempt_id, "input_identity": value.input_identity,
        "representation_report_identity": value.representation_report_identity,
        "publication_identity": value.publication_identity,
        "artifact_profile_identity": value.artifact_profile_identity,
        "records": [{"record_id": r.record_id, "text": r.text, "mode": SemanticMode(r.mode).value}
                    for r in value.records],
    }
    raw = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    check_request_caps(value.records, request_bytes=len(raw))
    try:
        _parsed, records = parse_worker_request(raw)
    except WorkerRequestError as error:
        raise DualArmRequestRefusal(REQUEST_WORKER_REFUSED) from error
    _require(records == value.records, REQUEST_ROUNDTRIP_MISMATCH)
    return raw


def _is_digest(value: object) -> bool:
    return type(value) is str and SHA256_PATTERN.fullmatch(value) is not None


def _require_inputs(generation: object, attempt_id: object, study_identity: object, profile: object, v1: object,
                    preparation: object, census: object, tasks: object, pin: object) -> None:
    _require(
        type(generation) is int and generation in (1, 2) and type(attempt_id) is str
        and ATTEMPT_ID_PATTERN.fullmatch(attempt_id) is not None and _is_digest(study_identity) and _is_digest(profile)
        and type(v1) is PublicGenerationInput and type(preparation) is PublicTextPreparation
        and type(census) is PublicTextCensus and type(tasks) is SelectedTaskSet
        and type(pin) is VerifiedPublicationPin and VerifiedPublicationPin.is_factory_issued(pin),
        REQUEST_INPUT_INVALID,
    )


def _require_current(v1: PublicGenerationInput, pin: VerifiedPublicationPin) -> None:
    try:
        current = pin.revalidate_current()
        v1.require_current()
    except Exception:
        raise DualArmRequestRefusal(REQUEST_CURRENT_MISMATCH) from None
    _require(current is pin, REQUEST_CURRENT_MISMATCH)


def _require_correspondence(generation: int, v1: PublicGenerationInput, preparation: PublicTextPreparation,
                            census: PublicTextCensus, tasks: SelectedTaskSet, pin: VerifiedPublicationPin) -> None:
    pin_identity = str(digest_json(pin.to_dict()))
    expected_tasks = [(task.task_id, task_sha256(task)) for task in tasks.for_generation(generation)]
    v1_pairs = {(d.representation.canonical_key, d.representation.source_binding_id): d.representation.input_digest
                for d in v1.documents}
    _require(
        pin.generation == generation and v1.provenance.to_dict() == pin.to_dict()
        and preparation.publication_identity == pin_identity == census.publication_identity
        and (preparation.graph_id, preparation.backend, preparation.run_id, preparation.generation)
        == (pin.graph_id, pin.backend, pin.run_id, pin.generation)
        and (census.graph_id, census.backend, census.generation) == (pin.graph_id, pin.backend, pin.generation)
        and census.status in {"ready", "document_only", "no_documents"}
        and census.privacy_scope_id == preparation.privacy_scope_id
        and census.document_count == len(preparation.documents)
        and census.v1_verified_pair_count == preparation.v1_verified_pair_count == len(v1.documents)
        and dict(census.exclusion_counts) == counter_mapping([item.reason for item in preparation.exclusions])
        and [(row.task_id, row.task_sha256) for row in census.tasks] == expected_tasks
        and [(d.task_id, d.task_sha256) for d in v1.query_decisions] == expected_tasks
        and [row.v1_learned_state for row in census.tasks] == [d.state for d in v1.query_decisions]
        and tasks.retained_digests(generation) == {
            task.task_id: retained_task_sha256(task) for task in tasks.for_generation(generation)}
        and [(row.task_id, row.retained_task_sha256) for row in census.tasks]
        == list(tasks.retained_digests(generation).items())
        and all(
            v1_pairs.get((doc.descriptor["canonical_key"], doc.descriptor["source_binding_id"]))
            == doc.descriptor["v1_input_digest"] for doc in preparation.documents
        ),
        REQUEST_CORRESPONDENCE_MISMATCH,
    )


def _manifest(value_fields: Mapping[str, Any], records: Sequence[SemanticText],
              layout: Sequence[DualArmRecord]) -> dict[str, Any]:
    v1, preparation, census = value_fields["v1"], value_fields["preparation"], value_fields["census"]
    tasks, pin = value_fields["tasks"], value_fields["pin"]
    return {
        "schema": DUAL_ARM_INPUT_SCHEMA, "phase": STUDY_PHASE, "request_schema": REQUEST_SCHEMA,
        "generation": value_fields["generation"], "study_identity": value_fields["study_identity"],
        "v1": {"input_identity": v1.input_identity, "representation_report_identity": v1.representation_report_identity},
        "preparation_identity": str(digest_json(preparation.to_dict())),
        "census_identity": census.to_dict()["census_identity"], "privacy_scope_id": preparation.privacy_scope_id,
        "task_pins_identity": tasks.pins.identity(), "selected_task_set_identity": tasks.identity(),
        "task_digest_schemes": {"retained": "canonical-json-ascii-v1", "v1_query": "canonical-json-utf8-v1"},
        "v1_query_task_digests": [[d.task_id, d.task_sha256] for d in v1.query_decisions],
        "catalog_identities": {
            "catalog_file_sha256": tasks.pins.catalog_file_sha256,
            "historical_semantic_catalog_identity": tasks.pins.historical_semantic_catalog_identity,
            "original_manifest_sha256": tasks.pins.original_manifest_sha256,
        },
        "publication_pin_identity": str(digest_json(pin.to_dict())),
        # F3: the study scheme (ASCII canonical) and the original v1 worker-request scheme (UTF-8) are distinct.
        "publication_identity_schemes": {"study": "canonical-json-ascii-v1", "v1_worker_request": "canonical-json-utf8-v1"},
        "v1_publication_identity": v1_utf8_digest(v1.provenance.to_dict()),
        "partitions": {name: sum(1 for row in layout if row.partition == name) for name in PARTITIONS},
        "versions": {
            "v1": ARM_V1, "public_text": ARM_PTX, "descriptor_schema": DESCRIPTOR_SCHEMA,
            "model_text_version": MODEL_TEXT_VERSION, "admission_policy_version": ADMISSION_POLICY_VERSION,
        },
        "records": [[row.record_id, row.arm, row.mode.value, _text_sha256(record.text), row.source_identity]
                    for record, row in zip(records, layout, strict=True)],
    }


def build_dual_arm_input(
    *,
    generation: int,
    attempt_id: str,
    study_identity: str,
    v1_input: PublicGenerationInput,
    preparation: PublicTextPreparation,
    census: PublicTextCensus,
    tasks: SelectedTaskSet,
    publication_pin: VerifiedPublicationPin,
    artifact_profile_identity: str,
) -> DualArmInput:
    """Validate, revalidate and bind every owner, then plan, cap-check and round-trip the request."""
    pin = publication_pin
    _require_inputs(generation, attempt_id, study_identity, artifact_profile_identity, v1_input, preparation,
                    census, tasks, pin)
    _require_current(v1_input, pin)
    _require_correspondence(generation, v1_input, preparation, census, tasks, pin)
    records, layout = plan_records(
        generation=generation, v1_records=v1_input.records,
        v1_document_sources={d.record_id: d.representation.input_digest for d in v1_input.documents},
        ptx_documents=tuple((doc.identity, doc.model_text) for doc in preparation.documents),
        ptx_query_task_ids=tuple(row.task_id for row in census.tasks if row.public_text_state == "admitted"),
        task_sources=tasks.retained_digests(generation),
    )
    fields = {"generation": generation, "study_identity": study_identity, "v1": v1_input,
              "preparation": preparation, "census": census, "tasks": tasks, "pin": pin}
    manifest = _manifest(fields, records, layout)
    value = DualArmInput(
        generation, attempt_id, study_identity, v1_input, preparation, census, tasks, pin, records, layout,
        str(digest_json(manifest)),
        str(digest_json({"v1": v1_input.representation_report_identity,
                         "public_text": manifest["preparation_identity"]})),
        preparation.publication_identity, artifact_profile_identity, manifest,
    )
    encode_dual_arm_request(value)
    return value
