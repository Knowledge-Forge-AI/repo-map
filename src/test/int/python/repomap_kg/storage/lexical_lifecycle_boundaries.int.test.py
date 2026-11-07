"""Integration proofs for retained lexical lifecycle, reload, and ACL boundaries."""

from __future__ import annotations

import shutil
from pathlib import Path

import psycopg
import pytest

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig, OpsConfigError
from common_lore_index.ops.lexical_publication import (
    build_and_publish_lexical_generation,
    lexical_connection_parameters,
    resolve_ops_graph,
)
from common_lore_index.ops.lexical_service import (
    build_graph_lexical_generation,
    query_graph_lexical_generation,
)
from common_lore_index.retrieval.lexical_envelopes import LexicalQueryRequest
from common_lore_index.retrieval.query_contracts import CapabilityState
from common_lore_index.runtime.database_role_contract import (
    READ_STATUS_ROLE,
    RoleSecrets,
)
from common_lore_index.storage.lexical_driver import (
    LexicalStorageError,
    execute_fetchall,
    execute_fetchone,
    lexical_connection_scope,
)
from repomap_test_support.host_mcp_publication import provision_roles
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus,
)


def _disable_companion(text: str) -> str:
    """Edit only the maintained companion binding block in repomap.rpl.toml."""
    header, *blocks = text.split("[[graphs.source_bindings]]")
    for index, block in enumerate(blocks):
        if 'alias = "companion"' in block:
            blocks[index] = block.replace("enabled = true", "enabled = false", 1)
            break
    return "[[graphs.source_bindings]]".join((header, *blocks))


def _config_diagnostic_codes(error: OpsConfigError) -> set[str]:
    return {diagnostic.code for diagnostic in error.diagnostics}


def test_lexical_lifecycle_boundaries_use_retained_publication_reload_and_acl(
    tmp_path: Path,
) -> None:
    """Prove retained bytes, subset policy, cleanup fencing, reloads, and role ACLs."""
    with temporary_postgres() as pg_db:
        working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
        home = write_mixed_v1_postgres_home(
            tmp_path / "home",
            working_copy,
            host=pg_db.host,
            port=pg_db.port,
            database=pg_db.database,
            user=pg_db.user,
            password=pg_db.password,
            declared_aliases=("core", "companion"),
        )
        publish_and_load_postgres_corpus(home, psql_command=pg_db.psql_command)
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
        params = lexical_connection_parameters(config, graph)
        core_id = binding_id_for_alias("core")
        companion_id = binding_id_for_alias("companion")
        config_path = home / "repomap.rpl.toml"
        original_config = config_path.read_text(encoding="utf-8")

        first = build_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            selected_binding_ids=(core_id, companion_id),
            authorize_body=True,
        )
        assert first.result == "published" and first.published is not None
        first_generation_id = first.published.lexical_generation_id

        # The accepted portable ArtifactStore remains authoritative after roots vanish.
        shutil.rmtree(working_copy / "core")
        shutil.rmtree(working_copy / "companion")
        subset = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="RetrievalExecutionPipeline",
                selected_binding_ids=(core_id,),
                limit=10,
            ),
            authorize_body=True,
        )
        assert subset.capability_state in {
            CapabilityState.AVAILABLE,
            CapabilityState.PARTIAL,
        }
        assert any(
            hit.locator.source_relative_path == "pkg/pipeline.py"
            for hit in subset.hits
        )

        # Recheck a changed scope with the old config and prove owner cleanup is narrow.
        config_path.write_text(_disable_companion(original_config), encoding="utf-8")
        changed_config = load_graph_registry_config_home(home)
        assert isinstance(changed_config, OpsConfig)
        config_path.write_text(original_config, encoding="utf-8")
        with pytest.raises(LexicalStorageError) as failed_build:
            build_and_publish_lexical_generation(
                config,
                MIXED_V1_GRAPH_ID,
                selected_binding_ids=(core_id,),
                authorize_body=True,
                recheck_config_fn=lambda: changed_config,
            )
        assert failed_build.value.code == "cloe_lexical_policy_digest_mismatch"

        with lexical_connection_scope(params) as conn:
            authority = execute_fetchone(
                conn,
                """
                SELECT a.lexical_generation_id, g.state
                FROM cloe_lexical.authority a
                JOIN cloe_lexical.generations g
                  ON g.repository_id = a.repository_id
                 AND g.lexical_generation_id = a.lexical_generation_id
                """,
            )
            assert authority == (first_generation_id, "published")
            lifecycle_rows = execute_fetchall(
                conn,
                "SELECT state, revocation_reason FROM cloe_lexical.generations",
            )
            assert ("invalidated", "build_failed_rollback") in lifecycle_rows
            assert ("building", None) not in lifecycle_rows

        after_cleanup = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="RetrievalExecutionPipeline",
                selected_binding_ids=(core_id,),
                limit=10,
            ),
            authorize_body=True,
        )
        assert after_cleanup.capability_state in {
            CapabilityState.AVAILABLE,
            CapabilityState.PARTIAL,
        }
        assert after_cleanup.hits

        # A scope edit is reloaded from disk even when callers retain old OpsConfig.
        config_path.write_text(_disable_companion(original_config), encoding="utf-8")
        try:
            stale = query_graph_lexical_generation(
                config,
                MIXED_V1_GRAPH_ID,
                LexicalQueryRequest(
                    query="RetrievalExecutionPipeline",
                    selected_binding_ids=(core_id, companion_id),
                ),
                authorize_body=True,
            )
            assert stale.capability_state == CapabilityState.STALE
            assert stale.provenance["stale_detail"] == "stale_policy_digest_mismatch"
        finally:
            config_path.write_text(original_config, encoding="utf-8")

        # Missing and malformed repomap.rpl.toml fail before any DB connection opens.
        try:
            config_path.unlink()
            with pytest.raises(OpsConfigError) as missing:
                query_graph_lexical_generation(
                    config,
                    MIXED_V1_GRAPH_ID,
                    LexicalQueryRequest(query="pipeline", selected_binding_ids=(core_id,)),
                    authorize_body=True,
                )
            assert "config-home-empty" in _config_diagnostic_codes(missing.value)

            config_path.write_text("[graphs\n", encoding="utf-8")
            with pytest.raises(OpsConfigError) as malformed:
                query_graph_lexical_generation(
                    config,
                    MIXED_V1_GRAPH_ID,
                    LexicalQueryRequest(query="pipeline", selected_binding_ids=(core_id,)),
                    authorize_body=True,
                )
            assert "invalid-toml" in _config_diagnostic_codes(malformed.value)
        finally:
            config_path.write_text(original_config, encoding="utf-8")

        # Existing configured read-status role can read the public graph, not lexical bodies.
        secrets = RoleSecrets(
            read_status="fixture-read-status-secret",
            refresh_publication="fixture-refresh-secret",
            coordinator_control="fixture-control-secret",
        )
        provision_roles(pg_db.user, pg_db, secrets)
        with psycopg.connect(
            host=pg_db.host,
            port=pg_db.port,
            dbname=pg_db.database,
            user=READ_STATUS_ROLE,
            password=secrets.read_status,
        ) as limited:
            assert limited.execute("SELECT current_user").fetchone() == (READ_STATUS_ROLE,)
            public_count = limited.execute("SELECT count(*) FROM public.repositories").fetchone()
            assert public_count is not None and public_count[0] >= 1
            with pytest.raises(psycopg.errors.InsufficientPrivilege) as denied:
                limited.execute("SELECT count(*) FROM cloe_lexical.generations")
            assert denied.value.sqlstate == "42501"
            limited.rollback()
