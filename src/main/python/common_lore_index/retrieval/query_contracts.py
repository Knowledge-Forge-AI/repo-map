"""Internal CLOE retrieval query-mode contracts and envelopes (ADR 0127 / S1)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import math
from types import MappingProxyType
from typing import Any

QUERY_CONTRACT_VERSION = "cloe-retrieval-query-v1"
DEFAULT_ORDERING_POLICY_VERSION = "deterministic-locator-v1"
ALLOWED_BACKENDS = frozenset({"sqlite", "postgresql", "captured_reference", "native_filesystem"})


class QueryMode(str, Enum):
    """Six canonical retrieval query intentions."""

    EXACT_IDENTITY = "exact_identity"
    CURRENT_LITERAL_ENUMERATION = "current_literal_enumeration"
    LITERAL_CAPTURED_TEXT = "literal_captured_text"
    RANKED_DISCOVERY = "ranked_discovery"
    GRAPH_INVESTIGATION = "graph_investigation"
    SEMANTIC_DISCOVERY = "semantic_discovery"


class CapabilityState(str, Enum):
    """Explicit capability and completeness states for a retrieval query."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    REFUSED = "refused"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    NOT_RUN = "not_run"


class MatchSurface(str, Enum):
    """Representation surface where matches were evaluated."""

    CAPTURED_TEXT = "captured_text"
    STORED_METADATA = "stored_metadata"
    GRAPH_TOPOLOGY = "graph_topology"
    DIRECT_HANDOFF = "direct_handoff"
    NONE = "none"


class UnavailableReason(str, Enum):
    """Standard reasons why a query capability is unavailable."""

    BACKEND_UNSUPPORTED = "backend_unsupported"
    CAPABILITY_NOT_ADMITTED = "capability_not_admitted"
    ARTIFACT_STORE_EXPIRED = "artifact_store_expired"
    PROJECTION_ABSENT = "projection_absent"
    EXTERNAL_TOOL_UNAVAILABLE = "external_tool_unavailable"


_METADATA_ONLY_MODES = frozenset({
    QueryMode.EXACT_IDENTITY,
    QueryMode.CURRENT_LITERAL_ENUMERATION,
    QueryMode.GRAPH_INVESTIGATION,
})


def _validate_relative_path(path: str, field_name: str) -> str:
    if not isinstance(path, str) or not path or "\x00" in path or "\\" in path:
        raise ValueError(f"{field_name} must be a non-empty POSIX relative path")
    if path.startswith("/") or path.startswith("./"):
        raise ValueError(f"{field_name} must not start with '/' or './'")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError(f"{field_name} contains invalid path traversal segment")
    return path


