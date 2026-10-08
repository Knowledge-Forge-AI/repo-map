from __future__ import annotations

from copy import deepcopy

import pytest

from repomap_kg.coordinator import _control_reconciliation as subject
from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator.semantics import reconcile_publication as model_reconcile
from repomap_test_support.control_db_fakes import ScriptedCursor, connect_with


CLAIM = JobClaim("job-1", "graph-1", 2, "worker-1", 3)


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("marker", ["absent", "matching_committed", "conflicting"])
@pytest.mark.parametrize(
    "publication,proof,without_cancel,with_cancel",
    [
        ("not_started", "unproved", "queued", "reconciliation_required"),
        ("prepared", "unproved", "queued", "reconciliation_required"),
        ("rolled_back", "unproved", "queued", "cancelled"),
        ("commit_unknown", "unproved", "reconciliation_required", "reconciliation_required"),
        ("not_started", "fenced_absence", "queued", "cancelled"),
        ("prepared", "fenced_absence", "reconciliation_required", "reconciliation_required"),
        ("rolled_back", "fenced_absence", "reconciliation_required", "reconciliation_required"),
        ("commit_unknown", "fenced_absence", "reconciliation_required", "reconciliation_required"),
        ("transaction_started", "fenced_absence", "reconciliation_required", "reconciliation_required"),
        ("committed", "fenced_absence", "reconciliation_required", "reconciliation_required"),
    ],
)
def test_model_and_durable_decision_table_agree(
    monkeypatch, publication, marker, proof, without_cancel, with_cancel, cancel,
):
    row = matching_evidence() if marker != "absent" else evidence()
    row.update(
        job_publication_state=publication, attempt_publication_state=publication,
        cancel_requested_at="now" if cancel else None,
    )
    if marker == "conflicting":
        row["marker_graph_id"] = "conflicting-graph"
    cursor = ScriptedCursor(rows=[row])
    monkeypatch.setattr(subject, "require_live_owner", lambda *_args: None)
    outcome = subject.reconcile_publication(
        connect_with(cursor), CLAIM, max_attempts=3,
        reconciler_instance_id="coordinator", reconciler_epoch=7,
        unpublished_proved=proof == "fenced_absence",
    )
    expected = {"matching_committed": "succeeded", "conflicting": "quarantined"}.get(
        marker, with_cancel if cancel else without_cancel,
    )
    assert outcome == expected
    assert model_reconcile(publication, marker, cancel, absence_proof=proof) == expected
    if outcome == "reconciliation_required":
        assert not any(stmt.lstrip().startswith("UPDATE") for stmt, _ in cursor.executions)


def evidence() -> dict[str, object]:
    return {
        "attempt_finished_at": "finished",
        "job_publication_state": "prepared",
        "attempt_publication_state": "prepared",
        "current_attempt": 2,
        "error_category": "transient",
        "cancel_requested_at": None,
        "graph_id": "graph-1",
        "job_source_generation": "sg",
        "job_config_generation": "cg",
        "job_extractor_generation": "eg",
        "job_canonicalizer_generation": "kg",
        "attempt_source_generation": "sg",
        "attempt_config_generation": "cg",
        "attempt_extractor_generation": "eg",
        "attempt_canonicalizer_generation": "kg",
        "marker_outcome": None,
        "marker_graph_id": None,
        "marker_source_generation": None,
        "marker_config_generation": None,
        "marker_extractor_generation": None,
        "marker_canonicalizer_generation": None,
    }


def matching_evidence() -> dict[str, object]:
    row = evidence()
    row.update(
        marker_outcome="committed",
        marker_graph_id="graph-1",
        marker_source_generation="sg",
        marker_config_generation="cg",
        marker_extractor_generation="eg",
        marker_canonicalizer_generation="kg",
    )
    return row


@pytest.mark.parametrize(
    ("mutate", "maximum", "expected"),
    [
        (lambda _row: None, 3, "queued"),
        (lambda row: row.update(attempt_finished_at=None), 3, "reconciliation_required"),
        (lambda row: row.update(marker_outcome="committed", marker_graph_id="other"), 3, "quarantined"),
        (lambda row: row.update(error_category="protocol"), 3, "quarantined"),
        (lambda row: row.update(job_publication_state="commit_unknown"), 3, "reconciliation_required"),
        (lambda row: row.update(cancel_requested_at="now"), 3, "reconciliation_required"),
        (
            lambda row: row.update(
                cancel_requested_at="now",
                job_publication_state="rolled_back",
                attempt_publication_state="rolled_back",
            ),
            3,
            "cancelled",
        ),
        (lambda _row: None, 2, "failed"),
    ],
)
def test_reconcile_publication_decisions(monkeypatch, mutate, maximum, expected) -> None:
    row = evidence()
    mutate(row)
    cursor = ScriptedCursor(rows=[row])
    monkeypatch.setattr(subject, "require_live_owner", lambda *_args: None)

    assert subject.reconcile_publication(
        connect_with(cursor),
        CLAIM,
        max_attempts=maximum,
        reconciler_instance_id="coordinator",
        reconciler_epoch=7,
    ) == expected


