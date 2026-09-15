from __future__ import annotations

from collections.abc import Mapping

import pytest

from repomap_kg.storage import publication_fencing
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.publication import (
    PortablePublicationBinding,
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_fencing import (
    PublicationHandoff,
    PublicationReconciliationOutcome,
    PublicationContractError,
    build_publication_finalize_statements,
    build_publication_prepare_statements,
    build_publication_reconciliation_statements,
    classify_publication_marker,
)
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.staging_ownership import StageOwner


def _handoff(*, mode: str = "coordinator", job_id: str | None = "job-scale5") -> PublicationHandoff:
    op_id = OperationId(job_id or "direct-operation")
    typed_job_id = JobId(job_id) if job_id is not None else None
    owner = StageOwner(
        repository_id=7,
        operation_id=op_id,
        attempt=AttemptNumber(2),
        execution_mode=mode,
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
        job_id=typed_job_id,
        coordinator_instance_id="coord-scale5" if mode == "coordinator" else None,
        singleton_fencing_epoch=9 if mode == "coordinator" else 0,
        graph_lease_fencing_epoch=9 if mode == "coordinator" else 0,
    )
    receipt = RunPublicationReceipt(
        RunPublicationAttempt(JobId(job_id or "direct-operation"), AttemptNumber(2)),
        RunPublicationGenerations(
            "sg1:source", "cg1:config", "eg1:extractor", "kg1:canonicalizer"
        ),
    )
    return PublicationHandoff(MergeContext("stage-scale5", owner, 41), receipt)


def test_publication_handoff_requires_exact_attempt_and_generations() -> None:
    handoff = _handoff()
    assert handoff.validate() is handoff
    statements = build_publication_finalize_statements(handoff)
    assert len(statements) == 2
    assert all("BEGIN;" not in statement for statement in statements)
    assert all("COMMIT;" not in statement for statement in statements)
    assert "graph_publication_authority" in statements[0]
    assert "publication_job_id" in statements[1]

    wrong_attempt = PublicationHandoff(
        handoff.merge,
        RunPublicationReceipt(
            RunPublicationAttempt(JobId("other-job"), AttemptNumber(2)), handoff.receipt.generations
        ),
    )
    with pytest.raises(PublicationContractError, match="attempt identity"):
        wrong_attempt.validate()

    wrong_generations = PublicationHandoff(
        handoff.merge,
        RunPublicationReceipt(
            handoff.receipt.attempt,
            RunPublicationGenerations(
                "sg1:other", "cg1:config", "eg1:extractor", "kg1:canonicalizer"
            ),
        ),
    )
    with pytest.raises(PublicationContractError, match="generation"):
        wrong_generations.validate()


def test_publication_preparation_is_a_durable_stage_transition_only() -> None:
    statements = build_publication_prepare_statements(_handoff())
    assert len(statements) == 2
    assert "state = 'merging'" in statements[1]
    assert "publication_reconciliation_state = 'reconciled'" not in "".join(
        statements
    )


def test_coordinator_claim_registration_precedes_publication_without_receipt() -> None:
    builder = getattr(
        publication_fencing,
        "build_graph_publication_claim_statements",
        None,
    )
    assert builder is not None

    statements = builder(_handoff().merge)
    assert len(statements) == 1
    assert "graph_publication_authority" in statements[0]
    assert "last_run_id" in statements[0]
    assert "NULL" in statements[0]
    assert "stale graph publication claim" in statements[0]
    assert builder(_handoff(mode="direct", job_id=None).merge) == ()


def test_direct_identity_is_explicit_and_does_not_require_a_coordinator_job() -> None:
    handoff = _handoff(mode="direct", job_id=None)
    assert handoff.validate() is handoff
    assert "job-direct-operation" not in "".join(
        build_publication_finalize_statements(handoff)
    )


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        (None, PublicationReconciliationOutcome.ABSENT),
        (
            {
                "latest_run_identity": "run-41",
                "source_generation": "sg1:source",
                "config_generation": "cg1:config",
                "extractor_generation": "eg1:extractor",
                "canonicalizer_generation": "kg1:canonicalizer",
            },
            PublicationReconciliationOutcome.MATCHING_COMMITTED,
        ),
        (
            {
                "latest_run_identity": "run-41",
                "source_generation": "sg1:other",
                "config_generation": "cg1:config",
                "extractor_generation": "eg1:extractor",
                "canonicalizer_generation": "kg1:canonicalizer",
            },
            PublicationReconciliationOutcome.CONFLICTING,
        ),
        ({"latest_run_identity": "run-41"}, PublicationReconciliationOutcome.INSUFFICIENT),
    ],
)
def test_publication_marker_classification(
    marker: Mapping[str, object] | None,
    expected: PublicationReconciliationOutcome,
) -> None:
    assert classify_publication_marker(_handoff(), marker) is expected


def test_publication_marker_must_identify_the_expected_run() -> None:
    marker = {
        "latest_run_identity": "run-42",
        "source_generation": "sg1:source",
        "config_generation": "cg1:config",
        "extractor_generation": "eg1:extractor",
        "canonicalizer_generation": "kg1:canonicalizer",
    }
    assert classify_publication_marker(_handoff(), marker) is PublicationReconciliationOutcome.CONFLICTING


def test_publication_builder_rejects_direct_coordinator_fields() -> None:
    handoff = _handoff(mode="direct", job_id=None)
    owner = handoff.merge.owner
    invalid = PublicationHandoff(
        MergeContext(
            handoff.merge.stage_id,
            StageOwner(
                **{
                    **owner.__dict__,
                    "coordinator_instance_id": "coord-scale5",
                }
            ),
            handoff.merge.run_id,
        ),
        handoff.receipt,
    )
    with pytest.raises(PublicationContractError):
        invalid.validate()


