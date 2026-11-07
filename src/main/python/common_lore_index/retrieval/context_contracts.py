"""Closed contracts, locked key orders, and request validation for W4 compact context."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common_lore_index.graph.edge_kinds import CANONICAL_EDGE_KINDS
from common_lore_index.retrieval.context_identity import (
    ContextIdentityError,
    validate_accepted_pin_mapping,
)
from common_lore_index.retrieval.intent_policy import INTENT_DEFAULT_EDGE_KINDS, NAVIGATION_INTENTS
from common_lore_index.retrieval.query_contracts import MatchSurface, QueryMode
from common_lore_index.storage.navigation_search import NavigationSearchQuery

COMPACT_CONTEXT_SCHEMA_VERSION = "cloe-compact-context-v1"
SOURCE_SELECTION_SCHEMA_VERSION = "cloe-source-selection-v1"
ADVISORY_FRESHNESS_SCHEMA_VERSION = "cloe-advisory-freshness-v1"
COMPACTION_POLICY_ID = "skeleton_compaction_v1"
ADMISSION_ORDER_POLICY_ID = "seeds_then_neighbors_v1"

MIN_BUDGET_BYTES = 4096
MAX_BUDGET_BYTES = 65536
DEFAULT_BUDGET_BYTES = 16384
BUDGET_ERROR_HARD_CAP_BYTES = 512

MAX_BINDINGS = 8
MAX_PREFIXES_PER_BINDING = 4
MAX_SCAN_UNITS = 8

QUERY_MODE_VALUES: tuple[str, ...] = tuple(m.value for m in QueryMode)
MATCH_SURFACE_VALUES: tuple[str, ...] = tuple(s.value for s in MatchSurface)
PACKET_STATUSES: tuple[str, ...] = (
    "complete", "partial", "refused", "stale", "unavailable", "failed", "budget_error",
)
REFUSAL_REASONS: tuple[str, ...] = (
    "invalid_request", "invalid_mode", "missing_mode", "invalid_target_flags",
    "invalid_intent", "invalid_expand_depth", "invalid_fallback",
    "binding_limit_exceeded", "prefix_limit_exceeded", "scan_unit_limit_exceeded",
    "invalid_selection_record", "selection_fingerprint_mismatch",
    "selection_graph_mismatch", "selection_binding_changed",
    "selection_binding_missing", "selection_output_exists",
)
UNAVAILABLE_REASONS: tuple[str, ...] = (
    "backend_unsupported", "capability_not_admitted", "publication_absent",
    "accepted_publication_unverified", "unlocatable_kind_in_scoped_selection",
    "database_unavailable",
)
STALE_REASONS: tuple[str, ...] = (
    "selection_publication_advanced", "publication_advanced_during_assembly",
)
OMISSION_COUNT_KEYS: tuple[str, ...] = (
    "output_budget", "item_limit", "location_limit",
    "ambiguous_alternative_omitted_by_budget", "expansion_node_limit",
    "expansion_edge_limit", "expansion_backend_unsupported",
    "candidate_scan_incomplete", "unlocatable_kind_pattern_excluded",
    "oversize_field_withheld", "unencodable_field_withheld",
)
PACKET_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "schema", "status", "requested_mode", "effective_mode", "fallback",
    "consistency_mode", "request", "scope", "publication", "ordering",
    "expansion", "omission_counts", "work_ledger", "freshness", "absence_basis",
    "items", "neighbors", "relations", "omissions",
)
CONTEXT_ITEM_KEYS: tuple[str, ...] = (
    "item_id", "item_role", "canonical_key", "kind", "display_name",
    "subject_family", "match_surface", "rank", "match_class", "rank_tiers",
    "rank_reasons", "identity_state", "locations", "omitted_location_count",
)
CONTEXT_LOCATION_KEYS: tuple[str, ...] = (
    "source_binding_id", "binding_revision", "snapshot_id", "source_relative_path",
    "run_id", "publication_relation", "path_namespace", "graph_path",
    "start_line", "end_line", "evidence_link_kind", "evidence_raw_kind",
    "evidence_confidence", "freshness",
)
CONTEXT_FRESHNESS_OBS_KEYS: tuple[str, ...] = ("state", "reason", "limits", "inspected_span")
CONTEXT_RELATION_KEYS: tuple[str, ...] = (
    "source_key", "edge_kind", "target_key", "match_surface", "support",
)


class ContextRequestError(ValueError):
    """Raised when a ContextRequest fails pre-execution validation."""

    def __init__(self, message: str, *, refusal_reason: str = "invalid_request") -> None:
        super().__init__(message)
        self.refusal_reason = refusal_reason
        self.diagnostic = message


def valid_source_path_prefix(value: Any) -> bool:
    """Validate a source-relative path prefix using NavigationSearchQuery rules."""
    if not isinstance(value, str) or not value or len(value) > 500:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value:
        return False
    prefix = value.rstrip("/")
    if not prefix or prefix.startswith(("/", "~")) or ":" in prefix:
        return False
    return not any(part in {"", ".", ".."} for part in prefix.split("/"))


@dataclass(frozen=True, slots=True)
class ExpectedPublicationPin:
    """Full 7-field expected_publication pin in cloe-source-selection-v1."""

    accepted_run_id: int
    publication_bundle_id: str
    snapshot_manifest_id: str
    generation: int
    job_id: str
    attempt: int
    extraction_receipt_id: str

    def validate(self) -> "ExpectedPublicationPin":
        for val in (self.accepted_run_id, self.generation, self.attempt):
            if type(val) is not int or val < 1:
                raise ContextRequestError(
                    "invalid integer field in expected_publication",
                    refusal_reason="invalid_selection_record",
                )
        for sval in (
            self.publication_bundle_id, self.snapshot_manifest_id,
            self.job_id, self.extraction_receipt_id,
        ):
            if not isinstance(sval, str) or not sval.strip():
                raise ContextRequestError(
                    "invalid string field in expected_publication",
                    refusal_reason="invalid_selection_record",
                )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_run_id": self.accepted_run_id,
            "publication_bundle_id": self.publication_bundle_id,
            "snapshot_manifest_id": self.snapshot_manifest_id,
            "generation": self.generation,
            "job_id": self.job_id,
            "attempt": self.attempt,
            "extraction_receipt_id": self.extraction_receipt_id,
        }

    def matches_accepted(self, accepted: Mapping[str, Any]) -> bool:
        """Compare all 7 run-level pin fields against accepted_publication."""
        try:
            self.validate()
            normalized = validate_accepted_pin_mapping(accepted)
        except (ContextIdentityError, ContextRequestError, TypeError):
            return False
        return (
            normalized["generation"] == self.generation
            and normalized["accepted_run_id"] == self.accepted_run_id
            and normalized["publication_bundle_id"] == self.publication_bundle_id
            and normalized["snapshot_manifest_id"] == self.snapshot_manifest_id
            and normalized["extraction_receipt_id"] == self.extraction_receipt_id
            and normalized["job_id"] == self.job_id
            and normalized["attempt"] == self.attempt
        )


@dataclass(frozen=True, slots=True)
class FreshnessCheckConfig:
    """Caller-provided opt-in advisory freshness roots."""

    enabled: bool = False
    source_roots: Mapping[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextRequest:
    """Explicit mode-governed W4 compact context request."""

    graph_id: str
    mode: str = "ranked_discovery"
    canonical_key: str | None = None
    query: str | None = None
    intent: str | None = None
    selection_path: Path | None = None
    bindings: tuple[str, ...] = ()
    path_prefixes: Mapping[str, Sequence[str]] = field(default_factory=dict)
    kinds: tuple[str, ...] = ()
    budget_bytes: Any = DEFAULT_BUDGET_BYTES
    max_items: int = 12
    locations_per_item: int = 2
    offset: int = 0
    expand_depth: int | None = None
    expand_seeds: int = 3
    node_limit: int = 8
    edge_limit: int = 16
    edge_kinds: tuple[str, ...] = ()
    fallback_to: str | None = None
    freshness: str = "none"
    source_roots: Mapping[str, Path] = field(default_factory=dict)
    allow_partial: bool = False
    expected_publication: ExpectedPublicationPin | None = None

    def effective_expand_depth(self) -> int:
        if self.expand_depth is not None:
            return self.expand_depth
        return 1 if self.mode == "graph_investigation" else 0

    def effective_intent(self) -> str | None:
        if self.mode in {"exact_identity", "current_literal_enumeration"}:
            return None
        return self.intent or "general"

    def effective_edge_kinds(self) -> tuple[str, ...]:
        if self.effective_expand_depth() == 0:
            return ()
        if self.edge_kinds:
            return tuple(dict.fromkeys(self.edge_kinds))
        eff_intent = self.effective_intent() or "general"
        return INTENT_DEFAULT_EDGE_KINDS.get(eff_intent, ())

    def validate(self) -> "ContextRequest":
        if not isinstance(self.graph_id, str) or not self.graph_id.strip():
            raise ContextRequestError("graph_id is required")
        if not isinstance(self.mode, str) or not self.mode:
            raise ContextRequestError("mode is required", refusal_reason="missing_mode")
        if self.mode not in QUERY_MODE_VALUES:
            raise ContextRequestError(
                f"unsupported mode: {self.mode!r}", refusal_reason="invalid_mode"
            )
        if self.mode in {"literal_captured_text", "semantic_discovery"}:
            return self
        if self.expected_publication is not None:
            self.expected_publication.validate()
        if self.expand_depth is not None and (
            type(self.expand_depth) is not int or self.expand_depth not in {0, 1}
        ):
            raise ContextRequestError(
                "expand_depth must be 0 or 1", refusal_reason="invalid_expand_depth"
            )
        eff_depth = self.effective_expand_depth()
        if self.mode == "exact_identity":
            if (
                not isinstance(self.canonical_key, str)
                or not self.canonical_key.strip()
                or self.query is not None
                or self.intent is not None
                or eff_depth != 0
            ):
                raise ContextRequestError(
                    "exact_identity requires canonical_key and rejects query, intent, expand_depth=1",
                    refusal_reason="invalid_target_flags",
                )
        elif self.mode == "current_literal_enumeration":
            if (
                not isinstance(self.query, str)
                or self.canonical_key is not None
                or self.intent is not None
                or eff_depth != 0
            ):
                raise ContextRequestError(
                    "current_literal_enumeration requires query and rejects canonical_key, intent, expand_depth=1",
                    refusal_reason="invalid_target_flags",
                )
        elif self.mode == "ranked_discovery":
            if not isinstance(self.query, str) or self.canonical_key is not None:
                raise ContextRequestError(
                    "ranked_discovery requires query and rejects canonical_key",
                    refusal_reason="invalid_target_flags",
                )
        elif self.mode == "graph_investigation":
            if not isinstance(self.canonical_key, str) or not self.canonical_key.strip():
                raise ContextRequestError(
                    "graph_investigation requires canonical_key",
                    refusal_reason="invalid_target_flags",
                )
            if eff_depth != 1:
                raise ContextRequestError(
                    "graph_investigation requires expand_depth=1",
                    refusal_reason="invalid_expand_depth",
                )
            if self.query is not None and self.fallback_to != "ranked_discovery":
                raise ContextRequestError(
                    "graph_investigation rejects query unless fallback_to=ranked_discovery",
                    refusal_reason="invalid_target_flags",
                )
        if self.intent is not None and self.intent not in NAVIGATION_INTENTS:
            raise ContextRequestError(
                f"unsupported intent: {self.intent!r}", refusal_reason="invalid_intent"
            )
        if self.fallback_to is not None:
            if self.fallback_to not in {"exact_identity", "ranked_discovery"}:
                raise ContextRequestError("invalid fallback_to", refusal_reason="invalid_fallback")
            if self.fallback_to == "ranked_discovery" and not isinstance(self.query, str):
                raise ContextRequestError(
                    "fallback_to=ranked_discovery requires query", refusal_reason="invalid_fallback"
                )
        if type(self.offset) is not int or not (0 <= self.offset <= 1000):
            raise ContextRequestError("offset must be in 0..1000")
        if self.query is not None:
            stripped = self.query.strip()
            if not (1 <= len(stripped) <= 200) or len(stripped.encode("utf-8")) > 800:
                raise ContextRequestError("query must be 1..200 stripped chars and <=800 UTF-8 bytes")
            NavigationSearchQuery(query=stripped, offset=self.offset).validate()
        for val, lo, hi, label in (
            (self.max_items, 1, 50, "max_items"),
            (self.locations_per_item, 1, 5, "locations_per_item"),
            (self.expand_seeds, 1, 5, "expand_seeds"),
            (self.node_limit, 1, 32, "node_limit"),
            (self.edge_limit, 1, 64, "edge_limit"),
        ):
            if type(val) is not int or not (lo <= val <= hi):
                raise ContextRequestError(f"{label} must be in {lo}..{hi}")
        if any(ek not in CANONICAL_EDGE_KINDS for ek in self.edge_kinds):
            raise ContextRequestError("unsupported edge_kind")
        if self.freshness not in {"none", "check"}:
            raise ContextRequestError("freshness must be none or check")
        if self.selection_path is not None and (self.bindings or self.path_prefixes):
            raise ContextRequestError("cannot combine selection_path with inline bindings/prefixes")
        if len(set(self.bindings)) > MAX_BINDINGS:
            raise ContextRequestError("too many bindings", refusal_reason="binding_limit_exceeded")
        scan_units = 0
        for bid, pfxs in self.path_prefixes.items():
            if bid not in self.bindings:
                raise ContextRequestError(f"path_prefix for unselected binding: {bid}")
            unique_pfxs = list(dict.fromkeys(pfxs))
            if len(unique_pfxs) > MAX_PREFIXES_PER_BINDING:
                raise ContextRequestError(
                    "too many prefixes per binding", refusal_reason="prefix_limit_exceeded"
                )
            for pfx in unique_pfxs:
                if not valid_source_path_prefix(pfx):
                    raise ContextRequestError(f"invalid path prefix: {pfx!r}")
        for bid in dict.fromkeys(self.bindings):
            pfxs = list(dict.fromkeys(self.path_prefixes.get(bid, ())))
            scan_units += max(1, len(pfxs))
        if scan_units > MAX_SCAN_UNITS:
            raise ContextRequestError(
                "scan_unit_limit_exceeded", refusal_reason="scan_unit_limit_exceeded"
            )
        return self
