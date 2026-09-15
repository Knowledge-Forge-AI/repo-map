"""Run-scoped final-state readback for the SCALE11 profiler."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

import psycopg

from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)


def read_final_state(
    psql_args: Sequence[str],
    repository_id: int,
    run_id: int,
    stage_id: str,
) -> tuple[dict[str, int], bool]:
    """Return seven-family counts and resolved cleanup eligibility."""

    params = _psycopg_connection_params_from_psql_args(psql_args)
    with psycopg.connect(
        host=params.get("host"), port=params.get("port"),
        user=params.get("user"), dbname=params.get("dbname"),
    ) as connection:
        counts = {
            "files": _count(connection, "files", repository_id),
            "raw_observations": _run_count(
                connection, "raw_observations", repository_id, run_id
            ),
            "canonical_nodes": _count(
                connection, "canonical_nodes", repository_id
            ),
            "canonical_edges": _count(
                connection, "canonical_edges", repository_id
            ),
            "canonical_evidence": _run_count(
                connection, "canonical_evidence", repository_id, run_id
            ),
            "canonical_node_evidence": _required_count(connection.execute(
                "SELECT count(*) FROM canonical_node_evidence link "
                "JOIN canonical_nodes node ON node.id = link.canonical_node_id "
                "JOIN canonical_evidence evidence "
                "ON evidence.id = link.canonical_evidence_id "
                "WHERE node.repository_id = %s AND evidence.run_id = %s",
                (repository_id, run_id),
            ).fetchone()),
            "canonical_edge_evidence": _required_count(connection.execute(
                "SELECT count(*) FROM canonical_edge_evidence link "
                "JOIN canonical_edges edge ON edge.id = link.canonical_edge_id "
                "JOIN canonical_evidence evidence "
                "ON evidence.id = link.canonical_evidence_id "
                "WHERE edge.repository_id = %s AND evidence.run_id = %s",
                (repository_id, run_id),
            ).fetchone()),
        }
        stage_state = connection.execute(
            "SELECT state, merge_status, publication_reconciliation_state, "
            "cleanup_eligibility FROM ingestion_stages WHERE stage_id = %s",
            (stage_id,),
        ).fetchone()
    resolved = stage_state == (
        "published",
        "committed",
        "reconciled",
        "eligible",
    )
    return counts, resolved


def _count(
    connection: psycopg.Connection[tuple[Any, ...]],
    table: Literal["files", "canonical_nodes", "canonical_edges"],
    repository_id: int,
) -> int:
    return _required_count(connection.execute(
        f"SELECT count(*) FROM {table} WHERE repository_id = %s",
        (repository_id,),
    ).fetchone())


def _run_count(
    connection: psycopg.Connection[tuple[Any, ...]],
    table: Literal["raw_observations", "canonical_evidence"],
    repository_id: int,
    run_id: int,
) -> int:
    return _required_count(connection.execute(
        f"SELECT count(*) FROM {table} "
        "WHERE repository_id = %s AND run_id = %s",
        (repository_id, run_id),
    ).fetchone())


def _required_count(row: tuple[Any, ...] | None) -> int:
    if row is None or len(row) != 1 or type(row[0]) is not int:
        raise ValueError("profile count query did not return one integer")
    return row[0]
