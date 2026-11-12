"""Closed public-text descriptor, reason, decision and private-scope contracts.

Public objects carry only hashes, offsets, counts, accepted metadata and closed
reasons. Private marker values, their digest, raw bytes and model text never
appear in a public serializer or repr.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import re
import secrets
from types import MappingProxyType
from typing import Any
import unicodedata

from common_lore_index.retrieval.projection_policy import ExclusionReason
from common_lore_index.storage.semantic_candidates import digest_json
from retrieval_public_text_privacy import is_safe_public_metadata

DESCRIPTOR_SCHEMA = "cloe-public-text-descriptor-v1"
REPRESENTATION_VERSION = "canonical-node-public-text-v2"
MODEL_TEXT_VERSION = "cloe-public-text-model-text-v1"
ADMISSION_POLICY_VERSION = "cloe-public-text-admission-v1"
BODY_PRECHECK_LAYER = "public_text_body_precheck"
MAX_EXCERPT_BYTES = 4096

SPAN_INVALID = "public_text_span_invalid"
SPAN_REVERSED = "public_text_span_reversed"
SPAN_OUT_OF_FILE = "public_text_span_out_of_file"
SPAN_LINK_MISMATCH = "public_text_span_link_mismatch"
SELECTED_EVIDENCE_MISSING = "public_text_selected_evidence_missing"
BINDING_POLICY_MISSING = "public_text_binding_policy_missing"
ARTIFACT_NOT_IN_MANIFEST = "public_text_artifact_not_in_manifest"
METADATA_PRIVACY_REFUSED = "public_text_metadata_privacy_refused"
EXCERPT_INVALID_UTF8 = "public_text_excerpt_invalid_utf8"
EXCERPT_BLANK = "public_text_excerpt_blank"
EXCERPT_PRIVACY_REFUSED = "public_text_excerpt_privacy_refused"
# Conservative coverage exclusion (study section 14 item 3); not a claim that a secret exists.
EXCERPT_CREDENTIAL_SHAPE_EXCLUDED = "public_text_excerpt_credential_shape_excluded"
LINE_CONVENTION_MISMATCH = "public_text_line_convention_mismatch"
PROJECTION_TRUNCATED = "public_text_projection_truncated"
PROJECTION_RECORD_MISSING = "public_text_projection_record_missing"
PROJECTION_RECORD_MISMATCH = "public_text_projection_record_mismatch"
ARTIFACT_INTEGRITY_REFUSED = "public_text_artifact_integrity_refused"
# Whole-preparation refusals.
PRIVATE_MARKER_SCOPE_INVALID = "public_text_private_marker_scope_invalid"
PROJECTION_POLICY_INCOMPATIBLE = "public_text_projection_policy_incompatible"
PROJECTION_SETUP_REFUSED = "public_text_projection_setup_refused"
PROJECTION_INPUTS_UNAVAILABLE = "public_text_projection_inputs_unavailable"
AGGREGATE_BUDGET_EXCEEDED = "public_text_aggregate_budget_exceeded"
SPAN_CORRESPONDENCE_REFUSED = "public_text_span_correspondence_refused"
PUBLICATION_REVALIDATION_FAILED = "public_text_publication_revalidation_failed"
PUBLICATION_MISMATCH = "public_text_publication_mismatch"
POLICY_DIGEST_MISMATCH = "public_text_policy_digest_mismatch"
REPRESENTATION_READBACK_REFUSED = "public_text_representation_readback_refused"
DESCRIPTOR_SET_CHANGED = "public_text_descriptor_set_changed"
DOCUMENT_CAP_EXCEEDED = "public_text_document_cap_exceeded"
TASK_DIGEST_MISMATCH = "public_text_task_digest_mismatch"
CENSUS_SCOPE_REFUSED = "public_text_census_scope_refused"
DESCRIPTOR_CONSTRUCTION_REFUSED = "public_text_descriptor_construction_refused"

PAIR_REASONS = frozenset({
    SPAN_INVALID, SPAN_REVERSED, SPAN_OUT_OF_FILE, SPAN_LINK_MISMATCH, SELECTED_EVIDENCE_MISSING,
    BINDING_POLICY_MISSING, ARTIFACT_NOT_IN_MANIFEST, METADATA_PRIVACY_REFUSED, EXCERPT_INVALID_UTF8,
    EXCERPT_BLANK, EXCERPT_PRIVACY_REFUSED, EXCERPT_CREDENTIAL_SHAPE_EXCLUDED, LINE_CONVENTION_MISMATCH,
    PROJECTION_TRUNCATED, PROJECTION_RECORD_MISSING, PROJECTION_RECORD_MISMATCH, ARTIFACT_INTEGRITY_REFUSED,
})
PREPARATION_REFUSALS = frozenset({
    PRIVATE_MARKER_SCOPE_INVALID, PROJECTION_POLICY_INCOMPATIBLE, PROJECTION_SETUP_REFUSED,
    PROJECTION_INPUTS_UNAVAILABLE, AGGREGATE_BUDGET_EXCEEDED, SPAN_CORRESPONDENCE_REFUSED,
    PUBLICATION_REVALIDATION_FAILED, PUBLICATION_MISMATCH, POLICY_DIGEST_MISMATCH,
    REPRESENTATION_READBACK_REFUSED, DESCRIPTOR_SET_CHANGED, DOCUMENT_CAP_EXCEEDED,
    TASK_DIGEST_MISMATCH, CENSUS_SCOPE_REFUSED, DESCRIPTOR_CONSTRUCTION_REFUSED,
})
# Pair reasons that carry one maintained ExclusionReason suffix.
MAINTAINED_REASON_PREFIXES = frozenset({
    "public_text_body_policy_denied", "public_text_binding_excluded",
    "public_text_pre_open_excluded", "public_text_projection_excluded",
})
_MAINTAINED_VALUES = frozenset(item.value for item in ExclusionReason)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}\Z")
_SCOPE_ID = re.compile(r"^ptscope1:[0-9a-f]{64}\Z")
_SCOPE_TOKEN = object()
ACCEPTED_REFERENCE_FIELDS = (
    "graph_id", "repository_id", "backend", "run_id", "publication_bundle_id", "job_id", "attempt",
    "accepted_generation", "snapshot_manifest_id", "extraction_receipt_id", "trusted_caller",
)


class PublicTextRefusal(ValueError):
    """Closed refusal; the message is the closed code and never carries private detail."""

    def __init__(self, code: str) -> None:
        if code not in PREPARATION_REFUSALS and not is_pair_reason(code):
            raise ValueError("unknown public-text refusal code")
        super().__init__(code)
        self.code = code


def maintained_reason(prefix: str, reason: ExclusionReason | str) -> str:
    value = reason.value if isinstance(reason, ExclusionReason) else reason
    code = f"{prefix}:{value}"
    if not is_pair_reason(code):
        raise ValueError("unknown maintained public-text reason")
    return code


def is_pair_reason(code: object) -> bool:
    if type(code) is not str:
        return False
    if code in PAIR_REASONS:
        return True
    prefix, sep, suffix = code.partition(":")
    return bool(sep) and prefix in MAINTAINED_REASON_PREFIXES and suffix in _MAINTAINED_VALUES


def is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _is_exact_int(value: object, minimum: int) -> bool:
    return type(value) is int and value >= minimum


def _public_text(value: object) -> bool:
    return is_safe_public_metadata(value)


@dataclass(frozen=True, eq=False)
class PrivateMarkerScope:
    """Trusted controller scope; only the random public scope ID is ever exposed."""

    scope_id: str
    _markers: tuple[str, ...] = field(repr=False)
    _digest: str = field(repr=False)
    _token: object = field(repr=False, default=None)

    def __post_init__(self) -> None:
        if self._token is not _SCOPE_TOKEN or _SCOPE_ID.fullmatch(self.scope_id) is None:
            raise PublicTextRefusal(PRIVATE_MARKER_SCOPE_INVALID)

    def __repr__(self) -> str:
        return f"PrivateMarkerScope(scope_id={self.scope_id!r})"

    @classmethod
    def create(cls, markers: object) -> PrivateMarkerScope:
        if type(markers) is not tuple or not 1 <= len(markers) <= 128:
            raise PublicTextRefusal(PRIVATE_MARKER_SCOPE_INVALID)
        for marker in markers:
            if type(marker) is not str or not marker.strip():
                raise PublicTextRefusal(PRIVATE_MARKER_SCOPE_INVALID)
            if any(unicodedata.category(ch) in {"Cc", "Cs"} for ch in marker):
                raise PublicTextRefusal(PRIVATE_MARKER_SCOPE_INVALID)
            if len(marker.encode("utf-8")) > 4096:
                raise PublicTextRefusal(PRIVATE_MARKER_SCOPE_INVALID)
        unique = tuple(sorted(set(markers)))
        digest = sha256_bytes(json.dumps(list(unique), ensure_ascii=False).encode("utf-8"))
        return cls("ptscope1:" + secrets.token_hex(32), unique, digest, _SCOPE_TOKEN)

    @property
    def markers(self) -> tuple[str, ...]:
        return self._markers

    def is_valid(self) -> bool:
        unique = tuple(sorted(set(self._markers)))
        digest = sha256_bytes(json.dumps(list(unique), ensure_ascii=False).encode("utf-8"))
        return self._token is _SCOPE_TOKEN and unique == self._markers and digest == self._digest

    def private_digest_matches(self, digest: str) -> bool:
        return secrets.compare_digest(self._digest, digest)


def require_scope(scope: object) -> PrivateMarkerScope:
    if type(scope) is not PrivateMarkerScope or not scope.is_valid():
        raise PublicTextRefusal(PRIVATE_MARKER_SCOPE_INVALID)
    return scope


@dataclass(frozen=True)
class SpanRow:
    """One companion accepted-evidence row with its nullable stored line span."""

    canonical_key: str
    evidence_key: str
    run_id: int
    graph_key_version: int
    path: str | None
    metadata_json: Mapping[str, Any] | str | None
    link_kind: str
    start_line: Any
    end_line: Any

    @property
    def row_key(self) -> tuple[str, str, str, int, int]:
        return (self.canonical_key, self.evidence_key, self.link_kind, self.run_id, self.graph_key_version)


@dataclass(frozen=True)
class PairExclusion:
    canonical_key: str
    source_binding_id: str
    reason: str

    def __post_init__(self) -> None:
        if not is_pair_reason(self.reason):
            raise ValueError("unknown public-text pair reason")

    def to_dict(self) -> dict[str, str]:
        return {"canonical_key": self.canonical_key, "source_binding_id": self.source_binding_id, "reason": self.reason}


_STR_FIELDS = (
    "graph_id", "repository_identity", "receipt_identity", "policy_digest", "publication_bundle_id",
    "snapshot_manifest_id", "extraction_receipt_id", "candidate_id", "source_binding_id", "snapshot_id",
    "canonical_key", "kind", "display_name", "evidence_key", "source_relative_path", "artifact_privacy",
)
_INT_FIELDS = {
    "run_id": 1, "generation": 1, "binding_revision": 1, "start_line": 1, "end_line": 1,
    "artifact_size_bytes": 0, "span_start_byte": 0, "span_end_byte": 0, "excerpt_end_byte": 0,
    "excerpt_bytes": 1, "utf8_tail_dropped_bytes": 0, "lf_count": 0, "crlf_count": 0, "model_text_bytes": 1,
}
_DIGEST_FIELDS = ("v1_input_digest", "artifact_content_digest", "excerpt_digest", "input_digest")
_BOOL_FIELDS = ("span_cut", "final_line_without_lf")
DESCRIPTOR_FIELDS = (
    "schema", "representation_version", "model_text_version", "admission_policy_version", "graph_id",
    "repository_identity", "backend", "run_id", "generation", "receipt_identity", "policy_digest",
    "privacy_scope_id", "accepted_reference", "publication_bundle_id", "snapshot_manifest_id",
    "extraction_receipt_id", "candidate_id", "source_binding_id", "binding_revision", "snapshot_id",
    "canonical_key", "kind", "display_name", "v1_input_digest", "evidence_key", "source_relative_path",
    "start_line", "end_line", "artifact_content_digest", "artifact_size_bytes", "artifact_privacy",
    "span_start_byte", "span_end_byte", "excerpt_end_byte", "excerpt_bytes", "excerpt_digest", "span_cut",
    "utf8_tail_dropped_bytes", "lf_count", "crlf_count", "final_line_without_lf", "model_text_bytes",
    "input_digest",
)


def validate_accepted_reference(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or tuple(sorted(raw)) != tuple(sorted(ACCEPTED_REFERENCE_FIELDS)):
        raise ValueError("accepted_reference must carry exactly the eleven accepted fields")
    for name in ("graph_id", "repository_id", "publication_bundle_id", "job_id", "snapshot_manifest_id", "extraction_receipt_id"):
        if not _public_text(raw[name]):
            raise ValueError(f"accepted_reference.{name} is invalid")
    if raw["backend"] not in {"sqlite", "postgresql"} or raw["trusted_caller"] is not True:
        raise ValueError("accepted_reference backend/trust is invalid")
    for name in ("run_id", "attempt", "accepted_generation"):
        if not _is_exact_int(raw[name], 1):
            raise ValueError(f"accepted_reference.{name} must be an exact positive int")
    return {name: raw[name] for name in ACCEPTED_REFERENCE_FIELDS}


@dataclass(frozen=True)
class PublicTextDescriptor:
    """Strict frozen cloe-public-text-descriptor-v1; unknown or missing keys refuse."""

    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(_validated_descriptor(self.values)))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> PublicTextDescriptor:
        return cls(raw)

    def __getitem__(self, name: str) -> Any:
        return self.values[name]

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.values)
        result["accepted_reference"] = dict(self.values["accepted_reference"])
        return result

    @property
    def identity(self) -> str:
        return str(digest_json(self.to_dict()))


def _validated_descriptor(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("descriptor must be a mapping")
    keys = set(raw)
    if keys != set(DESCRIPTOR_FIELDS):
        raise ValueError("descriptor keys must match the closed field set exactly")
    expected = {
        "schema": DESCRIPTOR_SCHEMA, "representation_version": REPRESENTATION_VERSION,
        "model_text_version": MODEL_TEXT_VERSION, "admission_policy_version": ADMISSION_POLICY_VERSION,
    }
    for name, value in expected.items():
        if raw[name] != value or type(raw[name]) is not str:
            raise ValueError(f"descriptor {name} is unsupported")
    for name in _STR_FIELDS:
        if not _public_text(raw[name]):
            raise ValueError(f"descriptor {name} is not a public-safe string")
    for name, minimum in _INT_FIELDS.items():
        if not _is_exact_int(raw[name], minimum):
            raise ValueError(f"descriptor {name} must be an exact int >= {minimum}")
    for name in _DIGEST_FIELDS:
        if not is_sha256(raw[name]):
            raise ValueError(f"descriptor {name} must be a sha256 digest")
    for name in _BOOL_FIELDS:
        if type(raw[name]) is not bool:
            raise ValueError(f"descriptor {name} must be an exact bool")
    if raw["backend"] not in {"sqlite", "postgresql"}:
        raise ValueError("descriptor backend is unsupported")
    if type(raw["privacy_scope_id"]) is not str or _SCOPE_ID.fullmatch(raw["privacy_scope_id"]) is None:
        raise ValueError("descriptor privacy_scope_id is invalid")
    reference = validate_accepted_reference(raw["accepted_reference"])
    _check_descriptor_invariants(raw, reference)
    result = {name: raw[name] for name in DESCRIPTOR_FIELDS}
    result["accepted_reference"] = MappingProxyType(reference)
    return result


def _check_descriptor_invariants(raw: Mapping[str, Any], reference: Mapping[str, Any]) -> None:
    for left, right in (
        ("graph_id", "graph_id"), ("repository_identity", "repository_id"), ("backend", "backend"),
        ("run_id", "run_id"), ("generation", "accepted_generation"),
        ("publication_bundle_id", "publication_bundle_id"), ("snapshot_manifest_id", "snapshot_manifest_id"),
        ("extraction_receipt_id", "extraction_receipt_id"),
    ):
        if raw[left] != reference[right]:
            raise ValueError(f"descriptor {left} disagrees with accepted_reference")
    start, end, cut_end = raw["span_start_byte"], raw["span_end_byte"], raw["excerpt_end_byte"]
    dropped = raw["utf8_tail_dropped_bytes"]
    if raw["start_line"] > raw["end_line"] or not start <= cut_end <= end <= raw["artifact_size_bytes"]:
        raise ValueError("descriptor span offsets are inconsistent")
    if raw["excerpt_bytes"] != cut_end - start or raw["excerpt_bytes"] > MAX_EXCERPT_BYTES:
        raise ValueError("descriptor excerpt length is inconsistent")
    if dropped > 3 or cut_end + dropped > end or raw["span_cut"] is not (cut_end + dropped < end):
        raise ValueError("descriptor cut accounting is inconsistent")
    if dropped and not raw["span_cut"]:
        raise ValueError("descriptor tail drop requires a cut span")
    if raw["crlf_count"] > raw["lf_count"]:
        raise ValueError("descriptor line terminator counts are inconsistent")


@dataclass(frozen=True)
class PublicTextQueryDecision:
    """Unmodified v1 evaluator decision plus the supplemental public-text arm state."""

    v1_decision: Any
    state: str
    reason_category: str | None
    refusal_code: str | None
    policy_enforcement_layer: str | None

    def __post_init__(self) -> None:
        if self.state not in {"admitted", "refused", "unavailable"}:
            raise ValueError("public-text state is not closed")
        if (self.state == "refused") is (self.refusal_code is None):
            raise ValueError("public-text refusal code must accompany exactly the refused state")
        if self.state == "admitted" and (self.reason_category or self.policy_enforcement_layer):
            raise ValueError("admitted public-text decision carries no reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "admission_policy_version": ADMISSION_POLICY_VERSION, "v1": self.v1_decision.to_dict(),
            "public_text": {
                "state": self.state, "reason_category": self.reason_category,
                "refusal_code": self.refusal_code, "policy_enforcement_layer": self.policy_enforcement_layer,
            },
        }


def counter_mapping(items: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return dict(sorted(counts.items()))
