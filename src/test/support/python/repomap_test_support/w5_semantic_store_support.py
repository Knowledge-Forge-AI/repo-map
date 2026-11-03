"""SQLite and PostgreSQL live store readback support for W5 semantic integration tests (ADR 0137)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json

from common_lore_index.ops.config_local import (
    LocalSqliteConfig,
    load_graph_registry_config_home,
    local_graph_binding,
    sqlite_graph_database_path,
)
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.storage.context_postgres_identity import (
    format_postgres_accepted_publication,
    postgres_accepted_json_sql,
    postgres_accepted_run_cte_sql,
    postgres_repo_predicate_sql,
)
from common_lore_index.storage.publication import RunPublicationReceipt
from common_lore_index.storage.readback_driver import execute_json_readback
from common_lore_index.storage.sqlite_local.connection import read_transaction
from repomap_test_support.retrieval_evaluation_publication import (
    PublishedCorpusState,
    read_postgres_accepted_publication,
    read_sqlite_accepted_publication,
)
from retrieval_semantic_representation import (
    AcceptedEvidenceRecord,
    AcceptedNodeRecord,
    AcceptedStoreReadback,
    PublicationReadbackAdapter,
)


def load_sqlite_accepted_nodes_and_evidence(
    published: PublishedCorpusState,
) -> tuple[dict[str, object], tuple[AcceptedNodeRecord, ...], tuple[AcceptedEvidenceRecord, ...]]:
    """Read accepted publication mapping, canonical nodes, and evidence directly from SQLite tables."""
    config = load_graph_registry_config_home(published.home_root)
    if not isinstance(config, LocalSqliteConfig):
        raise TypeError("expected LocalSqliteConfig for SQLite readback")
    graph = next(c for c in config.graphs if c.id == published.graph_id)
    db_path = sqlite_graph_database_path(config, graph)
    binding = local_graph_binding(graph)
    with read_transaction(db_path, binding) as conn:
        acc_row = conn.execute(
            "SELECT a.run_id, a.generation, r.publication_job_id, r.publication_attempt, "
            "r.publication_bundle_id, r.snapshot_manifest_id, r.extraction_receipt_id, "
            "r.graph_candidate_id, r.snapshot_vector_json, r.source_generation, "
            "r.config_generation, r.extractor_generation, r.canonicalizer_generation "
            "FROM accepted_publication a JOIN runs r ON r.id = a.run_id LIMIT 1"
        ).fetchone()
        assert acc_row is not None
        run_id = int(acc_row[0])
        node_rows = conn.execute(
            "SELECT canonical_key, kind, display_name, graph_key_version, last_seen_run_id "
            "FROM canonical_nodes WHERE graph_key_version = 1 ORDER BY canonical_key ASC"
        ).fetchall()
        ev_rows = conn.execute(
            "SELECT cn.canonical_key, ce.evidence_key, ce.run_id, ce.graph_key_version, ce.path, ce.metadata_json, link.link_kind "
            "FROM canonical_node_evidence link "
            "JOIN canonical_nodes cn ON cn.id = link.canonical_node_id "
            "JOIN canonical_evidence ce ON ce.id = link.canonical_evidence_id "
            "WHERE cn.graph_key_version = 1 AND ce.graph_key_version = 1 AND ce.run_id = ? "
            "ORDER BY cn.canonical_key ASC, ce.evidence_key ASC, link.link_kind ASC",
            (run_id,),
        ).fetchall()
    raw_vec = json.loads(str(acc_row[8])) if isinstance(acc_row[8], str) else acc_row[8]
    snap_vec = [
        [item["binding_id"], item.get("binding_revision", item.get("revision")), item["snapshot_id"]]
        if isinstance(item, Mapping) else list(item)
        for item in (raw_vec or ())
    ]
    pub_map = {
        "run_id": run_id,
        "generation": int(acc_row[1]),
        "job_id": str(acc_row[2]),
        "attempt": int(acc_row[3]),
        "publication_bundle_id": str(acc_row[4]),
        "snapshot_manifest_id": str(acc_row[5]),
        "extraction_receipt_id": str(acc_row[6]),
        "graph_candidate_id": str(acc_row[7]),
        "snapshot_vector": snap_vec,
        "source_generation": str(acc_row[9]),
        "config_generation": str(acc_row[10]),
        "extractor_generation": str(acc_row[11]),
        "canonicalizer_generation": str(acc_row[12]),
    }
    nodes = tuple(AcceptedNodeRecord(str(r[0]), r[1], r[2], int(r[3]), int(r[4])) for r in node_rows)
    evidence = tuple(
        AcceptedEvidenceRecord(str(r[0]), str(r[1]), int(r[2]), int(r[3]), r[4], r[5], str(r[6]))
        for r in ev_rows
    )
    return pub_map, nodes, evidence


def make_sqlite_readback_adapter(
    published: PublishedCorpusState,
    receipt_getter: Callable[[], RunPublicationReceipt] | None = None,
) -> PublicationReadbackAdapter:
    """Create a live SQLite store readback adapter for a published local graph."""
    config = load_graph_registry_config_home(published.home_root)
    if not isinstance(config, LocalSqliteConfig):
        raise TypeError("expected LocalSqliteConfig for SQLite readback")
    graph = next(c for c in config.graphs if c.id == published.graph_id)
    repo_id = str(local_graph_binding(graph).repository_identity)

    def _adapter() -> AcceptedStoreReadback:
        pub_map, _nodes, _ev = load_sqlite_accepted_nodes_and_evidence(published)
        if receipt_getter is not None:
            rec = receipt_getter()
        else:
            _accepted_ref, rec = read_sqlite_accepted_publication(config, published.graph_id)
        return AcceptedStoreReadback(
            graph_id=str(published.graph_id),
            repository_identity=repo_id,
            backend="sqlite",
            accepted_publication=pub_map,
            receipt=rec,
        )

    return _adapter


def load_postgres_accepted_nodes_and_evidence(
    published: PublishedCorpusState, *, psql_command: str = "psql"
) -> tuple[dict[str, object], tuple[AcceptedNodeRecord, ...], tuple[AcceptedEvidenceRecord, ...]]:
    """Read accepted publication mapping, canonical nodes, and evidence directly from PostgreSQL tables."""
    config = load_graph_registry_config_home(published.home_root)
    if not isinstance(config, OpsConfig):
        raise TypeError("expected OpsConfig for PostgreSQL readback")
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
        f"  'accepted', (SELECT {postgres_accepted_json_sql(context_identity=True)} FROM accepted_run acc),\n"
        f"  'run_meta', (SELECT json_build_object('job_id', r.publication_job_id, 'attempt', r.publication_attempt, 'graph_candidate_id', r.graph_candidate_id, "
        f"'source_generation', r.source_generation, 'config_generation', r.config_generation, 'extractor_generation', r.extractor_generation, 'canonicalizer_generation', r.canonicalizer_generation) "
        f"FROM public.runs r JOIN accepted_run acc ON r.id = acc.run_id),\n"
        f"  'nodes', COALESCE((SELECT json_agg(json_build_object('canonical_key', cn.canonical_key, 'kind', cn.kind, 'display_name', cn.display_name, "
        f"'graph_key_version', cn.graph_key_version, 'last_seen_run_id', cn.last_seen_run_id) ORDER BY cn.canonical_key COLLATE \"C\" ASC) "
        f"FROM public.canonical_nodes cn JOIN matched_repo mr ON mr.repository_id = cn.repository_id WHERE cn.graph_key_version = 1), '[]'::json),\n"
        f"  'evidence', COALESCE((SELECT json_agg(json_build_object('canonical_key', cn.canonical_key, 'evidence_key', ce.evidence_key, 'run_id', ce.run_id, "
        f"'graph_key_version', ce.graph_key_version, 'path', ce.path, 'metadata_json', ce.metadata_json, 'link_kind', link.link_kind) "
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
        label="w5_pg_nodes",
        expected_shape="object",
        password=config.postgres.password,
    )
    if not isinstance(payload, dict):
        raise TypeError("expected object-shaped PostgreSQL readback")
    accepted = payload.get("accepted")
    if not isinstance(accepted, Mapping):
        raise TypeError("expected accepted publication object")
    formatted_acc = format_postgres_accepted_publication(accepted, context_identity=True)
    run_meta = payload.get("run_meta") or {}
    snap_vec = [
        [item["binding_id"], item.get("binding_revision", item.get("revision")), item["snapshot_id"]]
        if isinstance(item, Mapping) else list(item)
        for item in (formatted_acc.get("snapshot_vector") or ())
    ]
    pub_map = {
        "run_id": int(formatted_acc["run_id"]),
        "generation": int(formatted_acc["generation"]),
        "job_id": str(run_meta["job_id"]),
        "attempt": int(run_meta["attempt"]),
        "publication_bundle_id": str(formatted_acc["publication_bundle_id"]),
        "snapshot_manifest_id": str(formatted_acc["snapshot_manifest_id"]),
        "extraction_receipt_id": str(formatted_acc["extraction_receipt_id"]),
        "graph_candidate_id": str(run_meta.get("graph_candidate_id") or formatted_acc.get("graph_candidate_id")),
        "snapshot_vector": snap_vec,
        "source_generation": str(run_meta["source_generation"]),
        "config_generation": str(run_meta["config_generation"]),
        "extractor_generation": str(run_meta["extractor_generation"]),
        "canonicalizer_generation": str(run_meta["canonicalizer_generation"]),
    }
    nodes = tuple(
        AcceptedNodeRecord(
            str(r["canonical_key"]), r.get("kind"), r.get("display_name"),
            int(r["graph_key_version"]), int(r["last_seen_run_id"]),
        )
        for r in (payload.get("nodes") or ())
    )
    evidence = tuple(
        AcceptedEvidenceRecord(
            str(r["canonical_key"]), str(r["evidence_key"]), int(r["run_id"]),
            int(r["graph_key_version"]), r.get("path"), r.get("metadata_json"), str(r["link_kind"]),
        )
        for r in (payload.get("evidence") or ())
    )
    return pub_map, nodes, evidence


def make_postgres_readback_adapter(
    published: PublishedCorpusState,
    *,
    psql_command: str = "psql",
    receipt_getter: Callable[[], RunPublicationReceipt] | None = None,
) -> PublicationReadbackAdapter:
    """Create a live PostgreSQL store readback adapter for a published local graph."""
    config = load_graph_registry_config_home(published.home_root)
    if not isinstance(config, OpsConfig):
        raise TypeError("expected OpsConfig for PostgreSQL readback")
    graph = next(c for c in config.graphs if c.id == published.graph_id)
    repo_id = str(local_graph_binding(graph).repository_identity)

    def _adapter() -> AcceptedStoreReadback:
        pub_map, _nodes, _ev = load_postgres_accepted_nodes_and_evidence(published, psql_command=psql_command)
        if receipt_getter is not None:
            rec = receipt_getter()
        else:
            _accepted_ref, rec = read_postgres_accepted_publication(
                config, published.graph_id, psql_command=psql_command
            )
        return AcceptedStoreReadback(
            graph_id=str(published.graph_id),
            repository_identity=repo_id,
            backend="postgresql",
            accepted_publication=pub_map,
            receipt=rec,
        )

    return _adapter


__all__ = [
    "load_postgres_accepted_nodes_and_evidence",
    "load_sqlite_accepted_nodes_and_evidence",
    "make_postgres_readback_adapter",
    "make_sqlite_readback_adapter",
]
