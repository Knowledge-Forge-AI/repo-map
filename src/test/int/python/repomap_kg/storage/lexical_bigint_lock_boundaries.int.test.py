"""Disposable PostgreSQL proofs for BIGINT lexical lifecycle lock boundaries."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pytest

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_publication import (
    lexical_connection_parameters,
    resolve_ops_graph,
)
from common_lore_index.ops.lexical_service import (
    build_graph_lexical_generation,
    query_graph_lexical_generation,
    revoke_graph_lexical_generation,
)
from common_lore_index.ops.resolved_config import configured_repository_identity
from common_lore_index.retrieval.lexical_envelopes import LexicalQueryRequest
from common_lore_index.storage.lexical_build_lease import (
    acquire_repository_lifecycle_lock,
)
from common_lore_index.storage.lexical_driver import (
    LexicalStorageError,
    execute_fetchone,
    lexical_connection_scope,
)
from common_lore_index.storage.lexical_lifecycle import VERIFY_FENCE_AT_COMMIT_SQL
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


LARGE_REPOSITORY_ID = 2**31 + 1
DISTINCT_REPOSITORY_ID = LARGE_REPOSITORY_ID + 1


def _final_fence_lock(connection: Any, repository_id: int) -> bool:
    """Execute the actual final-fence lock expression, without fabricating graph rows."""
    match = re.search(
        r"(pg_try_advisory_xact_lock\(pg_catalog\.hashtextextended\([^\n]+\)\)) AS advisory_lock_acquired",
        VERIFY_FENCE_AT_COMMIT_SQL,
    )
    assert match is not None
    row = execute_fetchone(
        connection,
        f"WITH lc(repository_id) AS (VALUES (%s::bigint)) SELECT {match.group(1)} FROM lc",
        (repository_id,),
    )
    assert row is not None and len(row) == 1 and isinstance(row[0], bool)
    return row[0]


def _fixture_home(tmp_path: Path, postgres: Any) -> tuple[Path, OpsConfig]:
    """Publish genuine graph rows through the incumbent's supported ordinary ID path."""
    working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
    home = write_mixed_v1_postgres_home(
        tmp_path / "home",
        working_copy,
        host=postgres.host,
        port=postgres.port,
        database=postgres.database,
        user=postgres.user,
        password=postgres.password,
        declared_aliases=("core", "companion"),
    )
    config = load_graph_registry_config_home(home)
    assert isinstance(config, OpsConfig)
    publish_and_load_postgres_corpus(home, psql_command=postgres.psql_command)
    loaded = load_graph_registry_config_home(home)
    assert isinstance(loaded, OpsConfig)
    return home, loaded


