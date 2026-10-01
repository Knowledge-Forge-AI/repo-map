from __future__ import annotations

from datetime import timedelta

import pytest

from repomap_kg.coordinator import _control_maintenance as maintenance
from repomap_kg.coordinator._control_types import JobClaim
from repomap_test_support.control_db_fakes import ScriptedCursor, connect_with


@pytest.fixture
def sample_claim() -> JobClaim:
    return JobClaim("job-100", "graph-1", 1, "instance-1", 5)


def test_record_publication_marker_new_marker_returns_true(
    sample_claim: JobClaim,
) -> None:
    expected_values = ("job-100", 1, "graph-1", "run-1", "sg-1", "cg-1", "eg-1", "kg-1", "succeeded")
    cursor = ScriptedCursor(rowcounts=[1])

    inserted = maintenance.record_publication_marker(
        connect_with(cursor), sample_claim, run_identity="run-1",
        source_generation="sg-1", config_generation="cg-1",
        extractor_generation="eg-1", canonicalizer_generation="kg-1", outcome="succeeded",
    )

    assert inserted is True
    assert len(cursor.executions) == 1
    statement, params = cursor.executions[0]
    assert "INSERT INTO synthetic_publication_markers" in statement
    assert "ON CONFLICT (job_id, attempt) DO NOTHING" in statement
    assert params == expected_values
    assert cursor.closed is True
    assert cursor.exits == [(None, None, None)]
    assert cursor.connection is not None
    assert cursor.connection.closed is True
    assert cursor.connection.exits == [(None, None, None)]


def test_record_publication_marker_same_marker_returns_false(sample_claim: JobClaim) -> None:
    expected_values = ("job-100", 1, "graph-1", "run-1", "sg-1", "cg-1", "eg-1", "kg-1", "succeeded")
    cursor = ScriptedCursor(rowcounts=[0], rows=[expected_values])

    inserted = maintenance.record_publication_marker(
        connect_with(cursor), sample_claim, run_identity="run-1",
        source_generation="sg-1", config_generation="cg-1",
        extractor_generation="eg-1", canonicalizer_generation="kg-1", outcome="succeeded",
    )

    assert inserted is False
    assert len(cursor.executions) == 2
    assert "INSERT INTO synthetic_publication_markers" in cursor.executions[0][0]
    assert "SELECT job_id, attempt, graph_id" in cursor.executions[1][0]
    assert cursor.executions[1][1] == ("job-100", 1)
    assert cursor.closed is True
    assert cursor.connection is not None
    assert cursor.connection.closed is True


def test_record_publication_marker_conflict_raises_value_error(sample_claim: JobClaim) -> None:
    conflicting_row = ("job-100", 1, "graph-1", "run-CONFLICT", "sg-1", "cg-1", "eg-1", "kg-1", "succeeded")
    cursor = ScriptedCursor(rowcounts=[0], rows=[conflicting_row])

    with pytest.raises(ValueError, match="publication marker conflict"):
        maintenance.record_publication_marker(
            connect_with(cursor), sample_claim, run_identity="run-1",
            source_generation="sg-1", config_generation="cg-1",
            extractor_generation="eg-1", canonicalizer_generation="kg-1", outcome="succeeded",
        )

    assert len(cursor.executions) == 2
    assert cursor.closed is True
    assert len(cursor.exits) == 1
    assert cursor.exits[0][0] is ValueError
    assert cursor.connection is not None
    assert cursor.connection.closed is True
    assert cursor.connection.exits[0][0] is ValueError


def test_record_publication_marker_exception_propagation_and_context_exit(sample_claim: JobClaim) -> None:
    cursor = ScriptedCursor(execute_error=RuntimeError("database offline"))

    with pytest.raises(RuntimeError, match="database offline"):
        maintenance.record_publication_marker(
            connect_with(cursor), sample_claim, run_identity="run-1",
            source_generation="sg-1", config_generation="cg-1",
            extractor_generation="eg-1", canonicalizer_generation="kg-1", outcome="succeeded",
        )

    assert cursor.closed is True
    assert len(cursor.exits) == 1
    assert cursor.exits[0][0] is RuntimeError
    assert cursor.connection is not None
    assert cursor.connection.closed is True
    assert cursor.connection.exits[0][0] is RuntimeError


@pytest.mark.parametrize(
    "negative_age",
    [
        timedelta(seconds=-1),
        timedelta(microseconds=-1),
        timedelta(days=-1),
    ],
)
def test_cleanup_terminal_rejects_negative_age_before_connect(
    negative_age: timedelta,
) -> None:
    connected = False

    def uncalled_connect():
        nonlocal connected
        connected = True
        raise AssertionError("connect must not be called when bounds are invalid")

    with pytest.raises(ValueError, match="cleanup bounds are invalid"):
        maintenance.cleanup_terminal(
            uncalled_connect,
            negative_age,
            limit=10,
            dry_run=False,
        )

    assert connected is False


