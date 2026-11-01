"""Real PostgreSQL proof for callable lexical restore reconciliation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


def test_d12_round_trip_probe_observes_btree_and_gin_across_pg_dump_restore(
    tmp_path: Path,
) -> None:
    """D12 ROUND_TRIP_PY custom-format pg_dump/pg_restore preserves btree and gin indexes."""
    import json
    import os
    import subprocess
    import sys
    from repomap_test_support.d12_image_probes import ROUND_TRIP_PY
    from repomap_test_support.postgres_harness import postgres_bin_dir
    from tools.system.d12_candidate_assessment import ACCEPTED_INDEX_ACCESS_METHODS, _verify_round_trip

    assert '"-p", "5432"' in ROUND_TRIP_PY and "port=5432" in ROUND_TRIP_PY
    assert '"/tmp/d12-source.dump"' in ROUND_TRIP_PY
    bin_dir = postgres_bin_dir()

    with temporary_postgres() as pg_db:
        archive_path = tmp_path / "d12-source.dump"
        restore_shim = tmp_path / "pg_restore_shim.py"
        restore_shim.write_text(
            f"#!{sys.executable}\n"
            "import os, subprocess, sys\n"
            f"real_restore = {str(bin_dir / 'pg_restore')!r}\n"
            f"real_psql = {str(bin_dir / 'psql')!r}\n"
            "if '-l' in sys.argv:\n"
            "    os.execv(real_restore, [real_restore, *sys.argv[1:]])\n"
            "sql = subprocess.check_output([real_restore, '-f', '-', sys.argv[-1]], text=True)\n"
            "clean = '\\n'.join(l for l in sql.splitlines() if l != 'SET transaction_timeout = 0;') + '\\n'\n"
            "subprocess.run([real_psql, *sys.argv[1:-3], '--single-transaction', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1'], input=clean, text=True, check=True)\n",
            encoding="utf-8",
        )
        restore_shim.chmod(0o755)
        probe_script = (
            ROUND_TRIP_PY.replace('"127.0.0.1"', repr(pg_db.host))
            .replace('"-p", "5432"', f'"-p", "{pg_db.port}"')
            .replace("port=5432", f"port={pg_db.port}")
            .replace('"/tmp/d12-source.dump"', repr(str(archive_path)))
        )
        env = dict(
            os.environ,
            PYTHONPATH=os.pathsep.join(sys.path),
            REPOMAP_PACKAGED_PSQL=str(bin_dir / "psql"),
            REPOMAP_PACKAGED_PG_DUMP=str(bin_dir / "pg_dump"),
            REPOMAP_PACKAGED_PG_RESTORE=str(restore_shim),
            PGUSER=pg_db.user,
            PGDATABASE=pg_db.database,
            PGPASSWORD=pg_db.password or "",
        )
        pg_db.psql_scalar("DROP DATABASE IF EXISTS d12_source;")
        pg_db.psql_scalar("DROP DATABASE IF EXISTS d12_restore;")
        try:
            completed = subprocess.run(
                [sys.executable, "-c", probe_script],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            round_trip: dict[str, Any] = json.loads(completed.stdout)
            _verify_round_trip(round_trip)
            assert round_trip["source"]["index_access_methods"] == list(ACCEPTED_INDEX_ACCESS_METHODS)
            assert round_trip["restored"]["index_access_methods"] == list(ACCEPTED_INDEX_ACCESS_METHODS)
        finally:
            pg_db.psql_scalar("DROP DATABASE IF EXISTS d12_source;")
            pg_db.psql_scalar("DROP DATABASE IF EXISTS d12_restore;")
