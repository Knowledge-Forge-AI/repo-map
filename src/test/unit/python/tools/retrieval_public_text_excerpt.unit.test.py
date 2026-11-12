"""Literal X1-X17 byte-span vectors and the fixed public-text model-text encoder.

Expected digests are computed here from literal expected bytes with hashlib,
never through the module under test.
"""

from __future__ import annotations

import hashlib

import pytest

from common_lore_index.retrieval.projection_text import normalize_and_bound_text
from retrieval_public_text_contracts import (
    EXCERPT_BLANK, EXCERPT_INVALID_UTF8, EXCERPT_PRIVACY_REFUSED, LINE_CONVENTION_MISMATCH,
    METADATA_PRIVACY_REFUSED, SPAN_INVALID, SPAN_OUT_OF_FILE, SPAN_REVERSED, PublicTextRefusal,
)
from retrieval_public_text_excerpt import (
    check_span_endpoints, encode_model_text, map_excerpt, model_text_input_digest, raw_line_count,
    validate_metadata_fields,
)

CANARY = "CANARY-PRIVATE-HOME-7731"


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _map(raw: bytes, start: object, end: object, *, projected: int | None = None, markers: tuple[str, ...] = ()):
    return map_excerpt(raw, start, end, projected_raw_line_count=projected, private_markers=markers)


def test_x1_middle_line_with_lf() -> None:
    span, reason = _map(b"a\nbc\nd\n", 2, 2)
    assert reason is None and span is not None
    assert (span.span_start_byte, span.span_end_byte, span.excerpt_end_byte) == (2, 5, 5)
    assert span.excerpt == "bc\n" and span.excerpt_digest == _sha(b"bc\n") and span.line_count == 3
    assert (span.lf_count, span.crlf_count, span.span_cut, span.final_line_without_lf) == (1, 0, False, False)


def test_x2_crlf_stays_two_bytes_per_terminator() -> None:
    span, reason = _map(b"x\r\ny\r\n", 1, 2)
    assert reason is None and span is not None
    assert (span.span_start_byte, span.span_end_byte, span.excerpt_bytes) == (0, 6, 6)
    assert (span.crlf_count, span.lf_count) == (2, 2) and span.excerpt_digest == _sha(b"x\r\ny\r\n")


def test_x3_final_line_without_lf() -> None:
    span, reason = _map(b"p\nq", 2, 2)
    assert reason is None and span is not None
    assert (span.span_start_byte, span.span_end_byte, span.excerpt) == (2, 3, "q")
    assert span.final_line_without_lf is True and span.excerpt_digest == _sha(b"q")


@pytest.mark.parametrize("raw,start,end,expected", [
    (b"p\nq", 3, 3, SPAN_OUT_OF_FILE),          # X4
    (b"p\n", 2, 2, SPAN_OUT_OF_FILE),           # X5: terminal LF adds no line
    (bytes.fromhex("61FF620A"), 1, 1, EXCERPT_INVALID_UTF8),  # X8
    (b"p\nq", 3, 2, SPAN_REVERSED),             # X10
    (b"p\nq", 0, 1, SPAN_INVALID),              # X10
    (b"", 1, 1, SPAN_OUT_OF_FILE),              # X11
    (b"\n", 1, 1, EXCERPT_BLANK),               # X12
    (b"a\rb\n", 2, 2, LINE_CONVENTION_MISMATCH),  # X15
    (b"a\rb\n", 1, 1, LINE_CONVENTION_MISMATCH),  # X15
    (bytes.fromhex("61C285620A"), 1, 1, LINE_CONVENTION_MISMATCH),  # X16 (U+0085)
    (b"a\r", 1, 1, LINE_CONVENTION_MISMATCH),   # X17
])
def test_literal_exclusion_vectors(raw: bytes, start: int, end: int, expected: str) -> None:
    span, reason = _map(raw, start, end)
    assert span is None and reason == expected


def test_x6_two_byte_tail_is_trimmed_at_the_cap() -> None:
    raw = b"a" * 4095 + bytes.fromhex("C3A9") + b"\n"
    span, reason = _map(raw, 1, 1)
    assert reason is None and span is not None
    assert (span.excerpt_bytes, span.span_cut, span.utf8_tail_dropped_bytes) == (4095, True, 1)
    assert (span.span_end_byte, span.excerpt_end_byte) == (4098, 4095)
    assert span.excerpt_digest == _sha(b"a" * 4095)


def test_x7_four_byte_tail_is_trimmed_at_the_cap() -> None:
    raw = b"a" * 4094 + bytes.fromhex("F09F9880") + b"\n"
    span, reason = _map(raw, 1, 1)
    assert reason is None and span is not None
    assert (span.excerpt_bytes, span.span_cut, span.utf8_tail_dropped_bytes) == (4094, True, 2)
    assert span.excerpt_digest == _sha(b"a" * 4094)


