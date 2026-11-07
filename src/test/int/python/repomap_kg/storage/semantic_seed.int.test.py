"""Public JSON-RPC stdio integration owner for stored-node similarity.

Tests the full public entry boundary via `python -m common_lore_index.server.mcp` subprocess stdio:
- Multi-source publication built via maintained portable source path (no hand-injected metadata)
- Shared canonical module across two sources -> ambiguous seed without binding qualification
- Qualification via source_binding_id resolves seed and keeps other source copy in candidates
- Deterministic candidate tie breaking and bounds
- Missing seed node vs missing seed embedding
- Profile mismatch (identity and dimensions)
- Stale publication refusal after graph successor refresh
- Foreign graph refusal
- Read-only purity: zero mutation to canonical graph truth
"""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any

import pytest

from common_lore_index.storage import apply_migrations, default_rdbms_root, query_canonical_node_records
from common_lore_index.storage.psql import run_psql
from common_lore_index.storage.semantic_candidate_import import candidate_schema_sql
from common_lore_index.storage.semantic_seed import SimilarNodesQuery
from common_lore_index.storage.semantic_seed_readback import query_seed_candidates, query_similar_nodes
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.semantic_candidate_fixtures import PROFILE
from repomap_test_support.semantic_candidate_restore import (
    optional_sql_fixture_cleanup,
)
from repomap_test_support.semantic_seed_publication import (
    SEED_KEY,
    import_seed_embeddings,
    publish_portable_seed_graph,
    run_mcp_stdio_requests,
    write_seed_mcp_config,
)

GRAPH_ID = "seed-graph"
REPO_NAME = "seed-repo"
REPO_IDENTITY = f"repo1:{GRAPH_ID}"
REBUILD_ID = "rebuild-seed-20261008-01"
READER = "seed_fixture_reader"
WRITER = "seed_fixture_enrichment"


