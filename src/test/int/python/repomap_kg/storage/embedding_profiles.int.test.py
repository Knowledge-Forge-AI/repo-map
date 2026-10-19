"""Real PG16/pgvector087 profile discovery and explicit stdio seed comparison."""

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest

from repomap_kg.storage.semantic_candidates import EmbeddingProfilesQuery
from repomap_kg.storage.semantic_candidate_readback import query_embedding_profiles
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.psql import run_psql
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.semantic_candidate_import import candidate_schema_sql
from repomap_kg.storage.semantic_candidates import EmbeddingProfile
from repomap_kg.storage.sql_core import sql_literal
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.semantic_candidate_restore import teardown_optional_schema_without_cascade
from repomap_test_support.semantic_seed_publication import (
    SEED_KEY, import_seed_embeddings, publish_portable_seed_graph,
    run_mcp_stdio_requests, write_seed_mcp_config,
)

GRAPH = "profile-graph"
REPOSITORY = "repo1:profile-graph"
READER = "profile_fixture_reader"
WRITER = "profile_fixture_enrichment"
PROFILE = EmbeddingProfile("synthetic-axis-fixture", "1", "public-fixture-author", "1", 3)


def execute(postgres, sql, *, role=None):
    prefix = f'SET ROLE "{role}";\n' if role else ""
    run_psql([postgres.psql_command, *postgres.psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
             input_text=prefix + sql)


def discover(postgres, *, repository=REPOSITORY, limit=20):
    with patch.dict(os.environ, {"PGOPTIONS": f"-c role={READER} -c default_transaction_read_only=on"}):
        return query_embedding_profiles(postgres.psql_args, repository_identity=repository,
            query=EmbeddingProfilesQuery(selected=True, limit=limit), psql_command=postgres.psql_command)


def rpc(req_id, name="repomap_embedding_profiles", **arguments):
    return {"jsonrpc": "2.0", "id": req_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}


def content(response):
    assert not response["result"].get("isError"), response
    return response["result"]["structuredContent"]


@pytest.mark.requires_pgvector
def test_profile_discovery_publication_and_stdio_boundary():
    require_postgres_binaries()
    with temporary_postgres() as postgres, tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        assert postgres.psql_scalar("SELECT current_setting('server_version_num')::int / 10000") == "16"
        assert postgres.psql_scalar(
            "SELECT count(*) FROM pg_available_extension_versions WHERE name='vector' AND version='0.8.7'"
        ) == "1", "profile owner requires the pinned pgvector test image"
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        execute(postgres, f"CREATE ROLE {READER} NOLOGIN; CREATE ROLE {WRITER} NOLOGIN; "
                "CREATE SCHEMA repomap_vector; "
                "CREATE EXTENSION vector WITH SCHEMA repomap_vector VERSION '0.8.7';")
        try:
            execute(postgres, candidate_schema_sql(read_principal=READER, enrichment_principal=WRITER))
            context = publish_portable_seed_graph(postgres, root, graph_id=GRAPH,
                repository_name="profile-repository", repository_identity=REPOSITORY)
            config = write_seed_mcp_config(root / "mcp-ops.local.toml", postgres, context)
            assert discover(postgres).reason == "no_import"
            import_seed_embeddings(postgres, context, rebuild_id="z-profile", writer_role=WRITER, profile=PROFILE)
            alternate = replace(PROFILE, model_version="2")
            import_seed_embeddings(postgres, context, rebuild_id="a-profile", writer_role=WRITER, profile=alternate)
            foreign_root = root / "foreign"
            foreign_root.mkdir()
            foreign = publish_portable_seed_graph(postgres, foreign_root, graph_id="foreign-profile",
                repository_name="foreign-profile-repository", repository_identity="repo1:foreign-profile")
            import_seed_embeddings(postgres, foreign, rebuild_id="foreign-profile", writer_role=WRITER, profile=PROFILE)

            assert postgres.psql_scalar(f"SELECT rolsuper FROM pg_roles WHERE rolname='{READER}'") == "f"
            assert postgres.psql_scalar(f"SELECT has_database_privilege('{READER}', current_database(), 'CREATE')") == "f"
            for table in ("repomap_enrichment.rebuilds", "repomap_enrichment.embeddings",
                          "public.runs", "public.canonical_nodes", "public.canonical_evidence"):
                for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    assert postgres.psql_scalar(
                        f"SELECT has_table_privilege('{READER}', '{table}', '{privilege}')"
                    ) == "f"
            with pytest.raises(StorageSchemaError):
                execute(postgres, "DELETE FROM repomap_enrichment.rebuilds WHERE false", role=READER)
            with pytest.raises(StorageSchemaError):
                execute(postgres, "UPDATE public.runs SET status='complete' WHERE false", role=READER)

            before = postgres.psql_scalar("SELECT json_build_array((SELECT count(*) FROM canonical_nodes), "
                "(SELECT count(*) FROM canonical_edges), (SELECT count(*) FROM canonical_evidence), "
                "(SELECT count(*) FROM repomap_enrichment.rebuilds), "
                "(SELECT count(*) FROM repomap_enrichment.embeddings))::text")
            result = discover(postgres)
            assert result.status == "ok" and [p["rebuild_id"] for p in result.profiles] == ["a-profile", "z-profile"]
            assert not result.has_excluded_rebuilds  # Foreign imports never enter this repository scope.
            assert [p["profile_identity"] for p in result.profiles] == [alternate.identity, PROFILE.identity]
            assert all(p["row_count"] == 5 and p["dimensions"] == 3 for p in result.profiles)
            assert result.provenance["receipt_identity"] == context.publication.receipt_identity
            assert {s["source_binding_id"] for s in result.profiles[0]["source_scope"]} == {
                context.binding_a_id, context.binding_b_id}
            limited = discover(postgres, limit=1)
            assert limited.has_more and [p["rebuild_id"] for p in limited.profiles] == ["a-profile"]

            responses = run_mcp_stdio_requests(config, postgres.psql_command, [
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                rpc(2, graph_id=GRAPH), rpc(3, graph_id=GRAPH, selected=True, limit=1),
                rpc(4, graph_id=GRAPH, selected="true"), rpc(5, graph_id="unknown", selected=True),
            ], reader_role=READER)
            by_id = {item["id"]: item for item in responses}
            assert len(by_id[1]["result"]["tools"]) == 31
            assert any(t["name"] == "repomap_embedding_profiles" for t in by_id[1]["result"]["tools"])
            assert content(by_id[2])["reason"] == "disabled"
            discovered = content(by_id[3])
            assert discovered["status"] == "ok" and discovered["has_more"]
            chosen, = discovered["profiles"]
            assert chosen == result.profiles[0]
            assert by_id[4]["result"]["isError"] and by_id[5]["result"]["isError"]
            selected = {field: chosen[field] for field in ("rebuild_id", "profile_identity", "dimensions")}
            compared = content(run_mcp_stdio_requests(config, postgres.psql_command, [
                rpc(6, "repomap_similar_nodes", graph_id=GRAPH, canonical_key=SEED_KEY,
                    source_binding_id=context.binding_a_id, selected=True, **selected),
            ], reader_role=READER)[0])
            assert compared["status"] == "ok" and len(compared["candidates"]) == 4
            assert {field: compared["provenance"][field] for field in ("rebuild_id", "profile_identity")} == {
                field: chosen[field] for field in ("rebuild_id", "profile_identity")}
            assert compared["provenance"]["profile"]["dimensions"] == chosen["dimensions"]
            assert compared["provenance"]["receipt_identity"] == discovered["provenance"]["receipt_identity"]
            serialized = json.dumps(discovered)
            for forbidden in (READER, WRITER, "foreign-profile", str(root), '"embedding"', "raw_source"):
                assert forbidden not in serialized
            assert postgres.psql_scalar("SELECT json_build_array((SELECT count(*) FROM canonical_nodes), "
                "(SELECT count(*) FROM canonical_edges), (SELECT count(*) FROM canonical_evidence), "
                "(SELECT count(*) FROM repomap_enrichment.rebuilds), "
                "(SELECT count(*) FROM repomap_enrichment.embeddings))::text") == before

            # Lifecycle corruption never authorizes optimistic metadata adoption.
            execute(postgres, "UPDATE repomap_enrichment.rebuilds SET profile_identity='sha256:' || repeat('f',64) "
                             "WHERE rebuild_id='a-profile'")
            assert discover(postgres).reason == "invalid_identity"
            execute(postgres, f"UPDATE repomap_enrichment.rebuilds SET profile_identity={sql_literal(alternate.identity)} "
                             "WHERE rebuild_id='a-profile'")
            execute(postgres, "UPDATE repomap_enrichment.rebuilds SET row_count=6 WHERE rebuild_id='a-profile'")
            partial = discover(postgres)
            assert partial.status == "ok" and partial.has_excluded_rebuilds
            assert [p["rebuild_id"] for p in partial.profiles] == ["z-profile"]
            execute(postgres, "UPDATE repomap_enrichment.rebuilds SET row_count=6")
            assert discover(postgres).reason == "invalid_rebuild"
            execute(postgres, "UPDATE repomap_enrichment.rebuilds SET row_count=5")
            execute(postgres, "UPDATE repomap_enrichment.embeddings SET snapshot_id='snap1:foreign' "
                             "WHERE rebuild_id IN ('a-profile','z-profile')")
            assert discover(postgres).reason == "invalid_rebuild"
            for binding, snapshot in context.snapshots.items():
                execute(postgres, f"UPDATE repomap_enrichment.embeddings SET snapshot_id={sql_literal(snapshot)} "
                    f"WHERE source_binding_id={sql_literal(binding)} AND rebuild_id IN ('a-profile','z-profile')")

            # A successful capability probe cannot hide a SELECT privilege defect.
            execute(postgres, f"REVOKE SELECT ON repomap_enrichment.rebuilds FROM {READER}")
            with pytest.raises(StorageSchemaError, match="embedding profile query failed"):
                discover(postgres)
            execute(postgres, f"GRANT SELECT ON repomap_enrichment.rebuilds TO {READER}")

            # Publish a real successor between receipt read and fenced metadata SQL.
            from repomap_kg.storage import semantic_candidate_readback as owner
            original = owner.execute_json_readback
            successors = []

            def drift(sql, **kwargs):
                if sql.startswith("WITH "):
                    with patch.dict(os.environ, {"PGOPTIONS": ""}):
                        successor = publish_portable_seed_graph(postgres, root, graph_id=GRAPH,
                            repository_name="profile-repository", repository_identity=REPOSITORY, revision=2)
                        assert successor.publication.publication.run_id > context.publication.publication.run_id
                        assert successor.publication.receipt_identity != context.publication.receipt_identity
                        successors.append(successor)
                return original(sql, **kwargs)

            with patch.object(owner, "execute_json_readback", drift):
                assert discover(postgres).reason == "stale_publication"
            stale = content(run_mcp_stdio_requests(config, postgres.psql_command,
                [rpc(7, graph_id=GRAPH, selected=True)], reader_role=READER)[0])
            assert stale["reason"] == "stale_rebuild" and stale["profiles"] == []
            successor, = successors
            import_seed_embeddings(postgres, successor, rebuild_id="b-successor", writer_role=WRITER, profile=PROFILE)
            current = discover(postgres)
            assert current.status == "ok" and current.has_excluded_rebuilds
            assert [p["rebuild_id"] for p in current.profiles] == ["b-successor"]
            private_token = "privateuser"
            token_profile = replace(PROFILE, model=f"fixture-{private_token}-model")
            path_profile = replace(PROFILE, model=f"fixture:{config}")
            import_seed_embeddings(postgres, successor, rebuild_id="c-private", writer_role=WRITER, profile=token_profile)
            import_seed_embeddings(postgres, successor, rebuild_id="d-path", writer_role=WRITER, profile=path_profile)
            before_private = postgres.psql_scalar("SELECT json_build_array((SELECT count(*) FROM canonical_nodes), "
                "(SELECT count(*) FROM canonical_edges), (SELECT count(*) FROM canonical_evidence), "
                "(SELECT count(*) FROM repomap_enrichment.rebuilds), "
                "(SELECT count(*) FROM repomap_enrichment.embeddings))::text")
            with patch.dict(os.environ, {"HOME": f"/nonexistent-home/{private_token}"}):
                private_responses = run_mcp_stdio_requests(config, postgres.psql_command, [
                    rpc(8, graph_id=GRAPH, selected=True, limit=2),
                    rpc(9, "repomap_similar_nodes", graph_id=GRAPH, canonical_key=SEED_KEY,
                        source_binding_id=successor.binding_a_id, rebuild_id="c-private",
                        profile_identity=token_profile.identity, dimensions=token_profile.dimensions, selected=True),
                    rpc(10, "repomap_similar_nodes", graph_id=GRAPH, canonical_key=SEED_KEY,
                        source_binding_id=successor.binding_a_id, rebuild_id="d-path",
                        profile_identity=path_profile.identity, dimensions=path_profile.dimensions, selected=True),
                    rpc(11, "repomap_similar_nodes", graph_id=GRAPH, canonical_key=SEED_KEY,
                        source_binding_id=successor.binding_a_id, rebuild_id="b-successor",
                        profile_identity=PROFILE.identity, dimensions=PROFILE.dimensions, selected=True),
                ], reader_role=READER)
            private_by_id = {item["id"]: content(item) for item in private_responses}
            assert (private_by_id[8]["status"], private_by_id[8]["reason"],
                    private_by_id[8]["profiles"], private_by_id[8]["provenance"]) == (
                "capability_unavailable", "privacy_refused", [], None)
            for req_id in (9, 10):
                assert (private_by_id[req_id]["status"], private_by_id[req_id]["reason"],
                        private_by_id[req_id]["candidates"], private_by_id[req_id]["provenance"]) == (
                    "capability_unavailable", "privacy_refused", [], None)
            assert private_by_id[11]["status"] == "ok" and len(private_by_id[11]["candidates"]) == 4
            private_serialized = json.dumps([private_by_id[8], private_by_id[9], private_by_id[10]])
            for forbidden in (READER, WRITER, str(root), private_token, token_profile.model,
                              path_profile.model, '"embedding"', "raw_source"):
                assert forbidden not in private_serialized
            assert postgres.psql_scalar("SELECT json_build_array((SELECT count(*) FROM canonical_nodes), "
                "(SELECT count(*) FROM canonical_edges), (SELECT count(*) FROM canonical_evidence), "
                "(SELECT count(*) FROM repomap_enrichment.rebuilds), "
                "(SELECT count(*) FROM repomap_enrichment.embeddings))::text") == before_private
            # A graph with only a foreign repository's import cannot adopt it.
            empty_root = root / "empty"
            empty_root.mkdir()
            publish_portable_seed_graph(postgres, empty_root, graph_id="unimported-profile",
                repository_name="unimported-profile-repository", repository_identity="repo1:unimported-profile")
            assert discover(postgres, repository="repo1:unimported-profile").reason == "no_import"
        finally:
            teardown_optional_schema_without_cascade(postgres, reader=READER, writer=WRITER)
            execute(postgres, f"DROP OWNED BY {READER}, {WRITER}; DROP ROLE {READER}; DROP ROLE {WRITER};")