def test_reconcile_publication_accepts_matching_commit_without_cancel(monkeypatch) -> None:
    cursor = ScriptedCursor(rows=[matching_evidence()])
    monkeypatch.setattr(subject, "require_live_owner", lambda *_args: None)

    assert subject.reconcile_publication(
        connect_with(cursor),
        CLAIM,
        max_attempts=3,
        reconciler_instance_id="coordinator",
        reconciler_epoch=7,
    ) == "succeeded"

    attempt_updates = [
        (stmt, params) for stmt, params in cursor.executions
        if "UPDATE job_attempts" in stmt
    ]
    assert len(attempt_updates) == 1
    assert attempt_updates[0][1] == (
        "committed", None, None, CLAIM.job_id, CLAIM.attempt, CLAIM.instance_id, CLAIM.fencing_epoch
    )


def test_reconcile_publication_matching_commit_after_cancel_succeeds_with_diagnostic(monkeypatch) -> None:
    row = matching_evidence()
    row.update(cancel_requested_at="2026-10-07T12:00:00Z")
    cursor = ScriptedCursor(rows=[row])
    monkeypatch.setattr(subject, "require_live_owner", lambda *_args: None)

    assert subject.reconcile_publication(
        connect_with(cursor),
        CLAIM,
        max_attempts=3,
        reconciler_instance_id="coordinator",
        reconciler_epoch=7,
    ) == "succeeded"

    job_updates = [
        (stmt, params) for stmt, params in cursor.executions
        if "UPDATE jobs SET state = %s" in stmt
    ]
    assert len(job_updates) == 1
    assert job_updates[0][1] == ("succeeded", "committed", None, CLAIM.job_id, CLAIM.attempt)

    attempt_updates = [
        (stmt, params) for stmt, params in cursor.executions
        if "UPDATE job_attempts" in stmt
    ]
    assert len(attempt_updates) == 1
    assert attempt_updates[0][1] == (
        "committed", None, "cancellation_not_applied",
        CLAIM.job_id, CLAIM.attempt, CLAIM.instance_id, CLAIM.fencing_epoch,
    )


def test_reconcile_publication_fenced_absence_permits_cancellation(monkeypatch) -> None:
    row = evidence()
    row.update(
        job_publication_state="not_started",
        attempt_publication_state="not_started",
        cancel_requested_at="2026-10-07T12:00:00Z",
    )
    cursor = ScriptedCursor(rows=[row])
    monkeypatch.setattr(subject, "require_live_owner", lambda *_args: None)

    assert subject.reconcile_publication(
        connect_with(cursor),
        CLAIM,
        max_attempts=3,
        reconciler_instance_id="coordinator",
        reconciler_epoch=7,
        unpublished_proved=True,
    ) == "cancelled"

    job_updates = [
        (stmt, params) for stmt, params in cursor.executions
        if "UPDATE jobs SET state = %s" in stmt
    ]
    assert len(job_updates) == 1
    assert job_updates[0][1] == ("cancelled", "rolled_back", "cancelled", CLAIM.job_id, CLAIM.attempt)


def test_reconcile_publication_unproved_absence_retains_uncertainty(monkeypatch) -> None:
    row = evidence()
    row.update(
        job_publication_state="not_started",
        attempt_publication_state="not_started",
        cancel_requested_at="2026-10-07T12:00:00Z",
    )
    cursor = ScriptedCursor(rows=[row])
    monkeypatch.setattr(subject, "require_live_owner", lambda *_args: None)

    assert subject.reconcile_publication(
        connect_with(cursor),
        CLAIM,
        max_attempts=3,
        reconciler_instance_id="coordinator",
        reconciler_epoch=7,
        unpublished_proved=False,
    ) == "reconciliation_required"
    assert not any(stmt.lstrip().startswith("UPDATE") for stmt, _ in cursor.executions)


