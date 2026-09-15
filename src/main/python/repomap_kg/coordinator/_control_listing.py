"""Read-only bounded recent-job pages for the coordinator control store."""

from __future__ import annotations

from datetime import datetime, timezone

from psycopg.rows import dict_row

from repomap_kg.coordinator._control_types import (
    ConnectionFactory,
    JobListItem,
    JobListPage,
)
from repomap_kg.coordinator.job_listing import (
    JobListCursor,
    encode_job_cursor,
    format_utc_timestamp,
    validate_job_list_options,
)


def list_recent_jobs(
    connect: ConnectionFactory,
    *,
    limit: int,
    graph_id: str | None = None,
    cursor: str | None = None,
) -> JobListPage:
    """Return one deterministic newest-first page from bounded retained jobs."""

    page_size, graph_filter, boundary = validate_job_list_options(
        limit=limit, graph_id=graph_id, cursor=cursor
    )
    clauses: list[str] = []
    parameters: list[object] = []
    if graph_filter is not None:
        clauses.append("graph_id = %s")
        parameters.append(graph_filter)
    if boundary is not None:
        clauses.append("(submitted_at, job_id) < (%s, %s)")
        parameters.extend((_cursor_timestamp(boundary), boundary.job_id))
    where = "" if not clauses else "WHERE " + " AND ".join(clauses)
    parameters.append(page_size + 1)
    with connect() as connection:
        with connection.cursor(row_factory=dict_row) as query:
            query.execute(
                f"""
                SELECT job_id, graph_id, state, submitted_at
                FROM jobs {where}
                ORDER BY submitted_at DESC, job_id DESC
                LIMIT %s
                """,
                parameters,
            )
            rows = query.fetchall()
    visible = rows[:page_size]
    jobs = tuple(
        JobListItem(
            row["job_id"],
            row["graph_id"],
            row["state"],
            format_utc_timestamp(row["submitted_at"]),
        )
        for row in visible
    )
    next_cursor = None
    if len(rows) > page_size:
        last = jobs[-1]
        next_cursor = encode_job_cursor(
            JobListCursor(last.submitted_at, last.job_id)
        )
    return JobListPage(jobs, next_cursor)


def _cursor_timestamp(cursor: JobListCursor) -> datetime:
    return datetime.strptime(
        cursor.submitted_at, "%Y-%m-%dT%H:%M:%S.%fZ"
    ).replace(tzinfo=timezone.utc)


__all__ = ["list_recent_jobs"]
