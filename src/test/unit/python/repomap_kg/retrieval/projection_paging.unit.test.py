"""Public paging behavior and bounded retention for dense high-offset queries."""

from __future__ import annotations

from pathlib import Path

from dataclasses import replace
import tracemalloc

from common_lore_index.retrieval.projection_build import build_captured_text_projection
from common_lore_index.retrieval.projection_query import CapturedTextQueryRequest, query_captured_text
from repomap_test_support.retrieval_evaluation_query_fixture import build_fixture_projection


def test_dense_high_offset_does_not_retain_the_skipped_match_population(tmp_path: Path) -> None:
    inputs, policy = build_fixture_projection(extra_tail=b"a" * 262144, spool_dir=tmp_path / "spool")
    projection = build_captured_text_projection(
        inputs, replace(policy, max_projected_file_bytes=1048576)
    )
    total = sum(chunk.content_text.count("a") for file in projection.projected_files
                if file.source_relative_path == "pkg/alpha.py" for chunk in file.chunks)
    already_tracing = tracemalloc.is_tracing()
    tracemalloc.start()
    tracemalloc.reset_peak()
    baseline, _ = tracemalloc.get_traced_memory()
    try:
        result = query_captured_text(
            projection, CapturedTextQueryRequest(
                query="a", source_path_prefix="pkg/alpha.py", offset=10000, limit=1
            )
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        if not already_tracing:
            tracemalloc.stop()
    assert len(result.hits) == 1
    assert result.hits[0].locator.source_relative_path == "pkg/alpha.py"
    assert result.provenance["total_matches_before_paging"] == total
    assert peak - baseline < 1024 * 1024


def test_offset_crosses_files_in_canonical_order_and_preserves_total_count(tmp_path: Path) -> None:
    inputs, policy = build_fixture_projection(spool_dir=tmp_path / "spool")
    projection = build_captured_text_projection(inputs, policy)
    first = query_captured_text(projection, CapturedTextQueryRequest(query="line", limit=1))
    last = query_captured_text(projection, CapturedTextQueryRequest(query="line", offset=99, limit=1))
    assert first.hits[0].locator.source_relative_path == "pkg/alpha.py"
    assert last.hits[0].locator.source_relative_path == "pkg/beta.py"
    assert last.hits[0].locator.start_line == 2
    assert last.provenance["total_matches_before_paging"] == 100
