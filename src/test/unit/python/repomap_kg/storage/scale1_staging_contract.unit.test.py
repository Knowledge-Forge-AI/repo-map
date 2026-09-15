from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId

from repomap_kg.storage.staging import (
    CleanupEligibility,
    LEGAL_STAGE_TRANSITIONS,
    MergeStatus,
    PublicationReconciliationState,
    StageHeader,
    StageOwner,
    StageState,
    StageTransitionError,
    StageOwnershipError,
    ValidationStatus,
    STAGING_FAMILIES,
    cleanup_eligibility,
    checksum_family,
    require_stage_owner,
    validate_stage_transition,
)


def coordinator_owner() -> StageOwner:
    return StageOwner(
        repository_id=7,
        operation_id=OperationId("job-001"),
        attempt=AttemptNumber(2),
        execution_mode="coordinator",
        job_id=JobId("job-001"),
        coordinator_instance_id="coord-001",
        singleton_fencing_epoch=4,
        graph_lease_fencing_epoch=4,
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
    )


def direct_owner() -> StageOwner:
    return StageOwner(
        repository_id=7,
        operation_id=OperationId("direct-001"),
        attempt=AttemptNumber(1),
        execution_mode="direct",
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
    )


def test_staging_manifest_retains_every_active_writer_family() -> None:
    assert STAGING_FAMILIES == (
        "files",
        "raw_observations",
        "canonical_nodes",
        "canonical_edges",
        "canonical_evidence",
        "canonical_node_evidence",
        "canonical_edge_evidence",
    )
def test_stage_state_machine_has_explicit_commit_unknown_and_cleanup_paths() -> None:
    assert validate_stage_transition(StageState.LOADING, StageState.PREPARED)
    assert validate_stage_transition(StageState.MERGING, StageState.PUBLISHED)
    assert validate_stage_transition(StageState.MERGING, StageState.COMMIT_UNKNOWN)
    assert validate_stage_transition(
        StageState.COMMIT_UNKNOWN, StageState.QUARANTINED
    )
    assert validate_stage_transition(StageState.PUBLISHED, StageState.CLEANUP_PENDING)
    assert validate_stage_transition(StageState.CLEANUP_PENDING, StageState.CLEANED)
    assert validate_stage_transition(StageState.LOADING, StageState.LOADING)
    assert StageState.CLEANED not in LEGAL_STAGE_TRANSITIONS[StageState.CLEANED]


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (StageState.LOADING, StageState.MERGING),
        (StageState.MERGING, StageState.CANCELLED),
        (StageState.COMMIT_UNKNOWN, StageState.PREPARED),
        (StageState.CLEANED, StageState.LOADING),
    ],
)
def test_stage_state_machine_rejects_unsafe_transitions(
    current: StageState, target: StageState
) -> None:
    with pytest.raises(StageTransitionError):
        validate_stage_transition(current, target)


def test_stage_owner_accepts_coordinator_and_direct_modes_without_forking_identity() -> None:
    coordinator = coordinator_owner()
    direct = direct_owner()
    assert coordinator.validate() is coordinator
    assert direct.validate() is direct
    require_stage_owner(coordinator, coordinator)

    with pytest.raises(StageOwnershipError):
        require_stage_owner(
            coordinator,
            StageOwner(
                **{
                    **coordinator.__dict__,
                    "attempt": 3,
                }
            ),
        )


@pytest.mark.parametrize(
    "owner",
    [
        StageOwner(
            repository_id=7,
            operation_id=OperationId("/synthetic-source"),
            attempt=AttemptNumber(1),
            execution_mode="direct",
            source_generation="sg1:source",
            config_generation="cg1:config",
            extractor_generation="eg1:extractor",
            canonicalizer_generation="kg1:canonicalizer",
        ),
        StageOwner(
            repository_id=7,
            operation_id=OperationId("direct-001"),
            attempt=AttemptNumber(1),
            execution_mode="direct",
            source_generation="sg1:/synthetic-source",
            config_generation="cg1:config",
            extractor_generation="eg1:extractor",
            canonicalizer_generation="kg1:canonicalizer",
        ),
    ],
)
def test_stage_owner_rejects_private_or_unsafe_identity_without_echoing(
    owner: StageOwner,
) -> None:
    with pytest.raises(StageOwnershipError) as caught:
        owner.validate()

    assert str(caught.value) == "invalid stage owner"
    assert "/synthetic-source" not in str(caught.value)


