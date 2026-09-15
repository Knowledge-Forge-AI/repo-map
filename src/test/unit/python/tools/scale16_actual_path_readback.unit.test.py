from __future__ import annotations

from repomap_kg.storage.authority import AttemptNumber, JobId
from repomap_kg.storage.publication import RunPublicationAttempt
from scale15_terminal_contracts import (
    CleanupState,
    PublicationState,
    StageState,
    TerminalReadback,
)
from scale16_actual_path_readback import (
    BoundAttemptEvidence,
    classify_bound_attempt,
)


def _base(state: PublicationState) -> TerminalReadback:
    return TerminalReadback(
        state,
        (
            StageState.PUBLISHED_RECONCILED
            if state is PublicationState.PUBLISHED
            else StageState.FAILED_RECONCILED
        ),
        CleanupState.ELIGIBLE,
        {
            "files": 1,
            "raw_observations": 1,
            "canonical_nodes": 0,
            "canonical_edges": 0,
            "canonical_evidence": 0,
            "canonical_node_evidence": 0,
            "canonical_edge_evidence": 0,
        },
        "0" * 64,
        7,
        7 if state is PublicationState.PUBLISHED else None,
    )


def _attempt(value: str) -> RunPublicationAttempt:
    return RunPublicationAttempt(JobId(value), AttemptNumber(1))


def test_exact_bound_success_requires_stage_run_and_publication_equality() -> None:
    attempt = _attempt("direct-a")
    evidence = BoundAttemptEvidence(
        exact_stage_attempt=attempt,
        exact_stage_run_id=7,
        newest_stage_attempt=attempt,
        latest_run_id=7,
        latest_publication_attempt=attempt,
        latest_publication_run_id=7,
        canonical_publication_attempt=attempt,
        canonical_publication_run_id=7,
    )

    assert classify_bound_attempt(_base(PublicationState.PUBLISHED), attempt, evidence) == _base(PublicationState.PUBLISHED)


def test_same_generation_foreign_publication_is_rejected() -> None:
    bound = _attempt("direct-a")
    foreign = _attempt("direct-b")
    evidence = BoundAttemptEvidence(
        exact_stage_attempt=bound,
        exact_stage_run_id=6,
        newest_stage_attempt=foreign,
        latest_run_id=7,
        latest_publication_attempt=foreign,
        latest_publication_run_id=7,
        canonical_publication_attempt=foreign,
        canonical_publication_run_id=7,
    )

    result = classify_bound_attempt(_base(PublicationState.PUBLISHED), bound, evidence)

    assert result.publication_state is PublicationState.FOREIGN_PUBLICATION_DETECTED


def test_missing_exact_stage_with_foreign_stage_is_rejected() -> None:
    bound = _attempt("direct-a")
    evidence = BoundAttemptEvidence(
        exact_stage_attempt=None,
        exact_stage_run_id=None,
        newest_stage_attempt=_attempt("direct-b"),
        latest_run_id=7,
        latest_publication_attempt=None,
        latest_publication_run_id=None,
        canonical_publication_attempt=None,
        canonical_publication_run_id=None,
    )

    result = classify_bound_attempt(_base(PublicationState.NOT_PUBLISHED), bound, evidence)

    assert result.publication_state is PublicationState.FOREIGN_STAGE_DETECTED


def test_missing_exact_stage_with_foreign_publication_is_rejected() -> None:
    bound = _attempt("direct-a")
    foreign = _attempt("direct-b")
    evidence = BoundAttemptEvidence(
        exact_stage_attempt=None,
        exact_stage_run_id=None,
        newest_stage_attempt=foreign,
        latest_run_id=7,
        latest_publication_attempt=foreign,
        latest_publication_run_id=7,
        canonical_publication_attempt=foreign,
        canonical_publication_run_id=7,
    )

    result = classify_bound_attempt(
        _base(PublicationState.PUBLISHED), bound, evidence
    )

    assert result.publication_state is (
        PublicationState.FOREIGN_PUBLICATION_DETECTED
    )


def test_prior_preservation_requires_bound_failed_stage_run() -> None:
    bound = _attempt("direct-a")
    evidence = BoundAttemptEvidence(
        exact_stage_attempt=bound,
        exact_stage_run_id=8,
        newest_stage_attempt=bound,
        latest_run_id=9,
        latest_publication_attempt=_attempt("direct-prior"),
        latest_publication_run_id=7,
        canonical_publication_attempt=_attempt("direct-prior"),
        canonical_publication_run_id=7,
    )

    result = classify_bound_attempt(
        _base(PublicationState.PRIOR_PUBLICATION_PRESERVED),
        bound,
        evidence,
    )

    assert result.publication_state is PublicationState.LAUNCH_ATTEMPT_MISMATCH