def _check_exact_keys(mapping: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    if not isinstance(mapping, Mapping):
        raise ValueError(f"{label} must be a mapping")
    extra = set(mapping.keys()) - allowed
    if extra:
        raise ValueError(f"{label} has unexpected fields: {sorted(extra)}")


@dataclass(frozen=True)
class EvaluationLocator:
    """Normalized source-binding and relative-path locator with optional span and provenance."""

    binding_id: str
    source_relative_path: str
    start_line: int | None = None
    end_line: int | None = None
    canonical_key: str | None = None
    evidence_key: str | None = None
    link_kind: str | None = None

    def validate(self) -> EvaluationLocator:
        if not isinstance(self.binding_id, str) or not self.binding_id.strip():
            raise ValueError("binding_id must be a non-empty string")
        _validate_relative_path(self.source_relative_path, "source_relative_path")
        if self.start_line is not None and (isinstance(self.start_line, bool) or not isinstance(self.start_line, int) or self.start_line < 1):
            raise ValueError("start_line must be a positive integer when present")
        if self.end_line is not None:
            if isinstance(self.end_line, bool) or not isinstance(self.end_line, int) or self.end_line < 1:
                raise ValueError("end_line must be a positive integer when present")
            if self.start_line is None or self.end_line < self.start_line:
                raise ValueError("end_line requires start_line and end_line >= start_line")
        for opt_name, opt_val in (("canonical_key", self.canonical_key), ("evidence_key", self.evidence_key), ("link_kind", self.link_kind)):
            if opt_val is not None and (not isinstance(opt_val, str) or not opt_val.strip()):
                raise ValueError(f"{opt_name} must be a non-empty string when present")
        return self

    def identity_key(self) -> tuple[str, str, int | None, int | None]:
        return (self.binding_id, self.source_relative_path, self.start_line, self.end_line)

    def file_identity_key(self) -> tuple[str, str]:
        return (self.binding_id, self.source_relative_path)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "binding_id": self.binding_id, "source_relative_path": self.source_relative_path,
            "start_line": self.start_line, "end_line": self.end_line,
            "canonical_key": self.canonical_key, "evidence_key": self.evidence_key, "link_kind": self.link_kind,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> EvaluationLocator:
        _check_exact_keys(raw, frozenset({"binding_id", "source_relative_path", "start_line", "end_line", "canonical_key", "evidence_key", "link_kind"}), "EvaluationLocator")
        return cls(
            binding_id=raw["binding_id"], source_relative_path=raw["source_relative_path"],
            start_line=raw.get("start_line"), end_line=raw.get("end_line"),
            canonical_key=raw.get("canonical_key"), evidence_key=raw.get("evidence_key"), link_kind=raw.get("link_kind"),
        ).validate()


@dataclass(frozen=True)
class QueryScope:
    """Publication and source-binding scope for a retrieval query."""

    graph_id: str
    backend: str
    publication_bundle_id: str | None = None
    snapshot_manifest_id: str | None = None
    selected_binding_ids: tuple[str, ...] = ()
    source_path_prefix: str | None = None

    def validate(self) -> QueryScope:
        if not isinstance(self.graph_id, str) or not self.graph_id.strip():
            raise ValueError("graph_id must be a non-empty string")
        if self.backend not in ALLOWED_BACKENDS:
            raise ValueError(f"unsupported backend: {self.backend!r}")
        for name, val in (("publication_bundle_id", self.publication_bundle_id), ("snapshot_manifest_id", self.snapshot_manifest_id), ("source_path_prefix", self.source_path_prefix)):
            if val is not None and (not isinstance(val, str) or not val.strip()):
                raise ValueError(f"{name} must be a non-empty string when present")
        if not isinstance(self.selected_binding_ids, tuple) or any(not isinstance(b, str) or not b.strip() for b in self.selected_binding_ids):
            raise ValueError("selected_binding_ids must be a tuple of non-empty strings")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "graph_id": self.graph_id, "backend": self.backend,
            "publication_bundle_id": self.publication_bundle_id, "snapshot_manifest_id": self.snapshot_manifest_id,
            "selected_binding_ids": list(self.selected_binding_ids), "source_path_prefix": self.source_path_prefix,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> QueryScope:
        _check_exact_keys(raw, frozenset({"graph_id", "backend", "publication_bundle_id", "snapshot_manifest_id", "selected_binding_ids", "source_path_prefix"}), "QueryScope")
        raw_bindings = raw.get("selected_binding_ids", ())
        if not isinstance(raw_bindings, (list, tuple)):
            raise ValueError("selected_binding_ids must be a sequence")
        return cls(
            graph_id=raw["graph_id"], backend=raw["backend"],
            publication_bundle_id=raw.get("publication_bundle_id"), snapshot_manifest_id=raw.get("snapshot_manifest_id"),
            selected_binding_ids=tuple(raw_bindings), source_path_prefix=raw.get("source_path_prefix"),
        ).validate()


@dataclass(frozen=True)
class OmissionRecord:
    """Explicit disclosure of an omitted or excluded binding or file within scope."""

    binding_id: str
    source_relative_path: str | None
    reason_code: str
    detail: str

    def validate(self) -> OmissionRecord:
        if not isinstance(self.binding_id, str) or not self.binding_id.strip():
            raise ValueError("binding_id must be a non-empty string")
        if self.source_relative_path is not None:
            _validate_relative_path(self.source_relative_path, "source_relative_path")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip() or not isinstance(self.detail, str) or not self.detail.strip():
            raise ValueError("reason_code and detail must be non-empty strings")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"binding_id": self.binding_id, "source_relative_path": self.source_relative_path, "reason_code": self.reason_code, "detail": self.detail}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> OmissionRecord:
        _check_exact_keys(raw, frozenset({"binding_id", "source_relative_path", "reason_code", "detail"}), "OmissionRecord")
        return cls(binding_id=raw["binding_id"], source_relative_path=raw.get("source_relative_path"), reason_code=raw["reason_code"], detail=raw["detail"]).validate()


@dataclass(frozen=True)
class FallbackDisclosure:
    """Caller-selected mode fallback disclosure; silent mode substitution is forbidden."""

    caller_selected: bool
    from_mode: QueryMode
    to_mode: QueryMode
    reason_code: str

    def validate(self) -> FallbackDisclosure:
        if self.caller_selected is not True:
            raise ValueError("fallback requires caller_selected=True; silent fallback is forbidden")
        if not isinstance(self.from_mode, QueryMode) or not isinstance(self.to_mode, QueryMode) or self.from_mode == self.to_mode:
            raise ValueError("from_mode and to_mode must be distinct QueryMode instances")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise ValueError("reason_code must be a non-empty string")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"caller_selected": self.caller_selected, "from_mode": self.from_mode.value, "to_mode": self.to_mode.value, "reason_code": self.reason_code}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> FallbackDisclosure:
        _check_exact_keys(raw, frozenset({"caller_selected", "from_mode", "to_mode", "reason_code"}), "FallbackDisclosure")
        return cls(caller_selected=raw["caller_selected"], from_mode=QueryMode(raw["from_mode"]), to_mode=QueryMode(raw["to_mode"]), reason_code=raw["reason_code"]).validate()