def test_real_build_query_and_revoke_preserve_accepted_repository(tmp_path: Path) -> None:
    """The changed lock retains a real ordinary-ID publication/build/query/revoke path."""
    with temporary_postgres() as postgres:
        _, config = _fixture_home(tmp_path, postgres)
        graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
        params = lexical_connection_parameters(config, graph)
        repository_identity = str(configured_repository_identity(graph.id))

        with lexical_connection_scope(params) as connection:
            row = execute_fetchone(
                connection,
                "SELECT id FROM public.repositories WHERE repository_identity = %s",
                (repository_identity,),
            )
        assert row is not None
        accepted_repository_id = int(row[0])

        core_id = binding_id_for_alias("core")
        companion_id = binding_id_for_alias("companion")
        built = build_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            selected_binding_ids=(core_id, companion_id),
            authorize_body=True,
        )
        assert built.result == "published"
        assert built.published is not None
        assert built.published.repository_id == accepted_repository_id

        envelope = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="RetrievalExecutionPipeline",
                selected_binding_ids=(core_id,),
            ),
            authorize_body=True,
        )
        assert envelope.hits

        # Live query styles: normalized_phrase, literal_captured_text with fallback, and empty_tsquery
        from common_lore_index.retrieval.query_contracts import FallbackDisclosure, QueryMode
        phrase_env = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="RetrievalExecutionPipeline",
                query_style="normalized_phrase",
                selected_binding_ids=(core_id,),
                path_prefixes=("pkg",),
            ),
            authorize_body=True,
        )
        assert phrase_env.hits
        lit_fb = FallbackDisclosure(
            caller_selected=True,
            from_mode=QueryMode.GRAPH_INVESTIGATION,
            to_mode=QueryMode.LITERAL_CAPTURED_TEXT,
            reason_code="int_fallback",
        ).validate()
        lit_env = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="RetrievalExecutionPipeline",
                query_style="literal_captured_text",
                selected_binding_ids=(core_id,),
                source_path_prefix="pkg",
                fallback=lit_fb,
            ),
            authorize_body=True,
        )
        assert lit_env.hits and lit_env.effective_mode == QueryMode.LITERAL_CAPTURED_TEXT
        empty_ts_env = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="!!!",
                query_style="ranked_terms",
                selected_binding_ids=(core_id,),
            ),
            authorize_body=True,
        )
        assert empty_ts_env.refusal_code == "empty_lexical_tsquery"

        # Live open_lexical_connection, execute_fetchall, execute_fetchone, and driver/envelope boundaries
        import common_lore_index.storage.lexical_driver as drv
        auth = drv.resolve_lexical_postgres_authority(config, postgres.database)
        with drv.open_lexical_connection(auth, read_only=True, autocommit=True) as ro_conn:
            assert drv.execute_fetchall(ro_conn, "SELECT 1") == [(1,)]
            assert drv.execute_fetchone(ro_conn, "SELECT 1 WHERE false") is None
        with drv.lexical_connection_scope(params, read_only=True) as ro_scope:
            with pytest.raises(drv.LexicalStorageError) as ro_err:
                drv.execute_fetchone(ro_scope, "CREATE TABLE public._ro_disallow(id int)")
            assert ro_err.value.code == "lexical_read_only_violation"

        revoked = revoke_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            reason="bigint_lifecycle_boundary",
            purge_rows=True,
            confirmed=True,
        )
        assert revoked.repository_id == accepted_repository_id
        assert revoked.revoked_generation_count >= 1
        assert revoked.purge_rows is True
        unavail_after_revoke = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(query="RetrievalExecutionPipeline", selected_binding_ids=(core_id,)),
            authorize_body=True,
        )
        assert unavail_after_revoke.capability_state.value == "unavailable"
        assert unavail_after_revoke.provenance.get("revocation_reason") == "bigint_lifecycle_boundary"




def test_real_bigint_lifecycle_lock_blocks_same_id_but_allows_distinct_id(
    tmp_path: Path,
) -> None:
    """Overlapping native transactions distinguish same-key contention from another BIGINT ID."""
    with temporary_postgres() as postgres:
        _, config = _fixture_home(tmp_path, postgres)
        graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
        params = lexical_connection_parameters(config, graph)

        with lexical_connection_scope(params) as held:
            acquire_repository_lifecycle_lock(held, LARGE_REPOSITORY_ID)
            with lexical_connection_scope(params) as distinct:
                acquire_repository_lifecycle_lock(distinct, DISTINCT_REPOSITORY_ID)
                with lexical_connection_scope(params) as competing:
                    with pytest.raises(LexicalStorageError) as error:
                        acquire_repository_lifecycle_lock(competing, LARGE_REPOSITORY_ID)
                    assert error.value.code == (
                        "cloe_lexical_competing_builder_in_progress"
                    )
                with lexical_connection_scope(params) as final_fence:
                    assert _final_fence_lock(final_fence, LARGE_REPOSITORY_ID) is False
                    assert _final_fence_lock(final_fence, 2**63 - 1) is True
        with lexical_connection_scope(params) as final_fence:
            assert _final_fence_lock(final_fence, LARGE_REPOSITORY_ID) is True
            with lexical_connection_scope(params) as competing:
                with pytest.raises(LexicalStorageError):
                    acquire_repository_lifecycle_lock(competing, LARGE_REPOSITORY_ID)
