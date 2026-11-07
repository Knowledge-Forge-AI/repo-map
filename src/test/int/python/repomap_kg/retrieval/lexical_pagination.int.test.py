"""Real PostgreSQL lexical pagination and literal-occurrence cap proof."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_service import (
    build_graph_lexical_generation,
    query_graph_lexical_generation,
)
from common_lore_index.retrieval.lexical_envelopes import LexicalQueryRequest
from common_lore_index.retrieval.query_contracts import CapabilityState
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


def _public_core_fixture(tmp_path: Path, pg_db: Any) -> tuple[OpsConfig, str]:
    """Publish the maintained all-public fixture and build a real core generation."""
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
    core_id = binding_id_for_alias("core")
    built = build_graph_lexical_generation(
        config,
        MIXED_V1_GRAPH_ID,
        selected_binding_ids=(core_id,),
        authorize_body=True,
    )
    assert built.result == "published"
    assert built.published is not None
    return config, core_id


def test_real_literal_pagination_order_and_occurrence_cap(tmp_path: Path) -> None:
    """Real literal pages preserve order and disclose per-file occurrence caps."""
    with temporary_postgres() as pg_db:
        config, core_id = _public_core_fixture(tmp_path, pg_db)
        full = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="def",
                query_style="literal_captured_text",
                selected_binding_ids=(core_id,),
                limit=100,
            ),
            authorize_body=True,
        )
        assert full.capability_state == CapabilityState.AVAILABLE
        assert full.scope_complete is True
        assert len(full.hits) >= 2
        assert not any(omission.reason_code == "result_page_bounded" for omission in full.omissions)
        full_locators = [hit.locator.identity_key() for hit in full.hits]

        page = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="def",
                query_style="literal_captured_text",
                selected_binding_ids=(core_id,),
                limit=1,
                offset=1,
            ),
            authorize_body=True,
        )
        assert page.capability_state == CapabilityState.PARTIAL
        assert page.scope_complete is False
        assert len(page.hits) == 1
        assert page.hits[0].rank == 1
        assert full.hits[0].rank == 1 and full.hits[1].rank == 2
        assert page.hits[0].locator.identity_key() == full_locators[1]
        assert any(omission.reason_code == "result_page_bounded" for omission in page.omissions)

        capped = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(
                query="def",
                query_style="literal_captured_text",
                selected_binding_ids=(core_id,),
                limit=100,
            ),
            authorize_body=True,
            max_occurrences_per_file=1,
        )
        assert capped.capability_state == CapabilityState.PARTIAL
        assert capped.scope_complete is False
        cap_omissions = [
            omission
            for omission in capped.omissions
            if omission.reason_code == "literal_occurrence_cap_exceeded"
        ]
        assert cap_omissions
        assert any(omission.source_relative_path == "pkg/pipeline.py" for omission in cap_omissions)
        assert capped.hits
        per_file_counts = Counter(hit.locator.source_relative_path for hit in capped.hits)
        assert all(count <= 1 for count in per_file_counts.values())
