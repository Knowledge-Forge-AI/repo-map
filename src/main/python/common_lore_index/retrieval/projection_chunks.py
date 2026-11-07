"""Deterministic chunking, UTF-8 long-line splitting, and framed SHA-256 digests (S1)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
from typing import Any


def frame_digest(prefix: str, parts: Sequence[str | bytes]) -> str:
    """Compute a length-prefixed SHA-256 digest (`<prefix>:<64hex>`) over ordered parts."""
    if not isinstance(prefix, str) or not prefix.strip():
        raise ValueError("prefix must be a non-empty string")
    hasher = hashlib.sha256()
    hasher.update(f"cloe-frame-v1:{len(parts)}:".encode("utf-8"))
    for part in parts:
        raw = part.encode("utf-8") if isinstance(part, str) else bytes(part)
        hasher.update(f"{len(raw)}:".encode("ascii"))
        hasher.update(raw)
        hasher.update(b";")
    return f"{prefix}:{hasher.hexdigest()}"


def _split_lf_lines_keepends(text: str) -> list[str]:
    if not text:
        return []
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _split_long_utf8_line(line: str, max_chunk_bytes: int) -> list[str]:
    pieces: list[str] = []
    current_chars: list[str] = []
    current_bytes = 0
    for ch in line:
        ch_len = len(ch.encode("utf-8"))
        if current_chars and current_bytes + ch_len > max_chunk_bytes:
            pieces.append("".join(current_chars))
            current_chars = [ch]
            current_bytes = ch_len
        else:
            current_chars.append(ch)
            current_bytes += ch_len
    if current_chars:
        pieces.append("".join(current_chars))
    return pieces


@dataclass(frozen=True)
class ProjectedChunk:
    """One contiguous, non-overlapping chunk of projected file text."""

    chunk_id: str
    file_projection_id: str
    chunk_index: int
    binding_id: str
    source_relative_path: str
    start_line: int
    end_line: int
    normalized_byte_start: int
    normalized_byte_end: int
    byte_length: int
    line_count: int
    line_split_continuation: bool
    is_empty_file_record: bool
    content_text: str
    content_digest: str
    artifact_privacy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "file_projection_id": self.file_projection_id,
            "chunk_index": self.chunk_index,
            "binding_id": self.binding_id,
            "source_relative_path": self.source_relative_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "normalized_byte_start": self.normalized_byte_start,
            "normalized_byte_end": self.normalized_byte_end,
            "byte_length": self.byte_length,
            "line_count": self.line_count,
            "line_split_continuation": self.line_split_continuation,
            "is_empty_file_record": self.is_empty_file_record,
            "content_text": self.content_text,
            "content_digest": self.content_digest,
            "artifact_privacy": self.artifact_privacy,
        }


def build_file_chunks(
    *,
    file_projection_id: str,
    binding_id: str,
    source_relative_path: str,
    normalized_text: str,
    artifact_privacy: str,
    policy_digest: str,
    publication_bundle_id: str,
    max_chunk_lines: int = 80,
    max_chunk_bytes: int = 8192,
) -> tuple[ProjectedChunk, ...]:
    """Split normalized text into contiguous chunks bounded by lines and UTF-8 bytes."""
    if max_chunk_lines < 1 or max_chunk_bytes < 4:
        raise ValueError("max_chunk_lines >= 1 and max_chunk_bytes >= 4 are required")

    if normalized_text == "":
        content_digest = frame_digest("sha256", (b"",))
        chunk_id = frame_digest(
            "projchunk1",
            (
                policy_digest,
                publication_bundle_id,
                file_projection_id,
                binding_id,
                source_relative_path,
                "0",
                "0",
                "0",
                "0",
                "empty",
                content_digest,
            ),
        )
        return (
            ProjectedChunk(
                chunk_id=chunk_id,
                file_projection_id=file_projection_id,
                chunk_index=0,
                binding_id=binding_id,
                source_relative_path=source_relative_path,
                start_line=0,
                end_line=0,
                normalized_byte_start=0,
                normalized_byte_end=0,
                byte_length=0,
                line_count=0,
                line_split_continuation=False,
                is_empty_file_record=True,
                content_text="",
                content_digest=content_digest,
                artifact_privacy=artifact_privacy,
            ),
        )

    lines = _split_lf_lines_keepends(normalized_text)
    raw_specs: list[tuple[int, int, str, bool]] = []
    buf_lines: list[str] = []
    buf_bytes = 0
    buf_start_line = 1
    buf_end_line = 1

    def _flush() -> None:
        nonlocal buf_lines, buf_bytes
        if not buf_lines:
            return
        raw_specs.append((buf_start_line, buf_end_line, "".join(buf_lines), False))
        buf_lines = []
        buf_bytes = 0

    for line_no, line in enumerate(lines, start=1):
        line_bytes = len(line.encode("utf-8"))
        if line_bytes > max_chunk_bytes:
            _flush()
            pieces = _split_long_utf8_line(line, max_chunk_bytes)
            for idx, piece in enumerate(pieces):
                raw_specs.append((line_no, line_no, piece, idx > 0))
            continue

        if buf_lines and (
            len(buf_lines) >= max_chunk_lines or buf_bytes + line_bytes > max_chunk_bytes
        ):
            _flush()

        if not buf_lines:
            buf_start_line = line_no
        buf_lines.append(line)
        buf_bytes += line_bytes
        buf_end_line = line_no

    _flush()

    chunks: list[ProjectedChunk] = []
    byte_cursor = 0
    for chunk_index, (start_line, end_line, text_piece, is_cont) in enumerate(raw_specs):
        piece_bytes = text_piece.encode("utf-8")
        byte_len = len(piece_bytes)
        byte_start = byte_cursor
        byte_end = byte_cursor + byte_len
        byte_cursor = byte_end
        line_cnt = 1 if is_cont else (end_line - start_line + 1)
        c_digest = frame_digest("sha256", (piece_bytes,))
        c_id = frame_digest(
            "projchunk1",
            (
                policy_digest,
                publication_bundle_id,
                file_projection_id,
                binding_id,
                source_relative_path,
                str(chunk_index),
                str(start_line),
                str(end_line),
                str(byte_start),
                str(byte_end),
                c_digest,
            ),
        )
        chunks.append(
            ProjectedChunk(
                chunk_id=c_id,
                file_projection_id=file_projection_id,
                chunk_index=chunk_index,
                binding_id=binding_id,
                source_relative_path=source_relative_path,
                start_line=start_line,
                end_line=end_line,
                normalized_byte_start=byte_start,
                normalized_byte_end=byte_end,
                byte_length=byte_len,
                line_count=line_cnt,
                line_split_continuation=is_cont,
                is_empty_file_record=False,
                content_text=text_piece,
                content_digest=c_digest,
                artifact_privacy=artifact_privacy,
            )
        )
    return tuple(chunks)
