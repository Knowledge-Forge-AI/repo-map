"""Unchanged v1 decisions plus supplemental per-arm public-text body policy.

The evaluator decision from ``admit_w5_task`` and the learned
``QueryInputDecision`` are never rebuilt. Document-pair gates read only policy,
manifest and accepted evidence-row metadata; none of them opens a body.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any

from common_lore_index.artifacts._manifest_records import ManifestArtifact, ManifestBinding
from common_lore_index.retrieval.projection_policy import (
    BodyProjectionPolicy, ExclusionReason, evaluate_artifact_pre_open, evaluate_binding_exclusion,
)
from retrieval_evaluation_admission_w5 import _policy_denial, admit_w5_task
from retrieval_public_text_contracts import (
    ARTIFACT_NOT_IN_MANIFEST, BINDING_POLICY_MISSING, BODY_PRECHECK_LAYER, METADATA_PRIVACY_REFUSED,
    SELECTED_EVIDENCE_MISSING, PairExclusion, PublicTextQueryDecision, SpanRow, maintained_reason,
)
from retrieval_public_text_excerpt import check_span_endpoints, validate_metadata_fields
from retrieval_public_text_privacy import is_safe_public_metadata
from retrieval_semantic_primitives import VerifiedNodeRepresentation

_INFERRED = frozenset({"inferred", "inferred_from_edge"})


def supplemental_body_reason(policy: BodyProjectionPolicy, binding_id: str) -> str | None:
    """Missing declarations refuse; the helper's None for an absent binding is not authority."""
    if binding_id not in policy.bindings:
        return BINDING_POLICY_MISSING
    return _policy_denial(policy, binding_id, body=True)


def public_text_applicability(task: Any) -> str | None:
    """The complete unchanged v1 predicate, evaluated in v1 order with v1 reasons."""
    if task.comparability_stratum != "metadata" or task.intended_match_surface == "captured_text":
        return "metadata_representation_not_comparable"
    if task.requested_mode != "ranked_discovery":
        return "unsupported_semantic_query_mode"
    if task.grading_rule not in {"ranked_positive", "absent_answer"}:
        return "unsupported_semantic_task_rule"
    return None


def admit_public_text_query(
    task: Any,
    *,
    policy: BodyProjectionPolicy,
    publication_pin: Any,
    observed_backend: str,
    frozen_policy_digest: str | None = None,
    post_publication_pin: Any | None = None,
) -> PublicTextQueryDecision:
    """Wrap the unchanged evaluator decision and add the supplemental public-text arm state."""
    v1 = admit_w5_task(
        task, policy=policy, publication_pin=publication_pin, observed_backend=observed_backend,
        frozen_policy_digest=frozen_policy_digest, post_publication_pin=post_publication_pin,
    )
    if v1.state.value != "admitted":
        return PublicTextQueryDecision(
            v1, v1.state.value, v1.reason_category, v1.refusal_code, v1.policy_enforcement_layer,
        )
    for binding_id in v1.selected_binding_ids:
        reason = supplemental_body_reason(policy, binding_id)
        if reason is not None:
            return PublicTextQueryDecision(v1, "refused", "authorization_denial", reason, BODY_PRECHECK_LAYER)
    unavailable = public_text_applicability(task)
    if unavailable is not None:
        return PublicTextQueryDecision(v1, "unavailable", unavailable, None, None)
    return PublicTextQueryDecision(v1, "admitted", None, None, None)


def dependent_fusion_state(public_text: PublicTextQueryDecision) -> tuple[str, str | None]:
    """A fusion arm consuming the public-text arm inherits its state and first reason."""
    return public_text.state, public_text.refusal_code or public_text.reason_category


def incumbent_fusion_state(public_text: PublicTextQueryDecision) -> tuple[str, str | None]:
    """Incumbent fusion keeps the unchanged v1 decision."""
    v1 = public_text.v1_decision
    return v1.state.value, v1.refusal_code or v1.reason_category


@dataclass(frozen=True)
class AdmittedPair:
    """Metadata-only admitted pair; no body has been opened."""

    representation: VerifiedNodeRepresentation
    row: SpanRow
    source_relative_path: str
    binding: ManifestBinding
    entry: ManifestArtifact