def test_stage_header_validates_manifest_counts_and_state_invariants() -> None:
    now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
    header = StageHeader(
        stage_id="stage-001",
        owner=coordinator_owner(),
        state=StageState.PUBLISHED,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
        expected_row_counts={family: 0 for family in STAGING_FAMILIES},
        validation_status=ValidationStatus.PASSED,
        merge_status=MergeStatus.COMMITTED,
        publication_reconciliation_state=PublicationReconciliationState.RECONCILED,
    )

    assert header.validate() is header

    with pytest.raises(ValueError, match="stage header"):
        StageHeader(
            stage_id="stage-001",
            owner=coordinator_owner(),
            state=StageState.COMMIT_UNKNOWN,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(hours=1),
            merge_status=MergeStatus.UNKNOWN,
            publication_reconciliation_state=PublicationReconciliationState.NOT_STARTED,
        ).validate()


def test_checksum_is_order_independent_and_type_strict() -> None:
    rows = (
        {"stable_key": "node:b", "value": 1, "enabled": True},
        {"stable_key": "node:a", "value": 1.0, "enabled": False},
        {"stable_key": "node:a", "value": 1, "enabled": False},
    )
    first = checksum_family(rows, identity_fields=("stable_key",))
    second = checksum_family(tuple(reversed(rows)), identity_fields=("stable_key",))

    assert first == second
    assert first.row_count == 3
    assert first.normalized_byte_count > 0
    assert len(first.stable_key_digest) == 64
    assert len(first.payload_digest) == 64
    assert first.stable_key_digest != checksum_family(
        rows[:2], identity_fields=("stable_key",)
    ).stable_key_digest


def test_checksum_rejects_missing_identity_field_without_exposing_row_values() -> None:
    with pytest.raises(ValueError) as caught:
        checksum_family(({"payload": "private"},), identity_fields=("stable_key",))

    assert str(caught.value) == "checksum identity field is missing"
    assert "private" not in str(caught.value)


def test_cleanup_reconciles_before_deleting_stage_rows() -> None:
    now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
    expired = now - timedelta(minutes=1)

    assert cleanup_eligibility(
        StageState.COMMIT_UNKNOWN,
        PublicationReconciliationState.REQUIRED,
        attempt_live=False,
        now=now,
        expires_at=expired,
    ) is CleanupEligibility.BLOCKED
    assert cleanup_eligibility(
        StageState.QUARANTINED,
        PublicationReconciliationState.CONFLICTING,
        attempt_live=False,
        now=now,
        expires_at=expired,
    ) is CleanupEligibility.QUARANTINED
    assert cleanup_eligibility(
        StageState.FAILED,
        PublicationReconciliationState.NOT_STARTED,
        attempt_live=True,
        now=now,
        expires_at=expired,
    ) is CleanupEligibility.BLOCKED
    assert cleanup_eligibility(
        StageState.FAILED,
        PublicationReconciliationState.REQUIRED,
        attempt_live=False,
        now=now,
        expires_at=expired,
    ) is CleanupEligibility.BLOCKED
    assert cleanup_eligibility(
        StageState.CANCELLED,
        PublicationReconciliationState.RECONCILED,
        attempt_live=False,
        now=now,
        expires_at=expired,
    ) is CleanupEligibility.EXPIRED
    assert cleanup_eligibility(
        StageState.CLEANED,
        PublicationReconciliationState.RECONCILED,
        attempt_live=False,
        now=now,
        expires_at=expired,
    ) is CleanupEligibility.CLEANED


@pytest.mark.parametrize("invalid_status", ["unknown-status", None, []])
def test_stage_header_rejects_invalid_validation_status_with_causal_error(
    invalid_status: object,
) -> None:
    from dataclasses import replace

    now = datetime.now(UTC)
    header = StageHeader(
        stage_id="stage-001", owner=coordinator_owner(),
        created_at=now, updated_at=now, expires_at=now + timedelta(hours=1),
    )
    assert header.validate() is header
    invalid = replace(header)
    object.__setattr__(invalid, "validation_status", invalid_status)
    with pytest.raises(ValueError, match="invalid stage header") as caught:
        invalid.validate()
    assert isinstance(caught.value.__cause__, (TypeError, ValueError))
    assert header.validation_status is ValidationStatus.NOT_STARTED
    assert header.validate() is header
