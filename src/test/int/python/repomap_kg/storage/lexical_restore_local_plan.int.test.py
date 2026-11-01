"""Real PostgreSQL proof for callable lexical restore reconciliation."""

from __future__ import annotations

from pathlib import Path

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_publication import (
    lexical_connection_parameters,
    resolve_ops_graph,
)
from common_lore_index.ops.lexical_service import build_graph_lexical_generation
from common_lore_index.runtime._lexical_restore import RESTORED_INVALIDATION_REASON
from common_lore_index.runtime.backup import drop_database, init_database_from_dump
from common_lore_index.storage.lexical_driver import (
    execute_fetchone,
    lexical_connection_scope,
)
from repomap_test_support.local_db_backup import (
    connect_real_postgres,
    setup_real_backup_home,
)
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


def test_local_plan_restore_uses_real_reconciler_and_purges_derived_rows(
    tmp_path: Path,
) -> None:
    """Restore keeps canonical graph rows while invalidating restored lexical rows."""
    with temporary_postgres() as pg_db:
        database = f"{pg_db.database}_lexical_restore"
        pg_db.create_database(database)
        working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
        publication_home = write_mixed_v1_postgres_home(
            tmp_path / "publication-home",
            working_copy,
            host=pg_db.host,
            port=pg_db.port,
            database=database,
            user=pg_db.user,
            password=pg_db.password,
            declared_aliases=("core", "companion"),
        )
        publish_and_load_postgres_corpus(
            publication_home,
            psql_command=pg_db.psql_command,
        )
        config = load_graph_registry_config_home(publication_home)
        assert isinstance(config, OpsConfig)
        graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
        params = lexical_connection_parameters(config, graph)
        core_id = binding_id_for_alias("core")
        companion_id = binding_id_for_alias("companion")
        build = build_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            selected_binding_ids=(core_id, companion_id),
            authorize_body=True,
        )
        assert build.result == "published" and build.published is not None
        generation_id = build.published.lexical_generation_id

        with lexical_connection_scope(params) as conn:
            canonical_before = execute_fetchone(conn, "SELECT count(*) FROM public.repositories")
            canonical_identity_before = execute_fetchone(
                conn,
                "SELECT repository_identity FROM public.repositories ORDER BY id LIMIT 1",
            )
            generation_before = execute_fetchone(
                conn,
                "SELECT count(*) FROM cloe_lexical.generations",
            )
            documents_before = execute_fetchone(
                conn,
                "SELECT count(*) FROM cloe_lexical.documents",
            )
            chunks_before = execute_fetchone(
                conn,
                "SELECT count(*) FROM cloe_lexical.chunks",
            )
            authority_before = execute_fetchone(
                conn,
                "SELECT count(*) FROM cloe_lexical.authority",
            )
        assert canonical_before is not None and canonical_before[0] > 0
        assert canonical_identity_before is not None
        assert generation_before == (1,)
        assert documents_before is not None and documents_before[0] > 0
        assert chunks_before is not None and chunks_before[0] > 0
        assert authority_before == (1,)

        # setup_real_backup_home injects only owned-container inspection; its runner
        # maps every database command to the active temporary PostgreSQL container.
        runtime_home = tmp_path / "restore-runtime-home"
        _identity, runner = setup_real_backup_home(
            runtime_home,
            pg_db,
            graph_db=database,
        )
        dropped = drop_database(
            runtime_home,
            database=database,
            backup_first=True,
            confirmed=True,
            timestamp="20261031T000000Z",
            command_runner=runner,
        )
        assert dropped.result == "success" and dropped.database_dropped is True

        restored = init_database_from_dump(
            runtime_home,
            database=database,
            backup=dropped.backup_plan.backup_path,
            command_runner=runner,
        )
        assert restored.result == "success" and restored.dump_restored is True
        assert restored.runtime_plan.graph_databases == (database,)

        with connect_real_postgres(pg_db, database) as conn:
            canonical_after = execute_fetchone(
                conn,
                "SELECT count(*) FROM public.repositories",
            )
            canonical_identity_after = execute_fetchone(
                conn,
                "SELECT repository_identity FROM public.repositories ORDER BY id LIMIT 1",
            )
            generation_after = execute_fetchone(
                conn,
                "SELECT count(*) FROM cloe_lexical.generations",
            )
            generation_state = execute_fetchone(
                conn,
                """
                SELECT lexical_generation_id, state, revocation_reason,
                       builder_owner_id, lease_expires_at
                FROM cloe_lexical.generations
                ORDER BY created_at DESC
                LIMIT 1
                """,
            )
            derived_counts = {
                table: execute_fetchone(
                    conn,
                    f"SELECT count(*) FROM cloe_lexical.{table}",
                )
                for table in ("documents", "chunks", "authority", "omissions")
            }

        assert canonical_after == canonical_before
        assert canonical_identity_after == canonical_identity_before
        assert generation_after == generation_before
        assert generation_state == (
            generation_id,
            "revoked",
            RESTORED_INVALIDATION_REASON,
            None,
            None,
        )
        assert all(row == (0,) for row in derived_counts.values())