def test_reconcile_publication_attempt_commit_unknown_retains_uncertainty(monkeypatch) -> None:
    row = evidence()
    row.update(
        job_publication_state="prepared",
        attempt_publication_state="commit_unknown",
        cancel_requested_at="2026-10-07T12:00:00Z",
    )
    cursor = ScriptedCursor(rows=[row])
    monkeypatch.setattr(subject, "require_live_owner", lambda *_args: None)

    assert subject.reconcile_publication(
        connect_with(cursor),
        CLAIM,
        max_attempts=3,
        reconciler_instance_id="coordinator",
        reconciler_epoch=7,
    ) == "reconciliation_required"
    assert not any(stmt.lstrip().startswith("UPDATE") for stmt, _ in cursor.executions)


def test_reconcile_publication_reports_lost_job_ownership(monkeypatch) -> None:
    cursor = ScriptedCursor(rows=[None])
    monkeypatch.setattr(subject, "require_live_owner", lambda *_args: None)

    assert subject.reconcile_publication(
        connect_with(cursor),
        CLAIM,
        max_attempts=3,
        reconciler_instance_id="coordinator",
        reconciler_epoch=7,
    ) == "ownership_lost"


def test_fabricated_unpublished_boolean_does_not_override_uncertainty(monkeypatch) -> None:
    row = evidence()
    row.update(job_publication_state="commit_unknown", attempt_publication_state="commit_unknown")
    cursor = ScriptedCursor(rows=[row])
    monkeypatch.setattr(subject, "require_live_owner", lambda *_args: None)
    assert subject.reconcile_publication(
        connect_with(cursor), CLAIM, max_attempts=3,
        reconciler_instance_id="coordinator", reconciler_epoch=7, unpublished_proved=True,
    ) == "reconciliation_required"
    assert not any(query.lstrip().startswith("UPDATE") for query, _ in cursor.executions)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("marker_outcome", "rolled_back"),
        ("marker_graph_id", "other"),
        ("marker_source_generation", "other"),
        ("job_source_generation", "other"),
        ("attempt_source_generation", "other"),
        ("marker_config_generation", "other"),
        ("job_config_generation", "other"),
        ("attempt_config_generation", "other"),
        ("marker_extractor_generation", "other"),
        ("job_extractor_generation", "other"),
        ("attempt_extractor_generation", "other"),
        ("marker_canonicalizer_generation", "other"),
        ("job_canonicalizer_generation", "other"),
        ("attempt_canonicalizer_generation", "other"),
    ],
)
def test_marker_classification_rejects_each_conflict(key, value) -> None:
    row = matching_evidence()
    row[key] = value

    assert subject._marker_classification(row) == "conflicting"


def test_marker_classification_distinguishes_absent_and_matching() -> None:
    assert subject._marker_classification(evidence()) == "absent"
    assert subject._marker_classification(matching_evidence()) == "matching_committed"


@pytest.mark.parametrize(
    ("operation", "rowcounts", "message"),
    [
        (subject._close_attempt, [0], "attempt closure"),
        (subject._delete_lease, [0], "lease release"),
    ],
)
def test_reconciliation_mutations_fail_closed(operation, rowcounts, message) -> None:
    cursor = ScriptedCursor(rowcounts=rowcounts)

    with pytest.raises(RuntimeError, match=message):
        if operation is subject._close_attempt:
            operation(cursor, CLAIM, "rolled_back", "transient")
        else:
            operation(cursor, CLAIM)


def test_reconciliation_helpers_bind_claim_identity() -> None:
    cursor = ScriptedCursor(rows=[deepcopy(evidence())])

    assert subject._lock_evidence(cursor, CLAIM) == evidence()
    subject._pause_graph_intent(cursor, CLAIM)
    subject._close_terminal(cursor, CLAIM, "failed", "rolled_back", "permanent")
    subject._queue_retry(cursor, CLAIM)

    rendered = "\n".join(statement for statement, _ in cursor.executions)
    assert "FOR UPDATE OF j, a" in rendered
    assert "INSERT INTO coalescing_state" in rendered
    assert "UPDATE jobs SET state = %s" in rendered
    assert "UPDATE jobs SET state = 'queued'" in rendered


def test_reconcile_publication_refuses_zero_epoch_without_graph_fence(monkeypatch) -> None:
    row = evidence()
    row.update(attempt_graph_lease_fencing_epoch=0)
    cursor = ScriptedCursor(rows=[row])
    monkeypatch.setattr(subject, "require_live_owner", lambda *_args: None)

    assert subject.reconcile_publication(
        connect_with(cursor),
        CLAIM,
        max_attempts=3,
        reconciler_instance_id="coordinator",
        reconciler_epoch=7,
    ) == "reconciliation_required"

    rendered = "\n".join(statement for statement, _ in cursor.executions)
    assert "DELETE FROM graph_leases" not in rendered
    assert "UPDATE jobs" not in rendered
