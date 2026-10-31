"""Strict UTF-8 decoding, NUL byte rejection, CRLF/CR normalization, and prefix bounding (S1)."""

from __future__ import annotations

from dataclasses import dataclass

from common_lore_index.retrieval.projection_chunks import frame_digest
from common_lore_index.retrieval.projection_policy import ExclusionReason

REPRESENTATION_VERSION = "lf-utf8-v1"
DEFAULT_MAX_PROJECTED_FILE_BYTES = 262144


def _count_lf_lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") if text.endswith("\n") else text.count("\n") + 1


def _count_raw_lines(raw_bytes: bytes) -> int:
    if not raw_bytes:
        return 0
    normalized = raw_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return normalized.count(b"\n") if normalized.endswith(b"\n") else normalized.count(b"\n") + 1


def _utf8_safe_prefix(data: bytes, max_bytes: int) -> bytes:
    if len(data) <= max_bytes:
        return data
    cut = max_bytes
    while cut > 0 and (data[cut] & 0xC0) == 0x80:
        cut -= 1
    candidate = data[:cut]
    try:
        candidate.decode("utf-8", errors="strict")
        return candidate
    except UnicodeDecodeError:
        while cut > 0:
            cut -= 1
            try:
                data[:cut].decode("utf-8", errors="strict")
                return data[:cut]
            except UnicodeDecodeError:
                continue
        return b""


@dataclass(frozen=True)
class NormalizedTextResult:
    """Normalized UTF-8 text and extent accounting under lf-utf8-v1."""

    representation_version: str
    normalized_text: str
    normalized_bytes: bytes
    raw_byte_length: int
    raw_line_count: int
    normalized_byte_length: int
    normalized_line_count: int
    projected_byte_length: int
    projected_line_count: int
    had_crlf_or_cr: bool
    truncated: bool
    representation_digest: str


def normalize_and_bound_text(
    raw_bytes: bytes,
    *,
    max_projected_bytes: int = DEFAULT_MAX_PROJECTED_FILE_BYTES,
) -> tuple[NormalizedTextResult | None, ExclusionReason | None]:
    """Validate strict UTF-8 without NUL bytes, normalize line endings, and bound prefix."""
    if max_projected_bytes < 1:
        raise ValueError("max_projected_bytes must be positive")
    if b"\x00" in raw_bytes:
        return None, ExclusionReason.NUL_BYTE_REJECTED
    try:
        decoded = raw_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None, ExclusionReason.INVALID_UTF8

    raw_byte_length = len(raw_bytes)
    raw_line_count = _count_raw_lines(raw_bytes)
    had_crlf_or_cr = ("\r" in decoded)
    full_normalized_text = decoded.replace("\r\n", "\n").replace("\r", "\n")
    full_normalized_bytes = full_normalized_text.encode("utf-8")
    normalized_byte_length = len(full_normalized_bytes)
    normalized_line_count = _count_lf_lines(full_normalized_text)

    if normalized_byte_length > max_projected_bytes:
        projected_bytes = _utf8_safe_prefix(full_normalized_bytes, max_projected_bytes)
        projected_text = projected_bytes.decode("utf-8", errors="strict")
        truncated = True
    else:
        projected_bytes = full_normalized_bytes
        projected_text = full_normalized_text
        truncated = False

    projected_byte_length = len(projected_bytes)
    projected_line_count = _count_lf_lines(projected_text)
    rep_digest = frame_digest(
        "sha256",
        (REPRESENTATION_VERSION, projected_bytes),
    )
    return (
        NormalizedTextResult(
            representation_version=REPRESENTATION_VERSION,
            normalized_text=projected_text,
            normalized_bytes=projected_bytes,
            raw_byte_length=raw_byte_length,
            raw_line_count=raw_line_count,
            normalized_byte_length=normalized_byte_length,
            normalized_line_count=normalized_line_count,
            projected_byte_length=projected_byte_length,
            projected_line_count=projected_line_count,
            had_crlf_or_cr=had_crlf_or_cr,
            truncated=truncated,
            representation_digest=rep_digest,
        ),
        None,
    )
