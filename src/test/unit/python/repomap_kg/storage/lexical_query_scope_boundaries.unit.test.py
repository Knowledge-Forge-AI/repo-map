"""Unit contracts for safe CLOE lexical scope prefixes and deterministic output SQL."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.graph.multi_source import SourceKind
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig
from common_lore_index.retrieval.lexical_envelopes import (
    LexicalQueryRequest,
    resolve_lexical_query_scope,
)
from common_lore_index.retrieval.lexical_policy import (
    LexicalGenerationPolicy, build_lexical_generation_policy,
)
from common_lore_index.storage.lexical_fence_sql import LEXICAL_FENCE_CTE_SQL
from common_lore_index.storage.lexical_literal_sql import LITERAL_CAPTURED_TEXT_QUERY_SQL
from common_lore_index.storage.lexical_query_sql import (
    NORMALIZED_PHRASE_QUERY_SQL,
    RANKED_TERMS_QUERY_SQL,
)
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
)


def _request(**overrides: Any) -> LexicalQueryRequest:
    """Inject runtime-invalid field types deliberately to exercise validation."""
    return replace(LexicalQueryRequest(
        query="LEXICAL_SCOPE_BOUNDARY_MARKER_20261031",
        selected_binding_ids=(binding_id_for_alias("core"),), limit=20,
    ), **overrides)


def _sample_graph_and_policy(tmp_path: Path) -> tuple[OpsGraphConfig, LexicalGenerationPolicy]:
    core = OpsGraphSourceBindingConfig(
        1,
        binding_id_for_alias("core"),
        "src1:" + ("a" * 64),
        "core",
        1,
        SourceKind.FOLDER,
        str(tmp_path),
        str(tmp_path),
        "core",
        "core",
        "public-dev",
        "full-authorized",
        "default",
        (),
        (),
        "sel1:" + ("a" * 64),
        "pinned",
        True,
        "primary",
    )
    companion = OpsGraphSourceBindingConfig(
        1,
        binding_id_for_alias("companion"),
        "src1:" + ("b" * 64),
        "companion",
        1,
        SourceKind.FOLDER,
        str(tmp_path),
        str(tmp_path),
        "companion",
        "companion",
        "public-dev",
        "full-authorized",
        "default",
        (),
        (),
        "sel1:" + ("b" * 64),
        "pinned",
        True,
        "companion",
    )
    graph = OpsGraphConfig(
        id=MIXED_V1_GRAPH_ID,
        name=MIXED_V1_GRAPH_ID,
        root_path=str(tmp_path),
        root_path_expanded=str(tmp_path),
        repository_name=MIXED_V1_GRAPH_ID,
        privacy="public-dev",
        enabled=True,
        mcp_visible=True,
        extractor_profile="default",
        refresh_policy="manual",
        database="repomap_mixed_v1",
        source_bindings=(core, companion),
        explicit_source_bindings=True,
    )
    return graph, build_lexical_generation_policy(graph)


def _compact(sql: str) -> str:
    return " ".join(sql.split())


def _assert_segment_fence(sql: str, column: str) -> None:
    compact = _compact(sql)
    raw_prefix = f"left({column}, length(p.prefix)) = p.prefix"
    exact_or_descendant = (
        f"{column} = p.prefix OR "
        f"left({column}, length(p.prefix) + 1) = p.prefix || '/'"
    )
    assert raw_prefix not in compact
    assert exact_or_descendant in compact


def _assert_ordered_hit_aggregate(sql: str, order_by: str) -> None:
    compact = _compact(sql)
    expected = f"json_agg(row_to_json(eh) ORDER BY {order_by})"
    assert expected in compact


def test_request_normalizes_trailing_slashes_and_deduplicates_segments() -> None:
    request = _request(
        source_path_prefix="  pkg/ ",
        path_prefixes=("pkg", "pkg/", "pkg/sub/", "pkg/sub"),
    )

    validated = request.validate()

    assert validated.effective_path_prefixes() == ("pkg", "pkg/sub")


def test_request_deduplication_preserves_first_seen_union_order() -> None:
    request = _request(
        source_path_prefix="pkg2/",
        path_prefixes=("pkg", "pkg2", "pkg/", "pkg2/"),
    )

    assert request.validate().effective_path_prefixes() == ("pkg2", "pkg")


def test_request_rejects_one_bad_prefix_even_with_a_safe_union_member() -> None:
    request = _request(path_prefixes=("pkg", "../escape"))

    with pytest.raises(ValueError):
        request.validate()


def test_request_without_a_prefix_remains_unscoped() -> None:
    assert _request().validate().effective_path_prefixes() == ()


def test_request_prefix_order_is_independent_of_duplicate_slash_spelling() -> None:
    request = _request(
        path_prefixes=("pkg/sub/", "pkg", "pkg/sub", "pkg/"),
    )

    assert request.validate().effective_path_prefixes() == ("pkg/sub", "pkg")


@pytest.mark.parametrize("prefix", ("pkg", "pkg/", "pkg/sub", "README.md", "pkg_2", "pkg%"))
def test_request_accepts_safe_relative_segment_prefixes(prefix: str) -> None:
    request = _request(source_path_prefix=prefix)

    assert request.validate().effective_path_prefixes()[0] == prefix.rstrip("/")


@pytest.mark.parametrize(
    ("field", "bad_prefix"),
    [
        ("source_path_prefix", ""),
        ("path_prefixes", ""),
        ("source_path_prefix", " "),
        ("path_prefixes", " "),
        ("source_path_prefix", "."),
        ("path_prefixes", "."),
        ("source_path_prefix", "./pkg"),
        ("path_prefixes", "./pkg"),
        ("source_path_prefix", "../pkg"),
        ("path_prefixes", "../pkg"),
        ("source_path_prefix", "pkg/../escape"),
        ("path_prefixes", "pkg/../escape"),
        ("source_path_prefix", "pkg/./nested"),
        ("path_prefixes", "pkg/./nested"),
        ("source_path_prefix", "pkg//nested"),
        ("path_prefixes", "pkg//nested"),
        ("source_path_prefix", "/pkg"),
        ("path_prefixes", "/pkg"),
        ("source_path_prefix", "~home"),
        ("path_prefixes", "~home"),
        ("source_path_prefix", "C:/pkg"),
        ("path_prefixes", "C:/pkg"),
        ("source_path_prefix", "pkg\\nested"),
        ("path_prefixes", "pkg\\nested"),
        ("source_path_prefix", "pkg\x00nested"),
        ("path_prefixes", "pkg\x00nested"),
        ("source_path_prefix", "pkg/*"),
        ("path_prefixes", "pkg/*"),
        ("source_path_prefix", "pkg/*.py"),
        ("path_prefixes", "pkg/*.py"),
        ("source_path_prefix", "pkg?"),
        ("path_prefixes", "pkg?"),
    ],
)
def test_request_rejects_unsafe_or_ambiguous_prefixes(field: str, bad_prefix: str) -> None:
    values: dict[str, object]
    if field == "source_path_prefix":
        values = {field: bad_prefix}
    else:
        values = {field: (bad_prefix,)}

    with pytest.raises(ValueError):
        _request(**values).validate()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("limit", 0),
        ("limit", 101),
        ("limit", 500),
        ("limit", True),
        ("limit", "20"),
        ("offset", -1),
        ("offset", 1001),
        ("offset", 10000),
        ("offset", True),
        ("offset", "0"),
    ],
)
def test_request_enforces_library_paging_contract(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        _request(**{field: value}).validate()


def test_request_accepts_only_spec_paging_edges() -> None:
    assert _request(limit=1, offset=0).validate().limit == 1
    assert _request(limit=100, offset=1000).validate().offset == 1000


def test_scope_carries_canonical_single_prefix_and_union_provenance(tmp_path: Path) -> None:
    _, policy = _sample_graph_and_policy(tmp_path)
    single = _request(source_path_prefix="pkg/", path_prefixes=("pkg",))
    single_resolution = resolve_lexical_query_scope(
        graph_id=MIXED_V1_GRAPH_ID,
        lexical_policy=policy,
        request=single,
    )

    assert single_resolution.scope.source_path_prefix == "pkg"

    union = _request(path_prefixes=("pkg/", "pkg2", "pkg/"))
    union_resolution = resolve_lexical_query_scope(
        graph_id=MIXED_V1_GRAPH_ID,
        lexical_policy=policy,
        request=union,
    )

    assert union_resolution.scope.source_path_prefix is None
    assert union.effective_path_prefixes() == ("pkg", "pkg2")


def test_ranked_and_phrase_sql_use_segment_fences_and_full_hit_order() -> None:
    ranked_order = (
        'eh.score DESC, eh.binding_id COLLATE "C" ASC, '
        'eh.source_relative_path COLLATE "C" ASC, eh.start_line ASC, '
        'eh.end_line ASC, eh.chunk_id COLLATE "C" ASC'
    )
    for sql in (RANKED_TERMS_QUERY_SQL, NORMALIZED_PHRASE_QUERY_SQL):
        _assert_segment_fence(sql, "ch.source_relative_path")
        _assert_ordered_hit_aggregate(sql, ranked_order)


def test_literal_and_omission_sql_use_segment_fences_and_full_hit_order() -> None:
    literal_order = (
        'eh.binding_id COLLATE "C" ASC, '
        'eh.source_relative_path COLLATE "C" ASC, eh.start_line ASC, '
        "eh.end_line ASC, eh.match_pos_1 ASC, "
        'COALESCE(eh.chunk_id, \'\') COLLATE "C" ASC'
    )

    _assert_segment_fence(LITERAL_CAPTURED_TEXT_QUERY_SQL, "doc.source_relative_path")
    _assert_segment_fence(LEXICAL_FENCE_CTE_SQL, "om.source_relative_path")
    _assert_ordered_hit_aggregate(LITERAL_CAPTURED_TEXT_QUERY_SQL, literal_order)


def test_literal_aggregate_order_includes_occurrence_position_before_chunk_tiebreak() -> None:
    compact = _compact(LITERAL_CAPTURED_TEXT_QUERY_SQL)
    position = compact.index("json_agg(row_to_json(eh)")
    order_end = compact.index(") FROM enriched_hits", position)
    aggregate = compact[position:order_end]

    assert "eh.start_line ASC, eh.end_line ASC, eh.match_pos_1 ASC" in aggregate
    assert "COALESCE(eh.chunk_id, '') COLLATE \"C\" ASC" in aggregate


def test_all_lexical_sql_builders_retain_one_shared_fence_contract() -> None:
    sql_builders = (
        RANKED_TERMS_QUERY_SQL,
        NORMALIZED_PHRASE_QUERY_SQL,
        LITERAL_CAPTURED_TEXT_QUERY_SQL,
    )

    for sql in sql_builders:
        compact = _compact(sql)
        assert "cardinality(%(path_prefixes)s::text[]) = 0" in compact
        assert "FROM unnest(%(path_prefixes)s::text[]) AS p(prefix)" in compact
        assert "left(ch.source_relative_path, length(p.prefix)) = p.prefix" not in compact
        assert "left(doc.source_relative_path, length(p.prefix)) = p.prefix" not in compact


def test_sql_fences_preserve_an_unscoped_empty_prefix_array() -> None:
    for sql in (
        RANKED_TERMS_QUERY_SQL,
        NORMALIZED_PHRASE_QUERY_SQL,
        LITERAL_CAPTURED_TEXT_QUERY_SQL,
        LEXICAL_FENCE_CTE_SQL,
    ):
        compact = _compact(sql)
        assert "cardinality(%(path_prefixes)s::text[]) = 0" in compact
        assert "OR EXISTS ( SELECT 1 FROM unnest(%(path_prefixes)s::text[])" in compact