@dataclass(frozen=True)
class QueryHit:
    """One ranked or ordered match returned in a QueryEnvelope."""

    locator: EvaluationLocator
    match_surface: MatchSurface
    rank: int
    score: float | None = None
    snippet_digest: str | None = None
    chunk_id: str | None = None
    representation_version: str | None = None
    artifact_privacy: str | None = None

    def validate(self) -> QueryHit:
        self.locator.validate()
        if not isinstance(self.match_surface, MatchSurface) or self.match_surface == MatchSurface.NONE:
            raise ValueError("QueryHit match_surface must be a concrete MatchSurface")
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1:
            raise ValueError("rank must be a positive integer")
        if self.score is not None and (isinstance(self.score, bool) or not isinstance(self.score, (int, float)) or not math.isfinite(self.score)):
            raise ValueError("score must be numeric when present")
        for value in (self.snippet_digest, self.chunk_id, self.representation_version, self.artifact_privacy):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError("optional hit provenance must be non-empty strings")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "locator": self.locator.to_dict(), "match_surface": self.match_surface.value, "rank": self.rank,
            "score": float(self.score) if self.score is not None else None, "snippet_digest": self.snippet_digest,
            "chunk_id": self.chunk_id, "representation_version": self.representation_version, "artifact_privacy": self.artifact_privacy,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> QueryHit:
        _check_exact_keys(raw, frozenset({"locator", "match_surface", "rank", "score", "snippet_digest", "chunk_id", "representation_version", "artifact_privacy"}), "QueryHit")
        return cls(
            locator=EvaluationLocator.from_mapping(raw["locator"]), match_surface=MatchSurface(raw["match_surface"]),
            rank=raw["rank"], score=raw.get("score"),
            snippet_digest=raw.get("snippet_digest"), chunk_id=raw.get("chunk_id"),
            representation_version=raw.get("representation_version"), artifact_privacy=raw.get("artifact_privacy"),
        ).validate()


