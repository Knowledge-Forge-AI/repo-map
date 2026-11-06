"""High-ID portable publication and lexical lifecycle keep one accepted source."""

from __future__ import annotations

import psycopg
from psycopg.conninfo import make_conninfo

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_service import (
    build_graph_lexical_generation,
    query_graph_lexical_generation,
    revoke_graph_lexical_generation,
)
from common_lore_index.ops.resolved_config import configured_repository_identity
from common_lore_index.retrieval.lexical_envelopes import LexicalQueryRequest
from common_lore_index.storage import apply_migrations, default_rdbms_root
from common_lore_index.storage.readback_driver import _psycopg_connection_params_from_psql_args
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)
from repomap_test_support.retrieval_evaluation_publication import publish_and_load_postgres_corpus


def test_high_id_portable_sealing_publication_and_lexical_writes_with_row_holder(tmp_path):
    repository_id = 2**31
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
        home = write_mixed_v1_postgres_home(
            tmp_path / "home", working_copy, host=postgres.host, port=postgres.port,
            database=postgres.database, user=postgres.user, password=postgres.password,
            declared_aliases=("core", "companion"),
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        identity = str(configured_repository_identity(MIXED_V1_GRAPH_ID))
        with psycopg.connect(make_conninfo(**params)) as setup:
            setup.execute(
                "INSERT INTO repositories(id,name,root_path,repository_identity) VALUES (%s,%s,%s,%s)",
                (repository_id, "fixture", "fixture-seed-root", identity),
            )
        published = publish_and_load_postgres_corpus(home, psql_command=postgres.psql_command)
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        core = binding_id_for_alias("core")
        companion = binding_id_for_alias("companion")
        with psycopg.connect(make_conninfo(**params)) as holder:
            assert holder.execute(
                "SELECT id FROM repositories WHERE repository_identity=%s FOR NO KEY UPDATE NOWAIT",
                (identity,),
            ).fetchone() == (repository_id,)
            original = holder.execute(
                "SELECT id, publication_job_id, publication_attempt FROM runs WHERE repository_id=%s AND status='complete'",
                (repository_id,),
            ).fetchall()
            assert len(original) == 1
            built = build_graph_lexical_generation(
                config, MIXED_V1_GRAPH_ID, selected_binding_ids=(core, companion),
                authorize_body=True,
            )
            assert built.result == "published" and built.published is not None
            assert built.published.repository_id == repository_id
            envelope = query_graph_lexical_generation(
                config, MIXED_V1_GRAPH_ID,
                LexicalQueryRequest(query="RetrievalExecutionPipeline", selected_binding_ids=(core,)),
                authorize_body=True,
            )
            assert envelope.hits
            revoked = revoke_graph_lexical_generation(
                config, MIXED_V1_GRAPH_ID, reason="bigint_publication_compatibility",
                purge_rows=True, confirmed=True,
            )
            assert revoked.repository_id == repository_id
            assert revoked.revoked_generation_count >= 1 and revoked.purge_rows
            assert holder.execute(
                "SELECT id, publication_job_id, publication_attempt FROM runs WHERE repository_id=%s AND status='complete'",
                (repository_id,),
            ).fetchall() == original
        refreshed = publish_and_load_postgres_corpus(home, psql_command=postgres.psql_command)
        assert refreshed.manifest.manifest_id == published.manifest.manifest_id
        assert refreshed.manifest_reference.content_digest == published.manifest_reference.content_digest
