import psycopg
import pytest

from repomap_kg.coordinator import JobRequest, normalize_request
from repomap_kg.coordinator.job_listing import decode_job_cursor
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

        # Submit 5 jobs across two graphs (indices 0, 2, 4 -> graph-alpha; 1, 3 -> graph-beta)
        submitted = [
            store.submit(_request(f"req-traverse-{i}", f"key-traverse-{i}", "graph-alpha" if i % 2 == 0 else "graph-beta"))
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
        empty_filter = store.list_recent_jobs(limit=10, graph_id="graph-unseen")
        assert empty_filter.jobs == ()
        assert empty_filter.next_cursor is None

        # Exactly three submitted graph-alpha IDs and stable fields
        alpha_page = store.list_recent_jobs(limit=10, graph_id="graph-alpha")
        expected_alpha_ids = [submitted[4].job_id, submitted[2].job_id, submitted[0].job_id]
        assert [item.job_id for item in alpha_page.jobs] == expected_alpha_ids
        assert len(alpha_page.jobs) == 3
        assert alpha_page.next_cursor is None
        for item in alpha_page.jobs:
            assert item.graph_id == "graph-alpha"
            assert item.state == "queued"
            assert item.submitted_at.endswith("Z")

        # Meaningful pagination across graph-alpha jobs
        alpha_page_1 = store.list_recent_jobs(limit=2, graph_id="graph-alpha")
        assert [item.job_id for item in alpha_page_1.jobs] == [submitted[4].job_id, submitted[2].job_id]
        assert alpha_page_1.next_cursor is not None
        assert all(item.graph_id == "graph-alpha" for item in alpha_page_1.jobs)

        alpha_page_2 = store.list_recent_jobs(
            limit=2, graph_id="graph-alpha", cursor=alpha_page_1.next_cursor
        )
        assert [item.job_id for item in alpha_page_2.jobs] == [submitted[0].job_id]
        assert alpha_page_2.next_cursor is None
        assert alpha_page_2.jobs[0].graph_id == "graph-alpha"

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
