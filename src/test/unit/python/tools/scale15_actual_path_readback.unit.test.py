from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import pytest

from repomap_kg.storage.authority import (
    AttemptNumber,
    GraphRunId,
    JobId,
    PublicationGenerations,
)
from repomap_kg.storage.publication import (
    RunPublicationAttempt,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_readback import RunPublicationRecord
from repomap_kg.storage.run_authority import (
    ReceiptBearingPublication,
    RecordedRun,
    RunAuthoritySnapshot,
    RunStatus,
)
from scale15_actual_path_readback import (
    StageTerminalEvidence,
    TerminalStorageEvidence,
    classify_terminal_evidence,
)
from scale15_terminal_contracts import (
    CleanupState,
    ExpectedRefreshAuthority,
    PublicationState,
    StageState,
)


GENERATIONS = PublicationGenerations(
    "sg1:source",
    "cg1:config",
    "eg1:extractor",
    "kg1:canonicalizer",
)
COUNTS = {
    "files": 1,
    "raw_observations": 2,
    "canonical_nodes": 3,
    "canonical_edges": 1,
    "canonical_evidence": 2,
    "canonical_node_evidence": 2,
    "canonical_edge_evidence": 1,
}


def _receipt(generations: PublicationGenerations = GENERATIONS) -> RunPublicationReceipt:
    return RunPublicationReceipt(
        RunPublicationAttempt(JobId("direct-attempt"), AttemptNumber(1)),
        generations,
    ).validate()


def _stage(*, state: str = "published", generations: PublicationGenerations = GENERATIONS) -> StageTerminalEvidence:
    return StageTerminalEvidence(
        state,
        "committed" if state == "published" else "rolled_back",
        "reconciled",
        "eligible",
        "direct",
        "direct-attempt",
        1,
        generations,
        False,
    )


def _expected(
    *,
    repository_identity: str = "repo1:public-fixture",
    repository_name: str = "public-fixture",
    generations: PublicationGenerations = GENERATIONS,
    execution_mode: str = "direct",
    zero_state_first_publication: bool = True,
    expected_family_counts: Mapping[str, int] = COUNTS,
    expected_structural_digest: str | None = "a" * 64,
    prior_publication_run_id: int | None = None,
    prior_family_counts: Mapping[str, int] | None = None,
    prior_structural_digest: str | None = None,
    prior_latest_recorded_run_id: int | None = None,
) -> ExpectedRefreshAuthority:
    return ExpectedRefreshAuthority(
        repository_identity=repository_identity,
        repository_name=repository_name,
        generations=generations,
        execution_mode=execution_mode,
        zero_state_first_publication=zero_state_first_publication,
        expected_family_counts=expected_family_counts,
        expected_structural_digest=expected_structural_digest,
        prior_publication_run_id=prior_publication_run_id,
        prior_family_counts=prior_family_counts,
        prior_structural_digest=prior_structural_digest,
        prior_latest_recorded_run_id=prior_latest_recorded_run_id,
    ).validate()


def _evidence(*, status: RunStatus = RunStatus.COMPLETE) -> TerminalStorageEvidence:
    run = RecordedRun(GraphRunId(2), status, "2026-07-18T00:00:00Z", None)
    publication = ReceiptBearingPublication(run, _receipt())
    authority = RunAuthoritySnapshot(run, None, publication)
    return TerminalStorageEvidence(
        True,
        authority,
        RunPublicationRecord(GraphRunId(2), _receipt()),
        _receipt(),
        False,
        _stage(),
        dict(COUNTS),
        "a" * 64,
    )


def test_matching_complete_receipt_and_seven_families_publish() -> None:
    result = classify_terminal_evidence(_expected(), _evidence())

    assert result.publication_state is PublicationState.PUBLISHED
    assert result.stage_state is StageState.PUBLISHED_RECONCILED
    assert result.cleanup_state is CleanupState.ELIGIBLE


def test_receiptless_complete_run_is_not_publication_success() -> None:
    evidence = _evidence()
    evidence = replace(
        evidence,
        run_authority=replace(
            evidence.run_authority,
            latest_receipt_bearing_publication=None,
        ),
        canonical_publication=None,
        latest_run_receipt=None,
    )

    result = classify_terminal_evidence(_expected(), evidence)

    assert result.publication_state is PublicationState.RECEIPTLESS_COMPLETE


def test_partial_receipt_has_exact_closed_rejection() -> None:
    result = classify_terminal_evidence(
        _expected(), replace(_evidence(), latest_run_receipt_malformed=True)
    )

    assert result.publication_state is PublicationState.PARTIAL_RECEIPT


def test_generation_mismatch_is_rejected() -> None:
    other = PublicationGenerations(
        "sg1:other",
        "cg1:config",
        "eg1:extractor",
        "kg1:canonicalizer",
    )
    run = RecordedRun(GraphRunId(2), RunStatus.COMPLETE, "2026-07-18T00:00:00Z", None)
    evidence = replace(
        _evidence(),
        run_authority=RunAuthoritySnapshot(
            run,
            None,
            ReceiptBearingPublication(run, _receipt(other)),
        ),
        canonical_publication=RunPublicationRecord(GraphRunId(2), _receipt(other)),
        latest_run_receipt=_receipt(other),
        stage=_stage(generations=other),
    )

    result = classify_terminal_evidence(_expected(), evidence)

    assert result.publication_state is PublicationState.GENERATION_MISMATCH


def test_latest_recorded_and_receipt_publication_divergence_is_rejected() -> None:
    evidence = _evidence()
    old_run = RecordedRun(GraphRunId(1), RunStatus.COMPLETE, "2026-07-18T00:00:00Z", None)
    evidence = replace(
        evidence,
        run_authority=replace(
            evidence.run_authority,
            latest_receipt_bearing_publication=ReceiptBearingPublication(
                old_run, _receipt()
            ),
        ),
        canonical_publication=RunPublicationRecord(GraphRunId(1), _receipt()),
    )

    result = classify_terminal_evidence(_expected(), evidence)

    assert result.publication_state is (
        PublicationState.RECORDED_PUBLICATION_DIVERGED
    )


def test_zero_state_cancel_requires_all_seven_families_empty() -> None:
    run = RecordedRun(GraphRunId(2), RunStatus.FAILED, "2026-07-18T00:00:00Z", None)
    evidence = TerminalStorageEvidence(
        True,
        RunAuthoritySnapshot(run, None, None),
        None,
        None,
        False,
        _stage(state="failed"),
        {family: 0 for family in COUNTS},
        "0" * 64,
    )
    assert (
        classify_terminal_evidence(_expected(), evidence).publication_state
        is PublicationState.NOT_PUBLISHED
    )

    partial = dict(evidence.family_counts)
    partial["canonical_node_evidence"] = 1
    result = classify_terminal_evidence(
        _expected(), replace(evidence, family_counts=partial)
    )
    assert result.publication_state is PublicationState.FAMILY_STATE_MISMATCH


def test_prior_publication_is_authoritative_after_failed_second_attempt() -> None:
    failed = RecordedRun(GraphRunId(2), RunStatus.FAILED, "2026-07-18T00:00:01Z", None)
    prior = RecordedRun(GraphRunId(1), RunStatus.COMPLETE, "2026-07-18T00:00:00Z", None)
    evidence = TerminalStorageEvidence(
        True,
        RunAuthoritySnapshot(
            failed,
            None,
            ReceiptBearingPublication(prior, _receipt()),
        ),
        RunPublicationRecord(GraphRunId(1), _receipt()),
        None,
        False,
        _stage(state="failed"),
        dict(COUNTS),
        "a" * 64,
    )
    expected = _expected(
        zero_state_first_publication=False,
        prior_publication_run_id=1,
        prior_family_counts=COUNTS,
        prior_structural_digest="a" * 64,
        prior_latest_recorded_run_id=1,
    )

    result = classify_terminal_evidence(expected, evidence)

    assert result.publication_state is PublicationState.PRIOR_PUBLICATION_PRESERVED


def test_prior_preservation_requires_a_new_failed_run_after_launch_marker() -> None:
    failed = RecordedRun(GraphRunId(2), RunStatus.FAILED, "2026-07-18T00:00:01Z", None)
    prior = RecordedRun(GraphRunId(1), RunStatus.COMPLETE, "2026-07-18T00:00:00Z", None)
    evidence = TerminalStorageEvidence(
        True,
        RunAuthoritySnapshot(
            failed,
            None,
            ReceiptBearingPublication(prior, _receipt()),
        ),
        RunPublicationRecord(GraphRunId(1), _receipt()),
        None,
        False,
        _stage(state="failed"),
        dict(COUNTS),
        "a" * 64,
    )
    expected = _expected(
        zero_state_first_publication=False,
        prior_publication_run_id=1,
        prior_family_counts=COUNTS,
        prior_structural_digest="a" * 64,
        prior_latest_recorded_run_id=2,
    )

    result = classify_terminal_evidence(expected, evidence)

    assert result.publication_state is PublicationState.RECEIPT_CONFLICT


def test_commit_unknown_blocks_cleanup_and_publication() -> None:
    result = classify_terminal_evidence(
        _expected(), replace(_evidence(), stage=_stage(state="commit_unknown"))
    )

    assert result.publication_state is PublicationState.COMMIT_UNKNOWN_UNRESOLVED
    assert result.stage_state is StageState.COMMIT_UNKNOWN
    assert result.cleanup_state is CleanupState.BLOCKED_COMMIT_UNKNOWN


def test_stage_receipt_conflict_and_repository_identity_mismatch_are_exact() -> None:
    conflict = classify_terminal_evidence(
        _expected(),
        replace(
            _evidence(),
            stage=replace(_stage(), publication_identity="other-operation"),
        ),
    )
    identity = classify_terminal_evidence(
        _expected(),
        replace(_evidence(), repository_identity_matches=False),
    )

    assert conflict.publication_state is PublicationState.RECEIPT_CONFLICT
    assert identity.publication_state is (
        PublicationState.REPOSITORY_IDENTITY_MISMATCH
    )


@pytest.mark.parametrize(
    "family",
    (
        "files",
        "raw_observations",
        "canonical_nodes",
        "canonical_evidence",
        "canonical_node_evidence",
        "canonical_edge_evidence",
    ),
)
def test_each_partial_family_projection_is_rejected(family: str) -> None:
    counts = dict(COUNTS)
    counts[family] = counts[family] + 1

    result = classify_terminal_evidence(
        _expected(), replace(_evidence(), family_counts=counts)
    )

    assert result.publication_state is PublicationState.FAMILY_STATE_MISMATCH


def test_structural_digest_mismatch_is_not_collapsed_into_count_success() -> None:
    result = classify_terminal_evidence(
        _expected(), replace(_evidence(), structural_digest="b" * 64)
    )

    assert result.publication_state is (
        PublicationState.STRUCTURAL_DIGEST_MISMATCH
    )