@pytest.mark.parametrize("invalid_limit", [0, -1, -50])
def test_cleanup_terminal_rejects_nonpositive_limit_before_connect(
    invalid_limit: int,
) -> None:
    connected = False

    def uncalled_connect():
        nonlocal connected
        connected = True
        raise AssertionError("connect must not be called when bounds are invalid")

    with pytest.raises(ValueError, match="cleanup bounds are invalid"):
        maintenance.cleanup_terminal(
            uncalled_connect,
            timedelta(seconds=60),
            limit=invalid_limit,
            dry_run=False,
        )

    assert connected is False


def test_cleanup_terminal_accepts_zero_minimum_age() -> None:
    cursor = ScriptedCursor(rows=[])
    deleted = maintenance.cleanup_terminal(
        connect_with(cursor), timedelta(0), limit=5, dry_run=True,
    )
    assert deleted.deleted_job_ids == ()
    assert deleted.residuals == ()
    assert len(cursor.executions) == 1
    assert cursor.executions[0][1] == (0.0, 5)
    assert cursor.closed is True


def test_cleanup_terminal_dry_run_returns_candidate_ids_without_delete() -> None:
    candidate_rows = [("job-10",), ("job-20",), ("job-30",)]
    cursor = ScriptedCursor(rows=candidate_rows)
    deleted = maintenance.cleanup_terminal(
        connect_with(cursor), timedelta(hours=1), limit=10, dry_run=True,
    )
    assert deleted.deleted_job_ids == ("job-10", "job-20", "job-30")
    assert deleted.residuals == ()
    assert len(cursor.executions) == 1
    statement, params = cursor.executions[0]
    assert "SELECT j.job_id FROM jobs AS j" in statement
    assert params == (3600.0, 10)
    assert cursor.closed is True
    assert cursor.connection is not None
    assert cursor.connection.closed is True


def test_cleanup_terminal_empty_candidates_skips_delete() -> None:
    cursor = ScriptedCursor(rows=[])

    deleted = maintenance.cleanup_terminal(
        connect_with(cursor),
        timedelta(minutes=30),
        limit=10,
        dry_run=False,
    )

    assert deleted.deleted_job_ids == ()
    assert deleted.residuals == ()
    assert len(cursor.executions) == 1
    assert cursor.closed is True
    assert cursor.connection is not None
    assert cursor.connection.closed is True


def test_cleanup_terminal_bounded_deletion_and_custody_order() -> None:
    selected_ids = ("job-101", "job-102")
    cursor = ScriptedCursor(rows=[("job-101",), ("job-102",)])

    deleted = maintenance.cleanup_terminal(
        connect_with(cursor),
        timedelta(days=2),
        limit=2,
        dry_run=False,
    )

    assert deleted.deleted_job_ids == selected_ids
    assert deleted.residuals == ()
    assert len(cursor.executions) == 4

    # 1. Candidate query with all query constraints
    select_sql, select_params = cursor.executions[0]
    assert "SELECT j.job_id FROM jobs AS j" in select_sql
    assert "WHERE j.state IN (" in select_sql
    for job_state in ("succeeded", "failed", "cancelled", "superseded", "quarantined"):
        assert f"'{job_state}'" in select_sql
    assert "j.finished_at <= now() - make_interval(secs => %s)" in select_sql
    assert "j.publication_state <> 'commit_unknown'" in select_sql
    assert "FROM graph_leases AS gl" in select_sql
    assert "gl.job_id = j.job_id" in select_sql
    assert "other.replacement_job_id = j.job_id" in select_sql
    assert "other.parent_job_id = j.job_id" in select_sql
    assert "ORDER BY j.finished_at, j.job_id LIMIT %s" in select_sql
    assert "FOR UPDATE OF j SKIP LOCKED" in select_sql
    assert select_params == (172800.0, 2)

    # 2. Child table 1: synthetic_publication_markers
    del_pub_sql, del_pub_params = cursor.executions[1]
    assert del_pub_sql == (
        "DELETE FROM synthetic_publication_markers "
        "WHERE job_id = ANY(%s)"
    )
    assert del_pub_params == (["job-101", "job-102"],)

    # 3. Child table 2: job_attempts
    del_att_sql, del_att_params = cursor.executions[2]
    assert del_att_sql == (
        "DELETE FROM job_attempts WHERE job_id = ANY(%s)"
    )
    assert del_att_params == (["job-101", "job-102"],)

    # 4. Parent table: jobs
    del_jobs_sql, del_jobs_params = cursor.executions[3]
    assert del_jobs_sql == (
        "DELETE FROM jobs WHERE job_id = ANY(%s)"
    )
    assert del_jobs_params == (["job-101", "job-102"],)

    # Selected-ID custody: all 3 DELETEs received exactly the list of selected IDs
    assert del_pub_params[0] == list(selected_ids)
    assert del_att_params[0] == list(selected_ids)
    assert del_jobs_params[0] == list(selected_ids)

    assert cursor.closed is True
    assert cursor.connection is not None
    assert cursor.connection.closed is True