def _metadata_path(row: SpanRow) -> tuple[str, str] | None:
    raw = row.metadata_json
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, Mapping):
        return None
    binding_id, path = raw.get("binding_id"), raw.get("source_relative_path")
    if type(binding_id) is not str or type(path) is not str:
        return None
    return binding_id, path


def _endpoint(value: object) -> tuple[int, int]:
    if type(value) is int:
        return (1, value)
    return (0, 0)


def select_span_row(
    representation: VerifiedNodeRepresentation, rows: Sequence[SpanRow], *, run_id: int,
) -> tuple[SpanRow, str] | None:
    """Select the total-order minimum of the observed rows v1 already admitted for this pair."""
    candidates: list[tuple[tuple[bytes, bytes, tuple[int, int], tuple[int, int]], SpanRow, str]] = []
    for row in rows:
        if (
            row.canonical_key != representation.canonical_key or row.run_id != run_id
            or row.graph_key_version != 1 or row.link_kind in _INFERRED
            or row.evidence_key not in representation.evidence_keys
        ):
            continue
        parsed = _metadata_path(row)
        if parsed is None or parsed[0] != representation.source_binding_id:
            continue
        path = parsed[1]
        key = (path.encode("utf-8"), row.evidence_key.encode("utf-8"), _endpoint(row.start_line), _endpoint(row.end_line))
        candidates.append((key, row, path))
    if not candidates:
        return None
    _key, row, path = min(candidates, key=lambda item: item[0])
    return row, path


def admit_document_pair(
    representation: VerifiedNodeRepresentation,
    *,
    policy: BodyProjectionPolicy,
    bindings_by_id: Mapping[str, ManifestBinding],
    entries_by_key: Mapping[tuple[str, str], ManifestArtifact],
    rows: Sequence[SpanRow],
    run_id: int,
    private_markers: Sequence[str],
) -> AdmittedPair | PairExclusion:
    """Ordered pre-read gates G1-G8; the first failing gate owns the closed reason.

    G1 body policy, G2 manifest binding, G3 binding exclusion, G4 span-row
    selection, G5 span endpoints, G6 metadata privacy (K/T/N/P and the selected
    evidence key), G7 manifest entry, G8 artifact pre-open. None opens a body.
    """
    key, binding_id = representation.canonical_key, representation.source_binding_id

    def exclude(reason: str) -> PairExclusion:
        return PairExclusion(key, binding_id, reason)

    body_reason = supplemental_body_reason(policy, binding_id)
    if body_reason == BINDING_POLICY_MISSING:
        return exclude(BINDING_POLICY_MISSING)
    if body_reason is not None:
        return exclude(maintained_reason("public_text_body_policy_denied", body_reason))
    binding = bindings_by_id.get(binding_id)
    if binding is None:
        return exclude(ARTIFACT_NOT_IN_MANIFEST)
    binding_reason = evaluate_binding_exclusion(policy, binding)
    if binding_reason is not None:
        return exclude(maintained_reason("public_text_binding_excluded", binding_reason))
    selected = select_span_row(representation, rows, run_id=run_id)
    if selected is None:
        return exclude(SELECTED_EVIDENCE_MISSING)
    row, path = selected
    span_reason = check_span_endpoints(row.start_line, row.end_line)
    if span_reason is not None:
        return exclude(span_reason)
    metadata_reason = validate_metadata_fields(
        representation.canonical_key, representation.kind, representation.display_name, path,
        private_markers=private_markers,
    )
    if metadata_reason is not None:
        return exclude(metadata_reason)
    if not is_safe_public_metadata(row.evidence_key, private_markers=private_markers):
        return exclude(METADATA_PRIVACY_REFUSED)
    entry = entries_by_key.get((binding_id, path))
    if entry is None:
        return exclude(ARTIFACT_NOT_IN_MANIFEST)
    pre_reason, source_format = evaluate_artifact_pre_open(policy, binding, entry)
    if pre_reason is not None or source_format is None:
        return exclude(maintained_reason(
            "public_text_pre_open_excluded", pre_reason or ExclusionReason.UNSUPPORTED_SOURCE_FORMAT,
        ))
    return AdmittedPair(representation, row, path, binding, entry)
