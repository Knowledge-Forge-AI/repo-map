"""Native PostgreSQL lexical-driver timeout, rollback, and reopen proof."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_publication import (
    lexical_connection_parameters,
    resolve_ops_graph,
)
from common_lore_index.ops.lexical_service import build_graph_lexical_generation
from common_lore_index.storage.lexical_driver import (
    LexicalStorageError,
    execute_fetchone,
    lexical_connection_scope,
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


def _published_public_fixture(tmp_path: Path, pg_db: Any) -> OpsConfig:
    """Publish a real two-binding all-public fixture and build one lexical generation."""
    working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
    home = write_mixed_v1_postgres_home(
        tmp_path / "postgres-home",
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
    built = build_graph_lexical_generation(
        config,
        MIXED_V1_GRAPH_ID,
        selected_binding_ids=(binding_id_for_alias("core"),),
        authorize_body=True,
    )
    assert built.result == "published"
    assert built.published is not None
    return config


def test_real_lexical_statement_timeout_rolls_back_and_reopens(tmp_path: Path) -> None:
    """A native pg_sleep timeout is sanitized and leaves a usable fresh scope."""
    with temporary_postgres() as pg_db:
        config = _published_public_fixture(tmp_path, pg_db)
        graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
        params = lexical_connection_parameters(
            config,
            graph,
            statement_timeout_ms=50,
            read_only=False,
        )
        with pytest.raises(LexicalStorageError) as timeout_error:
            with lexical_connection_scope(params, operation="timeout") as connection:
                execute_fetchone(
                    connection,
                    "SELECT pg_sleep(%s)",
                    (0.25,),
                    operation="timeout",
                )
        assert timeout_error.value.code == "lexical_statement_timeout"
        assert "pg_sleep" not in timeout_error.value.detail
        assert "password" not in timeout_error.value.detail.lower()
        assert "postgresql://" not in timeout_error.value.detail.lower()
        assert "Traceback" not in str(timeout_error.value)

        with lexical_connection_scope(params, operation="reopen") as connection:
            row = execute_fetchone(
                connection,
                "SELECT count(*) FROM cloe_lexical.generations",
                operation="reopen",
            )
        assert row is not None
        assert int(row[0]) >= 1


def test_real_lexical_lock_timeout_releases_and_reopens(tmp_path: Path) -> None:
    """A real generations lock timeout is sanitized and released when both scopes close."""
    with temporary_postgres() as pg_db:
        config = _published_public_fixture(tmp_path, pg_db)
        graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
        holder_params = lexical_connection_parameters(config, graph, read_only=False)
        waiter_params = replace(holder_params, lock_timeout_ms=50)
        lock_sql = "LOCK TABLE cloe_lexical.generations IN ACCESS EXCLUSIVE MODE"

        with lexical_connection_scope(holder_params, operation="lock-holder") as holder:
            execute_fetchone(holder, lock_sql, operation="lock-holder")
            with pytest.raises(LexicalStorageError) as lock_error:
                with lexical_connection_scope(waiter_params, operation="lock-waiter") as waiter:
                    execute_fetchone(waiter, lock_sql, operation="lock-waiter")
        assert lock_error.value.code == "lexical_lock_not_available"
        assert "LOCK TABLE" not in lock_error.value.detail
        assert "postgresql://" not in lock_error.value.detail.lower()
        assert "password" not in lock_error.value.detail.lower()
        assert "Traceback" not in str(lock_error.value)

        with lexical_connection_scope(waiter_params, operation="lock-reopen") as fresh:
            execute_fetchone(fresh, lock_sql, operation="lock-reopen")
            row = execute_fetchone(
                fresh,
                "SELECT count(*) FROM cloe_lexical.generations",
                operation="lock-reopen",
            )
        assert row is not None and int(row[0]) >= 1
