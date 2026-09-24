import base64
from datetime import datetime, timedelta, timezone
import json
import psycopg
import pytest

from repomap_kg.coordinator import JobRequest, normalize_request
from repomap_kg.coordinator.job_listing import (
    JobListCursor,
    decode_job_cursor,
    encode_job_cursor,
)
from repomap_kg.coordinator.storage import ControlStore
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def test_recent_jobs_use_stable_keyset_pages_and_exact_graph_filter():
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        def connect():
            return psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname=postgres.database,
                password=postgres.password,
            )

        store = ControlStore(connect)
        store.initialize_schema()
        first = store.submit(_request("request-1", "key-1", "synthetic-a"))
        second = store.submit(_request("request-2", "key-2", "synthetic-b"))
        third = store.submit(_request("request-3", "key-3", "synthetic-a"))

        page_one = store.list_recent_jobs(limit=2)
        page_two = store.list_recent_jobs(limit=2, cursor=page_one.next_cursor)
        filtered = store.list_recent_jobs(limit=32, graph_id="synthetic-a")

        assert [item.job_id for item in page_one.jobs] == [third.job_id, second.job_id]
        assert page_one.next_cursor is not None
        assert [item.job_id for item in page_two.jobs] == [first.job_id]
        assert page_two.next_cursor is None
        assert [item.job_id for item in filtered.jobs] == [third.job_id, first.job_id]
        assert all(item.submitted_at.endswith("Z") for item in filtered.jobs)


def _request(request_id: str, key: str, graph_id: str) -> JobRequest:
    return normalize_request(
        {
            "schema_version": 1,
            "job_kind": "refresh_graph",
            "graph_id": graph_id,
            "request_id": request_id,
            "idempotency_key": key,
            "priority": "manual",
            "operation_options": {"reason": "listing-test"},
        },
        source_generation="sg1:synthetic",
        config_generation="cg1:synthetic",
    )


def test_job_listing_empty_database_and_multi_page_traversal():
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        def connect():
            return psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname=postgres.database,
                password=postgres.password,
            )

        store = ControlStore(connect)
        store.initialize_schema()

        # Empty store returns empty tuple and None cursor
        empty_page = store.list_recent_jobs(limit=10)
        assert empty_page.jobs == ()
        assert empty_page.next_cursor is None

        # Submit 5 jobs across two graphs (indices 0, 2, 4 -> synthetic-alpha; 1, 3 -> synthetic-beta)
        submitted = [
            store.submit(_request(f"req-traverse-{i}", f"key-traverse-{i}", "synthetic-alpha" if i % 2 == 0 else "synthetic-beta"))
            for i in range(5)
        ]

        # Exhaustive pagination with limit 2 across all graphs
        collected: list[str] = []
        cursor = None
        for _page_number in range(4):
            page = store.list_recent_jobs(limit=2, cursor=cursor)
            collected.extend(item.job_id for item in page.jobs)
            assert len(page.jobs) <= 2
            cursor = page.next_cursor
            if cursor is None:
                break
        else:
            pytest.fail("keyset cursor did not terminate")

        expected_order = [s.job_id for s in reversed(submitted)]
        assert collected == expected_order
        assert len(collected) == 5

        # Empty result on non-existent graph filter
        empty_filter = store.list_recent_jobs(limit=10, graph_id="synthetic-unseen")
        assert empty_filter.jobs == ()
        assert empty_filter.next_cursor is None

        # Exactly three submitted synthetic-alpha IDs and stable fields
        alpha_page = store.list_recent_jobs(limit=10, graph_id="synthetic-alpha")
        expected_alpha_ids = [submitted[4].job_id, submitted[2].job_id, submitted[0].job_id]
        assert [item.job_id for item in alpha_page.jobs] == expected_alpha_ids
        assert len(alpha_page.jobs) == 3
        assert alpha_page.next_cursor is None
        for item in alpha_page.jobs:
            assert item.graph_id == "synthetic-alpha"
            assert item.state == "queued"
            assert item.submitted_at.endswith("Z")

        # Meaningful pagination across synthetic-alpha jobs
        alpha_page_1 = store.list_recent_jobs(limit=2, graph_id="synthetic-alpha")
        assert [item.job_id for item in alpha_page_1.jobs] == [submitted[4].job_id, submitted[2].job_id]
        assert alpha_page_1.next_cursor is not None
        assert all(item.graph_id == "synthetic-alpha" for item in alpha_page_1.jobs)

        alpha_page_2 = store.list_recent_jobs(
            limit=2, graph_id="synthetic-alpha", cursor=alpha_page_1.next_cursor
        )
        assert [item.job_id for item in alpha_page_2.jobs] == [submitted[0].job_id]
        assert alpha_page_2.next_cursor is None
        assert alpha_page_2.jobs[0].graph_id == "synthetic-alpha"

        # Meaningful option, limit, cursor, and graph_id refusals
        for invalid_limit in (0, 33, -1):
            with pytest.raises(ValueError, match="job list options are invalid"):
                store.list_recent_jobs(limit=invalid_limit)

        for invalid_cursor in ("not-base64@@", "e30", "a" * 513):
            with pytest.raises(ValueError, match="job list options are invalid"):
                store.list_recent_jobs(limit=2, cursor=invalid_cursor)

        for invalid_graph in ("", "/invalid/graph/id", "a" * 129):
            with pytest.raises(ValueError, match="job list options are invalid"):
                store.list_recent_jobs(limit=2, graph_id=invalid_graph)

        with pytest.raises(ValueError, match="job list cursor is invalid"):
            decode_job_cursor("not-base64@@")


