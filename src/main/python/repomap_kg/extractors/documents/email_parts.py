"""MIME part and attachment observation extraction."""

from __future__ import annotations

from typing import Any

from repomap_kg.extractors.documents.email_common import (
    MAX_MIME_PARTS,
    PARSER,
    _hash_text,
    _MessageContext,
    _observation,
    _parse_error,
    _redacted_filename,
)
from repomap_kg.graph.keys import email_attachment_stub_key, email_part_key
from repomap_kg.observations.raw import RawObservation


def _part_observations(
    context: _MessageContext,
    message: Any,
    message_key: str,
) -> tuple[list[RawObservation], dict[str, int]]:
    observations: list[RawObservation] = []
    summary = {
        "text_plain_part_count": 0,
        "text_html_part_count": 0,
        "attachment_count": 0,
    }
    for index, (part, part_path, depth) in enumerate(_walk_parts(message), start=1):
        if index > MAX_MIME_PARTS:
            observations.append(
                _parse_error(
                    context,
                    "mime-part-count-limit",
                    "EML MIME part count exceeds static parser limit",
                    recovered=True,
                )
            )
            break
        content_type = part.get_content_type().lower()
        disposition = (part.get_content_disposition() or "").lower() or None
        filename = part.get_filename()
        is_attachment = disposition == "attachment" or bool(filename)
        byte_count = _part_byte_count(part)
        pointer = f"/parts/{part_path}"
        part_key = email_part_key(message_key, pointer)
        is_body_text = not is_attachment and not part.is_multipart()
        if is_body_text and content_type == "text/plain":
            summary["text_plain_part_count"] += 1
        if is_body_text and content_type == "text/html":
            summary["text_html_part_count"] += 1

        observations.append(
            _observation(
                kind="email.part",
                relative_path=context.relative_path,
                source_id=f"{context.source_id_prefix}#email-part:{part_path}",
                name=pointer,
                target=part_key,
                metadata={
                    "format": context.metadata_format,
                    "parser": PARSER,
                    "source_key": message_key,
                    "mime_type": content_type,
                    "content_type": content_type,
                    "content_disposition": disposition,
                    "charset": part.get_content_charset(),
                    "transfer_encoding": part.get("Content-Transfer-Encoding"),
                    "part_index": index,
                    "part_path": pointer,
                    "part_depth": depth,
                    "part_byte_count": byte_count,
                    "inline": disposition == "inline",
                    "content_id_present": part.get("Content-ID") is not None,
                    "redacted": True,
                    "redaction_reason": "body-or-attachment-content-omitted",
                },
            )
        )

        if is_attachment:
            summary["attachment_count"] += 1
            attachment_pointer = f"/attachments/{summary['attachment_count']}"
            observations.append(
                _observation(
                    kind="email.attachment_stub",
                    relative_path=context.relative_path,
                    source_id=(
                        f"{context.source_id_prefix}#email-attachment:"
                        f"{summary['attachment_count']}"
                    ),
                    name=attachment_pointer,
                    target=email_attachment_stub_key(message_key, attachment_pointer),
                    metadata={
                        "format": context.metadata_format,
                        "parser": PARSER,
                        "source_key": message_key,
                        "part_key": part_key,
                        "part_path": pointer,
                        "content_disposition": disposition,
                        "attachment_filename_redacted": _redacted_filename(filename),
                        "attachment_filename_hash": _hash_text(filename or ""),
                        "attachment_mime_type": content_type,
                        "attachment_byte_count": byte_count,
                        "inline": disposition == "inline",
                        "content_id_present": part.get("Content-ID") is not None,
                        "redacted": True,
                        "redaction_reason": "attachment-content-omitted",
                    },
                )
            )
    return observations, summary


def _walk_parts(message: Any) -> list[tuple[Any, str, int]]:
    parts: list[tuple[Any, str, int]] = []

    def visit(part: Any, path: str, depth: int) -> None:
        parts.append((part, path, depth))
        if part.is_multipart():
            for child_index, child in enumerate(part.iter_parts(), start=1):
                visit(child, f"{path}.{child_index}", depth + 1)

    visit(message, "1", 0)
    return parts


def _part_byte_count(part: Any) -> int:
    if part.is_multipart():
        return 0
    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        return len(payload)
    raw_payload = part.get_payload()
    if isinstance(raw_payload, str):
        return len(raw_payload.encode("utf-8", errors="replace"))
    return 0