def test_x9_remaining_cc_is_escaped_in_model_text() -> None:
    raw = bytes.fromhex("7FC29F0A")
    span, reason = _map(raw, 1, 1)
    assert reason is None and span is not None and span.excerpt == "\x7f\x9f\n"
    text = encode_model_text("py:mod.f", "function", "f", "src/m.py", span.excerpt, private_markers=())
    assert text.endswith('"excerpt":"\\u007f\\u009f\\n"}')


X13_RAW = b"def f():\n    return 1\n"
X13_EXPECTED = (
    b'{"v":"canonical-node-public-text-v2","canonical_key":"py:mod.f","kind":"function","display_name":"f",'
    b'"source_relative_path":"src/m.py","excerpt":"def f():\\n    return 1\\n"}'
)


def test_x13_model_text_is_exact_compact_ordered_json() -> None:
    span, reason = _map(X13_RAW, 1, 2)
    assert reason is None and span is not None
    text = encode_model_text("py:mod.f", "function", "f", "src/m.py", span.excerpt, private_markers=())
    assert text.encode("utf-8") == X13_EXPECTED
    assert model_text_input_digest(text) == _sha(X13_EXPECTED)
    assert (span.span_start_byte, span.span_end_byte, span.lf_count) == (0, len(X13_RAW), 2)


def test_x14_non_ascii_metadata_stays_literal_utf8() -> None:
    span, _reason = _map(X13_RAW, 1, 2)
    assert span is not None
    text = encode_model_text("py:mod.f", "function", "café", "src/m.py", span.excerpt, private_markers=())
    expected = X13_EXPECTED.replace(b'"display_name":"f"', b'"display_name":"caf\xc3\xa9"')
    assert text.encode("utf-8") == expected
    assert bytes.fromhex("636166C3A9") in text.encode("utf-8")
    assert model_text_input_digest(text) == _sha(expected)


def test_x17_line_count_agrees_and_only_the_first_guard_condition_catches_it() -> None:
    result, _reason = normalize_and_bound_text(b"a\r")
    assert result is not None and result.raw_line_count == 1 == raw_line_count(b"a\r")
    assert _map(b"a\r", 1, 1, projected=1) == (None, LINE_CONVENTION_MISMATCH)


def test_projected_line_count_cross_check_is_defensive() -> None:
    assert _map(b"a\nb\n", 1, 1, projected=3) == (None, LINE_CONVENTION_MISMATCH)
    span, reason = _map(b"a\nb\n", 1, 1, projected=2)
    assert reason is None and span is not None and span.excerpt == "a\n"


@pytest.mark.parametrize("start,end", [(True, 1), (1, False), (None, 1), (1, None), (1.0, 1), ("1", 1), (-1, 2)])
def test_endpoints_are_exact_ints_before_any_body_byte(start: object, end: object) -> None:
    assert check_span_endpoints(start, end) == SPAN_INVALID
    assert _map(b"\xff\xfe", start, end) == (None, SPAN_INVALID)


def test_excerpt_privacy_marker_refuses_without_redaction() -> None:
    raw = f"value = '{CANARY}'\n".encode("utf-8")
    assert _map(raw, 1, 1, markers=(CANARY,)) == (None, EXCERPT_PRIVACY_REFUSED)
    span, reason = _map(raw, 1, 1)
    assert reason is None and span is not None and CANARY not in repr(span)


def test_whitespace_only_excerpt_is_blank() -> None:
    assert _map("x\n \t　\n".encode("utf-8"), 2, 2) == (None, EXCERPT_BLANK)


def test_encoder_escapes_every_remaining_cc_character() -> None:
    for code in range(0x7F, 0xA0):
        text = encode_model_text("k", "t", "n", "p.py", f"a{chr(code)}b", private_markers=())
        assert f"a\\u{code:04x}b" in text
        assert chr(code) not in text


def test_encoder_refuses_surrogates_and_private_or_invalid_metadata() -> None:
    with pytest.raises(PublicTextRefusal) as error:
        encode_model_text("k", "t", "n", "p.py", "\ud800", private_markers=())
    assert error.value.code == EXCERPT_INVALID_UTF8
    for canonical_key, kind, display_name, source_relative_path in (
        ("k", "t", CANARY, "p.py"), ("k", "t", "n", "../p.py"), ("k", "t", "n", "/abs/p.py"),
        ("k", "", "n", "p.py"), ("k\x01", "t", "n", "p.py"), ("k", "t", "n", "a\\b.py"), (1, "t", "n", "p.py"),
    ):
        assert validate_metadata_fields(canonical_key, kind, display_name, source_relative_path,
                                        private_markers=(CANARY,)) == METADATA_PRIVACY_REFUSED
        with pytest.raises(PublicTextRefusal) as refused:
            encode_model_text(canonical_key, kind, display_name, source_relative_path, "body",
                              private_markers=(CANARY,))
        assert refused.value.code == METADATA_PRIVACY_REFUSED
    assert validate_metadata_fields("k", "t", "n", "p.py", private_markers=(CANARY,)) is None
