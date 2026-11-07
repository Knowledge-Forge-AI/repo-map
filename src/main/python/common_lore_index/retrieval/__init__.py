"""Internal CLOE retrieval query contracts and captured-input projection reference (ADR 0127)."""

from __future__ import annotations

from common_lore_index.retrieval.projection_build import (
    CapturedTextProjection,
    ExcludedBindingRecord,
    ExcludedFileRecord,
    ProjectedFileRecord,
    build_captured_text_projection,
)
from common_lore_index.retrieval.projection_chunks import (
    ProjectedChunk,
    build_file_chunks,
    frame_digest,
)
from common_lore_index.retrieval.projection_evidence import (
    ProjectedEvidenceLink,
    index_bundle_evidence,
    links_for_line_span,
)
from common_lore_index.retrieval.projection_policy import (
    BodyProjectionPolicy,
    ExclusionReason,
    ResolvedBindingPolicy,
    evaluate_artifact_pre_open,
    evaluate_binding_exclusion,
)
from common_lore_index.retrieval.projection_query import (
    CapturedTextQueryRequest,
    query_captured_text,
)
from common_lore_index.retrieval.projection_text import (
    NormalizedTextResult,
    REPRESENTATION_VERSION,
    normalize_and_bound_text,
)
from common_lore_index.retrieval.publication_binding import (
    AcceptedPublicationReference,
    CorrespondenceErrorCode,
    CorrespondenceRefusal,
    PROJECTION_REFERENCE_VERSION,
    ProjectionInputs,
    check_correspondence,
)
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
    UnavailableReason,
    refused_envelope,
    stale_envelope,
    unavailable_envelope,
)

__all__ = (
    "AcceptedPublicationReference",
    "BodyProjectionPolicy",
    "CapabilityState",
    "CapturedTextProjection",
    "CapturedTextQueryRequest",
    "CorrespondenceErrorCode",
    "CorrespondenceRefusal",
    "DEFAULT_ORDERING_POLICY_VERSION",
    "EvaluationLocator",
    "ExcludedBindingRecord",
    "ExcludedFileRecord",
    "ExclusionReason",
    "FallbackDisclosure",
    "MatchSurface",
    "NormalizedTextResult",
    "OmissionRecord",
    "PROJECTION_REFERENCE_VERSION",
    "ProjectedChunk",
    "ProjectedEvidenceLink",
    "ProjectedFileRecord",
    "ProjectionInputs",
    "QUERY_CONTRACT_VERSION",
    "QueryEnvelope",
    "QueryHit",
    "QueryMode",
    "QueryScope",
    "REPRESENTATION_VERSION",
    "ResolvedBindingPolicy",
    "UnavailableReason",
    "build_captured_text_projection",
    "build_file_chunks",
    "check_correspondence",
    "evaluate_artifact_pre_open",
    "evaluate_binding_exclusion",
    "frame_digest",
    "index_bundle_evidence",
    "links_for_line_span",
    "normalize_and_bound_text",
    "query_captured_text",
    "refused_envelope",
    "stale_envelope",
    "unavailable_envelope",
)
