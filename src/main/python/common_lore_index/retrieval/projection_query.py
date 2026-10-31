"""Query execution over the in-memory captured-input text projection reference (S1)."""

from __future__ import annotations

import bisect
from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType

from common_lore_index.retrieval.projection_build import (
    CapturedTextProjection,
    ProjectedFileRecord,
)
from common_lore_index.retrieval.projection_chunks import frame_digest
from common_lore_index.retrieval.projection_evidence import links_for_line_span
from common_lore_index.retrieval.publication_binding import AcceptedPublicationReference
from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    DEFAULT_ORDERING_POLICY_VERSION,
    EvaluationLocator,
    FallbackDisclosure,
    MatchSurface,
    OmissionRecord,
    QUERY_CONTRACT_VERSION,
    QueryEnvelope,
    QueryHit,
    QueryMode,
    QueryScope,
    refused_envelope,
    stale_envelope,
)


@dataclass(frozen=True)
class CapturedTextQueryRequest:
    """Bounded literal captured-text query request."""

    query: str
    selected_binding_ids: tuple[str, ...] = ()
    source_path_prefix: str | None = None
    limit: int = 50
    offset: int = 0
    fallback: FallbackDisclosure | None = None

    def validate(self) -> CapturedTextQueryRequest:
        if not isinstance(self.query, str) or not self.query or "\x00" in self.query:
            raise ValueError("query must be a non-empty string without NUL")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit < 1 or self.limit > 500:
            raise ValueError("limit must be an integer between 1 and 500")
        if isinstance(self.offset, bool) or not isinstance(self.offset, int) or self.offset < 0 or self.offset > 10000:
            raise ValueError("offset must be an integer between 0 and 10000")
        if self.fallback is not None:
            self.fallback.validate()
            if self.fallback.to_mode != QueryMode.LITERAL_CAPTURED_TEXT:
                raise ValueError("projection fallback target must be literal_captured_text")
        return self


def _resolve_current_reference(
    current: AcceptedPublicationReference | Callable[[], AcceptedPublicationReference | None] | None,
) -> tuple[bool, AcceptedPublicationReference | None]:
    if current is None:
        return False, None
    if callable(current):
        return True, current()
    return True, current


def _find_file_matches(
    file_rec: ProjectedFileRecord,
    needle: str,
    *,
    max_materialize: int | None = None,
    skip_matches: int = 0,
) -> tuple[list[tuple[int, int, int, str, str]], int]:
    """Find literal occurrences across contiguous chunks of one file without crossing files."""
    if not file_rec.chunks or file_rec.chunks[0].is_empty_file_record:
        return [], 0
    full_text = "".join(c.content_text for c in file_rec.chunks)
    if needle not in full_text:
        return [], 0

    line_starts: list[int] | None = None
    chunk_char_ends: list[int] | None = None
    snippet_digest = frame_digest("sha256", (needle,))

    matches: list[tuple[int, int, int, str, str]] = []
    total_count = 0
    start_pos = 0
    needle_len = len(needle)
    while True:
        found = full_text.find(needle, start_pos)
        if found == -1:
            break
        total_count += 1
        if total_count > skip_matches and (max_materialize is None or len(matches) < max_materialize):
            if line_starts is None or chunk_char_ends is None:
                line_starts = [0]
                for idx, ch in enumerate(full_text):
                    if ch == "\n" and idx + 1 < len(full_text):
                        line_starts.append(idx + 1)
                chunk_char_ends = []
                running_chars = 0
                for chunk in file_rec.chunks:
                    running_chars += len(chunk.content_text)
                    chunk_char_ends.append(running_chars)
            end_pos = found + needle_len - 1
            end_line_pos = end_pos - 1 if (full_text[end_pos] == "\n" and end_pos > found) else end_pos
            start_line = bisect.bisect_right(line_starts, found)
            end_line = bisect.bisect_right(line_starts, end_line_pos)
            chunk_idx = bisect.bisect_right(chunk_char_ends, found)
            if chunk_idx >= len(file_rec.chunks):
                chunk_idx = len(file_rec.chunks) - 1
            covering_chunk = file_rec.chunks[chunk_idx]
            matches.append((start_line, end_line, found, covering_chunk.chunk_id, snippet_digest))
        start_pos = found + 1
    return matches, total_count


