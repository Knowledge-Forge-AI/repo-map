from __future__ import annotations

import pytest

from repomap_kg.coordinator import _control_coalescing as subject
from repomap_kg.coordinator.contracts import JobRequest
from repomap_kg.coordinator.limits import CoordinatorLimits
from repomap_kg.storage.authority import RequestId
from repomap_test_support.control_db_fakes import ScriptedCursor, connect_with


GENERATIONS = ("sg1:abc123", "cg1:def456", "eg1:ghi789", "kg1:jkl012")


def request(*, priority: str = "automatic") -> JobRequest:
    return JobRequest(
        schema_version=1,
        job_kind="refresh_graph",
        graph_id="synthetic-example-graph",
        request_id=RequestId("request-001"),
        idempotency_key="request-key",
        priority=priority,
        operation_options=(("reason", "watcher-hint"),),
        source_generation=GENERATIONS[0],
        config_generation=GENERATIONS[1],
        extractor_generation=GENERATIONS[2],
        canonicalizer_generation=GENERATIONS[3],
    )


def current(**updates: object) -> dict[str, object]:
    row = {
        "paused": False,
        "desired_source_generation": GENERATIONS[0],
        "desired_config_generation": GENERATIONS[1],
        "desired_extractor_generation": GENERATIONS[2],
        "desired_canonicalizer_generation": GENERATIONS[3],
        "queued_job_id": None,
        "running_job_id": None,
    }
    row.update(updates)
    return row


def prepare(monkeypatch) -> None:
    monkeypatch.setattr(subject, "validate_request", lambda value: value)
    monkeypatch.setattr(subject, "require_transaction_admission", lambda *_: None)
    monkeypatch.setattr(subject, "_enforce_admission", lambda *_: None)


def test_coalescing_rejects_manual_request() -> None:
    with pytest.raises(ValueError, match="automatic priority"):
        subject.coalesce_automatic(
            connect_with(ScriptedCursor()),
            request(priority="manual"),
            requester="watcher",
            limits=CoordinatorLimits(),
        )


def test_coalescing_rejects_paused_graph(monkeypatch) -> None:
    prepare(monkeypatch)
    cursor = ScriptedCursor(rows=[current(paused=True)])

    with pytest.raises(ValueError, match="intent is paused"):
        subject.coalesce_automatic(
            connect_with(cursor), request(), requester="watcher", limits=CoordinatorLimits()
        )


@pytest.mark.parametrize(
    ("queued", "running"), [("queued-job", None), (None, "running-job")]
)
def test_coalescing_replays_matching_live_job(monkeypatch, queued, running) -> None:
    prepare(monkeypatch)
    existing_id = queued or running
    cursor = ScriptedCursor(
        rows=[current(queued_job_id=queued, running_job_id=running), {"state": "claimed"}]
    )

    result = subject.coalesce_automatic(
        connect_with(cursor), request(), requester="watcher", limits=CoordinatorLimits()
    )

    assert (result.job_id, result.state, result.replayed) == (
        existing_id,
        "claimed",
        True,
    )


@pytest.mark.parametrize("existing", [None, {"state": "succeeded"}])
def test_coalescing_replaces_stale_queued_job(monkeypatch, existing) -> None:
    prepare(monkeypatch)
    cursor = ScriptedCursor(rows=[current(queued_job_id="old-job"), existing])

    result = subject.coalesce_automatic(
        connect_with(cursor), request(), requester="watcher", limits=CoordinatorLimits()
    )

    assert (result.state, result.replayed) == ("queued", False)
    rendered = "\n".join(statement for statement, _ in cursor.executions)
    assert "state = 'superseded'" in rendered
    assert "replacement_job_id" in rendered


def test_coalescing_creates_first_intent(monkeypatch) -> None:
    prepare(monkeypatch)
    cursor = ScriptedCursor(rows=[None])

    result = subject.coalesce_automatic(
        connect_with(cursor), request(), requester="watcher", limits=CoordinatorLimits()
    )

    assert (result.state, result.replayed) == ("queued", False)
    rendered = "\n".join(statement for statement, _ in cursor.executions)
    assert "INSERT INTO jobs" in rendered
    assert "INSERT INTO coalescing_state" in rendered
    assert "state = 'superseded'" not in rendered


def test_coalescing_creates_job_when_matching_intent_has_no_job(monkeypatch) -> None:
    prepare(monkeypatch)
    cursor = ScriptedCursor(rows=[current()])

    result = subject.coalesce_automatic(
        connect_with(cursor), request(), requester="watcher", limits=CoordinatorLimits()
    )

    assert (result.state, result.replayed) == ("queued", False)


def test_coalescing_replaces_changed_desired_generations(monkeypatch) -> None:
    prepare(monkeypatch)
    cursor = ScriptedCursor(
        rows=[current(desired_source_generation="older", queued_job_id="old-job")]
    )

    result = subject.coalesce_automatic(
        connect_with(cursor), request(), requester="watcher", limits=CoordinatorLimits()
    )

    assert (result.state, result.replayed) == ("queued", False)
    assert any("state = 'superseded'" in sql for sql, _ in cursor.executions)


def test_desired_returns_ordered_generation_tuple() -> None:
    assert subject._desired(current()) == GENERATIONS


def test_upsert_intent_records_public_reason() -> None:
    cursor = ScriptedCursor()

    subject._upsert_intent(cursor, request(), "job-1", GENERATIONS)

    parameters = cursor.executions[0][1]
    assert isinstance(parameters, tuple)
    assert parameters[-2:] == (["watcher-hint"], "job-1")
