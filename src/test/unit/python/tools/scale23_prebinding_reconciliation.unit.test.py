from collections.abc import Mapping
from actual_refresh_terminal import storage_reconciled
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
from semantic_digest_readback import empty_semantic_digest
from scale15_terminal_contracts import (
    CleanupState,
    ExpectedRefreshAuthority,
    PublicationState,
    StageState,
)
from scale16_actual_path_readback import (
    BoundAttemptEvidence,
    classify_bound_attempt,
)


GENERATIONS = PublicationGenerations(
    "sg1:source",
    "cg1:config",
    "eg1:extractor",
    "kg1:canonicalizer",
)
EMPTY_COUNTS = {
    "files": 0,
    "raw_observations": 0,
    "canonical_nodes": 0,
    "canonical_edges": 0,
    "canonical_evidence": 0,
    "canonical_node_evidence": 0,
    "canonical_edge_evidence": 0,
}
PRIOR_COUNTS = {family: index + 1 for index, family in enumerate(EMPTY_COUNTS)}


def _receipt() -> RunPublicationReceipt:
    return RunPublicationReceipt(
        RunPublicationAttempt(JobId("direct-attempt"), AttemptNumber(1)),
        GENERATIONS,
    ).validate()


def _expected(
    *,
    repository_identity: str = "repo1:public-fixture",
    repository_name: str = "public-fixture",
    generations: PublicationGenerations = GENERATIONS,
    execution_mode: str = "direct",
    zero_state_first_publication: bool = True,
    expected_family_counts: Mapping[str, int] = PRIOR_COUNTS,
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


def test_prebinding_absent_repository_is_exact_reconciled_zero_state() -> None:
    evidence = TerminalStorageEvidence(
        False,
        RunAuthoritySnapshot(None, None, None),
        None,
        None,
        False,
        None,
        dict(EMPTY_COUNTS),
        empty_semantic_digest(),
        False,
    )

    result = classify_terminal_evidence(_expected(), evidence, pre_binding=True)

    assert result.publication_state is PublicationState.NOT_PUBLISHED
    assert result.stage_state is StageState.PRE_BINDING_RECONCILED
    assert result.cleanup_state is CleanupState.NOT_ELIGIBLE


def test_bound_attempt_before_stage_is_exact_reconciled_zero_state() -> None:
    evidence = TerminalStorageEvidence(
        False,
        RunAuthoritySnapshot(None, None, None),
        None,
        None,
        False,
        None,
        dict(EMPTY_COUNTS),
        empty_semantic_digest(),
        False,
    )
    base = classify_terminal_evidence(_expected(), evidence, pre_stage=True)

    result = classify_bound_attempt(
        base,
        _receipt().attempt,
        BoundAttemptEvidence(None, None, None, None, None, None, None, None),
    )

    assert result.publication_state is PublicationState.NOT_PUBLISHED
    assert result.stage_state is StageState.PRE_STAGE_RECONCILED
    assert result.cleanup_state is CleanupState.NOT_ELIGIBLE
    assert storage_reconciled(
        True,
        True,
        result.publication_state,
        result.stage_state,
        result.cleanup_state,
    )


def test_prebinding_prior_publication_is_preserved_without_new_run_or_stage() -> None:
    prior = RecordedRun(GraphRunId(1), RunStatus.COMPLETE, "2026-07-20T00:00:00Z", None)
    publication = ReceiptBearingPublication(prior, _receipt())
    evidence = TerminalStorageEvidence(
        True,
        RunAuthoritySnapshot(prior, None, publication),
        RunPublicationRecord(GraphRunId(1), _receipt()),
        _receipt(),
        False,
        None,
        dict(PRIOR_COUNTS),
        "a" * 64,
    )
    expected = _expected(
        zero_state_first_publication=False,
        prior_publication_run_id=1,
        prior_family_counts=PRIOR_COUNTS,
        prior_structural_digest="a" * 64,
        prior_latest_recorded_run_id=1,
    )

    result = classify_terminal_evidence(expected, evidence, pre_binding=True)

    assert result.publication_state is PublicationState.PRIOR_PUBLICATION_PRESERVED
    assert result.stage_state is StageState.PRE_BINDING_RECONCILED
    assert result.cleanup_state is CleanupState.NOT_ELIGIBLE


def test_prebinding_prior_publication_accepts_exact_prior_stage() -> None:
    prior = RecordedRun(GraphRunId(1), RunStatus.COMPLETE, "2026-07-20T00:00:00Z", None)
    publication = ReceiptBearingPublication(prior, _receipt())
    prior_stage = StageTerminalEvidence(
        "published",
        "committed",
        "reconciled",
        "eligible",
        "direct",
        "direct-attempt",
        1,
        GENERATIONS,
        False,
    )
    evidence = TerminalStorageEvidence(
        True,
        RunAuthoritySnapshot(prior, None, publication),
        RunPublicationRecord(GraphRunId(1), _receipt()),
        _receipt(),
        False,
        prior_stage,
        dict(PRIOR_COUNTS),
        "a" * 64,
    )
    expected = _expected(
        zero_state_first_publication=False,
        prior_publication_run_id=1,
        prior_family_counts=PRIOR_COUNTS,
        prior_structural_digest="a" * 64,
        prior_latest_recorded_run_id=1,
    )

    result = classify_terminal_evidence(expected, evidence, pre_binding=True)

    assert result.publication_state is PublicationState.PRIOR_PUBLICATION_PRESERVED
    assert result.stage_state is StageState.PRE_BINDING_RECONCILED
    assert result.cleanup_state is CleanupState.NOT_ELIGIBLE


def test_prebinding_foreign_stage_remains_unreconciled() -> None:
    stage = StageTerminalEvidence(
        "failed",
        "rolled_back",
        "reconciled",
        "eligible",
        "direct",
        "foreign-attempt",
        1,
        GENERATIONS,
        False,
    )
    evidence = TerminalStorageEvidence(
        True,
        RunAuthoritySnapshot(None, None, None),
        None,
        None,
        False,
        stage,
        dict(EMPTY_COUNTS),
        empty_semantic_digest(),
    )

    result = classify_terminal_evidence(_expected(), evidence, pre_binding=True)

    assert result.publication_state is not PublicationState.NOT_PUBLISHED
    assert result.stage_state is not StageState.PRE_BINDING_RECONCILED


def test_prebinding_cleanup_pair_is_reconciled_only_before_binding() -> None:
    assert storage_reconciled(
        True,
        True,
        PublicationState.NOT_PUBLISHED,
        StageState.PRE_BINDING_RECONCILED,
        CleanupState.NOT_ELIGIBLE,
    )
    assert not storage_reconciled(
        True,
        True,
        PublicationState.NOT_PUBLISHED,
        StageState.FAILED_RECONCILED,
        CleanupState.NOT_ELIGIBLE,
    )


def test_prebinding_prior_publication_requires_exact_receipt() -> None:
    prior = RecordedRun(GraphRunId(1), RunStatus.COMPLETE, "2026-07-20T00:00:00Z", None)
    publication = ReceiptBearingPublication(prior, _receipt())
    different_receipt = RunPublicationReceipt(
        RunPublicationAttempt(JobId("different-attempt"), AttemptNumber(1)),
        GENERATIONS,
    ).validate()
    evidence = TerminalStorageEvidence(
        True,
        RunAuthoritySnapshot(prior, None, publication),
        RunPublicationRecord(GraphRunId(1), different_receipt),
        _receipt(),
        False,
        None,
        dict(PRIOR_COUNTS),
        "a" * 64,
    )
    expected = _expected(
        zero_state_first_publication=False,
        prior_publication_run_id=1,
        prior_family_counts=PRIOR_COUNTS,
        prior_structural_digest="a" * 64,
        prior_latest_recorded_run_id=1,
    )

    result = classify_terminal_evidence(expected, evidence, pre_binding=True)

    assert result.publication_state is not PublicationState.PRIOR_PUBLICATION_PRESERVED
    assert result.stage_state is not StageState.PRE_BINDING_RECONCILED