def test_reconciliation_requires_proof_and_is_fail_closed() -> None:
    handoff = _handoff()
    with pytest.raises(PublicationContractError, match="rollback proof"):
        build_publication_reconciliation_statements(
            handoff, PublicationReconciliationOutcome.ABSENT
        )

    assert build_publication_reconciliation_statements(
        handoff, PublicationReconciliationOutcome.INSUFFICIENT
    ) == ()

    matching = build_publication_reconciliation_statements(
        handoff, PublicationReconciliationOutcome.MATCHING_COMMITTED
    )
    assert len(matching) == 1
    assert "SCALE5 reconciliation stage update failed" in matching[0]
    assert "state = 'published'" in matching[0]

    conflicting = build_publication_reconciliation_statements(
        handoff, PublicationReconciliationOutcome.CONFLICTING
    )
    assert "state = 'quarantined'" in conflicting[0]


def _portable_binding() -> PortablePublicationBinding:
    return PortablePublicationBinding(
        route="portable-worker-v1",
        snapshot_manifest_id="snapmanifest1:" + "1" * 64,
        snapshot_vector=(("bind1:" + "2" * 64, 1, "snap1:" + "3" * 64),),
        extraction_receipt_id="receipt1:" + "4" * 64,
        publication_bundle_id="bundle1:" + "5" * 64,
        candidate_id="cand1:" + "6" * 64,
        resolver_identity="resolver1:nix-static-v2",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
        protocol_version="1.0",
        worker_capability_identity="cap1:portable-worker-v1",
        stage_id="stage-scale5",
        execution_mode="coordinator",
        singleton_fencing_epoch=9,
        graph_lease_fencing_epoch=9,
        family_receipts={
            family: {
                "count": 1,
                "byte_length": 10,
                "digest": "sha256:" + "7" * 64,
            }
            for family in (
                "files", "raw_observations", "canonical_nodes",
                "canonical_edges", "canonical_evidence",
                "canonical_node_evidence", "canonical_edge_evidence",
            )
        },
    )


def _portable_handoff() -> PublicationHandoff:
    base = _handoff()
    binding = _portable_binding()
    receipt = RunPublicationReceipt(base.receipt.attempt, base.receipt.generations, binding)
    return PublicationHandoff(base.merge, receipt)


def test_portable_publication_marker_classification() -> None:
    handoff = _portable_handoff()
    assert handoff.receipt.portable is not None
    marker = {
        "latest_run_identity": f"run-{handoff.merge.run_id}",
        "source_generation": "sg1:source",
        "config_generation": "cg1:config",
        "extractor_generation": "eg1:extractor",
        "canonicalizer_generation": "kg1:canonicalizer",
        **handoff.receipt.portable.to_mapping(),
    }
    assert classify_publication_marker(handoff, marker) is PublicationReconciliationOutcome.MATCHING_COMMITTED
    assert classify_publication_marker(handoff, None) is PublicationReconciliationOutcome.ABSENT

    # Missing a required portable field
    incomplete_marker = {k: v for k, v in marker.items() if k != "publication_bundle_id"}
    assert classify_publication_marker(handoff, incomplete_marker) is PublicationReconciliationOutcome.INSUFFICIENT

    # Mismatched portable field
    conflicting_marker = {**marker, "publication_bundle_id": "bundle1:" + "f" * 64}
    assert classify_publication_marker(handoff, conflicting_marker) is PublicationReconciliationOutcome.CONFLICTING

    # Mismatched run identity
    wrong_run_marker = {**marker, "latest_run_identity": "run-999"}
    assert classify_publication_marker(handoff, wrong_run_marker) is PublicationReconciliationOutcome.CONFLICTING


def test_publication_handoff_rejects_invalid_stage_identity() -> None:
    from unittest.mock import Mock

    handoff = _handoff()
    mock_merge = Mock(owner=handoff.merge.owner, stage_id="invalid-stage-!@#", run_id=41)
    mock_merge.validate.return_value = mock_merge
    invalid_stage = PublicationHandoff(mock_merge, handoff.receipt)
    with pytest.raises(PublicationContractError, match="invalid publication stage"):
        invalid_stage.validate()


def test_publication_reconciliation_absent_requires_proof_and_valid_terminal() -> None:
    handoff = _handoff()
    with pytest.raises(PublicationContractError, match="rollback proof is required"):
        build_publication_reconciliation_statements(
            handoff,
            PublicationReconciliationOutcome.ABSENT,
            absence_proved=False,
        )

    with pytest.raises(PublicationContractError, match="invalid reconciliation terminal"):
        build_publication_reconciliation_statements(
            handoff,
            PublicationReconciliationOutcome.ABSENT,
            absence_proved=True,
            terminal="invalid_terminal",
        )


def test_classify_publication_marker_rejects_malformed_run_identity() -> None:
    handoff = _handoff()
    marker = {
        "latest_run_identity": "not-a-valid-run-identity",
        "source_generation": "sg1:source",
        "config_generation": "cg1:config",
        "extractor_generation": "eg1:extractor",
        "canonicalizer_generation": "kg1:canonicalizer",
    }
    assert classify_publication_marker(handoff, marker) is PublicationReconciliationOutcome.INSUFFICIENT

    marker_non_str = {
        **marker,
        "latest_run_identity": 42,
    }
    assert classify_publication_marker(handoff, marker_non_str) is PublicationReconciliationOutcome.INSUFFICIENT
