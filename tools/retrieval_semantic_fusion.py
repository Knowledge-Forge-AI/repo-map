"""Model-independent file-level RRF (k=60) fusion and cross-arm provenance alignment (ADR 0137)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_arm_validation import (
    MAX_ARM_CANDIDATES,
    AdmittedArmObservation,
    FileIdentityTuple,
    VectorCandidateInput,
    _extract_arm_raw_hits,
    _pins_match,
    _resolve_arm_pin,
    _verify_envelope_against_pin,
    _verify_observed_accepted_publication,
)
from retrieval_semantic_representation import (
    CANONICAL_NODE_REPRESENTATION_VERSION,
    W5_FOUNDATION_SCHEMA_VERSION,
    RepresentationValidationError,
    VerifiedPublicationPin,
    _require,
)

RRF_POLICY_VERSION = "cloe-w5-rrf-file-v1"
RRF_K_DEFAULT = 60
MAX_FUSED_RESULTS = 100
MAX_SUPPORTING_IDS = 16


def _is_verified_publication_pin(value: object) -> bool:
    """Keep the runtime refusal for callers that bypass the annotated API."""
    return isinstance(value, VerifiedPublicationPin)


@dataclass(frozen=True)
class CollapsedArmFileHit:
    """Per-arm file observation after collapsing multiple node/chunk hits to a single file."""
    arm_id: str
    file_identity: FileIdentityTuple
    ordinal_rank: int
    best_raw_rank: int
    raw_hit_count: int
    rrf_contribution: Fraction
    supporting_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm_id": self.arm_id, "file_identity": self.file_identity.to_dict(), "ordinal_rank": self.ordinal_rank,
            "best_raw_rank": self.best_raw_rank, "raw_hit_count": self.raw_hit_count,
            "rrf_numerator": self.rrf_contribution.numerator, "rrf_denominator": self.rrf_contribution.denominator,
            "supporting_ids": list(self.supporting_ids),
        }


@dataclass(frozen=True)
class FusedFileHit:
    """Deterministically ranked fused file hit with exact Fraction score and per-arm provenance."""
    fused_rank: int
    file_identity: FileIdentityTuple
    score_fraction: Fraction
    arm_contributions: tuple[CollapsedArmFileHit, ...]

    @property
    def score_float(self) -> float:
        return float(self.score_fraction)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fused_rank": self.fused_rank, "file_identity": self.file_identity.to_dict(),
            "score_numerator": self.score_fraction.numerator, "score_denominator": self.score_fraction.denominator,
            "score_float": round(self.score_float, 12), "contributing_arms": [c.to_dict() for c in self.arm_contributions],
        }


@dataclass(frozen=True)
class FileFusionResult:
    """Complete file-level RRF fusion result with provenance, refusal, fallback, and work accounting."""
    execution_state: ExecutionState
    refusal_code: str | None
    unavailable_reason: str | None
    failure_reason: str | None
    provenance: VerifiedPublicationPin | None
    rrf_k: int
    hits: tuple[FusedFileHit, ...]
    collapsed_by_arm: Mapping[str, tuple[CollapsedArmFileHit, ...]]
    per_arm_raw_hit_counts: Mapping[str, int]
    per_arm_collapsed_file_counts: Mapping[str, int]
    pre_cap_fused_file_count: int
    work_candidates_inspected: int
    truncated: bool
    partial_coverage: bool
    fallback_disclosed: bool = False
    fallback_from_arms: tuple[str, ...] = ()
    credited_as_fused: bool = False
    incomplete_arms: tuple[str, ...] = ()
    truncated_arms: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": W5_FOUNDATION_SCHEMA_VERSION, "policy_version": RRF_POLICY_VERSION,
            "representation_version": CANONICAL_NODE_REPRESENTATION_VERSION, "execution_state": self.execution_state.value,
            "refusal_code": self.refusal_code, "unavailable_reason": self.unavailable_reason, "failure_reason": self.failure_reason,
            "provenance": None if self.provenance is None else self.provenance.to_dict(), "rrf_k": self.rrf_k,
            "hits": [h.to_dict() for h in self.hits], "per_arm_raw_hit_counts": dict(self.per_arm_raw_hit_counts),
            "per_arm_collapsed_file_counts": dict(self.per_arm_collapsed_file_counts),
            "pre_cap_fused_file_count": self.pre_cap_fused_file_count, "work_candidates_inspected": self.work_candidates_inspected,
            "truncated": self.truncated, "partial_coverage": self.partial_coverage, "fallback_disclosed": self.fallback_disclosed,
            "fallback_from_arms": list(self.fallback_from_arms), "credited_as_fused": self.credited_as_fused,
            "incomplete_arms": list(self.incomplete_arms), "truncated_arms": list(self.truncated_arms),
        }


def _empty_result(
    state: ExecutionState, *, refusal_code: str | None = None, unavailable_reason: str | None = None,
    failure_reason: str | None = None, provenance: VerifiedPublicationPin | None = None,
    rrf_k: int = RRF_K_DEFAULT, work_inspected: int = 0,
) -> FileFusionResult:
    return FileFusionResult(state, refusal_code, unavailable_reason, failure_reason, provenance, rrf_k, (), {}, {}, {}, 0, work_inspected, False, False)


def collapse_arm_to_files(
    arm_id: str, raw_hits: Sequence[tuple[FileIdentityTuple, int, str]], *, rrf_k: int = RRF_K_DEFAULT
) -> tuple[CollapsedArmFileHit, ...]:
    """Collapse per-arm raw observations by FileIdentityTuple, retaining best raw rank."""
    _require(type(rrf_k) is int and rrf_k >= 1, "invalid_rrf_k", "rrf_k must be a positive int")
    grouped: dict[FileIdentityTuple, tuple[int, int, set[str]]] = {}
    for f_tuple, raw_rank, sup_id in raw_hits:
        _require(type(raw_rank) is int and raw_rank >= 1, "invalid_raw_rank", "raw_rank must be >= 1")
        if f_tuple not in grouped:
            grouped[f_tuple] = (raw_rank, 1, {sup_id})
        else:
            best_r, cnt, sups = grouped[f_tuple]
            sups.add(sup_id)
            grouped[f_tuple] = (min(best_r, raw_rank), cnt + 1, sups)
    ordered_files = sorted(grouped, key=lambda ft: (grouped[ft][0], ft.utf8_sort_key()))
    return tuple(
        CollapsedArmFileHit(
            arm_id, f_tuple, ord_rank, grouped[f_tuple][0], grouped[f_tuple][1],
            Fraction(1, rrf_k + ord_rank),
            tuple(sorted(grouped[f_tuple][2], key=lambda s: s.encode("utf-8"))[:MAX_SUPPORTING_IDS]),
        )
        for ord_rank, f_tuple in enumerate(ordered_files, start=1)
    )


def fuse_arm_observations_rrf(
    arms: Sequence[AdmittedArmObservation], *, expected_pin: VerifiedPublicationPin | None = None,
    rrf_k: int = RRF_K_DEFAULT, max_results: int = MAX_FUSED_RESULTS,
    allow_explicit_single_arm_fallback: bool = False, private_markers: Sequence[str] = (),
    **extra_kwargs: Any,
) -> FileFusionResult:
    """Fuse multi-arm observations into file-level RRF rankings with strict provenance and refusal precedence."""
    if "trusted" in extra_kwargs or "trusted_caller" in extra_kwargs:
        return _empty_result(ExecutionState.REFUSED, refusal_code="caller_trusted_escape_forbidden", provenance=expected_pin, rrf_k=rrf_k)
    if extra_kwargs or not arms or type(rrf_k) is not int or rrf_k < 1 or type(max_results) is not int or not 1 <= max_results <= MAX_FUSED_RESULTS:
        return _empty_result(ExecutionState.REFUSED, refusal_code="invalid_fusion_parameters", provenance=expected_pin, rrf_k=rrf_k if type(rrf_k) is int and rrf_k >= 1 else RRF_K_DEFAULT)
    if expected_pin is not None:
        if not _is_verified_publication_pin(expected_pin):
            return _empty_result(ExecutionState.REFUSED, refusal_code="unverified_publication_pin", rrf_k=rrf_k)
        try:
            expected_pin.revalidate_current()
        except RepresentationValidationError as exc:
            return _empty_result(ExecutionState.REFUSED, refusal_code=exc.code, provenance=expected_pin, rrf_k=rrf_k)
    markers = tuple(str(x) for x in private_markers if x)
    seen_arm_ids: set[str] = set()
    resolved_pins: list[VerifiedPublicationPin] = []
    effective_states: list[ExecutionState] = []
    refused_codes, failed_reasons, incomplete_arms, truncated_arms = [], [], [], []
    not_run_arms: list[tuple[str, str]] = []
    unavailable_arms: list[tuple[str, str]] = []
    for arm in arms:
        if type(arm.arm_id) is not str or not arm.arm_id.strip() or arm.arm_id in seen_arm_ids:
            return _empty_result(ExecutionState.REFUSED, refusal_code="duplicate_or_invalid_arm_id", provenance=expected_pin, rrf_k=rrf_k)
        seen_arm_ids.add(arm.arm_id)
        try:
            pin = _resolve_arm_pin(arm)
        except RepresentationValidationError as exc:
            refused_codes.append(exc.code)
            continue
        resolved_pins.append(pin)
        if arm.selected_binding_ids is not None and not arm.selected_binding_ids:
            refused_codes.append("empty_selected_bindings")
        for b_id in arm.selected_binding_ids or ():
            if type(b_id) is not str or not b_id.strip() or b_id in pin.denied_bindings or b_id not in pin.snapshot_by_binding():
                refused_codes.append(pin.denied_bindings.get(b_id, "unknown_source_binding") if type(b_id) is str else "invalid_binding_id")
        obs_err = _verify_observed_accepted_publication(arm.observed_accepted_publication, pin)
        if obs_err is not None:
            refused_codes.append(obs_err)
        env_err, env_state, env_reason, env_inc, env_trunc = _verify_envelope_against_pin(arm.envelope, pin)
        if env_err is not None:
            refused_codes.append(env_err)
        if arm.incomplete or arm.truncated or env_inc:
            incomplete_arms.append(arm.arm_id)
        if arm.truncated or env_trunc:
            truncated_arms.append(arm.arm_id)
        eff_state = arm.execution_state
        if env_state is not None:
            if arm.execution_state != ExecutionState.COMPLETED and arm.execution_state != env_state:
                refused_codes.append("envelope_execution_state_mismatch")
            eff_state = env_state if arm.execution_state == ExecutionState.COMPLETED else arm.execution_state
        effective_states.append(eff_state)
        if eff_state == ExecutionState.REFUSED:
            refused_codes.append(arm.refusal_code or env_err or "arm_refused")
        elif eff_state == ExecutionState.FAILED:
            failed_reasons.append(arm.failure_reason or env_reason or f"arm_{arm.arm_id}_failed")
        elif eff_state == ExecutionState.NOT_RUN:
            not_run_arms.append((arm.arm_id, arm.unavailable_reason or env_reason or "arm_not_run"))
        elif eff_state == ExecutionState.UNAVAILABLE:
            unavailable_arms.append((arm.arm_id, arm.unavailable_reason or env_reason or "arm_unavailable"))
    canonical_pin = expected_pin or (resolved_pins[0] if resolved_pins else None)
    if canonical_pin is not None:
        for pin in resolved_pins:
            mismatch = _pins_match(canonical_pin, pin)
            if mismatch is not None:
                refused_codes.append("stale_publication_receipt" if expected_pin is not None and pin.run_id != expected_pin.run_id else mismatch)
    if refused_codes:
        return _empty_result(ExecutionState.REFUSED, refusal_code=refused_codes[0], provenance=canonical_pin, rrf_k=rrf_k)
    if failed_reasons:
        return _empty_result(ExecutionState.FAILED, failure_reason=failed_reasons[0], provenance=canonical_pin, rrf_k=rrf_k)
    if not_run_arms and not allow_explicit_single_arm_fallback:
        return _empty_result(ExecutionState.NOT_RUN, unavailable_reason=not_run_arms[0][1], provenance=canonical_pin, rrf_k=rrf_k)
    if unavailable_arms and not allow_explicit_single_arm_fallback:
        return _empty_result(ExecutionState.UNAVAILABLE, unavailable_reason=unavailable_arms[0][1], provenance=canonical_pin, rrf_k=rrf_k)
    collapsed_by_arm: dict[str, tuple[CollapsedArmFileHit, ...]] = {}
    raw_counts, collapsed_counts, total_inspected = {}, {}, 0
    for arm, pin, eff_state in zip(arms, resolved_pins, effective_states, strict=True):
        if eff_state != ExecutionState.COMPLETED:
            raw_counts[arm.arm_id], collapsed_counts[arm.arm_id], collapsed_by_arm[arm.arm_id] = 0, 0, ()
            continue
        try:
            raw_hits, inspected, capped_trunc = _extract_arm_raw_hits(arm, pin, markers)
            if capped_trunc:
                incomplete_arms.append(arm.arm_id)
                truncated_arms.append(arm.arm_id)
            total_inspected += inspected
            collapsed = collapse_arm_to_files(arm.arm_id, raw_hits, rrf_k=rrf_k)
        except RepresentationValidationError as exc:
            return _empty_result(ExecutionState.REFUSED, refusal_code=exc.code, provenance=canonical_pin, rrf_k=rrf_k, work_inspected=total_inspected)
        raw_counts[arm.arm_id], collapsed_counts[arm.arm_id], collapsed_by_arm[arm.arm_id] = len(raw_hits), len(collapsed), collapsed
    executed_arm_count = sum(1 for st in effective_states if st == ExecutionState.COMPLETED)
    if executed_arm_count == 0:
        out_st = ExecutionState.NOT_RUN if not_run_arms else ExecutionState.UNAVAILABLE
        return _empty_result(out_st, unavailable_reason="no_executed_arms", provenance=canonical_pin, rrf_k=rrf_k)
    by_file: dict[FileIdentityTuple, list[CollapsedArmFileHit]] = {}
    for arm in arms:
        for c_hit in collapsed_by_arm.get(arm.arm_id, ()):
            by_file.setdefault(c_hit.file_identity, []).append(c_hit)
    scored = [(ft, sum((c.rrf_contribution for c in cs), start=Fraction(0, 1)), tuple(cs)) for ft, cs in by_file.items()]
    scored.sort(key=lambda item: (-item[1], item[0].utf8_sort_key()))
    pre_cap, capped = len(scored), scored[:max_results]
    fused_hits = tuple(FusedFileHit(rank, ft, sc, cs) for rank, (ft, sc, cs) in enumerate(capped, start=1))
    degraded_arms = not_run_arms + unavailable_arms
    truncated, is_fallback = len(fused_hits) < pre_cap, bool(degraded_arms)
    inc_tuple, trunc_tuple = tuple(sorted(set(incomplete_arms))), tuple(sorted(set(truncated_arms)))
    out_state = ExecutionState.NOT_RUN if not_run_arms else (ExecutionState.UNAVAILABLE if unavailable_arms else ExecutionState.COMPLETED)
    return FileFusionResult(
        out_state, None, degraded_arms[0][1] if is_fallback else None, None,
        canonical_pin, rrf_k, fused_hits, collapsed_by_arm, raw_counts, collapsed_counts, pre_cap, total_inspected,
        truncated or bool(trunc_tuple), truncated or is_fallback or bool(inc_tuple), is_fallback,
        tuple(a_id for a_id, _ in degraded_arms), not is_fallback and executed_arm_count >= 2 and not inc_tuple and not truncated,
        inc_tuple, trunc_tuple,
    )


__all__ = [
    "MAX_ARM_CANDIDATES", "MAX_FUSED_RESULTS", "MAX_SUPPORTING_IDS", "RRF_K_DEFAULT",
    "RRF_POLICY_VERSION", "AdmittedArmObservation", "CollapsedArmFileHit", "FileFusionResult",
    "FileIdentityTuple", "FusedFileHit", "VectorCandidateInput", "collapse_arm_to_files",
    "fuse_arm_observations_rrf",
]
