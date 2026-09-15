from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from repomap_kg.coordinator import _control_ownership as subject
from repomap_kg.coordinator._control_types import SingletonActiveError
from repomap_test_support.control_db_fakes import ScriptedCursor, connect_with


def queued_job(priority: str = "manual") -> dict[str, object]:
    return {
        "job_id": "job-1",
        "graph_id": "graph-1",
        "current_attempt": 1,
        "priority_class": priority,
        "source_generation": "sg",
        "config_generation": "cg",
        "extractor_generation": "eg",
        "canonicalizer_generation": "kg",
    }


def test_acquire_singleton_creates_first_owner() -> None:
    cursor = ScriptedCursor(rows=[None, {"fencing_epoch": 1}])

    assert subject.acquire_singleton(
        connect_with(cursor), "instance-a", timedelta(seconds=30)
    ) == 1
    assert "INSERT INTO coordinator_instances" in cursor.executions[1][0]


def test_acquire_singleton_rejects_unexpired_owner() -> None:
    now = datetime.now(timezone.utc)
    cursor = ScriptedCursor(
        rows=[{"status": "active", "database_now": now, "expires_at": now + timedelta(1)}]
    )

    with pytest.raises(SingletonActiveError, match="singleton is active"):
        subject.acquire_singleton(
            connect_with(cursor), "instance-b", timedelta(seconds=30)
        )


@pytest.mark.parametrize("status", ["stopped", "active"])
def test_acquire_singleton_replaces_stopped_or_expired_owner(status) -> None:
    now = datetime.now(timezone.utc)
    cursor = ScriptedCursor(
        rows=[
            {"status": status, "database_now": now, "expires_at": now - timedelta(1)},
            {"fencing_epoch": 4},
        ]
    )

    assert subject.acquire_singleton(
        connect_with(cursor), "instance-b", timedelta(seconds=30)
    ) == 4
    assert "UPDATE coordinator_instances" in cursor.executions[1][0]


@pytest.mark.parametrize(("operation", "rowcount", "expected"), [("heartbeat", 1, True), ("heartbeat", 0, False), ("stop", 1, True), ("stop", 0, False)])
def test_singleton_lease_mutations_report_ownership(operation, rowcount, expected) -> None:
    cursor = ScriptedCursor(rowcounts=[rowcount])

    if operation == "heartbeat":
        actual = subject.heartbeat_singleton(
            connect_with(cursor), "instance", 3, timedelta(seconds=30)
        )
    else:
        actual = subject.stop_singleton(connect_with(cursor), "instance", 3)

    assert actual is expected


def test_claim_once_returns_none_when_no_eligible_job(monkeypatch) -> None:
    cursor = ScriptedCursor(rows=[None])
    monkeypatch.setattr(subject, "require_transaction_admission", lambda *_: None)
    monkeypatch.setattr(subject, "require_live_owner", lambda *_: None)

    assert subject.claim_once(
        connect_with(cursor),
        "instance",
        3,
        30,
        max_attempts=3,
        automatic_only=False,
    ) is None


@pytest.mark.parametrize("priority", ["manual", "automatic"])
def test_claim_once_records_attempt_and_graph_lease(monkeypatch, priority) -> None:
    cursor = ScriptedCursor(
        rows=[queued_job(priority), {"graph_lease_fencing_epoch": 91}]
    )
    monkeypatch.setattr(subject, "require_transaction_admission", lambda *_: None)
    monkeypatch.setattr(subject, "require_live_owner", lambda *_: None)

    claim = subject.claim_once(
        connect_with(cursor),
        "instance",
        3,
        30,
        max_attempts=3,
        automatic_only=priority == "automatic",
    )

    assert claim is not None
    assert (claim.job_id, claim.attempt, claim.graph_lease_fencing_epoch) == (
        "job-1",
        2,
        91,
    )
    rendered = "\n".join(statement for statement, _ in cursor.executions)
    assert "INSERT INTO job_attempts" in rendered
    assert "INSERT INTO graph_leases" in rendered
    assert ("UPDATE coalescing_state" in rendered) is (priority == "automatic")


@pytest.mark.parametrize(("rowcount", "expected"), [(1, True), (0, False)])
def test_release_graph_lease_reports_exact_release(rowcount, expected) -> None:
    cursor = ScriptedCursor(rowcounts=[rowcount])

    assert subject.release_graph_lease(
        connect_with(cursor),
        "graph",
        "job",
        2,
        "worker",
        3,
        reconciler_instance_id="coordinator",
        reconciler_epoch=4,
    ) is expected
    assert (len(cursor.executions) == 2) is expected


def test_require_live_owner_accepts_matching_owner() -> None:
    subject.require_live_owner(ScriptedCursor(rows=[{"?column?": 1}]), "instance", 3)


def test_require_live_owner_rejects_missing_owner() -> None:
    with pytest.raises(SingletonActiveError, match="not owned"):
        subject.require_live_owner(ScriptedCursor(rows=[None]), "instance", 3)


@pytest.mark.parametrize("duration", [timedelta(0), timedelta(seconds=-1)])
def test_positive_seconds_rejects_nonpositive_duration(duration) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        subject.positive_seconds(duration)


def test_positive_seconds_preserves_fractional_duration() -> None:
    assert subject.positive_seconds(timedelta(milliseconds=1500)) == 1.5


@pytest.mark.parametrize(("constraint", "expected"), [("graph_leases_pkey", True), ("other", False), (None, False)])
def test_expected_graph_lease_race_matches_exact_constraint(constraint, expected) -> None:
    error = RuntimeError("database race")
    if constraint is not None:
        setattr(error, "diag", SimpleNamespace(constraint_name=constraint))

    assert subject.is_expected_graph_lease_race(error) is expected
