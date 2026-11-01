"""Real PostgreSQL lexical scope boundaries over a portable public publication."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.lexical_service import (
    build_graph_lexical_generation,
    query_graph_lexical_generation,
)
from common_lore_index.retrieval.lexical_envelopes import LexicalQueryRequest
from common_lore_index.retrieval.query_contracts import (
    FallbackDisclosure,
    QueryEnvelope,
    QueryHit,
    QueryMode,
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


BOUNDARY_MARKER = "LEXICAL_SCOPE_BOUNDARY_MARKER_20261031"
BOUNDARY_RELATIVE_PATH = "lexical_scope_boundary.py"
PUBLIC_ALIASES = ("core", "companion")
CORE_ID = binding_id_for_alias("core")
COMPANION_ID = binding_id_for_alias("companion")


def _write_boundary_files(working_copy: Path) -> None:
    """Add identical marker files only to the run-owned working copy."""
    body = f"{BOUNDARY_MARKER}\n{BOUNDARY_MARKER} {BOUNDARY_MARKER}\n"
    for directory in ("pkg", "pkg2"):
        target = working_copy / "core" / directory / BOUNDARY_RELATIVE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")


def _request(
    query_style: str,
    *,
    source_path_prefix: str | None = None,
    path_prefixes: tuple[str, ...] = (),
) -> LexicalQueryRequest:
    fallback = None
    if query_style == "literal_captured_text":
        fallback = FallbackDisclosure(
            caller_selected=True,
            from_mode=QueryMode.CURRENT_LITERAL_ENUMERATION,
            to_mode=QueryMode.LITERAL_CAPTURED_TEXT,
            reason_code="scope_boundary_literal",
        )
    return LexicalQueryRequest(
        query=BOUNDARY_MARKER,
        query_style=query_style,
        selected_binding_ids=(CORE_ID,),
        source_path_prefix=source_path_prefix,
        path_prefixes=path_prefixes,
        limit=20,
        offset=0,
        fallback=fallback,
    )


def _query(
    config: OpsConfig,
    query_style: str,
    *,
    source_path_prefix: str | None = None,
    path_prefixes: tuple[str, ...] = (),
    connection_factory: Callable[..., Any] | None = None,
) -> QueryEnvelope:
    kwargs: dict[str, Any] = {}
    if connection_factory is not None:
        kwargs["connection_factory"] = connection_factory
    return query_graph_lexical_generation(
        config,
        MIXED_V1_GRAPH_ID,
        _request(
            query_style,
            source_path_prefix=source_path_prefix,
            path_prefixes=path_prefixes,
        ),
        authorize_body=True,
        **kwargs,
    )


def _order_key(hit: QueryHit) -> tuple[float, str, str, int, int, str]:
    assert hit.score is not None
    assert hit.locator.start_line is not None and hit.locator.end_line is not None
    return (-hit.score, hit.locator.binding_id, hit.locator.source_relative_path,
            hit.locator.start_line, hit.locator.end_line, hit.chunk_id or "")


def _assert_ranked_order(envelope: QueryEnvelope) -> None:
    keys = [_order_key(hit) for hit in envelope.hits]
    assert keys == sorted(keys)
    assert [hit.rank for hit in envelope.hits] == list(range(1, len(envelope.hits) + 1))


def _assert_literal_order(envelope: QueryEnvelope, expected_paths: tuple[str, ...]) -> None:
    paths = tuple(hit.locator.source_relative_path for hit in envelope.hits)
    assert paths == expected_paths
    keys = [_order_key(hit)[1:] for hit in envelope.hits]
    assert keys == sorted(keys)
    assert [hit.rank for hit in envelope.hits] == list(range(1, len(envelope.hits) + 1))
    for start in range(0, len(envelope.hits), 3):
        assert [
            (hit.locator.start_line, hit.locator.end_line)
            for hit in envelope.hits[start : start + 3]
        ] == [(1, 1), (2, 2), (2, 2)]
        assert envelope.hits[start + 1].locator.identity_key() == envelope.hits[start + 2].locator.identity_key()


def _assert_hits_for_scope(envelope: QueryEnvelope, query_style: str, expected_paths: tuple[str, ...]) -> None:
    assert envelope.hits
    assert envelope.scope.backend == "postgresql"
    assert envelope.scope.selected_binding_ids == (CORE_ID,)
    paths = tuple(hit.locator.source_relative_path for hit in envelope.hits)
    assert paths == expected_paths
    if query_style == "literal_captured_text":
        _assert_literal_order(envelope, expected_paths)
    else:
        _assert_ranked_order(envelope)


def _assert_exact_scope_has_no_partial_filename_match(envelope: QueryEnvelope) -> None:
    assert envelope.hits == ()
    if envelope.omissions:
        assert envelope.scope_complete is False


def test_postgres_lexical_scope_prefixes_are_segment_bounded_and_ordered(
    tmp_path: Path,
) -> None:
    """Build/query a real public corpus and prove pkg is not a character prefix of pkg2."""
    with temporary_postgres() as pg_db:
        working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy", generation=1)
        _write_boundary_files(working_copy)
        for directory in ("pkg", "pkg2"):
            assert (
                working_copy / "core" / directory / BOUNDARY_RELATIVE_PATH
            ).read_text(encoding="utf-8") == (
                f"{BOUNDARY_MARKER}\n{BOUNDARY_MARKER} {BOUNDARY_MARKER}\n"
            )
        home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home",
            working_copy,
            host=pg_db.host,
            port=pg_db.port,
            database=pg_db.database,
            user=pg_db.user,
            password=pg_db.password,
            declared_aliases=PUBLIC_ALIASES,
        )
        published = publish_and_load_postgres_corpus(home, psql_command=pg_db.psql_command)
        assert published.backend == "postgresql"
        assert published.accepted_reference.graph_id == MIXED_V1_GRAPH_ID

        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        build = build_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            selected_binding_ids=(CORE_ID, COMPANION_ID),
            authorize_body=True,
        )
        assert build.result == "published"
        assert build.published is not None
        assert build.published.projected_document_count >= 2
        assert build.published.projected_chunk_count >= 2
        assert build.published.aggregate_projected_bytes > 0
        assert set(build.admitted_binding_ids) == {CORE_ID, COMPANION_ID}

        expected_pkg = (f"pkg/{BOUNDARY_RELATIVE_PATH}",)
        expected_pkg2 = (f"pkg2/{BOUNDARY_RELATIVE_PATH}",)
        expected_union = expected_pkg + expected_pkg2
        expected_literal_pkg = expected_pkg * 3
        expected_literal_pkg2 = expected_pkg2 * 3
        expected_literal_union = expected_literal_pkg + expected_literal_pkg2

        for style in ("ranked_terms", "normalized_phrase"):
            unscoped = _query(config, style)
            assert unscoped.provenance["path_prefixes"] == []
            _assert_hits_for_scope(unscoped, style, expected_union)

            pkg = _query(
                config,
                style,
                source_path_prefix="pkg",
                path_prefixes=("pkg/", "pkg"),
            )
            assert pkg.provenance["path_prefixes"] == ["pkg"]
            assert pkg.provenance["path_prefix_match"] == "any"
            assert pkg.scope.source_path_prefix == "pkg"
            _assert_hits_for_scope(pkg, style, expected_pkg)

            pkg2 = _query(
                config,
                style,
                source_path_prefix="pkg2/",
                path_prefixes=("pkg2", "pkg2/"),
            )
            assert pkg2.provenance["path_prefixes"] == ["pkg2"]
            assert pkg2.provenance["path_prefix_match"] == "any"
            assert pkg2.scope.source_path_prefix == "pkg2"
            _assert_hits_for_scope(pkg2, style, expected_pkg2)

            union = _query(
                config,
                style,
                path_prefixes=("pkg/", "pkg2/", "pkg"),
            )
            assert union.provenance["path_prefixes"] == ["pkg", "pkg2"]
            assert union.provenance["path_prefix_match"] == "any"
            assert union.scope.source_path_prefix is None
            _assert_hits_for_scope(union, style, expected_union)

            exact_file = _query(
                config,
                style,
                source_path_prefix=f"pkg/{BOUNDARY_RELATIVE_PATH}",
                path_prefixes=(f"pkg/{BOUNDARY_RELATIVE_PATH}/",),
            )
            assert exact_file.provenance["path_prefixes"] == [
                f"pkg/{BOUNDARY_RELATIVE_PATH}"
            ]
            _assert_hits_for_scope(exact_file, style, expected_pkg)

            partial_filename = _query(
                config,
                style,
                source_path_prefix="pkg/lexical_scope",
                path_prefixes=("pkg/lexical_scope",),
            )
            assert partial_filename.provenance["path_prefixes"] == ["pkg/lexical_scope"]
            _assert_exact_scope_has_no_partial_filename_match(partial_filename)

        literal_pkg = _query(
            config,
            "literal_captured_text",
            source_path_prefix="pkg",
            path_prefixes=("pkg/",),
        )
        assert literal_pkg.provenance["path_prefixes"] == ["pkg"]
        assert literal_pkg.scope.source_path_prefix == "pkg"
        _assert_hits_for_scope(literal_pkg, "literal_captured_text", expected_literal_pkg)

        literal_pkg2 = _query(
            config,
            "literal_captured_text",
            source_path_prefix="pkg2/",
            path_prefixes=("pkg2",),
        )
        assert literal_pkg2.provenance["path_prefixes"] == ["pkg2"]
        assert literal_pkg2.scope.source_path_prefix == "pkg2"
        _assert_hits_for_scope(literal_pkg2, "literal_captured_text", expected_literal_pkg2)

        literal_union = _query(
            config,
            "literal_captured_text",
            path_prefixes=("pkg/", "pkg2/"),
        )
        assert literal_union.provenance["path_prefixes"] == ["pkg", "pkg2"]
        assert literal_union.scope.source_path_prefix is None
        _assert_hits_for_scope(
            literal_union,
            "literal_captured_text",
            expected_literal_union,
        )

        literal_unscoped = _query(config, "literal_captured_text")
        assert literal_unscoped.provenance["path_prefixes"] == []
        _assert_hits_for_scope(
            literal_unscoped,
            "literal_captured_text",
            expected_literal_union,
        )

        literal_partial_filename = _query(
            config,
            "literal_captured_text",
            source_path_prefix="pkg/lexical_scope",
            path_prefixes=("pkg/lexical_scope",),
        )
        assert literal_partial_filename.provenance["path_prefixes"] == ["pkg/lexical_scope"]
        _assert_exact_scope_has_no_partial_filename_match(literal_partial_filename)

        # Percent is a literal filename character, never a SQL LIKE wildcard.
        for style in ("ranked_terms", "normalized_phrase", "literal_captured_text"):
            assert not _query(config, style, source_path_prefix="pkg%").hits

        def no_connection(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("unsafe lexical prefix opened a PostgreSQL connection")

        for bad_prefix in (
            "../pkg",
            "/pkg",
            "./pkg",
            "pkg/../escape",
            "pkg//nested",
            "pkg\\nested",
            "pkg/*",
        ):
            with pytest.raises(ValueError):
                _query(
                    config,
                    "ranked_terms",
                    source_path_prefix=bad_prefix,
                    connection_factory=no_connection,
                )
