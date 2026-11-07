"""Strict normalization for accepted W5 records and claimed representations."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any, Literal, NoReturn, overload

from common_lore_index.storage.semantic_candidates import EmbeddingEntry, MAX_DIMENSIONS, checked_vector
from retrieval_semantic_primitives import (
    AcceptedEvidenceRecord,
    AcceptedNodeRecord,
    ClaimedNodeRepresentation,
    RepresentationValidationError,
    freeze_jsonable,
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MISSING = object()
_CLAIM_FIELDS = frozenset({
    "canonical_key", "source_binding_id", "input_digest", "snapshot_id",
    "kind", "display_name", "vector", "dimensions",
})


def _fail(code: str, detail: str) -> NoReturn:
    raise RepresentationValidationError(code, detail)


@overload
def _text(value: Any, code: str) -> str: ...


@overload
def _text(value: Any, code: str, *, optional: Literal[True]) -> str | None: ...


def _text(value: Any, code: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if type(value) is not str or not value:
        _fail(code, "record text field is invalid")
    if "\x00" in value:
        _fail(code, "record text field is invalid")
    return value


def _positive_int(value: Any, code: str) -> int:
    if type(value) is not int or value <= 0:
        _fail(code, "record integer field is invalid")
    return value


def _mapping_value(raw: Mapping[str, Any], field: str, code: str) -> Any:
    try:
        if field not in raw:
            _fail(code, "record field is missing")
        return raw[field]
    except RepresentationValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise RepresentationValidationError(code, "record field is invalid") from exc


def _optional_mapping_value(raw: Mapping[str, Any], field: str, default: Any, code: str) -> Any:
    try:
        return raw.get(field, default)
    except (KeyError, TypeError, ValueError) as exc:
        raise RepresentationValidationError(code, "record field is invalid") from exc


def normalize_accepted_node(raw: object) -> AcceptedNodeRecord:
    """Normalize one accepted node without defaults or scalar coercion."""
    values: dict[str, Any]
    if isinstance(raw, AcceptedNodeRecord):
        values = {
            "canonical_key": raw.canonical_key, "kind": raw.kind,
            "display_name": raw.display_name, "graph_key_version": raw.graph_key_version,
            "last_seen_run_id": raw.last_seen_run_id,
        }
    elif isinstance(raw, Mapping):
        values = {
            "canonical_key": _mapping_value(raw, "canonical_key", "invalid_accepted_node"),
            "kind": _optional_mapping_value(raw, "kind", None, "invalid_accepted_node"),
            "display_name": _optional_mapping_value(raw, "display_name", None, "invalid_accepted_node"),
            "graph_key_version": _mapping_value(raw, "graph_key_version", "invalid_accepted_node"),
            "last_seen_run_id": _mapping_value(raw, "last_seen_run_id", "invalid_accepted_node"),
        }
    else:
        _fail("invalid_accepted_node", "record type is not supported")
    canonical_key = _text(values["canonical_key"], "invalid_accepted_node")
    kind = _text(values["kind"], "invalid_accepted_node", optional=True)
    display_name = _text(values["display_name"], "invalid_accepted_node", optional=True)
    return AcceptedNodeRecord(
        canonical_key, kind, display_name,
        _positive_int(values["graph_key_version"], "invalid_accepted_node"),
        _positive_int(values["last_seen_run_id"], "invalid_accepted_node"),
    )


def _freeze_metadata(value: Any) -> Any:
    try:
        return freeze_jsonable(value)
    except RepresentationValidationError as exc:
        raise RepresentationValidationError("invalid_evidence_metadata", "metadata is not bounded JSON") from exc


def normalize_accepted_evidence(raw: object) -> AcceptedEvidenceRecord:
    """Normalize evidence, freezing metadata while retaining privacy-invalid values for exclusion."""
    fields = ("canonical_key", "evidence_key", "run_id", "graph_key_version", "path", "metadata_json", "link_kind")
    values: dict[str, Any]
    if isinstance(raw, AcceptedEvidenceRecord):
        values = {field: getattr(raw, field) for field in fields}
    elif isinstance(raw, Mapping):
        values = {
            "canonical_key": _mapping_value(raw, "canonical_key", "invalid_accepted_evidence"),
            "evidence_key": _mapping_value(raw, "evidence_key", "invalid_accepted_evidence"),
            "run_id": _mapping_value(raw, "run_id", "invalid_accepted_evidence"),
            "graph_key_version": _mapping_value(raw, "graph_key_version", "invalid_accepted_evidence"),
            "path": _optional_mapping_value(raw, "path", None, "invalid_accepted_evidence"),
            "metadata_json": _optional_mapping_value(raw, "metadata_json", None, "invalid_accepted_evidence"),
            "link_kind": _optional_mapping_value(raw, "link_kind", "observed", "invalid_accepted_evidence"),
        }
    else:
        _fail("invalid_accepted_evidence", "record type is not supported")
    canonical_key = _text(values["canonical_key"], "invalid_accepted_evidence")
    evidence_key = _text(values["evidence_key"], "invalid_accepted_evidence")
    link_kind = _text(values["link_kind"], "invalid_accepted_evidence")
    return AcceptedEvidenceRecord(
        canonical_key, evidence_key,
        _positive_int(values["run_id"], "invalid_accepted_evidence"),
        _positive_int(values["graph_key_version"], "invalid_accepted_evidence"),
        values["path"], _freeze_metadata(values["metadata_json"]), link_kind,
    )


def _claim_mapping(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not set(raw).issubset(_CLAIM_FIELDS):
        _fail("invalid_claim_record", "claim contains an unapproved field")
    required = ("canonical_key", "source_binding_id", "input_digest")
    values = {field: _mapping_value(raw, field, "invalid_claim_record") for field in required}
    for field in ("snapshot_id", "kind", "display_name", "vector", "dimensions"):
        values[field] = raw.get(field, _MISSING)
    return values


def normalize_claimed_representation(
    raw: object,
) -> ClaimedNodeRepresentation:
    """Normalize one claim and validate vector/dimension shape without coercing identity fields."""
    values: dict[str, Any]
    if isinstance(raw, EmbeddingEntry):
        values = {
            "canonical_key": raw.canonical_key, "source_binding_id": raw.source_binding_id,
            "input_digest": raw.input_digest, "snapshot_id": None, "kind": None,
            "display_name": None, "vector": raw.vector, "dimensions": None,
        }
    elif isinstance(raw, ClaimedNodeRepresentation):
        values = {field: getattr(raw, field) for field in (
            "canonical_key", "source_binding_id", "input_digest", "snapshot_id",
            "claimed_kind", "claimed_display_name", "vector", "dimensions",
        )}
        values["kind"] = values.pop("claimed_kind")
        values["display_name"] = values.pop("claimed_display_name")
    elif isinstance(raw, Mapping):
        values = _claim_mapping(raw)
    else:
        _fail("invalid_claim_record", "claim type is not supported")
    canonical_key = _text(values["canonical_key"], "invalid_claim_identity")
    source_binding_id = _text(values["source_binding_id"], "invalid_claim_identity")
    digest: object = values["input_digest"]
    if type(digest) is not str:
        _fail("invalid_input_digest_format", "claim digest format is invalid")
    assert isinstance(digest, str)
    if _DIGEST.fullmatch(digest) is None:
        _fail("invalid_input_digest_format", "claim digest format is invalid")
    snapshot_id = None if values["snapshot_id"] is _MISSING else _text(values["snapshot_id"], "invalid_claim_record", optional=True)
    kind = None if values["kind"] is _MISSING else _text(values["kind"], "invalid_claim_record", optional=True)
    display_name = None if values["display_name"] is _MISSING else _text(values["display_name"], "invalid_claim_record", optional=True)
    raw_vector: object = values["vector"]
    vector: tuple[float, ...] | None
    if raw_vector is _MISSING or raw_vector is None:
        vector = None
    elif isinstance(raw_vector, (list, tuple)):
        vector = tuple(raw_vector)
    else:
        _fail("invalid_claim_vector", "claim vector must be a finite numeric sequence")
    raw_dimensions: object = values["dimensions"]
    if raw_dimensions is _MISSING or raw_dimensions is None:
        dimensions: int | None = None
    else:
        if type(raw_dimensions) is not int:
            _fail("invalid_claim_dimensions", "claim dimensions are invalid")
        assert isinstance(raw_dimensions, int)
        if not 1 <= raw_dimensions <= MAX_DIMENSIONS:
            _fail("invalid_claim_dimensions", "claim dimensions are invalid")
        dimensions = raw_dimensions
    if vector is not None:
        if dimensions is None:
            dimensions = len(vector)
        assert isinstance(dimensions, int)
        try:
            checked_vector(vector, dimensions)
        except (TypeError, ValueError) as exc:
            raise RepresentationValidationError("invalid_claim_vector", "claim vector is invalid") from exc
    return ClaimedNodeRepresentation(
        canonical_key, source_binding_id, digest, snapshot_id, kind, display_name, vector, dimensions,
    )


__all__ = (
    "normalize_accepted_evidence", "normalize_accepted_node", "normalize_claimed_representation",
)
