"""Real current-reader matching and pagination over publisher-backed fixtures."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.retrieval.query_contracts import QueryMode, QueryScope
from common_lore_index.server.ops import investigation_stores
from repomap_test_support.retrieval_evaluation_fixture import binding_id_for_alias
from repomap_test_support.w5_matching_fixture import MatchingDatabases, MatchingRow, matching_databases
from repomap_test_support.w5_semantic_support import make_w5_calibration_task
from retrieval_evaluation_graph import execute_graph_baseline_task
from retrieval_evaluation_graph import _execute_navigation_or_locations_mode
from retrieval_evaluation_correspondence_observation_records import FencedObservationResult
from retrieval_evaluation_observation_contracts import CurrentObservationReadError
from retrieval_evaluation_scope import source_path_matches_prefix


def _paths(result: FencedObservationResult) -> list[str]:
    return [row["metadata"]["source_relative_path"] for row in result.rows]


def _with_matching_field(row: MatchingRow, field: str, value: str) -> MatchingRow:
    if field == "text":
        return replace(row, text=value)
    if field == "kind":
        return replace(row, kind=value)
    if field == "source_id":
        return replace(row, source_id=value)
    if field == "path":
        return replace(row, path=value)
    raise AssertionError(f"unsupported matching fixture field: {field}")


def _seed_published_graph_traversal_rows(databases: MatchingDatabases) -> None:
    """Add duplicate accepted rows so graph pages span six and eight observations."""
    databases.set_rows([
        MatchingRow("pkg/pipeline.py", "module.nix", path="core/pkg/pipeline.py"),
        MatchingRow("pkg/router.py", "module.nix", path="core/pkg/router.py"),
        MatchingRow("pkg/router.py", "module.nix", path="core/pkg/router.py"),
    ])

    sqlite = databases.sqlite
    sqlite_prototype = sqlite.execute(
        "SELECT schema_version, kind, source_id, payload_json FROM raw_observations "
        "WHERE run_id = ? AND ordinal = ?",
        (databases.sqlite_run, databases.sqlite_rows[0][0]),
    ).fetchone()
    assert sqlite_prototype is not None
    sqlite_next = int(sqlite.execute(
        "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM raw_observations WHERE run_id = ?",
        (databases.sqlite_run,),
    ).fetchone()[0])

    postgres = databases.postgres
    postgres_prototype = postgres.execute(
        "SELECT repository_id, schema_version, kind, source_id, payload_json::text "
        "FROM public.raw_observations WHERE run_id = %s AND ordinal = %s",
        (databases.postgres_run, databases.postgres_rows[0][0]),
    ).fetchone()
    assert postgres_prototype is not None
    postgres_next = int(postgres.execute(
        "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM public.raw_observations WHERE run_id = %s",
        (databases.postgres_run,),
    ).fetchone()[0])

    for path, relative_path, duplicate_count in (
        ("core/pkg/pipeline.py", "pkg/pipeline.py", 5),
        ("core/pkg/router.py", "pkg/router.py", 6),
    ):
        for _ in range(duplicate_count):
            sqlite_payload = json.loads(str(sqlite_prototype[3]))
            sqlite_metadata = dict(sqlite_payload["metadata"])
            sqlite_metadata["source_relative_path"] = relative_path
            sqlite_payload["metadata"] = sqlite_metadata
            sqlite_payload["text"] = "module.nix"
            sqlite_encoded = json.dumps(sqlite_payload, ensure_ascii=False, separators=(",", ":"))
            sqlite.execute(
                "INSERT INTO raw_observations "
                "(run_id, ordinal, schema_version, kind, source_id, path, payload_json, payload_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    databases.sqlite_run, sqlite_next, int(sqlite_prototype[0]),
                    str(sqlite_prototype[1]), str(sqlite_prototype[2]), path, sqlite_encoded,
                    hashlib.sha256(sqlite_encoded.encode("utf-8")).hexdigest(),
                ),
            )
            sqlite_next += 1

            postgres_payload = json.loads(str(postgres_prototype[4]))
            postgres_metadata = dict(postgres_payload["metadata"])
            postgres_metadata["source_relative_path"] = relative_path
            postgres_payload["metadata"] = postgres_metadata
            postgres_payload["text"] = "module.nix"
            postgres_encoded = json.dumps(postgres_payload, ensure_ascii=False, separators=(",", ":"))
            postgres.execute(
                "INSERT INTO public.raw_observations "
                "(repository_id, run_id, ordinal, schema_version, kind, source_id, path, "
                "payload_json, payload_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
                (
                    int(postgres_prototype[0]), databases.postgres_run, postgres_next,
                    int(postgres_prototype[1]), str(postgres_prototype[2]),
                    str(postgres_prototype[3]), path, postgres_encoded,
                    hashlib.sha256(postgres_encoded.encode("utf-8")).hexdigest(),
                ),
            )
            postgres_next += 1
    sqlite.commit()
    postgres.commit()


def test_sqlite_and_postgres_use_one_literal_ascii_fold_before_pagination(tmp_path: Path) -> None:
    with matching_databases(tmp_path) as databases:
        for field in ("text", "kind", "source_id", "path"):
            for query, false_positive, positive in (
                ("W5MATCH_ÄRGER", "w5match_ärger", "w5match_Ärger"),
                ("W5MATCH_IOTA", "w5match_İOTA", "w5match_iota"),
                ("W5MATCH_SS", "w5match_ß", "w5match_ss"),
                ("W5MATCH_café", "w5match_cafe\u0301", "w5match_café"),
                ("W5MATCH_%_", "w5match_XY", "w5match_%_"),
                ("W5MATCH_\\literal", "w5match_literal", "w5match_\\literal"),
                ("W5MATCH_'); SELECT", "w5match_safe", "w5match_'); select"),
            ):
                originals = [
                    MatchingRow("scope/early.py", "no-match"),
                    MatchingRow("scope/answer.py", "no-match"),
                    MatchingRow("scope/later.py", "no-match"),
                ]
                rows = [_with_matching_field(row, field, value) for row, value in zip(
                    originals, (false_positive, positive, positive), strict=True,
                )]
                databases.set_rows(rows)
                # Payload matching searches PostgreSQL's JSONB text, including
                # JSON string escaping, rather than an unescaped body value.
                needle = query.replace("\\", "\\\\") if field == "text" else query
                for backend in ("sqlite", "postgresql"):
                    first = databases.read(backend, needle, limit=1, source_path_prefix="scope/")
                    assert _paths(first) == ["scope/answer.py"], (backend, field, query)
                    assert first.has_more and not first.scope_complete
                    second = databases.read(backend, needle, limit=1, offset=1, source_path_prefix="scope/")
                    assert _paths(second) == ["scope/later.py"], (backend, field, query)
                    assert not second.has_more and second.scope_complete
                    assert first.database_wire_bytes is None


def test_directory_prefix_and_literal_wildcards_do_not_widen_scope(tmp_path: Path) -> None:
    with matching_databases(tmp_path) as databases:
        token = "W5_DIRECTORY_BOUNDARY"
        databases.set_rows([
            MatchingRow("shared", token), MatchingRow("shared/answer.py", token),
            MatchingRow("shared2/wrong.py", token),
        ])
        for backend in ("sqlite", "postgresql"):
            assert _paths(databases.read(backend, token, source_path_prefix="shared/")) == ["shared/answer.py"]
            assert _paths(databases.read(backend, token, source_path_prefix="shared")) == ["shared", "shared/answer.py"]
        databases.set_rows([
            MatchingRow("sharedXY/wrong.py", token), MatchingRow("shared%_/answer.py", token),
            MatchingRow("shared%_/later.py", token),
        ])
        for backend in ("sqlite", "postgresql"):
            page = databases.read(backend, token, source_path_prefix="shared%_/", limit=1)
            assert _paths(page) == ["shared%_/answer.py"] and page.has_more


def test_literal_matching_controls_late_metadata_validation_on_both_backends(tmp_path: Path) -> None:
    with matching_databases(tmp_path) as databases:
        query = "W5MATCH_ÄRGER"
        databases.set_rows([
            MatchingRow("scope/answer.py", "w5match_Ärger"),
            MatchingRow("scope/not-a-match.py", "w5match_ärger", invalid_metadata=True),
            MatchingRow("scope/later.py", "w5match_Ärger"),
        ])
        for backend in ("sqlite", "postgresql"):
            assert _paths(databases.read(backend, query, source_path_prefix="scope/", limit=1)) == ["scope/answer.py"]
        databases.set_rows([
            MatchingRow("scope/answer.py", "w5match_Ärger"),
            MatchingRow("scope/not-a-match.py", "w5match_ärger", invalid_metadata=True),
            MatchingRow("outside/invalid.py", "w5match_Ärger", invalid_metadata=True),
        ])
        for backend in ("sqlite", "postgresql"):
            with pytest.raises(CurrentObservationReadError, match="malformed_observation_metadata"):
                databases.read(backend, query, source_path_prefix="scope/", limit=1)


def test_graph_envelopes_preserve_real_current_reader_page_omissions(tmp_path: Path) -> None:
    with matching_databases(tmp_path) as databases:
        token = "W5_GRAPH_PAGE_OMISSION"
        databases.set_rows([
            MatchingRow("scope/first.py", token), MatchingRow("scope/second.py", token),
            MatchingRow("outside/third.py", token),
        ])
        task = replace(
            make_w5_calibration_task(graph_id="mixed-v1", selected_bindings=("core",)),
            requested_mode="current_literal_enumeration", source_path_prefix="scope/",
            permitted_query_plan={"query": token, "limit": 1},
        ).validate()
        for home in (databases.sqlite_home, databases.postgres_home):
            state, envelope, _, _ = execute_graph_baseline_task(
                task, home, psql_command=databases.psql_command,
            )
            assert state.value == "completed"
            assert envelope.capability_state.value == "partial"
            assert not envelope.scope_complete
            assert len(envelope.hits) == 1
            assert sum(o.reason_code == "observation_page_limit" for o in envelope.omissions) == 1


def test_published_graph_navigation_keeps_shared_directory_scope_literal(tmp_path: Path) -> None:
    with matching_databases(tmp_path) as databases:
        config = load_graph_registry_config_home(databases.sqlite_home)
        store = investigation_stores(config).investigation_store()
        task = replace(
            make_w5_calibration_task(graph_id="mixed-v1", selected_bindings=("core",)),
            requested_mode="ranked_discovery", intended_match_surface="canonical_graph",
            source_path_prefix="shared",
            permitted_query_plan={"query": "status_codes", "graph_query": "status_codes", "limit": 10},
        ).validate()
        binding_id = binding_id_for_alias("core", task.graph_id)
        scope = QueryScope(
            graph_id=task.graph_id, backend="sqlite", selected_binding_ids=(binding_id,),
            source_path_prefix=task.source_path_prefix,
        ).validate()
        state, envelope, _elapsed, _accounting = _execute_navigation_or_locations_mode(
            store, task, scope, QueryMode.RANKED_DISCOVERY,
        )
        paths = [hit.locator.source_relative_path for hit in envelope.hits]
        assert state.value == "completed"
        assert "shared/status_codes.py" in paths
        assert all(source_path_matches_prefix(path, "shared") and not path.startswith("shared2/") for path in paths)


def test_published_graph_traversal_discloses_final_page_truncation(tmp_path: Path) -> None:
    with matching_databases(tmp_path) as databases:
        _seed_published_graph_traversal_rows(databases)
        task = replace(
            make_w5_calibration_task(graph_id="mixed-v1", selected_bindings=("core", "companion")),
            requested_mode="graph_investigation", intended_match_surface="canonical_graph",
            permitted_query_plan={
                "query": "module.nix", "graph_query": "module.nix",
                "seed_node": "file:core/pkg/pipeline.py", "limit": 10,
            },
        ).validate()
        for home in (databases.sqlite_home, databases.postgres_home):
            state, envelope, _elapsed, _accounting = execute_graph_baseline_task(
                task, home, psql_command=databases.psql_command,
            )
            assert state.value == "completed"
            assert len(envelope.hits) == 10
            assert [hit.locator.source_relative_path for hit in envelope.hits] == (
                ["pkg/pipeline.py"] * 6 + ["pkg/router.py"] * 4
            )
            assert envelope.capability_state.value == "partial"
            assert not envelope.scope_complete
            assert sum(o.reason_code == "graph_result_limit" for o in envelope.omissions) == 1
