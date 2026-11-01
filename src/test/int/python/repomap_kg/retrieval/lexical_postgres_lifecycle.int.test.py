"""Integration tests for PostgreSQL 16 cloe_lexical build, query styles, fences, role denial, and restore (Unit 1)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from common_lore_index.cli.main import main as cli_main
from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.lexical_publication import (
    lexical_connection_parameters,
    resolve_ops_graph,
)
from common_lore_index.ops.lexical_service import (
    build_graph_lexical_generation,
    query_graph_lexical_generation,
)
from common_lore_index.retrieval.lexical_envelopes import (
    FTS_ORDERING_POLICY_VERSION,
    LexicalQueryRequest,
)
from common_lore_index.retrieval.projection_policy import ExclusionReason
from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    DEFAULT_ORDERING_POLICY_VERSION,
    QueryMode,
)
from common_lore_index.runtime._lexical_restore import (
    reconcile_restored_graph_lexical_roles,
)
from common_lore_index.storage.lexical_driver import (
    LIMITED_LEXICAL_ROLES,
    LexicalRoleDeniedError,
    LexicalStorageError,
    execute_fetchone,
    lexical_connection_scope,
)
from common_lore_index.storage.lexical_probe import probe_lexical_runtime
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus,
)


def test_postgres_lexical_build_query_styles_fence_reclassification_revoke_and_restore(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exercise full cloe_lexical lifecycle, 3 query styles, single-statement fence, role denial, and restore purge."""
    with temporary_postgres() as pg_db:
        wc_gen1 = materialize_mixed_v1_working_copy(tmp_path / "wc_pg", generation=1)
        mixed_home = write_mixed_v1_postgres_home(
            tmp_path / "pg_mixed_home", wc_gen1,
            host=pg_db.host, port=pg_db.port, database=pg_db.database,
            user=pg_db.user, password=pg_db.password,
        )
        publish_and_load_postgres_corpus(mixed_home, psql_command=pg_db.psql_command)
        mixed_cfg = load_graph_registry_config_home(mixed_home)
        assert isinstance(mixed_cfg, OpsConfig)

        # 0. Strict mixed-privacy graph refusal: 4-binding mixed-v1 resolves graph.privacy == "private-ops"
        core_id = binding_id_for_alias("core")
        comp_id = binding_id_for_alias("companion")
        mixed_build = build_graph_lexical_generation(
            mixed_cfg, MIXED_V1_GRAPH_ID, selected_binding_ids=(core_id, comp_id), authorize_body=True
        )
        assert mixed_build.result == "refused"
        assert mixed_build.refusal_code == ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value
        mixed_query = query_graph_lexical_generation(
            mixed_cfg, MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(query="RetrievalExecutionPipeline", selected_binding_ids=(core_id,)),
            authorize_body=True,
        )
        assert mixed_query.capability_state == CapabilityState.REFUSED
        assert mixed_query.refusal_code == ExclusionReason.GRAPH_PRIVACY_NOT_AUTHORIZED.value

        # Create 2-binding all-public view (declared_aliases=("core", "companion"))
        pub_db = f"{pg_db.database}_pub"
        admin_args = [pg_db.psql_command, *mixed_cfg.postgres.psql_args_for_database("postgres"), "-tAc"]
        subprocess.run([*admin_args, f'CREATE DATABASE "{pub_db}"'], check=True)
        pg_home = write_mixed_v1_postgres_home(
            tmp_path / "pg_home", wc_gen1,
            host=pg_db.host, port=pg_db.port, database=pub_db,
            user=pg_db.user, password=pg_db.password,
            declared_aliases=("core", "companion"),
        )
        publish_and_load_postgres_corpus(pg_home, psql_command=pg_db.psql_command)
        config = load_graph_registry_config_home(pg_home)
        assert isinstance(config, OpsConfig)
        graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
        params = lexical_connection_parameters(config, graph)

        # 1. Probe PG16 runtime and cloe_lexical schema readiness
        with lexical_connection_scope(params) as conn:
            probe = probe_lexical_runtime(conn).require_ready()
            assert probe.ready is True and probe.server_version_num >= 160000
            assert probe.table_count == 5 and probe.gin_index_count == 2

        # 2. Query before build -> unavailable (projection_absent)
        pre_env = query_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="RetrievalExecutionPipeline", query_style="ranked_terms", selected_binding_ids=(core_id,)
            ),
            authorize_body=True,
        )
        assert pre_env.capability_state == CapabilityState.UNAVAILABLE
        assert pre_env.unavailable_reason == "projection_absent"

        # 3. Delete a live working-copy file BEFORE lexical-build to prove capture reads retained ArtifactStore
        (wc_gen1 / "core" / "pkg" / "tokens.py").unlink()
        build_out = build_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID, selected_binding_ids=(core_id, comp_id), authorize_body=True
        )
        assert build_out.result == "published" and build_out.published is not None
        assert build_out.published.projected_document_count > 0
        assert build_out.published.projected_chunk_count > 0
        assert set(build_out.admitted_binding_ids) == {core_id, comp_id}
        assert_canary_free(build_out.to_dict())

        # Verify zero canary strings exist anywhere in cloe_lexical tables
        with lexical_connection_scope(params) as conn:
            row = execute_fetchone(conn, "SELECT json_agg(t)::text FROM (SELECT * FROM cloe_lexical.chunks) t")
            assert row is not None
            assert_canary_free(row[0] or "")

        # 4. Query style 1: ranked_terms (with identifier/path alias split)
        ranked_env = query_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="RetrievalExecutionPipeline", query_style="ranked_terms",
                selected_binding_ids=(core_id, comp_id), limit=10,
            ),
            authorize_body=True,
        )
        assert ranked_env.capability_state in {CapabilityState.AVAILABLE, CapabilityState.PARTIAL}
        assert ranked_env.effective_mode == QueryMode.RANKED_DISCOVERY
        assert ranked_env.ordering_policy_version == FTS_ORDERING_POLICY_VERSION
        assert any(h.locator.source_relative_path == "pkg/pipeline.py" for h in ranked_env.hits)
        assert any(h.locator.canonical_key is not None for h in ranked_env.hits)
        assert_canary_free(ranked_env.to_dict())
        union_env = query_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(query="RetrievalExecutionPipeline", selected_binding_ids=(core_id,),
                                path_prefixes=("missing", "pkg"), limit=10),
            authorize_body=True,
        )
        assert union_env.hits and all(hit.locator.source_relative_path.startswith("pkg/") for hit in union_env.hits)
        assert union_env.scope.source_path_prefix is None
        assert union_env.provenance["path_prefixes"] == ["missing", "pkg"]
        assert union_env.provenance["path_prefix_match"] == "any"

        # Alias token query (splitting camelCase DispatchTable)
        alias_env = query_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="DispatchTable", query_style="ranked_terms", selected_binding_ids=(core_id,), limit=10
            ),
            authorize_body=True,
        )
        assert any(h.locator.source_relative_path == "pkg/router.py" for h in alias_env.hits)

        # 5. Query style 2: normalized_phrase (proving retained pkg/tokens.py was indexed despite live unlink!)
        phrase_env = query_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="verify candidate token", query_style="normalized_phrase",
                selected_binding_ids=(core_id,), limit=10,
            ),
            authorize_body=True,
        )
        assert phrase_env.effective_mode == QueryMode.RANKED_DISCOVERY
        assert any(h.locator.source_relative_path == "pkg/tokens.py" for h in phrase_env.hits)

        # 6. Query style 3: literal_captured_text (exact punctuation sensitivity)
        lit_env = query_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="ERR_CLOE_MANIFEST_SEAL_MISMATCH_409: snapshot_vector!=accepted_vector",
                query_style="literal_captured_text", selected_binding_ids=(core_id,), limit=10,
            ),
            authorize_body=True,
        )
        assert lit_env.capability_state == CapabilityState.AVAILABLE
        assert lit_env.effective_mode == QueryMode.LITERAL_CAPTURED_TEXT
        assert lit_env.ordering_policy_version == DEFAULT_ORDERING_POLICY_VERSION
        assert len(lit_env.hits) == 1
        assert lit_env.hits[0].locator.source_relative_path == "pkg/pipeline.py"
        assert lit_env.hits[0].locator.start_line == 9

        # 7. Refusals: punctuation-only empty tsquery
        ref_empty_tsq = query_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(query="::: --- !!!", query_style="ranked_terms", selected_binding_ids=(core_id,)),
            authorize_body=True,
        )
        assert ref_empty_tsq.capability_state == CapabilityState.REFUSED
        assert ref_empty_tsq.refusal_code == "empty_lexical_tsquery"

        # 8. Live on-disk config reload + policy reclassification check inside single-statement fence
        cfg_file = pg_home / "repomap.rpl.toml"
        orig_cfg_text = cfg_file.read_text(encoding="utf-8")
        try:
            cfg_file.write_text(
                orig_cfg_text.replace('evidence_retention = "full-authorized"', 'evidence_retention = "metadata-only"', 1),
                encoding="utf-8",
            )
            reclass_env = query_graph_lexical_generation(
                config, MIXED_V1_GRAPH_ID,
                LexicalQueryRequest(
                    query="RetrievalExecutionPipeline", query_style="ranked_terms",
                    selected_binding_ids=(core_id, comp_id),
                ),
                authorize_body=True,
            )
            assert reclass_env.capability_state == CapabilityState.REFUSED
            assert reclass_env.refusal_code == ExclusionReason.RETENTION_NOT_AUTHORIZED.value
        finally:
            cfg_file.write_text(orig_cfg_text, encoding="utf-8")

        # 9. Limited roles are denied access to cloe_lexical both in driver and in live PostgreSQL privileges
        psql_args = config.postgres.psql_args_for_database(pub_db)
        for limited_role in LIMITED_LEXICAL_ROLES:
            try:
                role_config = orig_cfg_text.replace(f'user = "{pg_db.user}"', f'user = "{limited_role}"')
                assert role_config != orig_cfg_text
                cfg_file.write_text(role_config, encoding="utf-8")
                with pytest.raises(LexicalRoleDeniedError, match=limited_role):
                    query_graph_lexical_generation(
                        config, MIXED_V1_GRAPH_ID,
                        LexicalQueryRequest(query="pipeline", selected_binding_ids=(core_id,)),
                        authorize_body=True,
                    )
            finally:
                cfg_file.write_text(orig_cfg_text, encoding="utf-8")
        with lexical_connection_scope(params) as conn:
            with conn.cursor() as cur:
                for limited_role in LIMITED_LEXICAL_ROLES:
                    cur.execute(
                        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{limited_role}') "
                        f"THEN CREATE ROLE {limited_role} NOLOGIN; END IF; END $$;"
                    )
            conn.commit()
        reconcile_restored_graph_lexical_roles(
            psql_args, psql_command=pg_db.psql_command, password=pg_db.password, purge_restored_rows=False
        )
        with lexical_connection_scope(params) as conn:
            for limited_role in LIMITED_LEXICAL_ROLES:
                priv_row = execute_fetchone(
                    conn,
                    "SELECT has_schema_privilege(%s, 'cloe_lexical', 'USAGE'), "
                    "has_table_privilege(%s, 'cloe_lexical.generations', 'SELECT')",
                    (limited_role, limited_role),
                )
                assert priv_row == (False, False)
                with conn.cursor() as cur:
                    cur.execute("SAVEPOINT sp_role_check")
                    cur.execute(f"SET LOCAL ROLE {limited_role}")
                with pytest.raises(LexicalStorageError) as exc_info:
                    execute_fetchone(conn, "SELECT count(*) FROM cloe_lexical.generations")
                assert exc_info.value.code == "lexical_permission_denied"
                assert exc_info.value.sqlstate == "42501"
                with conn.cursor() as cur:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_role_check")
                    cur.execute("RESET ROLE")

        # 10. Advance accepted graph publication to generation 2 without rebuilding lexical -> STALE
        materialize_mixed_v1_working_copy(wc_gen1, generation=2)
        publish_and_load_postgres_corpus(pg_home, psql_command=pg_db.psql_command)
        stale_env = query_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="RetrievalExecutionPipeline", query_style="ranked_terms", selected_binding_ids=(core_id,)
            ),
            authorize_body=True,
        )
        assert stale_env.capability_state == CapabilityState.STALE

        # 11. CLI lexical-build, lexical-query, lexical-revoke end-to-end (including opt-in flag enforcement)
        rc_no_auth = cli_main(["ops", "lexical-build", "--repo-map-home", str(pg_home), "--graph", MIXED_V1_GRAPH_ID])
        assert rc_no_auth == 1 and "body-authorization-required" in capsys.readouterr().err

        rc_no_bind = cli_main(
            ["ops", "lexical-build", "--repo-map-home", str(pg_home), "--graph", MIXED_V1_GRAPH_ID, "--authorize-body"]
        )
        assert rc_no_bind == 1 and "binding-selection-required" in capsys.readouterr().err

        rc_build = cli_main(
            [
                "ops", "lexical-build", "--repo-map-home", str(pg_home), "--graph", MIXED_V1_GRAPH_ID,
                "--authorize-body", "--binding", core_id, "--binding", comp_id, "--json",
            ]
        )
        out_build = json.loads(capsys.readouterr().out)
        assert rc_build == 0 and out_build["result"] == "published"
        assert out_build["published"]["superseded_generation_count"] == 1

        rc_query = cli_main(
            [
                "ops", "lexical-query", "--repo-map-home", str(pg_home), "--graph", MIXED_V1_GRAPH_ID,
                "--authorize-body", "--query", "RetrievalExecutionPipeline", "--query-style", "ranked_terms",
                "--binding-id", core_id, "--json",
            ]
        )
        out_query = json.loads(capsys.readouterr().out)
        assert rc_query == 0 and out_query["capability_state"] == "available" and out_query["hit_count"] >= 1

        # 12. Ordinary role reconciliation preserves ready cloe_lexical rows; restore reconciliation purges them
        reconcile_restored_graph_lexical_roles(
            psql_args, psql_command=pg_db.psql_command, password=pg_db.password, purge_restored_rows=False
        )
        preserved_env = query_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="RetrievalExecutionPipeline", query_style="ranked_terms", selected_binding_ids=(core_id,)
            ),
            authorize_body=True,
        )
        assert preserved_env.capability_state == CapabilityState.AVAILABLE

        reconcile_restored_graph_lexical_roles(
            psql_args, psql_command=pg_db.psql_command, password=pg_db.password
        )
        after_restore_env = query_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="RetrievalExecutionPipeline", query_style="ranked_terms", selected_binding_ids=(core_id,)
            ),
            authorize_body=True,
        )
        assert after_restore_env.capability_state == CapabilityState.UNAVAILABLE
        assert (
            after_restore_env.provenance.get("revocation_reason")
            == "restored_snapshot_unverified_lexical_index_invalidated"
        )

        # Rebuild and test explicit CLI lexical-revoke (--dry-run and --yes)
        build_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID, selected_binding_ids=(core_id, comp_id), authorize_body=True
        )
        rc_rev_unconfirmed = cli_main(
            ["ops", "lexical-revoke", "--repo-map-home", str(pg_home), "--graph", MIXED_V1_GRAPH_ID]
        )
        assert rc_rev_unconfirmed == 1 and "revoke-confirmation-required" in capsys.readouterr().err

        rc_rev_dry = cli_main(
            [
                "ops", "lexical-revoke", "--repo-map-home", str(pg_home), "--graph", MIXED_V1_GRAPH_ID,
                "--dry-run", "--json",
            ]
        )
        out_rev_dry = json.loads(capsys.readouterr().out)
        assert rc_rev_dry == 0 and out_rev_dry["dry_run"] is True and out_rev_dry["result"] == "dry_run"
        assert out_rev_dry["purged_chunk_count"] > 0

        rc_rev = cli_main(
            [
                "ops", "lexical-revoke", "--repo-map-home", str(pg_home), "--graph", MIXED_V1_GRAPH_ID,
                "--yes", "--reason", "manual_test_revoke", "--json",
            ]
        )
        out_rev = json.loads(capsys.readouterr().out)
        assert rc_rev == 0 and out_rev["result"] == "revoked"
        assert out_rev["revoked_generation_count"] >= 1 and out_rev["purged_chunk_count"] > 0