def _execute(postgres: Any, sql: str, *, role: str | None = None) -> None:
    text = (f'SET ROLE "{role}";\n' if role else "") + sql
    run_psql([postgres.psql_command, *postgres.psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"], input_text=text)


def _rpc_call(req_id: int, **arguments: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": "repomap_similar_nodes", "arguments": arguments},
    }


@pytest.mark.requires_pgvector
def test_seed_public_entry_boundary() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres, tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        available = postgres.psql_scalar(
            "SELECT count(*) FROM pg_available_extension_versions WHERE name = 'vector' AND version = '0.8.7'"
        )
        assert available == "1", "exact boundary requires an admitted pgvector 0.8.7 test image"
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)

        _execute(
            postgres,
            f"CREATE ROLE {READER} NOLOGIN; CREATE ROLE {WRITER} NOLOGIN; "
            "CREATE SCHEMA repomap_vector; CREATE EXTENSION vector WITH SCHEMA repomap_vector VERSION '0.8.7';",
        )
        with optional_sql_fixture_cleanup(
            postgres,
            reader=READER,
            writer=WRITER,
            execute_fn=_execute,
        ):
            _execute(postgres, candidate_schema_sql(read_principal=READER, enrichment_principal=WRITER))

            context = publish_portable_seed_graph(
                postgres, root, graph_id=GRAPH_ID, repository_name=REPO_NAME,
                repository_identity=REPO_IDENTITY, revision=1,
            )
            import_seed_embeddings(
                postgres, context, rebuild_id=REBUILD_ID, writer_role=WRITER, profile=PROFILE,
            )
            foreign_root = root / "foreign"
            foreign_root.mkdir()
            foreign_context = publish_portable_seed_graph(
                postgres, foreign_root, graph_id="foreign-seed-graph",
                repository_name="foreign-seed-repo", repository_identity="repo1:foreign-seed-graph",
            )
            import_seed_embeddings(
                postgres, foreign_context, rebuild_id="foreign-seed-rebuild",
                writer_role=WRITER, profile=PROFILE,
            )
            mcp_config = root / "mcp-ops.local.toml"
            write_seed_mcp_config(mcp_config, postgres, context)

            canonical_before = query_canonical_node_records(
                postgres.psql_args, root_path=f"graph:{GRAPH_ID}",
                repository_identity=REPO_IDENTITY, psql_command=postgres.psql_command,
            )
            edges_before = postgres.psql_scalar("SELECT count(*) FROM canonical_edges;")

            # 1. Low-level storage contract checks
            dis_q = SimilarNodesQuery(SEED_KEY, REBUILD_ID, PROFILE.identity, PROFILE.dimensions, selected=False)
            assert query_similar_nodes(postgres.psql_args, query=dis_q, repository_identity=REPO_IDENTITY, psql_command=postgres.psql_command).reason == "disabled"

            amb_q = SimilarNodesQuery(SEED_KEY, REBUILD_ID, PROFILE.identity, PROFILE.dimensions, selected=True)
            assert query_similar_nodes(postgres.psql_args, query=amb_q, repository_identity=REPO_IDENTITY, psql_command=postgres.psql_command).reason == "seed_ambiguous"

            qual_q = SimilarNodesQuery(
                SEED_KEY, REBUILD_ID, PROFILE.identity, PROFILE.dimensions,
                selected=True, source_binding_id=context.binding_a_id,
            )
            qual_res = query_similar_nodes(postgres.psql_args, query=qual_q, repository_identity=REPO_IDENTITY, psql_command=postgres.psql_command)
            assert qual_res.status == "ok", qual_res.reason
            assert qual_res.provenance is not None
            assert qual_res.provenance["seed"]["canonical_key"] == SEED_KEY
            assert qual_res.provenance["seed"]["source_binding_id"] == context.binding_a_id

            other_copy = next(
                (c for c in qual_res.candidates if c["canonical_key"] == SEED_KEY and c["source_binding_id"] == context.binding_b_id),
                None,
            )
            assert other_copy is not None, "qualification must keep other source copy in candidates"

            direct_res = query_seed_candidates(postgres.psql_args, publication=context.publication, query=qual_q, psql_command=postgres.psql_command)
            assert direct_res.status == "ok" and direct_res.candidates == qual_res.candidates

            # 2. Public JSON-RPC stdio integration boundary
            common_args = {
                "graph_id": GRAPH_ID, "canonical_key": SEED_KEY, "rebuild_id": REBUILD_ID,
                "profile_identity": PROFILE.identity, "dimensions": PROFILE.dimensions, "selected": True,
            }
            rpc_requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                _rpc_call(3, **{**common_args, "selected": False}),
                _rpc_call(4, **common_args),
                _rpc_call(5, **{**common_args, "source_binding_id": context.binding_a_id}),
                _rpc_call(6, **{**common_args, "source_binding_id": context.binding_a_id, "limit": 2}),
                _rpc_call(7, **{**common_args, "canonical_key": "file:src/nonexistent.py"}),
                _rpc_call(8, **{**common_args, "canonical_key": "file:src_a/src/unindexed.py", "source_binding_id": context.binding_a_id}),
                _rpc_call(9, **{**common_args, "profile_identity": "sha256:" + "f" * 64, "source_binding_id": context.binding_a_id}),
                _rpc_call(10, **{**common_args, "dimensions": 4, "source_binding_id": context.binding_a_id}),
                _rpc_call(11, **{**common_args, "rebuild_id": "absent-rebuild", "source_binding_id": context.binding_a_id}),
                _rpc_call(14, **{**common_args, "rebuild_id": "foreign-seed-rebuild",
                                "source_binding_id": context.binding_a_id}),
            ]

            responses = run_mcp_stdio_requests(mcp_config, postgres.psql_command, rpc_requests, reader_role=READER)
            resp_by_id = {r["id"]: r for r in responses}

            assert resp_by_id[1]["result"]["serverInfo"]["name"] == "repomap-kg"
            assert any(t["name"] == "repomap_similar_nodes" for t in resp_by_id[2]["result"]["tools"])

            def _sc(req_id: int) -> dict[str, Any]:
                return resp_by_id[req_id]["result"]["structuredContent"]

            assert _sc(3)["reason"] == "disabled"
            assert _sc(4)["reason"] == "seed_ambiguous"

            res5 = _sc(5)
            assert res5["status"] == "ok"
            expected_order = [
                (0.0, "file:src_a/src/worker_a.py", context.binding_a_id),
                (0.0, SEED_KEY, context.binding_b_id),
                (1.0, "file:src_b/src/service_b.py", context.binding_b_id),
                (1.0, "file:src_b/src/worker_b.py", context.binding_b_id),
            ]
            assert [(c["distance"], c["canonical_key"], c["source_binding_id"])
                    for c in res5["candidates"]] == expected_order
            # Backend returns seed in result["provenance"]["seed"], not top-level
            assert res5["provenance"]["seed"]["canonical_key"] == SEED_KEY
            assert res5["provenance"]["seed"]["source_binding_id"] == context.binding_a_id
            assert any(
                c["canonical_key"] == SEED_KEY and c["source_binding_id"] == context.binding_b_id
                for c in res5["candidates"]
            ), "other source copy must be kept in candidates"

            res6 = _sc(6)
            assert res6["status"] == "ok" and len(res6["candidates"]) == 2
            keys = [(c["distance"], c["canonical_key"], c["source_binding_id"]) for c in res6["candidates"]]
            assert keys == expected_order[:2]

            assert _sc(7)["reason"] == "seed_node_missing"
            assert _sc(8)["reason"] == "seed_embedding_missing"
            assert _sc(9)["reason"] == "profile_mismatch"
            assert _sc(10)["reason"] == "profile_mismatch"
            assert _sc(11)["reason"] == "enrichment_unavailable"
            assert _sc(14)["reason"] == "foreign_publication"

            canonical_after_reads = query_canonical_node_records(
                postgres.psql_args, root_path=f"graph:{GRAPH_ID}", repository_identity=REPO_IDENTITY,
                psql_command=postgres.psql_command,
            )
            assert canonical_after_reads == canonical_before
            assert postgres.psql_scalar("SELECT count(*) FROM canonical_edges;") == edges_before

            # 3. Stale publication after graph successor refresh
            publish_portable_seed_graph(
                postgres, root, graph_id=GRAPH_ID, repository_name=REPO_NAME,
                repository_identity=REPO_IDENTITY, revision=2,
            )
            stale_req = [_rpc_call(12, **{**common_args, "source_binding_id": context.binding_a_id})]
            stale_resp = run_mcp_stdio_requests(mcp_config, postgres.psql_command, stale_req, reader_role=READER)
            assert stale_resp[0]["result"]["structuredContent"]["reason"] == "stale_rebuild"

            foreign_req = [_rpc_call(13, **{**common_args, "graph_id": "nonexistent-graph"})]
            foreign_resp = run_mcp_stdio_requests(mcp_config, postgres.psql_command, foreign_req, reader_role=READER)
            assert foreign_resp[0]["result"]["isError"] is True

            # 4. Zero mutation proof
            canonical_after = query_canonical_node_records(
                postgres.psql_args, root_path=f"graph:{GRAPH_ID}",
                repository_identity=REPO_IDENTITY, psql_command=postgres.psql_command,
            )
            edges_after = postgres.psql_scalar("SELECT count(*) FROM canonical_edges;")
            assert len(canonical_after) == len(canonical_before)
            assert edges_after == edges_before