def query_captured_text(
    projection: CapturedTextProjection,
    request: CapturedTextQueryRequest,
    *,
    current_accepted_reference: (
        AcceptedPublicationReference
        | Callable[[], AcceptedPublicationReference | None]
        | None
    ) = None,
) -> QueryEnvelope:
    """Execute a literal_captured_text query over a verified in-memory projection."""
    request.validate()
    requested_mode = request.fallback.from_mode if request.fallback is not None else QueryMode.LITERAL_CAPTURED_TEXT
    requested_bindings = (
        request.selected_binding_ids
        if request.selected_binding_ids
        else tuple(sorted(projection.policy.selected_binding_ids))
    )
    scope = QueryScope(
        graph_id=projection.accepted_reference.graph_id,
        backend="captured_reference",
        publication_bundle_id=projection.publication_bundle_id,
        snapshot_manifest_id=projection.snapshot_manifest_id,
        selected_binding_ids=requested_bindings,
        source_path_prefix=request.source_path_prefix,
    ).validate()

    checked_current, actual_current = _resolve_current_reference(current_accepted_reference)
    if checked_current and not projection.accepted_reference.matches_current(actual_current):
        return stale_envelope(
            requested_mode=requested_mode,
            scope=scope,
            detail="accepted publication advanced or disappeared before query completion",
        )

    req_binding_set = frozenset(requested_bindings)
    excluded_binding_map = {eb.binding_id: eb for eb in projection.excluded_bindings}
    omissions: list[OmissionRecord] = []

    unauthorized_requested: list[str] = []
    for b_id in requested_bindings:
        if b_id in excluded_binding_map:
            eb = excluded_binding_map[b_id]
            unauthorized_requested.append(eb.reason.value)
            omissions.append(
                OmissionRecord(
                    binding_id=b_id,
                    source_relative_path=None,
                    reason_code=eb.reason.value,
                    detail=f"binding {b_id} excluded from body projection ({eb.reason.value})",
                )
            )
        elif b_id not in projection.policy.bindings:
            unauthorized_requested.append("unresolved_inherit_policy")
            omissions.append(
                OmissionRecord(
                    binding_id=b_id,
                    source_relative_path=None,
                    reason_code="unresolved_inherit_policy",
                    detail=f"binding {b_id} has no resolved projection policy",
                )
            )

    if requested_bindings and len(unauthorized_requested) == len(requested_bindings):
        return refused_envelope(
            requested_mode=requested_mode,
            scope=scope,
            refusal_code=unauthorized_requested[0],
            omissions=tuple(omissions),
            provenance={"projection_digest": projection.projection_digest},
        )

    prefix = request.source_path_prefix
    for ex_file in projection.excluded_files:
        if ex_file.binding_id not in req_binding_set:
            continue
        if ex_file.binding_id in excluded_binding_map:
            continue
        if prefix is not None and not ex_file.source_relative_path.startswith(prefix):
            continue
        omissions.append(
            OmissionRecord(
                binding_id=ex_file.binding_id,
                source_relative_path=ex_file.source_relative_path,
                reason_code=ex_file.reason.value,
                detail=f"file excluded from body projection ({ex_file.reason.value})",
            )
        )

    raw_candidates: list[tuple[ProjectedFileRecord, int, int, int, str, str]] = []
    total_matches = 0
    ordered_files = sorted(
        projection.projected_files, key=lambda file: (file.binding_id, file.source_relative_path)
    )
    for file_rec in ordered_files:
        if file_rec.binding_id not in req_binding_set:
            continue
        if prefix is not None and not file_rec.source_relative_path.startswith(prefix):
            continue
        if file_rec.truncated:
            omissions.append(
                OmissionRecord(
                    binding_id=file_rec.binding_id,
                    source_relative_path=file_rec.source_relative_path,
                    reason_code="projected_prefix_truncated",
                    detail=(
                        f"projected prefix truncated at {file_rec.projected_byte_length} "
                        f"of {file_rec.normalized_byte_length} normalized bytes"
                    ),
                )
            )
        remaining = max(0, request.limit - len(raw_candidates))
        file_matches, file_total = _find_file_matches(
            file_rec,
            request.query,
            max_materialize=remaining,
            skip_matches=max(0, request.offset - total_matches),
        )
        total_matches += file_total
        for start_line, end_line, char_pos, chunk_id, snippet_digest in file_matches:
            raw_candidates.append(
                (file_rec, start_line, end_line, char_pos, chunk_id, snippet_digest)
            )

    paged = raw_candidates
    has_more = (request.offset + request.limit) < total_matches
    if has_more or request.offset > 0:
        omissions.append(
            OmissionRecord(
                binding_id=requested_bindings[0] if requested_bindings else "scope",
                source_relative_path=None,
                reason_code="result_page_bounded",
                detail=f"returned {len(paged)} of {total_matches} matches (offset={request.offset}, limit={request.limit})",
            )
        )

    hits: list[QueryHit] = []
    for rank, (file_rec, start_line, end_line, _pos, chunk_id, snippet_digest) in enumerate(
        paged,
        start=1,
    ):
        overlapping_links = links_for_line_span(file_rec.evidence_links, start_line, end_line)
        primary_link = overlapping_links[0] if overlapping_links else None
        locator = EvaluationLocator(
            binding_id=file_rec.binding_id,
            source_relative_path=file_rec.source_relative_path,
            start_line=start_line,
            end_line=end_line,
            canonical_key=primary_link.canonical_node_key if primary_link is not None else None,
            evidence_key=primary_link.evidence_key if primary_link is not None else None,
            link_kind=primary_link.link_kind if primary_link is not None else None,
        ).validate()
        hits.append(
            QueryHit(
                locator=locator,
                match_surface=MatchSurface.CAPTURED_TEXT,
                rank=rank,
                score=1.0,
                snippet_digest=snippet_digest,
                chunk_id=chunk_id,
                representation_version=file_rec.representation_version,
                artifact_privacy=file_rec.artifact_privacy,
            ).validate()
        )

    is_partial = len(omissions) > 0
    cap_state = CapabilityState.PARTIAL if is_partial else CapabilityState.AVAILABLE
    return QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=requested_mode,
        effective_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        match_surface=MatchSurface.CAPTURED_TEXT,
        scope=scope,
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=cap_state,
        hits=tuple(hits),
        omissions=tuple(omissions),
        scope_complete=not is_partial,
        fallback=request.fallback,
        provenance=MappingProxyType({
            "projection_digest": projection.projection_digest,
            "policy_digest": projection.policy_digest,
            "accepted_backend": projection.accepted_reference.backend,
            "accepted_run_id": projection.accepted_reference.run_id,
            "total_matches_before_paging": total_matches,
        }),
    ).validate()
