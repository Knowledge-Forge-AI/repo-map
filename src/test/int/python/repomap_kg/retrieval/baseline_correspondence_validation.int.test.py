"""SQLite/PostgreSQL integration boundaries for publication validation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.retrieval.projection_build import build_captured_text_projection
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    PublishedCorpusState,
    publish_and_load_postgres_corpus,
    publish_and_load_sqlite_corpus,
)
from repomap_test_support.w5_publication_validation_fixtures import publication_tree


def _assert_validation_boundaries(state: PublishedCorpusState) -> None:
    """Exercise build-level policy and accepted-marker validation on a retained publication."""
    inputs = state.projection_inputs()
    assert inputs.spool_dir is not None
    before = publication_tree(inputs.spool_dir)

    with pytest.raises(ValueError, match="policy.graph_id"):
        build_captured_text_projection(
            inputs,
            replace(state.policy, graph_id="other-graph"),
        )
    assert publication_tree(inputs.spool_dir) == before

    # Invalid runtime field values deliberately cross the typed constructor boundary.
    mutations: tuple[tuple[dict[str, Any], str], ...] = (
        ({"accepted_generation": 0}, "accepted_generation"),
        ({"backend": "memory"}, "backend"),
    )
    for fields, message in mutations:
        invalid = replace(inputs.accepted_reference, **fields)
        with pytest.raises(ValueError, match=message):
            build_captured_text_projection(
                replace(inputs, accepted_reference=invalid),
                state.policy,
            )
        assert publication_tree(inputs.spool_dir) == before


def test_sqlite_publication_rejects_policy_and_marker_validation_boundaries(
    tmp_path: Path,
) -> None:
    """SQLite Local retained bytes are not opened when caller policy or marker validation fails."""
    working = materialize_mixed_v1_working_copy(tmp_path / "working", generation=1)
    home = write_mixed_v1_sqlite_home(tmp_path / "sqlite-home", working)
    state = publish_and_load_sqlite_corpus(home)
    _assert_validation_boundaries(state)


def test_postgres_publication_rejects_policy_and_marker_validation_boundaries(
    tmp_path: Path,
) -> None:
    """PostgreSQL matched publication uses the same policy and marker refusal contract."""
    with temporary_postgres() as pg_db:
        working = materialize_mixed_v1_working_copy(tmp_path / "working", generation=1)
        home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home",
            working,
            host=pg_db.host,
            port=pg_db.port,
            database=pg_db.database,
            user=pg_db.user,
            password=pg_db.password,
        )
        state = publish_and_load_postgres_corpus(
            home,
            psql_command=pg_db.psql_command,
        )
        _assert_validation_boundaries(state)
