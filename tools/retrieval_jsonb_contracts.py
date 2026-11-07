"""Workload contracts, facet validation, and payload decoding for the PostgreSQL JSONB experiment (ADR 0137)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import json
from typing import Any

from common_lore_index.storage.node_locations import NodeLocationsQuery, unavailable
from common_lore_index.storage.postgres_node_locations import (
    read_postgres_node_locations_with_executor,
)
from retrieval_semantic_representation import (
    RepresentationValidationError,
    _require,
    _validate_representation_string,
    freeze_jsonable,
    validate_relative_path,
)

JSONB_EXPERIMENT_POLICY_VERSION = "cloe-w5-jsonb-evidence-v1"
DISPOSABLE_SCHEMA = "repomap_w5_jsonb_exp"
PROJECTION_TABLE = "repomap_w5_jsonb_exp.node_evidence_jsonb_proj"
STATE_TABLE = "repomap_w5_jsonb_exp.projection_state"
GIN_OPS_INDEX = "idx_w5_jsonb_facet_gin_ops"
GIN_PATH_OPS_INDEX = "idx_w5_jsonb_facet_gin_path_ops"
VARIANT_NAMES: tuple[str, ...] = (
    "relational_baseline",
    "jsonb_no_index",
    "jsonb_gin_ops",
    "jsonb_gin_path_ops",
)


@dataclass(frozen=True)
class JsonbFacetFilter:
    """Predeclared facet containment/equality filter over evidence metadata."""

    binding_id: str
    snapshot_id: str
    source_relative_path: str | None = None

    def validate(self) -> JsonbFacetFilter:
        _validate_representation_string(self.binding_id, "binding_id")
        _validate_representation_string(self.snapshot_id, "snapshot_id")
        if self.source_relative_path is not None:
            _validate_representation_string(self.source_relative_path, "source_relative_path")
            try:
                validate_relative_path(self.source_relative_path, "source_relative_path")
            except ValueError as exc:
                raise RepresentationValidationError("invalid_relative_path", str(exc)) from exc
        return self

    def to_containment_json(self) -> str:
        self.validate()
        doc = {
            "binding_id": self.binding_id,
            "snapshot_id": self.snapshot_id,
            **({} if self.source_relative_path is None else {"source_relative_path": self.source_relative_path}),
        }
        return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.validate())


@dataclass(frozen=True)
class NamedEvidenceWorkloadItem:
    """One frozen node-evidence query in the predeclared experiment workload."""

    workload_id: str
    query: Any
    context_identity: bool = False
    facet_filter: JsonbFacetFilter | None = None
    expected_status: str = "ok"

    def validate(self) -> NamedEvidenceWorkloadItem:
        _validate_representation_string(self.workload_id, "workload_id")
        _require(
            self.expected_status in {"ok", "unavailable"},
            "invalid_expected_status",
            f"expected_status must be 'ok' or 'unavailable', got {self.expected_status!r}",
        )
        self.query.validate()
        if self.facet_filter is not None:
            self.facet_filter.validate()
        return self


def _thaw_jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _thaw_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_jsonable(item) for item in value]
    return value


def validate_evidence_metadata_facets(raw_metadata: Any) -> dict[str, str] | None:
    """Validate evidence metadata_json without inventing fallback binding/snapshot values."""
    if raw_metadata is None:
        return None
    parsed: Any = raw_metadata
    if isinstance(raw_metadata, str):
        try:
            parsed = json.loads(raw_metadata)
        except ValueError as exc:
            raise RepresentationValidationError("malformed_evidence_metadata", str(exc)) from exc
    _require(isinstance(parsed, Mapping), "malformed_evidence_metadata", "metadata_json must be a JSON object")
    assert isinstance(parsed, Mapping)
    if not parsed:
        return None
    out: dict[str, str] = {}
    for key in ("binding_id", "snapshot_id", "source_relative_path"):
        if key in parsed:
            val = parsed[key]
            _require(
                type(val) is str and bool(val.strip()),
                "malformed_evidence_metadata",
                f"invalid {key} in metadata_json",
            )
            try:
                norm_val = _validate_representation_string(val, key)
                if key == "source_relative_path":
                    validate_relative_path(norm_val, key)
            except (RepresentationValidationError, ValueError) as exc:
                raise RepresentationValidationError("malformed_evidence_metadata", str(exc)) from exc
            out[key] = norm_val
    _require(
        "binding_id" in out and "snapshot_id" in out,
        "malformed_evidence_metadata",
        "non-empty metadata_json must provide both binding_id and snapshot_id",
    )
    return out


def normalize_node_locations_result_for_equality(result: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a node_locations response for strict row-set, order, and refusal equality comparison."""
    return json.loads(
        json.dumps(_thaw_jsonable(freeze_jsonable(result)), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def decode_node_locations_payload(
    payload: Mapping[str, Any],
    *,
    query: Any,
    context_identity: bool = False,
    fail_on_malformed_facets: bool = False,
) -> dict[str, Any]:
    """Decode raw JSON readback payload using the exact postgres_node_locations wire contract plus stale/malformed guards."""
    if payload.get("projection_stale"):
        return dict(unavailable("projection_stale_for_live_publication"))
    if fail_on_malformed_facets and int(payload.get("malformed_metadata_count") or 0) > 0:
        raise RepresentationValidationError(
            "malformed_evidence_metadata", "repository contains malformed facet metadata_json"
        )
    return dict(
        read_postgres_node_locations_with_executor(
            query, executor=lambda _sql: dict(payload), context_identity=context_identity
        )
    )


__all__ = [
    "DISPOSABLE_SCHEMA",
    "GIN_OPS_INDEX",
    "GIN_PATH_OPS_INDEX",
    "JSONB_EXPERIMENT_POLICY_VERSION",
    "PROJECTION_TABLE",
    "STATE_TABLE",
    "VARIANT_NAMES",
    "JsonbFacetFilter",
    "NamedEvidenceWorkloadItem",
    "NodeLocationsQuery",
    "_thaw_jsonable",
    "decode_node_locations_payload",
    "normalize_node_locations_result_for_equality",
    "validate_evidence_metadata_facets",
]