def test_cleanup_terminal_select_exception_propagation_and_context_exit() -> None:
    cursor = ScriptedCursor(execute_error=RuntimeError("select failed"))

    with pytest.raises(RuntimeError, match="select failed"):
        maintenance.cleanup_terminal(
            connect_with(cursor),
            timedelta(minutes=5),
            limit=10,
            dry_run=False,
        )

    assert len(cursor.executions) == 1
    assert cursor.closed is True
    assert cursor.exits[0][0] is RuntimeError
    assert cursor.connection is not None
    assert cursor.connection.closed is True
    assert cursor.connection.exits[0][0] is RuntimeError


def test_cleanup_terminal_delete_exception_propagation_and_context_exit() -> None:
    cursor = ScriptedCursor(
        rows=[("job-1",)],
        execute_errors=[None, RuntimeError("child delete failed")],
    )

    with pytest.raises(RuntimeError, match="child delete failed"):
        maintenance.cleanup_terminal(
            connect_with(cursor),
            timedelta(minutes=5),
            limit=10,
            dry_run=False,
        )

    # Executed SELECT, then failed on first DELETE; subsequent DELETEs aborted
    assert len(cursor.executions) == 2
    assert cursor.closed is True
    assert cursor.exits[0][0] is RuntimeError
    assert cursor.connection is not None
    assert cursor.connection.closed is True
    assert cursor.connection.exits[0][0] is RuntimeError


class MultiQueryCursor(ScriptedCursor):
    def __init__(self, query_results: list[list[object]]) -> None:
        super().__init__()
        self._query_results = list(query_results)

    def fetchall(self) -> list[object]:
        if self._query_results:
            return self._query_results.pop(0)
        return []


def test_cleanup_terminal_retires_evidence_before_deleting_rows() -> None:
    retired_claims: list[object] = []
    cursor = MultiQueryCursor([
        [("job-1",)],
        [("job-1", 1, "graph-1", "inst-1", 1, "sg-1", "cg-1", "eg-1", "kg-1")],
    ])
    report = maintenance.cleanup_terminal(
        connect_with(cursor), timedelta(days=1), limit=5, dry_run=False,
        publication_retirer=retired_claims.append,
    )
    assert len(retired_claims) == 1
    assert getattr(retired_claims[0], "job_id", None) == "job-1"
    assert getattr(retired_claims[0], "attempt", None) == 1
    assert report.deleted_job_ids == ("job-1",)
    assert report.residuals == ()
    assert report.residual_count == 0
    assert len(cursor.executions) == 5
    assert cursor.executions[2][1] == (["job-1"],)
    assert cursor.executions[3][1] == (["job-1"],)
    assert cursor.executions[4][1] == (["job-1"],)


def test_cleanup_terminal_dry_run_never_invokes_retirer() -> None:
    def fail_retirer(_claim: object) -> None:
        raise AssertionError("retirer must not be invoked during dry run")

    cursor = ScriptedCursor(rows=[("job-1",), ("job-2",)])
    report = maintenance.cleanup_terminal(
        connect_with(cursor), timedelta(days=1), limit=5, dry_run=True,
        publication_retirer=fail_retirer,
    )
    assert report.deleted_job_ids == ("job-1", "job-2")
    assert report.residuals == ()
    assert len(cursor.executions) == 1


def test_cleanup_terminal_retirement_failure_preserves_job_records_and_reports_residuals() -> None:
    def failing_retirer(claim: object) -> None:
        assert isinstance(claim, JobClaim)
        raise ValueError("corrupted evidence payload")

    cursor = MultiQueryCursor([
        [("job-bad",)],
        [("job-bad", 1, "graph-1", "inst-1", 1, "sg-1", "cg-1", "eg-1", "kg-1")],
    ])
    report = maintenance.cleanup_terminal(
        connect_with(cursor), timedelta(days=1), limit=5, dry_run=False,
        publication_retirer=failing_retirer,
    )
    assert report.deleted_job_ids == ()
    assert report.residual_count == 1
    assert report.residuals == ("job-bad:1:validation_error",)
    assert len(cursor.executions) == 2


def test_cleanup_terminal_scans_past_residuals_within_bound_with_limit_one() -> None:
    def partial_retirer(claim: object) -> None:
        if getattr(claim, "job_id", "") == "job-unsafe":
            raise PermissionError("access denied")

    cursor = MultiQueryCursor([
        [("job-unsafe",), ("job-safe",)],
        [
            ("job-unsafe", 1, "graph-1", "inst-1", 1, "sg-1", "cg-1", "eg-1", "kg-1"),
            ("job-safe", 1, "graph-1", "inst-1", 1, "sg-1", "cg-1", "eg-1", "kg-1"),
        ],
    ])
    report = maintenance.cleanup_terminal(
        connect_with(cursor), timedelta(days=1), limit=1, dry_run=False,
        publication_retirer=partial_retirer,
    )
    assert report.deleted_job_ids == ("job-safe",)
    assert report.residual_count == 1
    assert report.residuals == ("job-unsafe:1:permission_denied",)
    assert len(cursor.executions) == 5
    assert cursor.executions[2][1] == (["job-safe"],)
    assert cursor.executions[3][1] == (["job-safe"],)
    assert cursor.executions[4][1] == (["job-safe"],)