@dataclass(frozen=True)
class QueryEnvelope:
    """Internal versioned retrieval envelope (cloe-retrieval-query-v1)."""

    contract_version: str
    requested_mode: QueryMode
    effective_mode: QueryMode
    match_surface: MatchSurface
    scope: QueryScope
    ordering_policy_version: str
    capability_state: CapabilityState
    hits: tuple[QueryHit, ...] = ()
    omissions: tuple[OmissionRecord, ...] = ()
    scope_complete: bool = False
    fallback: FallbackDisclosure | None = None
    unavailable_reason: str | None = None
    refusal_code: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def validate(self) -> QueryEnvelope:
        if self.contract_version != QUERY_CONTRACT_VERSION:
            raise ValueError(f"unsupported contract_version: {self.contract_version!r}")
        if not isinstance(self.requested_mode, QueryMode) or not isinstance(self.effective_mode, QueryMode):
            raise ValueError("requested_mode and effective_mode must be QueryMode")
        if not isinstance(self.match_surface, MatchSurface) or not isinstance(self.capability_state, CapabilityState):
            raise ValueError("match_surface and capability_state must be valid enum members")
        self.scope.validate()
        if not isinstance(self.scope_complete, bool):
            raise ValueError("scope_complete must be a boolean")
        if not isinstance(self.ordering_policy_version, str) or not self.ordering_policy_version.strip():
            raise ValueError("ordering_policy_version must be a non-empty string")
        if self.requested_mode != self.effective_mode:
            if self.fallback is None:
                raise ValueError("requested_mode != effective_mode requires explicit fallback disclosure")
            self.fallback.validate()
            if (self.fallback.from_mode, self.fallback.to_mode) != (self.requested_mode, self.effective_mode):
                raise ValueError("fallback modes must match requested_mode and effective_mode")
        elif self.fallback is not None:
            raise ValueError("fallback must be None when requested_mode == effective_mode")
        if self.effective_mode in _METADATA_ONLY_MODES and self.match_surface == MatchSurface.CAPTURED_TEXT:
            raise ValueError(f"{self.effective_mode.value} cannot claim captured_text surface")
        for idx, hit in enumerate(self.hits, start=1):
            hit.validate()
            if hit.rank != idx or hit.match_surface != self.match_surface:
                raise ValueError("hits must have contiguous 1..N ranks and matching surface")
        for omission in self.omissions:
            omission.validate()
        if self.omissions and self.scope_complete:
            raise ValueError("scope_complete cannot be True when omissions are present")
        if self.capability_state == CapabilityState.AVAILABLE and (self.unavailable_reason is not None or self.refusal_code is not None):
            raise ValueError("available state cannot set unavailable_reason or refusal_code")
        if self.capability_state == CapabilityState.UNAVAILABLE and (not self.unavailable_reason or self.hits or self.scope_complete):
            raise ValueError("unavailable state requires unavailable_reason, empty hits, and scope_complete=False")
        if self.capability_state == CapabilityState.REFUSED and (not self.refusal_code or self.hits or self.scope_complete):
            raise ValueError("refused state requires refusal_code, empty hits, and scope_complete=False")
        if self.capability_state in {CapabilityState.STALE, CapabilityState.FAILED, CapabilityState.NOT_RUN} and (self.hits or self.scope_complete):
            raise ValueError(f"{self.capability_state.value} requires empty hits and scope_complete=False")
        return self

    def establishes_absence(self) -> bool:
        self.validate()
        return self.capability_state == CapabilityState.AVAILABLE and self.scope_complete is True and len(self.hits) == 0

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "contract_version": self.contract_version, "requested_mode": self.requested_mode.value,
            "effective_mode": self.effective_mode.value, "match_surface": self.match_surface.value,
            "scope": self.scope.to_dict(), "ordering_policy_version": self.ordering_policy_version,
            "capability_state": self.capability_state.value, "hits": [hit.to_dict() for hit in self.hits],
            "omissions": [omission.to_dict() for omission in self.omissions], "scope_complete": self.scope_complete,
            "fallback": self.fallback.to_dict() if self.fallback is not None else None,
            "unavailable_reason": self.unavailable_reason, "refusal_code": self.refusal_code, "provenance": dict(self.provenance),
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> QueryEnvelope:
        _check_exact_keys(raw, frozenset({"contract_version", "requested_mode", "effective_mode", "match_surface", "scope", "ordering_policy_version", "capability_state", "hits", "omissions", "scope_complete", "fallback", "unavailable_reason", "refusal_code", "provenance"}), "QueryEnvelope")
        return cls(
            contract_version=raw["contract_version"], requested_mode=QueryMode(raw["requested_mode"]),
            effective_mode=QueryMode(raw["effective_mode"]), match_surface=MatchSurface(raw["match_surface"]),
            scope=QueryScope.from_mapping(raw["scope"]), ordering_policy_version=raw["ordering_policy_version"],
            capability_state=CapabilityState(raw["capability_state"]),
            hits=tuple(QueryHit.from_mapping(item) for item in raw.get("hits", ())),
            omissions=tuple(OmissionRecord.from_mapping(item) for item in raw.get("omissions", ())),
            scope_complete=raw.get("scope_complete", False),
            fallback=FallbackDisclosure.from_mapping(raw["fallback"]) if raw.get("fallback") is not None else None,
            unavailable_reason=raw.get("unavailable_reason"), refusal_code=raw.get("refusal_code"),
            provenance=MappingProxyType(raw.get("provenance", {})),
        ).validate()


def unavailable_envelope(
    *, requested_mode: QueryMode, scope: QueryScope, reason: str = UnavailableReason.BACKEND_UNSUPPORTED.value, provenance: Mapping[str, Any] | None = None
) -> QueryEnvelope:
    return QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION, requested_mode=requested_mode, effective_mode=requested_mode,
        match_surface=MatchSurface.NONE, scope=scope, ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.UNAVAILABLE, unavailable_reason=reason, provenance=MappingProxyType(dict(provenance or {})),
    ).validate()


def refused_envelope(
    *, requested_mode: QueryMode, scope: QueryScope, refusal_code: str, omissions: tuple[OmissionRecord, ...] = (), provenance: Mapping[str, Any] | None = None
) -> QueryEnvelope:
    return QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION, requested_mode=requested_mode, effective_mode=requested_mode,
        match_surface=MatchSurface.NONE, scope=scope, ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.REFUSED, refusal_code=refusal_code, omissions=omissions, provenance=MappingProxyType(dict(provenance or {})),
    ).validate()


def stale_envelope(*, requested_mode: QueryMode, scope: QueryScope, detail: str) -> QueryEnvelope:
    return QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION, requested_mode=requested_mode, effective_mode=requested_mode,
        match_surface=MatchSurface.NONE, scope=scope, ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.STALE, provenance=MappingProxyType({"stale_detail": detail}),
    ).validate()
