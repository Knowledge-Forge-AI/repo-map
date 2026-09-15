import psycopg

from repomap_kg.coordinator import JobRequest, normalize_request
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
