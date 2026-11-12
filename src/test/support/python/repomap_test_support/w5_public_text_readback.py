"""Companion SQLite/PostgreSQL accepted-evidence span readers for public-text tests.

These readers reuse the exact config resolution, repository predicate,
accepted-run fence and connection boundary of the unchanged v1 readers in
``w5_semantic_store_support`` and add only the two nullable span columns.
"""

from __future__ import annotations

from common_lore_index.ops.config_local import (
    LocalSqliteConfig,
    load_graph_registry_config_home,
    local_graph_binding,
    sqlite_graph_database_path,
)
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.storage.context_postgres_identity import (
    postgres_accepted_run_cte_sql,
    postgres_repo_predicate_sql,
)
from common_lore_index.storage.readback_driver import execute_json_readback
from common_lore_index.storage.sqlite_local.connection import read_transaction
from repomap_test_support.retrieval_evaluation_publication import PublishedCorpusState
from retrieval_public_text_contracts import SpanRow


def load_sqlite_span_rows(published: PublishedCorpusState) -> tuple[SpanRow, ...]:
    """Read accepted v1 evidence rows plus canonical_evidence.start_line/end_line from SQLite."""
    config = load_graph_registry_config_home(published.home_root)
    if not isinstance(config, LocalSqliteConfig):
        raise TypeError("expected LocalSqliteConfig for SQLite span readback")
    graph = next(c for c in config.graphs if c.id == published.graph_id)
    db_path = sqlite_graph_database_path(config, graph)
    binding = local_graph_binding(graph)
    with read_transaction(db_path, binding) as conn:
        acc_row = conn.execute(
            "SELECT a.run_id FROM accepted_publication a JOIN runs r ON r.id = a.run_id LIMIT 1"
        ).fetchone()
        assert acc_row is not None
        run_id = int(acc_row[0])
        rows = conn.execute(
            "SELECT cn.canonical_key, ce.evidence_key, ce.run_id, ce.graph_key_version, ce.path, ce.metadata_json, "
            "link.link_kind, ce.start_line, ce.end_line "
            "FROM canonical_node_evidence link "
            "JOIN canonical_nodes cn ON cn.id = link.canonical_node_id "
            "JOIN canonical_evidence ce ON ce.id = link.canonical_evidence_id "
            "WHERE cn.graph_key_version = 1 AND ce.graph_key_version = 1 AND ce.run_id = ? "
            "ORDER BY cn.canonical_key ASC, ce.evidence_key ASC, link.link_kind ASC",
            (run_id,),
        ).fetchall()
    return tuple(
        SpanRow(str(r[0]), str(r[1]), int(r[2]), int(r[3]), r[4], r[5], str(r[6]), r[7], r[8]) for r in rows
    )


def load_postgres_span_rows(
    published: PublishedCorpusState, *, psql_command: str = "psql"
) -> tuple[SpanRow, ...]:
    """Read accepted v1 evidence rows plus public.canonical_evidence.start_line/end_line from PostgreSQL."""
    config = load_graph_registry_config_home(published.home_root)
    if not isinstance(config, OpsConfig):
        raise TypeError("expected OpsConfig for PostgreSQL span readback")
    graph = next(c for c in config.graphs if c.id == published.graph_id)
    database = graph.database or config.postgres.database
    psql_args = config.postgres.psql_args_for_database(database)
    binding = local_graph_binding(graph)
    repo_pred = postgres_repo_predicate_sql(
        str(binding.repository_identity), str(binding.root_path), context_identity=True
    )
    sql = (
        f"WITH matched_repo AS MATERIALIZED (SELECT repo.id AS repository_id FROM public.repositories repo WHERE {repo_pred} ORDER BY repo.id DESC LIMIT 1),\n"
        f"{postgres_accepted_run_cte_sql(context_identity=True)}\n"
        f"SELECT json_build_object(\n"
        f"  'evidence', COALESCE((SELECT json_agg(json_build_object('canonical_key', cn.canonical_key, 'evidence_key', ce.evidence_key, 'run_id', ce.run_id, "
        f"'graph_key_version', ce.graph_key_version, 'path', ce.path, 'metadata_json', ce.metadata_json, 'link_kind', link.link_kind, "
        f"'start_line', ce.start_line, 'end_line', ce.end_line) "
        f"ORDER BY cn.canonical_key COLLATE \"C\" ASC, ce.evidence_key COLLATE \"C\" ASC, link.link_kind COLLATE \"C\" ASC) "
        f"FROM public.canonical_node_evidence link JOIN public.canonical_nodes cn ON cn.id = link.canonical_node_id "
        f"JOIN matched_repo mr ON mr.repository_id = cn.repository_id JOIN accepted_run acc ON TRUE "
        f"JOIN public.canonical_evidence ce ON ce.id = link.canonical_evidence_id AND ce.repository_id = cn.repository_id "
        f"WHERE cn.graph_key_version = 1 AND ce.graph_key_version = 1 AND ce.run_id = acc.run_id), '[]'::json)\n"
        f")::text;"
    )
    payload = execute_json_readback(
        sql,
        psql_args=psql_args,
        psql_command=psql_command,
        label="w5_pg_public_text_spans",
        expected_shape="object",
        password=config.postgres.password,
    )
    if not isinstance(payload, dict):
        raise TypeError("expected object-shaped PostgreSQL span readback")
    return tuple(
        SpanRow(
            str(r["canonical_key"]), str(r["evidence_key"]), int(r["run_id"]), int(r["graph_key_version"]),
            r.get("path"), r.get("metadata_json"), str(r["link_kind"]), r.get("start_line"), r.get("end_line"),
        )
        for r in (payload.get("evidence") or ())
    )


__all__ = ["load_postgres_span_rows", "load_sqlite_span_rows"]
