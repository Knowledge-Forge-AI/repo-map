"""Unit tests for deterministic chunking, long-line UTF-8 splitting, and framed digests (S1)."""

from __future__ import annotations

from common_lore_index.retrieval.projection_chunks import (
    build_file_chunks,
    frame_digest,
)


def test_empty_file_produces_explicit_complete_empty_chunk_record() -> None:
    """An empty file produces one explicit empty-file chunk record."""
    chunks = build_file_chunks(
        file_projection_id="projfile1:" + "1" * 64,
        binding_id="bind1:core",
        source_relative_path="pkg/__init__.py",
        normalized_text="",
        artifact_privacy="raw_source",
        policy_digest="sha256:" + "2" * 64,
        publication_bundle_id="bundle1:" + "3" * 64,
    )
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.is_empty_file_record is True
    assert chunk.chunk_index == 0
    assert chunk.start_line == 0 and chunk.end_line == 0
    assert chunk.normalized_byte_start == 0 and chunk.normalized_byte_end == 0
    assert chunk.byte_length == 0 and chunk.line_count == 0
    assert chunk.content_text == ""
    assert chunk.chunk_id.startswith("projchunk1:")


def test_contiguous_gapless_non_overlapping_chunk_coverage() -> None:
    """Multi-chunk files cover the exact normalized byte prefix without gaps or overlap."""
    lines = [f"line-{idx:04d}: payload value {idx}\n" for idx in range(1, 185)]
    text = "".join(lines)
    chunks = build_file_chunks(
        file_projection_id="projfile1:" + "1" * 64,
        binding_id="bind1:core",
        source_relative_path="pkg/module.py",
        normalized_text=text,
        artifact_privacy="raw_source",
        policy_digest="sha256:" + "2" * 64,
        publication_bundle_id="bundle1:" + "3" * 64,
        max_chunk_lines=80,
        max_chunk_bytes=8192,
    )
    assert len(chunks) == 3
    assert [c.line_count for c in chunks] == [80, 80, 24]
    assert chunks[0].start_line == 1 and chunks[0].end_line == 80
    assert chunks[1].start_line == 81 and chunks[1].end_line == 160
    assert chunks[2].start_line == 161 and chunks[2].end_line == 184

    cursor = 0
    for index, chunk in enumerate(chunks):
        assert chunk.chunk_index == index
        assert chunk.normalized_byte_start == cursor
        assert chunk.normalized_byte_end == cursor + chunk.byte_length
        cursor = chunk.normalized_byte_end
    assert cursor == len(text.encode("utf-8"))
    assert "".join(c.content_text for c in chunks) == text


def test_single_long_line_splits_only_at_valid_utf8_boundaries() -> None:
    """A single line exceeding max_chunk_bytes splits cleanly at UTF-8 codepoint boundaries."""
    long_line = ("café-🚀-" * 300) + "\n"
    chunks = build_file_chunks(
        file_projection_id="projfile1:" + "a" * 64,
        binding_id="bind1:companion",
        source_relative_path="docs/unicode.md",
        normalized_text=long_line,
        artifact_privacy="raw_source",
        policy_digest="sha256:" + "b" * 64,
        publication_bundle_id="bundle1:" + "c" * 64,
        max_chunk_lines=80,
        max_chunk_bytes=512,
    )
    assert len(chunks) >= 5
    assert chunks[0].line_split_continuation is False
    assert all(c.line_split_continuation is True for c in chunks[1:])
    assert all(c.start_line == 1 and c.end_line == 1 for c in chunks)
    assert all(c.byte_length <= 512 for c in chunks)
    assert "".join(c.content_text for c in chunks) == long_line


def test_framed_digest_prevents_boundary_concatenation_collision() -> None:
    """Length-prefixed framing distinguishes ('ab', 'c') from ('a', 'bc')."""
    d1 = frame_digest("sha256", ("ab", "c"))
    d2 = frame_digest("sha256", ("a", "bc"))
    assert d1 != d2


def test_chunk_line_splitting_uses_lf_only_not_unicode_or_control_separators() -> None:
    """VT, FF, NEL, U+2028, and U+2029 remain on the same line number during chunking."""
    text = "first\vpart\fstill_first\u2028same_line\nsecond_line\n"
    chunks = build_file_chunks(
        file_projection_id="projfile1:" + "1" * 64,
        binding_id="bind1:core",
        source_relative_path="pkg/control.py",
        normalized_text=text,
        artifact_privacy="raw_source",
        policy_digest="sha256:" + "2" * 64,
        publication_bundle_id="bundle1:" + "3" * 64,
    )
    assert len(chunks) == 1
    assert chunks[0].start_line == 1 and chunks[0].end_line == 2
    assert chunks[0].line_count == 2
