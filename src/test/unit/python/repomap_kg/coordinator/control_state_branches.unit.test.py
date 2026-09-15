from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

import pytest

from repomap_kg.coordinator import _control_state as state
from repomap_kg.coordinator._control_types import JobClaim


class Cursor:
    def __init__(
        self,
        *,
        rows: Iterable[object] = (),
        rowcounts: Iterable[int] = (),
    ) -> None:
        self._rows = iter(rows)
        self._rowcounts = iter(rowcounts)
        self.rowcount = -1
        self.executions: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, sql: str, parameters=None) -> None:
        self.executions.append((sql, parameters))
        self.rowcount = next(self._rowcounts, 1)

    def fetchone(self):
        return next(self._rows, None)


class Connection:
    def __init__(self, cursor: Cursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def cursor(self, **_kwargs):
        return self._cursor


def connect(cursor: Cursor):
    return lambda: Connection(cursor)


@pytest.fixture
def claim() -> JobClaim:
    return JobClaim("job-1", "graph-1", 1, "instance-1", 7)


@pytest.mark.parametrize(
    ("job_state", "publication_state", "message"),
    [
        ("succeeded", None, "committed publication"),
        ("failed", "committed", "safely unpublished"),
        ("cancelled", "commit_unknown", "safely unpublished"),
        ("superseded", "committed", "safely unpublished"),
        ("queued", "commit_unknown", "cannot be retried"),
    ],
)
def test_publication_state_rejects_unsafe_durable_transitions(
    job_state: str,
    publication_state: str | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        state.validate_state_publication(job_state, publication_state)


@pytest.mark.parametrize(
    ("job_state", "publication_state"),
    [
        ("succeeded", "committed"),
        ("failed", "not_started"),
        ("cancelled", "rolled_back"),
        ("superseded", "not_started"),
        ("queued", "prepared"),
        ("running", None),
    ],
)
def test_publication_state_accepts_safe_durable_transitions(
    job_state: str,
    publication_state: str | None,
) -> None:
    state.validate_state_publication(job_state, publication_state)


def test_compare_and_set_reports_a_lost_primary_update() -> None:
    cursor = Cursor(rowcounts=(0,))

    changed = state.compare_and_set_state(
        connect(cursor), "job-1", expected_state="running", new_state="succeeded", attempt=1,
        instance_id="instance-1", fencing_epoch=7, publication_state="committed", error_category=None,
    )
    assert changed is False
    assert len(cursor.executions) == 1


def test_compare_and_set_closes_a_terminal_attempt() -> None:
    cursor = Cursor(rowcounts=(1, 1))
    changed = state.compare_and_set_state(
        connect(cursor), "job-1", expected_state="running", new_state="succeeded", attempt=1,
        instance_id="instance-1", fencing_epoch=7, publication_state="committed", error_category=None,
    )
    assert changed is True
    assert len(cursor.executions) == 2


def test_compare_and_set_refuses_an_unclosed_terminal_attempt() -> None:
    cursor = Cursor(rowcounts=(1, 0))
    with pytest.raises(RuntimeError, match="attempt closure failed"):
        state.compare_and_set_state(
            connect(cursor), "job-1", expected_state="running", new_state="failed", attempt=1,
            instance_id="instance-1", fencing_epoch=7, publication_state="rolled_back",
            error_category="worker_crash",
        )


@pytest.mark.parametrize("attempt_rowcount", [0, 1])
def test_compare_and_set_updates_nonterminal_publication(
    attempt_rowcount: int,
) -> None:
    cursor = Cursor(rowcounts=(1, attempt_rowcount))
    if attempt_rowcount == 0:
        with pytest.raises(RuntimeError, match="publication update failed"):
            state.compare_and_set_state(
                connect(cursor), "job-1", expected_state="starting", new_state="running", attempt=1,
                instance_id="instance-1", fencing_epoch=7, publication_state="prepared",
                error_category=None,
            )
    else:
        assert state.compare_and_set_state(
            connect(cursor), "job-1", expected_state="starting", new_state="running", attempt=1,
            instance_id="instance-1", fencing_epoch=7, publication_state="prepared",
            error_category=None,
        )


def test_compare_and_set_leaves_nonterminal_publication_unchanged() -> None:
    cursor = Cursor(rowcounts=(1,))
    assert state.compare_and_set_state(
        connect(cursor), "job-1", expected_state="claimed", new_state="starting", attempt=1,
        instance_id="instance-1", fencing_epoch=7, publication_state=None, error_category=None,
    )
    assert len(cursor.executions) == 1


def test_heartbeat_reports_a_lost_graph_lease(monkeypatch, claim: JobClaim) -> None:
    monkeypatch.setattr(state, "require_live_owner", lambda *_args: None)
    cursor = Cursor(rowcounts=(0,))

    assert not state.heartbeat_attempt(
        connect(cursor),
        claim,
        timedelta(seconds=5),
        phase=None,
        completed=None,
        total=None,
        progress_counter_delta=10,
        progress_min_interval_seconds=1,
        max_counter=100,
    )


@pytest.mark.parametrize("total", [None, 10])
def test_heartbeat_updates_valid_progress(
    monkeypatch,
    claim: JobClaim,
    total: int | None,
) -> None:
    monkeypatch.setattr(state, "require_live_owner", lambda *_args: None)
    cursor = Cursor(rowcounts=(1, 1, 1))

    assert state.heartbeat_attempt(
        connect(cursor),
        claim,
        timedelta(seconds=5),
        phase="extracting",
        completed=5,
        total=total,
        progress_counter_delta=10,
        progress_min_interval_seconds=1,
        max_counter=100,
    )
    assert len(cursor.executions) == 3


@pytest.mark.parametrize("completed", [None, True, -1, 101, 1.5])
def test_heartbeat_rejects_invalid_completed_progress(
    monkeypatch,
    claim: JobClaim,
    completed,
) -> None:
    monkeypatch.setattr(state, "require_live_owner", lambda *_args: None)
    cursor = Cursor(rowcounts=(1, 1))

    with pytest.raises(ValueError, match="completed progress is invalid"):
        state.heartbeat_attempt(
            connect(cursor),
            claim,
            timedelta(seconds=5),
            phase="extracting",
            completed=completed,
            total=None,
            progress_counter_delta=10,
            progress_min_interval_seconds=1,
            max_counter=100,
        )


@pytest.mark.parametrize("total", [True, -1, 4, 101, 1.5])
def test_heartbeat_rejects_invalid_total_progress(
    monkeypatch,
    claim: JobClaim,
    total,
) -> None:
    monkeypatch.setattr(state, "require_live_owner", lambda *_args: None)
    cursor = Cursor(rowcounts=(1, 1))

    with pytest.raises(ValueError, match="total progress is invalid"):
        state.heartbeat_attempt(
            connect(cursor),
            claim,
            timedelta(seconds=5),
            phase="extracting",
            completed=5,
            total=total,
            progress_counter_delta=10,
            progress_min_interval_seconds=1,
            max_counter=100,
        )


def test_heartbeat_without_progress_only_refreshes_lease_and_attempt(
    monkeypatch,
    claim: JobClaim,
) -> None:
    monkeypatch.setattr(state, "require_live_owner", lambda *_args: None)
    cursor = Cursor(rowcounts=(1, 1))

    assert state.heartbeat_attempt(
        connect(cursor),
        claim,
        timedelta(seconds=5),
        phase=None,
        completed=None,
        total=None,
        progress_counter_delta=10,
        progress_min_interval_seconds=1,
        max_counter=100,
    )
    assert len(cursor.executions) == 2


@pytest.mark.parametrize("row", [("cancelled",), ("cancel_requested",)])
def test_request_cancellation_returns_the_durable_state(row: tuple[str]) -> None:
    assert state.request_cancellation(connect(Cursor(rows=(row,))), "job-1") == row[0]


def test_request_cancellation_rejects_a_non_cancellable_job() -> None:
    with pytest.raises(ValueError, match="cannot be cancelled"):
        state.request_cancellation(connect(Cursor()), "job-1")


def test_mark_attempt_terminated_requires_cleanup_proof(claim: JobClaim) -> None:
    with pytest.raises(ValueError, match="cleanup proof"):
        state.mark_attempt_terminated(
            connect(Cursor()),
            claim,
            process_cleanup_proved=False,
            reconciler_instance_id="reconciler-1",
            reconciler_epoch=9,
        )


@pytest.mark.parametrize(("rowcount", "expected"), [(0, False), (1, True)])
def test_mark_attempt_terminated_reports_the_compare_and_set_result(
    monkeypatch,
    claim: JobClaim,
    rowcount: int,
    expected: bool,
) -> None:
    monkeypatch.setattr(state, "require_live_owner", lambda *_args: None)
    assert (
        state.mark_attempt_terminated(
            connect(Cursor(rowcounts=(rowcount,))),
            claim,
            process_cleanup_proved=True,
            reconciler_instance_id="reconciler-1",
            reconciler_epoch=9,
        )
        is expected
    )


def test_schedule_retry_rejects_a_negative_delay(claim: JobClaim) -> None:
    with pytest.raises(ValueError, match="retry delay is invalid"):
        state.schedule_retry(
            connect(Cursor()),
            claim,
            expected_state="starting",
            delay=timedelta(seconds=-1),
            category="transient",
            max_attempts=3,
        )


def test_schedule_retry_reports_a_lost_claim(monkeypatch, claim: JobClaim) -> None:
    monkeypatch.setattr(state, "require_live_owner", lambda *_args: None)
    assert not state.schedule_retry(
        connect(Cursor()),
        claim,
        expected_state="starting",
        delay=timedelta(0),
        category="transient",
        max_attempts=3,
    )


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (("commit_unknown", 1), "publication cannot be retried"),
        (("not_started", 3), "retry is not permitted"),
        (("not_started", 1), "retry is not permitted"),
    ],
)
def test_schedule_retry_rejects_unsafe_or_disallowed_attempts(
    monkeypatch,
    claim: JobClaim,
    row: tuple[str, int],
    message: str,
) -> None:
    monkeypatch.setattr(state, "require_live_owner", lambda *_args: None)
    category = "permanent" if row == ("not_started", 1) else "transient"
    with pytest.raises(ValueError, match=message):
        state.schedule_retry(
            connect(Cursor(rows=(row,))),
            claim,
            expected_state="starting",
            delay=timedelta(0),
            category=category,
            max_attempts=3,
        )


def test_schedule_retry_closes_attempt_and_graph_lease(
    monkeypatch,
    claim: JobClaim,
) -> None:
    monkeypatch.setattr(state, "require_live_owner", lambda *_args: None)
    cursor = Cursor(rows=(("rolled_back", 1),))

    assert state.schedule_retry(
        connect(cursor),
        claim,
        expected_state="starting",
        delay=timedelta(0),
        category="transient",
        max_attempts=3,
    )
    assert len(cursor.executions) == 4


def test_status_rejects_an_unknown_job() -> None:
    with pytest.raises(KeyError, match="unknown job"):
        state.status(connect(Cursor()), "job-1")


def test_status_maps_the_durable_row() -> None:
    row = {
        "job_id": "job-1",
        "graph_id": "graph-1",
        "state": "running",
        "current_attempt": 2,
        "publication_state": "prepared",
        "phase": "extracting",
        "progress_completed": 3,
        "progress_total": 9,
        "error_category": None,
    }

    observed = state.status(connect(Cursor(rows=(row,))), "job-1")

    assert observed.job_id == "job-1"
    assert observed.attempt == 2
    assert observed.completed == 3
