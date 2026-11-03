"""Plan, payload, and exact-recall parsing for the W5 HNSW arm."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from common_lore_index.storage.semantic_candidates import checked_identity
from retrieval_semantic_ann_models import (
    CandidateIdentity,
    HnswCandidate,
    HnswEvaluationError,
    HnswPlanSummary,
    HnswRecallSummary,
    JsonObject,
    JsonValue,
    candidate_fields,
    digest_matches,
    evidence_fields,
    finite_number,
    nonnegative_int,
    optional_text,
)

_MAX_PAYLOAD_TEXT = 4096
_READBACK_STATUSES = frozenset({
    "ok", "stale_publication", "stale_rebuild", "profile_mismatch",
    "unsupported_extension", "rebuild_integrity_mismatch", "source_scope_unavailable",
})
_CANONICAL_CONFIDENCES = frozenset({"manual", "extracted", "heuristic", "unknown"})


def _bounded_text(value: object, code: str, *, nonempty: bool = True) -> str:
    if type(value) is not str or (nonempty and not value) or len(value) > _MAX_PAYLOAD_TEXT:
        raise HnswEvaluationError(code, "text field is outside its bound")
    if "\x00" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise HnswEvaluationError(code, "text field contains a control character")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise HnswEvaluationError(code, "text field is not valid UTF-8") from exc
    return value


def _nonnegative_optional_int(value: object, code: str) -> None:
    if value is not None and (type(value) is not int or value < 0):
        raise HnswEvaluationError(code, "evidence line field is invalid")


def _canonical_confidence(value: object, code: str) -> str:
    if type(value) is not str or value not in _CANONICAL_CONFIDENCES:
        raise HnswEvaluationError(code, "confidence is not a canonical graph value")
    return value


def _mapping(value: object, code: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise HnswEvaluationError(code, "expected a JSON object")
    return value


def _has_distance_order(value: object) -> bool:
    if value is None:
        return False
    if type(value) is str:
        return "<=>" in value
    if isinstance(value, list) and all(type(item) is str for item in value):
        return any("<=>" in item for item in value)
    raise HnswEvaluationError("invalid_explain", "Order By has an invalid shape")


def parse_hnsw_explain(
    payload: Sequence[JsonValue], *, expected_index_name: str, planner_forced: bool = False
) -> HnswPlanSummary:
    """Require an actual expected Index Scan with vector distance ordering."""
    if not payload:
        raise HnswEvaluationError("invalid_explain", "empty EXPLAIN payload")
    top = _mapping(payload[0], "invalid_explain")
    plan = _mapping(top.get("Plan"), "invalid_explain")
    node_types: list[str] = []
    index_names: list[str] = []
    distance_order = False
    expected_index_order = False

    def walk(node: Mapping[str, JsonValue]) -> None:
        nonlocal distance_order, expected_index_order
        node_type = node.get("Node Type")
        if type(node_type) is str:
            node_types.append(node_type)
        index_name = node.get("Index Name")
        if type(index_name) is str:
            index_names.append(index_name)
        has_distance_order = _has_distance_order(node.get("Order By"))
        if has_distance_order:
            distance_order = True
        if node_type == "Index Scan" and index_name == expected_index_name and has_distance_order:
            expected_index_order = True
        children = node.get("Plans")
        if children is not None:
            if not isinstance(children, list):
                raise HnswEvaluationError("invalid_explain", "plan children are not an array")
            for child in children:
                walk(_mapping(child, "invalid_explain"))

    walk(plan)
    used_index = expected_index_order
    return HnswPlanSummary(
        tuple(node_types), tuple(index_names),
        nonnegative_int(plan.get("Actual Rows", 0), "invalid_explain"),
        finite_number(top.get("Planning Time", 0.0), "invalid_explain"),
        finite_number(top.get("Execution Time", 0.0), "invalid_explain"),
        nonnegative_int(plan.get("Shared Hit Blocks", 0), "invalid_explain"),
        nonnegative_int(plan.get("Shared Read Blocks", 0), "invalid_explain"),
        used_index, "Seq Scan" in node_types, distance_order, planner_forced,
    )


def _parse_evidence(value: object, *, evidence_limit: int) -> tuple[JsonObject, ...]:
    if not isinstance(value, list):
        raise HnswEvaluationError("malformed_ann_payload", "candidate evidence is not an array")
    if len(value) > evidence_limit:
        raise HnswEvaluationError("malformed_ann_payload", "candidate evidence exceeds requested limit")
    result: list[JsonObject] = []
    for raw in value:
        row = dict(_mapping(raw, "malformed_ann_payload"))
        if set(row) != evidence_fields():
            raise HnswEvaluationError("malformed_ann_payload", "candidate evidence fields are incomplete or unapproved")
        _bounded_text(row["evidence_key"], "malformed_ann_payload")
        for field in ("path", "raw_kind", "extractor", "extractor_version"):
            if row[field] is not None:
                _bounded_text(row[field], "malformed_ann_payload")
        if isinstance(row["path"], str) and row["path"].startswith("/withheld/"):
            raise HnswEvaluationError("malformed_ann_payload", "withheld evidence path is not public")
        for field in ("start_line", "end_line"):
            _nonnegative_optional_int(row[field], "malformed_ann_payload")
        _canonical_confidence(row["confidence"], "malformed_ann_payload")
        result.append(row)
    return tuple(result)


def parse_hnsw_candidates(
    payload: Mapping[str, JsonValue], *, snapshot_by_binding: Mapping[str, str],
    requested_limit: int, evidence_limit: int,
) -> tuple[HnswCandidate, ...]:
    if not set(payload).issubset({"status", "candidates", "ann_scan_limit"}):
        raise HnswEvaluationError("malformed_ann_payload", "payload contains an unapproved field")
    status = payload.get("status")
    if status is not None:
        status = _bounded_text(status, "malformed_ann_payload")
        if status not in _READBACK_STATUSES:
            raise HnswEvaluationError("malformed_ann_payload", "status is not an accepted readback")
    if not isinstance(snapshot_by_binding, Mapping) or len(snapshot_by_binding) > 500:
        raise HnswEvaluationError("malformed_ann_payload", "publication snapshot scope is invalid")
    for binding_id, bound_snapshot_id in snapshot_by_binding.items():
        try:
            checked_identity(binding_id)
            checked_identity(bound_snapshot_id)
        except (TypeError, ValueError) as exc:
            raise HnswEvaluationError("malformed_ann_payload", "publication snapshot scope is invalid") from exc
    if type(requested_limit) is not int or not 1 <= requested_limit <= 100:
        raise HnswEvaluationError("malformed_ann_payload", "requested candidate limit is invalid")
    if type(evidence_limit) is not int or not 1 <= evidence_limit <= 20:
        raise HnswEvaluationError("malformed_ann_payload", "requested evidence limit is invalid")
    scan_limit = payload.get("ann_scan_limit")
    if scan_limit is not None and (
        type(scan_limit) is not int or not requested_limit <= scan_limit <= 500
    ):
        raise HnswEvaluationError("malformed_ann_payload", "ANN scan limit is invalid")
    rows = payload.get("candidates")
    if not isinstance(rows, list) or len(rows) > requested_limit:
        raise HnswEvaluationError("malformed_ann_payload", "candidate page exceeds its bound")
    result: list[HnswCandidate] = []
    previous: tuple[float, bytes, bytes] | None = None
    for rank, raw in enumerate(rows, start=1):
        row = _mapping(raw, "malformed_ann_payload")
        if set(row) != candidate_fields():
            raise HnswEvaluationError("malformed_ann_payload", "candidate fields are incomplete or unapproved")
        node_id = row.get("node_id")
        if type(node_id) is not int or node_id <= 0:
            raise HnswEvaluationError("malformed_ann_payload", "candidate node id is invalid")
        canonical_key = _bounded_text(row.get("canonical_key"), "malformed_ann_payload")
        source_binding_id = _bounded_text(row.get("source_binding_id"), "malformed_ann_payload")
        try:
            checked_identity(source_binding_id)
        except ValueError as exc:
            raise HnswEvaluationError("malformed_ann_payload", "candidate source binding is invalid") from exc
        distance = finite_number(row.get("distance"), "malformed_ann_payload")
        if not 0.0 <= distance <= 2.0:
            raise HnswEvaluationError("malformed_ann_payload", "cosine distance is outside its range")
        kind = _bounded_text(row.get("kind"), "malformed_ann_payload")
        display_name = _bounded_text(row.get("display_name"), "malformed_ann_payload")
        _canonical_confidence(row.get("confidence"), "malformed_ann_payload")
        if type(row.get("conflict")) is not bool:
            raise HnswEvaluationError("malformed_ann_payload", "candidate confidence or conflict is invalid")
        digest = optional_text(row, "input_digest")
        snapshot_id = optional_text(row, "snapshot_id")
        if digest is None or not digest_matches(digest):
            raise HnswEvaluationError("malformed_ann_payload", "candidate input digest is invalid")
        if snapshot_id is None:
            raise HnswEvaluationError("malformed_ann_payload", "candidate snapshot is outside the publication")
        try:
            checked_identity(snapshot_id)
        except ValueError as exc:
            raise HnswEvaluationError("malformed_ann_payload", "candidate snapshot is invalid") from exc
        if snapshot_by_binding.get(source_binding_id) != snapshot_id:
            raise HnswEvaluationError("malformed_ann_payload", "candidate snapshot is outside the publication")
        order = (distance, canonical_key.encode("utf-8"), source_binding_id.encode("utf-8"))
        if previous is not None and order < previous:
            raise HnswEvaluationError("malformed_ann_payload", "candidate tie order is not deterministic")
        previous = order
        result.append(HnswCandidate(
            node_id, canonical_key, source_binding_id, rank, distance, digest,
            snapshot_id, kind, display_name,
            _parse_evidence(row.get("evidence"), evidence_limit=evidence_limit),
        ))
    if len({item.identity for item in result}) != len(result):
        raise HnswEvaluationError("malformed_ann_payload", "candidate identities are duplicated")
    return tuple(result)


def compare_hnsw_to_exact(
    candidates: Sequence[HnswCandidate],
    exact_identities: Sequence[CandidateIdentity],
    *, limit: int,
) -> HnswRecallSummary:
    if type(limit) is not int or limit < 1:
        raise HnswEvaluationError("invalid_recall_limit", "recall limit must be positive")
    exact_top = tuple(exact_identities[:limit])
    ann_top = tuple(item.identity for item in candidates[:limit])
    denominator = min(limit, len(exact_top))
    overlap = len(set(exact_top) & set(ann_top))
    recall = None if denominator == 0 else overlap / denominator
    return HnswRecallSummary(
        len(exact_identities), len(candidates), overlap, recall,
        len(candidates) < denominator,
    )
