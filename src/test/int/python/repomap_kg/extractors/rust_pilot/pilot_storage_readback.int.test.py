"""Fake-protocol -> live Controller -> witnessed PostgreSQL readback (T1)."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import sys

import pytest

from common_lore_index.graph.keys import file_key
from common_lore_index.graph.rust_keys import rust_item_key, rust_source_file_key
from common_lore_index.ops.rust_pilot_publication import (
    publish_rust_pilot_generation,
    rust_publication_generations,
)
from common_lore_index.storage import apply_migrations, default_rdbms_root
from common_lore_index.storage.canonical import (
    query_canonical_edge_records,
    query_canonical_node_records,
)
from common_lore_index.storage.staged_rows import build_staged_rows
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage import staged_ingestion
from common_lore_index.storage.staged_ingestion import IngestionAuthority, new_direct_authority
from common_lore_index.storage.staged_prepared_refresh import run_staged_prepared_refresh
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.rust_pilot_inline_guest import InlineGuestExecutor
from repomap_test_support.rust_pilot_semantic_fixtures import live_pilot


def test_live_witness_staged_rows_publish_and_read_back_without_direct_inserts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with live_pilot(tmp_path, monkeypatch) as live, temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        prepared = build_staged_rows(
            live.witnessed.observations, repository_name="synthetic",
            stage_id="stage-rust-readback", witnessed=live.witnessed,
        )
        assert prepared.row_counts["raw_observations"] == len(live.witnessed.observations)
        prepared.close()

        resolved_stage_ids: list[str] = []
        original_stage_id = staged_ingestion.stage_id_for_authority
        def resolve_stage_once(authority: IngestionAuthority) -> str:
            value = original_stage_id(authority)
            resolved_stage_ids.append(value)
            return value
        monkeypatch.setattr(staged_ingestion, "stage_id_for_authority", resolve_stage_once)

        publish_rust_pilot_generation(
            postgres.psql_args, live.witnessed, repository_name="synthetic",
            root_path="synthetic-root", source_generation="sg1:" + "1" * 64,
            config_generation="cg1:" + "2" * 64,
            legacy_extractor_generation="eg1:" + "3" * 64,
            legacy_canonicalizer_generation="kg1:" + "4" * 64,
        )

        assert len(resolved_stage_ids) == 1

        nodes = query_canonical_node_records(
            postgres.psql_args, root_path="synthetic-root",
        )
        edges = query_canonical_edge_records(
            postgres.psql_args, root_path="synthetic-root",
        )
        node_map = {record.canonical_key: record for record in nodes}
        edge_map = {
            (record.source_key, record.edge_kind, record.target_key): record
            for record in edges
        }

        # Expected legacy values are generated from the unchanged incumbent
        # pipeline in the fixture, never authored 0/1 gold constants.
        for expected_node in live.legacy_result.graph.nodes:
            actual_node = node_map[expected_node.canonical_key]
            assert (
                actual_node.graph_key_version, actual_node.kind, actual_node.display_name, actual_node.metadata,
                actual_node.confidence, actual_node.conflict,
            ) == (
                expected_node.graph_key_version, expected_node.kind, expected_node.display_name,
                dict(expected_node.metadata), expected_node.confidence, expected_node.conflict,
            )
        for expected_edge in live.legacy_result.graph.edges:
            actual_edge = edge_map[(expected_edge.source_key, expected_edge.kind, expected_edge.target_key)]
            assert (
                actual_edge.graph_key_version, actual_edge.identity_metadata, actual_edge.metadata,
                actual_edge.confidence, actual_edge.conflict,
            ) == (
                expected_edge.graph_key_version, dict(expected_edge.identity_metadata),
                dict(expected_edge.metadata), expected_edge.confidence, expected_edge.conflict,
            )

        source_key = rust_source_file_key("src/lib.rs")
        function_observation = next(
            item for item in live.witnessed.observations
            if item.kind == "rust.item" and item.metadata.get("item_kind") == "fn"
        )
        function_key = rust_item_key(
            str(function_observation.metadata["namespace"]),
            function_observation.path,
            str(function_observation.metadata["pointer"]),
        )
        assert node_map[source_key].kind == "rust.source_file"
        assert node_map[function_key].kind == "rust.function"
        assert any(
            edge.source_key == file_key("src/lib.rs")
            and edge.edge_kind == "contains"
            and edge.target_key == source_key
            for edge in edges
        )
        assert any(edge.target_key == function_key for edge in edges)

        generations = rust_publication_generations(
            legacy_extractor_generation="eg1:" + "3" * 64,
            legacy_canonicalizer_generation="kg1:" + "4" * 64,
            lock_sha256=live.witnessed.lock_sha256,
            helper_closure_sha256=live.witnessed.helper_closure_sha256,
        )
        assert postgres.psql_scalar(
            "SELECT source_generation || '|' || config_generation || '|' || "
            "extractor_generation || '|' || canonicalizer_generation "
            "FROM runs WHERE id = (SELECT max(id) FROM runs)"
        ) == "|".join((
            "sg1:" + "1" * 64, "cg1:" + "2" * 64, *generations,
        ))
        assert postgres.psql_scalar(
            "SELECT COALESCE(string_agg(ordinal::text, ',' ORDER BY ordinal), '') "
            "FROM raw_observations WHERE run_id = (SELECT max(id) FROM runs)"
        ) == ",".join(str(index) for index in range(len(live.witnessed.observations)))

        # A legitimate earlier callback can close the run. The final witness
        # fence must observe that change and preserve the published graph.
        authority = new_direct_authority(
            source_generation="sg1:" + "5" * 64, config_generation="cg1:" + "2" * 64,
            extractor_generation=generations[0], canonicalizer_generation=generations[1],
        )
        authority = replace(authority, before_publication=live.controller.close).validate()
        with pytest.raises(StorageSchemaError, match="during publication callback"):
            run_staged_prepared_refresh(
                postgres.psql_args, live.witnessed, repository_name="synthetic",
                root_path="synthetic-root", authority=authority,
            )
        assert query_canonical_node_records(postgres.psql_args, root_path="synthetic-root") == nodes
        assert query_canonical_edge_records(postgres.psql_args, root_path="synthetic-root") == edges


def test_inline_guest_witnessed_rows_retain_semantics_in_real_postgres(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    path_before = tuple(sys.path)
    native_before = {name: sys.modules.get(name) for name in ("tree_sitter", "tree_sitter_rust")}
    with live_pilot(tmp_path, monkeypatch, guest_executor=InlineGuestExecutor()) as live:
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args,
                             psql_command=postgres.psql_command)
            prepared = build_staged_rows(
                live.witnessed.observations, repository_name="synthetic",
                stage_id="stage-rust-inline", witnessed=live.witnessed,
            )
            try:
                assert prepared.row_counts["raw_observations"] == len(live.witnessed.observations)
            finally:
                prepared.close()
            generations = rust_publication_generations(
                legacy_extractor_generation="eg1:" + "3" * 64,
                legacy_canonicalizer_generation="kg1:" + "4" * 64,
                lock_sha256=live.witnessed.lock_sha256,
                helper_closure_sha256=live.witnessed.helper_closure_sha256,
            )
            publish_rust_pilot_generation(
                postgres.psql_args, live.witnessed, repository_name="synthetic",
                root_path="synthetic-root", source_generation="sg1:" + "5" * 64,
                config_generation="cg1:" + "6" * 64,
                legacy_extractor_generation="eg1:" + "3" * 64,
                legacy_canonicalizer_generation="kg1:" + "4" * 64,
            )
            nodes = query_canonical_node_records(postgres.psql_args, root_path="synthetic-root")
            edges = query_canonical_edge_records(postgres.psql_args, root_path="synthetic-root")
            published = {
                row.canonical_key: (row.kind, row.display_name, dict(row.metadata))
                for row in nodes
            }
            legacy = {
                row.canonical_key: (row.kind, row.display_name, dict(row.metadata))
                for row in live.legacy_result.graph.nodes
            }
            assert all(published[key] == value for key, value in legacy.items())
            assert {
                (row.source_key, row.kind, row.target_key)
                for row in live.legacy_result.graph.edges
            } <= {(row.source_key, row.edge_kind, row.target_key) for row in edges}
            assert any(row.kind == "rust.function" for row in nodes)
            assert postgres.psql_scalar(
                "SELECT extractor_generation || '|' || canonicalizer_generation FROM runs "
                "WHERE id = (SELECT max(id) FROM runs)"
            ) == "|".join(generations)
    assert tuple(sys.path) == path_before
    assert {name: sys.modules.get(name) for name in native_before} == native_before
