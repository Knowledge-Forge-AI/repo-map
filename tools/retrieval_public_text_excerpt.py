"""Exact raw line/byte span mapping, bounded UTF-8 excerpts and the fixed model-text encoder.

Offsets always address the original verified raw bytes. Line 1 starts at
offset 0; each LF ends its line inclusively, so CRLF stays two bytes. The
whole-file line-convention guard runs before any span check that needs body
bytes, so every admitted file has one unambiguous line numbering.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import json
import re
from typing import Any
import unicodedata

from retrieval_public_text_contracts import (
    EXCERPT_BLANK, EXCERPT_CREDENTIAL_SHAPE_EXCLUDED, EXCERPT_INVALID_UTF8, EXCERPT_PRIVACY_REFUSED,
    LINE_CONVENTION_MISMATCH, MAX_EXCERPT_BYTES, METADATA_PRIVACY_REFUSED, REPRESENTATION_VERSION, SPAN_INVALID,
    SPAN_OUT_OF_FILE, SPAN_REVERSED, PublicTextRefusal, sha256_bytes,
)
from retrieval_semantic_primitives import (
    RepresentationValidationError, _validate_representation_string,
    validate_relative_path,
)
from retrieval_public_text_privacy import EXCERPT_CREDENTIAL_SHAPE, excerpt_privacy_class, is_safe_public_metadata

_LONE_CR = re.compile("\r(?!\n)")
_EXTRA_BREAKS = frozenset("\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029")
_ESCAPED_CC = re.compile("[\x7f-\x9f]")


@dataclass(frozen=True)
class ExcerptSpan:
    """Public span accounting plus the private excerpt text (never in repr)."""

    line_count: int
    span_start_byte: int
    span_end_byte: int
    excerpt_end_byte: int
    excerpt_bytes: int
    excerpt_digest: str
    span_cut: bool
    utf8_tail_dropped_bytes: int
    lf_count: int
    crlf_count: int
    final_line_without_lf: bool
    _excerpt: str = field(repr=False, compare=False)

    @property
    def excerpt(self) -> str:
        return self._excerpt

    def public_fields(self) -> dict[str, Any]:
        return {
            "span_start_byte": self.span_start_byte, "span_end_byte": self.span_end_byte,
            "excerpt_end_byte": self.excerpt_end_byte, "excerpt_bytes": self.excerpt_bytes,
            "excerpt_digest": self.excerpt_digest, "span_cut": self.span_cut,
            "utf8_tail_dropped_bytes": self.utf8_tail_dropped_bytes, "lf_count": self.lf_count,
            "crlf_count": self.crlf_count, "final_line_without_lf": self.final_line_without_lf,
        }


def excerpt_privacy_reason(excerpt: str, *, private_markers: Sequence[str]) -> str | None:
    """B4: marker/sanitizer/control failures keep the privacy reason; a credential shape is conservative."""
    found = excerpt_privacy_class(excerpt, private_markers=private_markers)
    if found is None:
        return None
    return EXCERPT_CREDENTIAL_SHAPE_EXCLUDED if found == EXCERPT_CREDENTIAL_SHAPE else EXCERPT_PRIVACY_REFUSED


def check_span_endpoints(start_line: object, end_line: object) -> str | None:
    """Content-blind endpoint checks: exact ints (bool is not int) >= 1, then start <= end."""
    if type(start_line) is not int or type(end_line) is not int or start_line < 1 or end_line < 1:
        return SPAN_INVALID
    if start_line > end_line:
        return SPAN_REVERSED
    return None


def raw_line_count(raw: bytes) -> int:
    """L = count(LF) + 1 for a nonempty final line without LF; an empty file has zero lines."""
    return raw.count(b"\n") + (1 if raw and raw[-1] != 0x0A else 0)


def line_convention_mismatch(text: str) -> bool:
    """True when any alternative convention could number lines differently from LF-only."""
    return _LONE_CR.search(text) is not None or any(ch in _EXTRA_BREAKS for ch in text)


def _line_bounds(raw: bytes, start_line: int, end_line: int) -> tuple[int, int]:
    starts = [0]
    position = raw.find(b"\n")
    while position != -1 and len(starts) <= end_line:
        starts.append(position + 1)
        position = raw.find(b"\n", position + 1)
    span_start = starts[start_line - 1]
    span_end = starts[end_line] if end_line < len(starts) else len(raw)
    return span_start, span_end


def map_excerpt(
    raw: bytes,
    start_line: object,
    end_line: object,
    *,
    projected_raw_line_count: int | None,
    private_markers: Sequence[str],
) -> tuple[ExcerptSpan | None, str | None]:
    """Map an accepted line span onto verified raw bytes, or return one closed exclusion reason."""
    reason = check_span_endpoints(start_line, end_line)
    if reason is not None:
        return None, reason
    assert type(start_line) is int and type(end_line) is int
    if type(raw) is not bytes:
        raise TypeError("verified raw bytes are required")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None, EXCERPT_INVALID_UTF8
    total_lines = raw_line_count(raw)
    if line_convention_mismatch(text) or (
        projected_raw_line_count is not None and total_lines != projected_raw_line_count
    ):
        return None, LINE_CONVENTION_MISMATCH
    if end_line > total_lines:
        return None, SPAN_OUT_OF_FILE
    span_start, span_end = _line_bounds(raw, start_line, end_line)
    cut_end = min(span_end, span_start + MAX_EXCERPT_BYTES)
    chunk = raw[span_start:cut_end]
    dropped = 0
    try:
        excerpt = chunk.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        partial_tail = (
            cut_end < span_end and error.end == len(chunk) and len(chunk) - error.start <= 3
            and error.reason == "unexpected end of data"
        )
        if not partial_tail:
            return None, EXCERPT_INVALID_UTF8
        dropped = len(chunk) - error.start
        chunk = chunk[: error.start]
        try:
            excerpt = chunk.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None, EXCERPT_INVALID_UTF8
    if not excerpt.strip():
        return None, EXCERPT_BLANK
    privacy_reason = excerpt_privacy_reason(excerpt, private_markers=private_markers)
    if privacy_reason is not None:
        return None, privacy_reason
    return ExcerptSpan(
        line_count=total_lines, span_start_byte=span_start, span_end_byte=span_end,
        excerpt_end_byte=span_start + len(chunk), excerpt_bytes=len(chunk), excerpt_digest=sha256_bytes(chunk),
        span_cut=cut_end < span_end, utf8_tail_dropped_bytes=dropped, lf_count=chunk.count(b"\n"),
        crlf_count=chunk.count(b"\r\n"), final_line_without_lf=span_end == len(raw) and not raw.endswith(b"\n"),
        _excerpt=excerpt,
    ), None


def validate_metadata_fields(
    canonical_key: Any, kind: Any, display_name: Any, source_relative_path: Any,
    *, private_markers: Sequence[str],
) -> str | None:
    """Apply validate_relative_path to P, then marker-aware string validation to K/T/N/P."""
    markers = tuple(private_markers)
    try:
        validate_relative_path(source_relative_path, "source_relative_path")
        for value, name in (
            (canonical_key, "canonical_key"), (kind, "kind"), (display_name, "display_name"),
            (source_relative_path, "source_relative_path"),
        ):
            _validate_representation_string(value, name, private_markers=markers)
            if not is_safe_public_metadata(value, private_markers=markers):
                return METADATA_PRIVACY_REFUSED
    except (ValueError, RepresentationValidationError):
        return METADATA_PRIVACY_REFUSED
    return None


def encode_model_text(
    canonical_key: object, kind: object, display_name: object, source_relative_path: object, excerpt: object,
    *, private_markers: Sequence[str],
) -> str:
    """Encode cloe-public-text-model-text-v1 with remaining Cc characters escaped as lowercase \\u00xx."""
    if validate_metadata_fields(
        canonical_key, kind, display_name, source_relative_path, private_markers=private_markers,
    ) is not None:
        raise PublicTextRefusal(METADATA_PRIVACY_REFUSED)
    if type(excerpt) is not str:
        raise PublicTextRefusal(EXCERPT_INVALID_UTF8)
    try:
        excerpt.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise PublicTextRefusal(EXCERPT_INVALID_UTF8) from error
    privacy_reason = excerpt_privacy_reason(excerpt, private_markers=private_markers)
    if privacy_reason is not None:
        raise PublicTextRefusal(privacy_reason)
    payload = {
        "v": REPRESENTATION_VERSION, "canonical_key": canonical_key, "kind": kind,
        "display_name": display_name, "source_relative_path": source_relative_path, "excerpt": excerpt,
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    text = _ESCAPED_CC.sub(lambda match: f"\\u{ord(match.group(0)):04x}", text)
    if any(unicodedata.category(ch) in {"Cc", "Cs"} for ch in text):
        raise PublicTextRefusal(EXCERPT_INVALID_UTF8)
    return text


def model_text_input_digest(model_text: str) -> str:
    return sha256_bytes(model_text.encode("utf-8", errors="strict"))