def test_job_listing_durable_mutation_refusal_and_cancellation_states():
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        def connect():
            return psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname=postgres.database,
                password=postgres.password,
            )

        store = ControlStore(connect)
        store.initialize_schema()

        # Submit 3 distinct jobs
        job_a = store.submit(_request("req-state-1", "key-state-1", "synthetic-alpha"))
        job_b = store.submit(_request("req-state-2", "key-state-2", "synthetic-beta"))
        job_c = store.submit(_request("req-state-3", "key-state-3", "synthetic-alpha"))

        # Direct cancellation of queued job
        cancel_a = store.request_cancellation(job_a.job_id)
        assert cancel_a == "cancelled"
        status_a = store.status(job_a.job_id)
        assert status_a.state == "cancelled"

        # Claim the oldest eligible job under an active coordinator singleton.
        # The ordering contract is priority, eligibility, submission time, and
        # job ID, so job_b is the claim returned after job_a is cancelled.
        epoch = store.acquire_singleton("inst-test-state", timedelta(seconds=60))
        try:
            claim_b = store.claim_next(
                "inst-test-state", epoch, timedelta(seconds=60)
            )
            assert claim_b is not None
            assert claim_b.job_id == job_b.job_id
            claimed_b = store.status(job_b.job_id)
            assert claimed_b.state == "claimed"
            assert claimed_b.attempt == claim_b.attempt == 1

            # Cancellation of a claimed job is durable before reconciliation.
            cancel_b = store.request_cancellation(job_b.job_id)
            assert cancel_b == "cancel_requested"
            assert store.status(job_b.job_id).state == "cancel_requested"

            # Model the maintained cancellation cleanup path: fence the live
            # attempt, reconcile its terminal state, and release its lease.
            assert store.compare_and_set_state(
                job_b.job_id,
                expected_state="cancel_requested",
                new_state="reconciliation_required",
                attempt=claim_b.attempt,
                instance_id=claim_b.instance_id,
                fencing_epoch=claim_b.fencing_epoch,
                publication_state="not_started",
                error_category="cancelled",
            )
            assert store.mark_attempt_terminated(
                claim_b,
                process_cleanup_proved=True,
            )
            assert store.reconcile_publication(claim_b) == "cancelled"
        finally:
            store.stop_singleton("inst-test-state", epoch)

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT state, current_attempt, publication_state,
                           error_category, finished_at
                    FROM jobs WHERE job_id = %s
                    """,
                    (job_b.job_id,),
                )
                cancelled_row = cur.fetchone()
                cur.execute(
                    """
                    SELECT is_current, finished_at, result_category,
                           publication_state
                    FROM job_attempts
                    WHERE job_id = %s AND attempt = %s
                    """,
                    (job_b.job_id, claim_b.attempt),
                )
                attempt_row = cur.fetchone()
                cur.execute(
                    "SELECT count(*) FROM graph_leases WHERE job_id = %s",
                    (job_b.job_id,),
                )
                lease_count = cur.fetchone()

        assert cancelled_row is not None
        assert cancelled_row[:4] == (
            "cancelled", 1, "rolled_back", "cancelled"
        )
        assert cancelled_row[4] is not None
        assert attempt_row is not None
        assert attempt_row[0] is False
        assert attempt_row[2:] == ("cancelled", "rolled_back")
        assert attempt_row[1] is not None
        assert lease_count is not None
        assert lease_count == (0,)

        # Terminal cancellation refusal
        with pytest.raises(ValueError, match="job cannot be cancelled"):
            store.request_cancellation(job_a.job_id)

        # Durable mutation refusal: invalid listing parameters preserve DB state exactly
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT job_id, state, updated_at FROM jobs ORDER BY job_id")
                before_state = cur.fetchall()

        for bad_limit in (0, 33, True):
            with pytest.raises(ValueError, match="job list options are invalid"):
                store.list_recent_jobs(limit=bad_limit)

        for bad_cursor in ("not-base64@@", "e30", "a" * 513):
            with pytest.raises(ValueError, match="job list options are invalid"):
                store.list_recent_jobs(limit=2, cursor=bad_cursor)

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT job_id, state, updated_at FROM jobs ORDER BY job_id")
                after_state = cur.fetchall()

        assert before_state == after_state

        # Keyset listing reflects current states across all jobs
        page = store.list_recent_jobs(limit=10)
        assert [item.job_id for item in page.jobs] == [job_c.job_id, job_b.job_id, job_a.job_id]
        state_map = {item.job_id: item.state for item in page.jobs}
        assert state_map[job_c.job_id] == "queued"
        assert state_map[job_b.job_id] == "cancelled"
        assert state_map[job_a.job_id] == "cancelled"


def test_job_listing_cursor_codec_and_sql_timezone_boundary_contracts():
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        def connect():
            return psycopg.connect(
                host=postgres.host,
                port=postgres.port,
                user=postgres.user,
                dbname=postgres.database,
                password=postgres.password,
            )

        store = ControlStore(connect)
        store.initialize_schema()

        newer = store.submit(
            _request("boundary-req-1", "boundary-key-1", "synthetic-gamma")
        )
        older = store.submit(
            _request("boundary-req-2", "boundary-key-2", "synthetic-gamma")
        )

        # PostgreSQL normalizes timestamptz values to UTC at the query
        # boundary; listing must expose that same exact cursor representation.
        newer_at = datetime(
            2026, 9, 20, 16, 0, 0, 123456,
            tzinfo=timezone(timedelta(hours=4)),
        )
        older_at = datetime(2026, 9, 20, 11, 0, 0, 123456, tzinfo=timezone.utc)
        with connect() as conn:
            conn.execute(
                "UPDATE jobs SET submitted_at = %s WHERE job_id = %s",
                (newer_at, newer.job_id),
            )
            conn.execute(
                "UPDATE jobs SET submitted_at = %s WHERE job_id = %s",
                (older_at, older.job_id),
            )

        first_page = store.list_recent_jobs(limit=1)
        assert len(first_page.jobs) == 1
        assert first_page.jobs[0].job_id == newer.job_id
        assert first_page.jobs[0].submitted_at == "2026-09-20T12:00:00.123456Z"
        assert first_page.next_cursor is not None

        # Roundtrip the cursor returned by the live listing boundary.
        decoded = decode_job_cursor(first_page.next_cursor)
        assert decoded == JobListCursor(first_page.jobs[0].submitted_at, newer.job_id)
        assert encode_job_cursor(decoded) == first_page.next_cursor
        resumed = store.list_recent_jobs(
            limit=10,
            cursor=first_page.next_cursor,
        )
        assert [item.job_id for item in resumed.jobs] == [older.job_id]
        assert resumed.jobs[0].submitted_at == "2026-09-20T11:00:00.123456Z"
        assert resumed.next_cursor is None

        invalid_payloads = (
            {"ts": first_page.jobs[0].submitted_at, "id": "job-1"},
            [first_page.jobs[0].submitted_at],
            [first_page.jobs[0].submitted_at, "job-1", "extra"],
            [123456, "job-1"],
            [first_page.jobs[0].submitted_at, 123456],
            ["2026-99-99T99:99:99.000000Z", "job-1"],
            [first_page.jobs[0].submitted_at, ""],
            [first_page.jobs[0].submitted_at, "invalid/char"],
        )
        invalid_cursors = [
            base64.urlsafe_b64encode(
                json.dumps(payload, separators=(",", ":")).encode("utf-8")
            ).decode("ascii").rstrip("=")
            for payload in invalid_payloads
        ]
        invalid_cursors.extend(("not-base64@@", "a" * 513))

        with connect() as conn:
            before_invalid = conn.execute(
                """
                SELECT job_id, state, submitted_at, updated_at
                FROM jobs ORDER BY job_id
                """
            ).fetchall()
        for invalid_cursor in invalid_cursors:
            with pytest.raises(ValueError, match="job list options are invalid"):
                store.list_recent_jobs(limit=1, cursor=invalid_cursor)
        with connect() as conn:
            after_invalid = conn.execute(
                """
                SELECT job_id, state, submitted_at, updated_at
                FROM jobs ORDER BY job_id
                """
            ).fetchall()
        assert before_invalid == after_invalid
