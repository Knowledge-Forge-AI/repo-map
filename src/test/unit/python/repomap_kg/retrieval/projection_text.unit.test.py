"""Unit tests for strict UTF-8 decoding, NUL rejection, CRLF normalization, and prefix bounding (S1)."""

from __future__ import annotations

from common_lore_index.retrieval.projection_policy import ExclusionReason
from common_lore_index.retrieval.projection_text import (
    REPRESENTATION_VERSION,
    normalize_and_bound_text,
)


def test_strict_utf8_and_nul_rejection() -> None:
    """Invalid UTF-8 sequences and NUL bytes anywhere (byte 0 or after 160 chars) are rejected."""
    for nul_payload in (b"\x00leading nul\n", b"valid line\n\x00hidden after nul\n"):
        res, reason = normalize_and_bound_text(nul_payload)
        assert res is None
        assert reason == ExclusionReason.NUL_BYTE_REJECTED

    res, reason = normalize_and_bound_text(b"valid start\xff\xfeinvalid utf8\n")
    assert res is None
    assert reason == ExclusionReason.INVALID_UTF8


def test_lf_only_line_counting_ignores_vertical_tab_form_feed_and_unicode_separators() -> None:
    """Under lf-utf8-v1, VT, FF, NEL, U+2028, and U+2029 do not split lines."""
    raw = "line1\vstill_line1\fstill_line1\u0085\u2028\u2029\nline2\n".encode("utf-8")
    res, reason = normalize_and_bound_text(raw)
    assert reason is None and res is not None
    assert res.raw_line_count == 2
    assert res.normalized_line_count == 2
    assert res.projected_line_count == 2


def test_crlf_and_cr_normalization_preserves_raw_and_normalized_extents() -> None:
    """CRLF and CR normalize to LF under lf-utf8-v1 while preserving raw vs normalized extents."""
    raw = b"alpha\r\nbeta\rgamma\n"
    res, reason = normalize_and_bound_text(raw)
    assert reason is None and res is not None
    assert res.representation_version == REPRESENTATION_VERSION
    assert res.normalized_text == "alpha\nbeta\ngamma\n"
    assert res.had_crlf_or_cr is True
    assert res.raw_byte_length == len(raw)
    assert res.normalized_byte_length == len(b"alpha\nbeta\ngamma\n")
    assert res.projected_byte_length == res.normalized_byte_length
    assert res.raw_line_count == 3
    assert res.normalized_line_count == 3
    assert res.projected_line_count == 3
    assert res.truncated is False
    assert res.representation_digest.startswith("sha256:")


def test_utf8_multibyte_safe_prefix_truncation() -> None:
    """Prefix truncation never splits a multi-byte UTF-8 codepoint."""
    # 'é' is 2 bytes in UTF-8 (\xc3\xa9); '🚀' is 4 bytes (\xf0\x9f\x9a\x80)
    text = "a" * 15 + "🚀" + "b" * 20 + "\n"
    raw = text.encode("utf-8")
    # Truncate at 17 bytes (which lands in the middle of the 4-byte '🚀' at bytes 15..19)
    res, reason = normalize_and_bound_text(raw, max_projected_bytes=17)
    assert reason is None and res is not None
    assert res.truncated is True
    assert res.projected_byte_length == 15
    assert res.normalized_text == "a" * 15
    assert res.normalized_byte_length == len(raw)
    assert res.raw_byte_length == len(raw)


def test_empty_file_normalization() -> None:
    """Empty files normalize cleanly with zero byte and line extents."""
    res, reason = normalize_and_bound_text(b"")
    assert reason is None and res is not None
    assert res.normalized_text == ""
    assert res.raw_byte_length == 0
    assert res.normalized_byte_length == 0
    assert res.projected_byte_length == 0
    assert res.raw_line_count == 0
    assert res.normalized_line_count == 0
    assert res.projected_line_count == 0
    assert res.truncated is False
