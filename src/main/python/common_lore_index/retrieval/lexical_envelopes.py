"""QueryEnvelope construction and policy/fence classification for cloe_lexical."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from common_lore_index.retrieval.lexical_policy import (
    LEXICAL_ALIAS_SPLIT_VERSION, LEXICAL_NORMALIZATION_FLAGS,
    LEXICAL_RANKING_FUNCTION, LEXICAL_REPRESENTATION_VERSION,
    LEXICAL_TEXT_CONFIG, LexicalGenerationPolicy,
    normalize_lexical_path_prefix,
)
from common_lore_index.retrieval.projection_chunks import frame_digest
from common_lore_index.retrieval.projection_policy import ExclusionReason
from common_lore_index.retrieval.query_contracts import (
    CapabilityState, DEFAULT_ORDERING_POLICY_VERSION, EvaluationLocator,
    FallbackDisclosure, MatchSurface, OmissionRecord, QUERY_CONTRACT_VERSION,
    QueryEnvelope, QueryHit, QueryMode, QueryScope, UnavailableReason,
    refused_envelope, stale_envelope, unavailable_envelope,
)
from common_lore_index.storage.lexical_query_sql import (
    ALLOWED_LEXICAL_QUERY_STYLES, RawLexicalQueryRow,
)

FTS_ORDERING_POLICY_VERSION = "ts-rank-cd-deterministic-v1"


@dataclass(frozen=True)
class LexicalQueryRequest:
    """Validated request for a PostgreSQL cloe_lexical query."""

    query: str
    query_style: str = "ranked_terms"
    requested_mode: QueryMode | None = None
    selected_binding_ids: tuple[str, ...] = ()
    source_path_prefix: str | None = None
    path_prefixes: tuple[str, ...] = ()
    limit: int = 50
    offset: int = 0
    fallback: FallbackDisclosure | None = None

    def effective_query_mode(self) -> QueryMode:
        if self.query_style == "literal_captured_text":
            return QueryMode.LITERAL_CAPTURED_TEXT
        return QueryMode.RANKED_DISCOVERY

    def resolved_requested_mode(self) -> QueryMode:
        if self.fallback is not None:
            return self.fallback.from_mode
        if self.requested_mode is not None:
            return self.requested_mode
        return self.effective_query_mode()

    def effective_path_prefixes(self) -> tuple[str, ...]:
        prefixes: list[str] = []
        if self.source_path_prefix is not None:
            prefixes.append(normalize_lexical_path_prefix(self.source_path_prefix))
        for p in self.path_prefixes:
            normalized = normalize_lexical_path_prefix(p)
            if normalized not in prefixes:
                prefixes.append(normalized)
        return tuple(prefixes)

    def validate(self) -> LexicalQueryRequest:
        if not isinstance(self.query, str) or not self.query or "\x00" in self.query:
            raise ValueError("query must be a non-empty string without NUL")
        if not self.selected_binding_ids or any(
            not isinstance(b, str) or not b.strip() for b in self.selected_binding_ids
        ):
            raise ValueError("selected_binding_ids must be a non-empty tuple of binding IDs")
        if self.query_style not in ALLOWED_LEXICAL_QUERY_STYLES:
            raise ValueError(f"unsupported lexical query_style: {self.query_style!r}")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit < 1 or self.limit > 100:
            raise ValueError("limit must be an integer between 1 and 100")
        if isinstance(self.offset, bool) or not isinstance(self.offset, int) or self.offset < 0 or self.offset > 1000:
            raise ValueError("offset must be an integer between 0 and 1000")
        self.effective_path_prefixes()
        eff_mode = self.effective_query_mode()
        if self.fallback is not None:
            self.fallback.validate()
            if self.fallback.to_mode != eff_mode:
                raise ValueError(
                    f"fallback to_mode {self.fallback.to_mode.value!r} does not match "
                    f"query_style {self.query_style!r} effective mode {eff_mode.value!r}"
                )
            if self.requested_mode is not None and self.requested_mode != self.fallback.from_mode:
                raise ValueError("requested_mode must match fallback.from_mode")
        elif self.requested_mode is not None and self.requested_mode != eff_mode:
            raise ValueError("requested_mode != effective_mode requires explicit fallback disclosure")
        return self


@dataclass(frozen=True)
class LexicalScopeResolution:
    """Pre-execution scope resolution before opening a PostgreSQL lexical query."""

    scope: QueryScope
    requested_mode: QueryMode
    effective_mode: QueryMode
    admitted_binding_ids: tuple[str, ...]
    omission_binding_ids: tuple[str, ...]
    pre_omissions: tuple[OmissionRecord, ...]
    immediate_envelope: QueryEnvelope | None = None


def resolve_lexical_query_scope(
    *,
    graph_id: str,
    lexical_policy: LexicalGenerationPolicy,
    request: LexicalQueryRequest,
    publication_bundle_id: str | None = None,
    snapshot_manifest_id: str | None = None,
) -> LexicalScopeResolution:
    """Resolve binding scope and detect immediate policy refusals before DB query."""
    request.validate()
    req_mode = request.resolved_requested_mode()
    eff_mode = request.effective_query_mode()
    prefixes = request.effective_path_prefixes()
    primary_prefix = prefixes[0] if len(prefixes) == 1 else None
    requested_bindings = (
        request.selected_binding_ids if request.selected_binding_ids else lexical_policy.admitted_binding_ids
    )
    scope = QueryScope(
        graph_id=graph_id, backend="postgresql",
        publication_bundle_id=publication_bundle_id, snapshot_manifest_id=snapshot_manifest_id,
        selected_binding_ids=requested_bindings, source_path_prefix=primary_prefix,
    ).validate()
    prov = {"policy_digest": lexical_policy.policy_digest, "query_style": request.query_style,
            "path_prefixes": list(prefixes), "path_prefix_match": "any"}

    if lexical_policy.resolved_graph_privacy != "public-dev":
        env = refused_envelope(
            requested_mode=req_mode, scope=scope,
            refusal_code=ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value, provenance=prov,
        )
        return LexicalScopeResolution(scope, req_mode, eff_mode, (), (), (), env)

    known_bindings = {b.binding_id: b for b in lexical_policy.body_policy.bindings.values()}
    pre_omissions: list[OmissionRecord] = []
    admitted_for_query: list[str] = []
    unauthorized_reasons: list[str] = []

    if request.selected_binding_ids:
        for b_id in request.selected_binding_ids:
            if b_id in lexical_policy.excluded_binding_reasons:
                r_code = lexical_policy.excluded_binding_reasons[b_id]
                unauthorized_reasons.append(r_code)
                detail = f"binding {b_id} excluded from lexical body query ({r_code})"
                pre_omissions.append(OmissionRecord(b_id, None, r_code, detail).validate())
            elif b_id not in known_bindings:
                r_code = ExclusionReason.UNRESOLVED_INHERIT_POLICY.value
                unauthorized_reasons.append(r_code)
                detail = f"binding {b_id} is not a configured source binding"
                pre_omissions.append(OmissionRecord(b_id, None, r_code, detail).validate())
            else:
                admitted_for_query.append(b_id)
        if len(unauthorized_reasons) == len(request.selected_binding_ids):
            env = refused_envelope(
                requested_mode=req_mode, scope=scope, refusal_code=unauthorized_reasons[0],
                omissions=tuple(pre_omissions), provenance=prov,
            )
            return LexicalScopeResolution(scope, req_mode, eff_mode, (), (), tuple(pre_omissions), env)
    else:
        admitted_for_query = list(lexical_policy.admitted_binding_ids)
        if not admitted_for_query:
            if lexical_policy.excluded_binding_reasons:
                for b_id, r_code in sorted(lexical_policy.excluded_binding_reasons.items()):
                    unauthorized_reasons.append(r_code)
                    detail = f"binding {b_id} excluded from lexical body query ({r_code})"
                    pre_omissions.append(OmissionRecord(b_id, None, r_code, detail).validate())
                env = refused_envelope(
                    requested_mode=req_mode, scope=scope, refusal_code=unauthorized_reasons[0],
                    omissions=tuple(pre_omissions), provenance=prov,
                )
                return LexicalScopeResolution(scope, req_mode, eff_mode, (), (), tuple(pre_omissions), env)
            env = unavailable_envelope(
                requested_mode=req_mode, scope=scope,
                reason=UnavailableReason.PROJECTION_ABSENT.value, provenance=prov,
            )
            return LexicalScopeResolution(scope, req_mode, eff_mode, (), (), (), env)

    return LexicalScopeResolution(
        scope, req_mode, eff_mode, tuple(admitted_for_query),
        tuple(admitted_for_query), tuple(pre_omissions), None,
    )


def build_lexical_query_envelope(
    *,
    resolution: LexicalScopeResolution,
    lexical_policy: LexicalGenerationPolicy,
    request: LexicalQueryRequest,
    raw_row: RawLexicalQueryRow,
) -> QueryEnvelope:
    """Construct a validated QueryEnvelope from a single-statement lexical query row."""
    scope = QueryScope(
        graph_id=resolution.scope.graph_id, backend="postgresql",
        publication_bundle_id=raw_row.publication_bundle_id or resolution.scope.publication_bundle_id,
        snapshot_manifest_id=raw_row.snapshot_manifest_id or resolution.scope.snapshot_manifest_id,
        selected_binding_ids=resolution.scope.selected_binding_ids,
        source_path_prefix=resolution.scope.source_path_prefix,
    ).validate()
    req_mode = resolution.requested_mode
    eff_mode = resolution.effective_mode
    base_prov: dict[str, Any] = {
        "policy_digest": lexical_policy.policy_digest,
        "query_style": request.query_style,
        "representation_version": LEXICAL_REPRESENTATION_VERSION,
        "text_config_regconfig": LEXICAL_TEXT_CONFIG,
        "ranking_function": LEXICAL_RANKING_FUNCTION,
        "normalization_flags": LEXICAL_NORMALIZATION_FLAGS,
        "alias_split_rule_version": LEXICAL_ALIAS_SPLIT_VERSION,
        "fence_status": raw_row.fence_status,
        "path_prefixes": list(request.effective_path_prefixes()),
        "path_prefix_match": "any",
    }
    if raw_row.lexical_generation_id is not None:
        base_prov["lexical_generation_id"] = raw_row.lexical_generation_id
    if raw_row.run_id is not None:
        base_prov["accepted_run_id"] = raw_row.run_id

    status = raw_row.fence_status
    if status == "refused_non_public_lexical_generation":
        return refused_envelope(
            requested_mode=req_mode, scope=scope,
            refusal_code=ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value,
            omissions=resolution.pre_omissions, provenance=base_prov,
        )
    if status.startswith("refused_reclassified:"):
        ref_code = status.split(":", 1)[1] or ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED.value
        return refused_envelope(
            requested_mode=req_mode, scope=scope,
            refusal_code=ref_code,
            omissions=resolution.pre_omissions, provenance=base_prov,
        )
    if status.startswith("unavailable_"):
        if raw_row.latest_revocation_reason is not None:
            base_prov["revocation_reason"] = raw_row.latest_revocation_reason
        if raw_row.latest_generation_id is not None:
            base_prov["latest_generation_id"] = raw_row.latest_generation_id
        return unavailable_envelope(
            requested_mode=req_mode, scope=scope,
            reason=UnavailableReason.PROJECTION_ABSENT.value, provenance=base_prov,
        )
    if status != "ok":
        return stale_envelope(requested_mode=req_mode, scope=scope, detail=status)
    if raw_row.empty_tsquery:
        return refused_envelope(
            requested_mode=req_mode, scope=scope, refusal_code="empty_lexical_tsquery",
            omissions=resolution.pre_omissions, provenance=base_prov,
        )

    omissions: list[OmissionRecord] = list(resolution.pre_omissions)
    seen_omissions = {(om.binding_id, om.source_relative_path, om.reason_code) for om in omissions}
    for raw_om in raw_row.omissions:
        rel_p = str(raw_om["source_relative_path"]) if raw_om.get("source_relative_path") is not None else None
        om = OmissionRecord(str(raw_om["binding_id"]), rel_p, str(raw_om["reason_code"]), str(raw_om["detail"])).validate()
        key = (om.binding_id, om.source_relative_path, om.reason_code)
        if key not in seen_omissions:
            seen_omissions.add(key)
            omissions.append(om)

    for capped_b_id, capped_path in raw_row.capped_files:
        detail = f"literal occurrences in {capped_path} exceeded per-file cap"
        om = OmissionRecord(capped_b_id, capped_path, "literal_occurrence_cap_exceeded", detail).validate()
        key = (om.binding_id, om.source_relative_path, om.reason_code)
        if key not in seen_omissions:
            seen_omissions.add(key)
            omissions.append(om)

    has_more = (request.offset + request.limit) < raw_row.total_matches
    if has_more or request.offset > 0:
        b_ref = resolution.scope.selected_binding_ids[0] if resolution.scope.selected_binding_ids else "scope"
        detail = f"returned {len(raw_row.hits)} of {raw_row.total_matches} matches (offset={request.offset}, limit={request.limit})"
        omissions.append(OmissionRecord(b_ref, None, "result_page_bounded", detail).validate())

    if raw_row.candidate_overflow:
        b_ref = resolution.scope.selected_binding_ids[0] if resolution.scope.selected_binding_ids else "scope"
        ov_reason = (
            "literal_scan_budget_exceeded"
            if request.query_style == "literal_captured_text"
            else "ranked_candidate_budget_exceeded"
        )
        omissions.append(
            OmissionRecord(
                b_ref,
                None,
                ov_reason,
                f"query candidate evaluation exceeded {ov_reason} ceiling",
            ).validate()
        )

    literal_digest = frame_digest("sha256", (request.query,)) if request.query_style == "literal_captured_text" else None
    hits: list[QueryHit] = []
    for rank, raw_hit in enumerate(raw_row.hits, start=1):
        locator = EvaluationLocator(
            binding_id=str(raw_hit["binding_id"]),
            source_relative_path=str(raw_hit["source_relative_path"]),
            start_line=int(raw_hit["start_line"]),
            end_line=int(raw_hit["end_line"]),
            canonical_key=str(raw_hit["canonical_key"]) if raw_hit.get("canonical_key") is not None else None,
            evidence_key=str(raw_hit["evidence_key"]) if raw_hit.get("evidence_key") is not None else None,
            link_kind=str(raw_hit["link_kind"]) if raw_hit.get("link_kind") is not None else None,
        ).validate()
        hits.append(
            QueryHit(
                locator=locator, match_surface=MatchSurface.CAPTURED_TEXT, rank=rank,
                score=float(raw_hit.get("score", 1.0)),
                snippet_digest=literal_digest or str(raw_hit.get("chunk_sha256") or ""),
                chunk_id=str(raw_hit["chunk_id"]) if raw_hit.get("chunk_id") is not None else None,
                representation_version=str(raw_hit.get("representation_version") or LEXICAL_REPRESENTATION_VERSION),
                artifact_privacy=str(raw_hit.get("artifact_privacy") or "public-dev"),
            ).validate()
        )

    is_partial = len(omissions) > 0
    cap_state = CapabilityState.PARTIAL if is_partial else CapabilityState.AVAILABLE
    ordering_version = (
        DEFAULT_ORDERING_POLICY_VERSION
        if request.query_style == "literal_captured_text"
        else FTS_ORDERING_POLICY_VERSION
    )
    base_prov["total_matches_before_paging"] = raw_row.total_matches
    return QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION, requested_mode=req_mode, effective_mode=eff_mode,
        match_surface=MatchSurface.CAPTURED_TEXT, scope=scope, ordering_policy_version=ordering_version,
        capability_state=cap_state, hits=tuple(hits), omissions=tuple(omissions),
        scope_complete=not is_partial, fallback=request.fallback, provenance=MappingProxyType(base_prov),
    ).validate()


__all__ = [
    "FTS_ORDERING_POLICY_VERSION", "LexicalQueryRequest", "LexicalScopeResolution",
    "build_lexical_query_envelope", "resolve_lexical_query_scope",
]
