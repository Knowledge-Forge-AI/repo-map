"""Privacy-preserving static EML extraction."""

from __future__ import annotations

import re
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from typing import Any

from repomap_kg.extractors.documents.email_common import (
    EXTRACTOR,
    MAX_MIME_PARTS,
    PARSER,
    SECRET_MARKERS,
    _hash_bytes,
    _hash_text,
    _header_slug,
    _is_secret_prone,
    _MessageContext,
    _observation,
    _parse_error,
    _parsed_date,
    _redacted_filename,
    _redacted_query,
    _redact_url,
    _redact_url_text,
    _urls_in_header,
)
from repomap_kg.extractors.documents.email_parts import (
    _part_byte_count,
    _part_observations,
    _walk_parts,
)
from repomap_kg.graph.keys import (
    email_address_key,
    email_mailbox_key,
    email_message_key,
    email_thread_hint_key,
    external_url_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


MAX_EML_BYTES = 2 * 1024 * 1024
MAX_MBOX_BYTES = 10 * 1024 * 1024
MAX_MBOX_MESSAGES = 1000
MAX_MBOX_MESSAGE_BYTES = MAX_EML_BYTES
MAX_HEADER_BYTES = 64 * 1024
MESSAGE_ID_RE = re.compile(r"<([^<>\s]+@[^<>\s]+)>")
HEADER_NAMES = (
    "Message-ID",
    "Date",
    "From",
    "To",
    "Cc",
    "Bcc",
    "Reply-To",
    "Sender",
    "Return-Path",
    "Subject",
    "In-Reply-To",
    "References",
    "List-Id",
    "List-Unsubscribe",
    "Content-Type",
)


ADDRESS_HEADERS = (
    ("From", "from"),
    ("To", "to"),
    ("Cc", "cc"),
    ("Bcc", "bcc"),
    ("Reply-To", "reply_to"),
    ("Sender", "sender"),
    ("Return-Path", "return_path"),
)
def extract_eml_file_observations(
    relative_path: str,
    content: bytes,
) -> tuple[RawObservation, ...]:
    """Extract safe static metadata from a local EML message."""

    context = _MessageContext(
        relative_path=relative_path,
        source_id_prefix=relative_path,
        metadata_format="eml",
    )
    if len(content) > MAX_EML_BYTES:
        return (
            _parse_error(
                context,
                "file-size-limit",
                "EML file exceeds static parser byte limit",
                recovered=False,
            ),
        )

    try:
        message = BytesParser(policy=policy.default).parsebytes(content)
    except Exception as error:  # pragma: no cover - stdlib parser is permissive.
        return (
            _parse_error(
                context,
                "parse-error",
                str(error)[:120],
                recovered=False,
            ),
        )

    return _extract_message_observations(context, message)


def extract_mbox_file_observations(
    relative_path: str,
    content: bytes,
    *,
    max_messages: int = MAX_MBOX_MESSAGES,
    max_message_bytes: int = MAX_MBOX_MESSAGE_BYTES,
) -> tuple[RawObservation, ...]:
    """Extract safe static metadata from a local MBOX mailbox archive."""

    mailbox_key = email_mailbox_key(relative_path)
    mailbox_file_key = f"file:{relative_path}"
    observations: list[RawObservation] = []
    if len(content) > MAX_MBOX_BYTES:
        observations.append(
            _mailbox_observation(
                relative_path=relative_path,
                mailbox_key=mailbox_key,
                message_count=0,
                limited=True,
                status="limit_exceeded",
                limit_reason="file-size-limit",
                byte_count=len(content),
                content=content,
            )
        )
        observations.append(
            _parse_error(
                _MessageContext(relative_path, relative_path, "mbox"),
                "mbox-file-size-limit",
                "MBOX file exceeds static parser byte limit",
                recovered=False,
            )
        )
        return tuple(observations)

    messages, has_separator = _split_mbox_messages(content)
    message_count_limited = len(messages) > max_messages
    parsed_messages = messages[:max_messages]
    parse_status = "parsed" if has_separator else "malformed"
    limit_reason = None
    if message_count_limited:
        parse_status = "limited"
        limit_reason = "message-count-limit"
    observations.append(
        _mailbox_observation(
            relative_path=relative_path,
            mailbox_key=mailbox_key,
            message_count=len(parsed_messages),
            limited=message_count_limited,
            status=parse_status,
            limit_reason=limit_reason,
            byte_count=len(content),
            content=content,
        )
    )
    mailbox_context = _MessageContext(
        relative_path=relative_path,
        source_id_prefix=relative_path,
        metadata_format="mbox",
    )
    if not has_separator:
        observations.append(
            _parse_error(
                mailbox_context,
                "mbox-missing-from-separator",
                "MBOX file does not start with a From separator",
                recovered=True,
            )
        )
        return tuple(observations)
    if message_count_limited:
        observations.append(
            _parse_error(
                mailbox_context,
                "mbox-message-count-limit",
                "MBOX message count exceeds static parser limit",
                recovered=True,
            )
        )

    for ordinal, message_bytes in enumerate(parsed_messages, start=1):
        source_id_prefix = f"{relative_path}#mbox-message:{ordinal}"
        message_context = _MessageContext(
            relative_path=relative_path,
            source_id_prefix=source_id_prefix,
            metadata_format="mbox",
            message_parent_key=mailbox_key,
            mailbox_file_key=mailbox_file_key,
            mbox_message_ordinal=ordinal,
        )
        if len(message_bytes) > max_message_bytes:
            observations.append(
                _parse_error(
                    message_context,
                    "mbox-message-size-limit",
                    "MBOX message exceeds static parser byte limit",
                    recovered=True,
                )
            )
            continue
        try:
            message = BytesParser(policy=policy.default).parsebytes(message_bytes)
        except Exception as error:  # pragma: no cover - stdlib parser is permissive.
            observations.append(
                _parse_error(
                    message_context,
                    "mbox-message-parse-error",
                    str(error)[:120],
                    recovered=True,
                )
            )
            continue
        observations.extend(_extract_message_observations(message_context, message))
    return tuple(observations)


def _extract_message_observations(
    context: _MessageContext,
    message: Any,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    message_id = message.get("Message-ID")
    identity = _message_identity(context, message_id, message)
    message_key = email_message_key(context.relative_path, identity["identity"])
    header_bytes = _header_byte_count(message)
    address_observations, address_counts = _address_observations(
        context,
        message,
        message_key,
    )
    part_observations, part_summary = _part_observations(context, message, message_key)
    thread_observations, reference_observations = _thread_observations(
        context,
        message,
        message_key,
    )
    header_observations = _header_observations(context, message)
    unsubscribe_references = _list_unsubscribe_references(
        context,
        message,
        message_key,
    )
    subject = message.get("Subject")
    parsed_date, date_status = _parsed_date(message.get("Date"))
    redacted = bool(subject) or bool(unsubscribe_references)

    observations.append(
        _observation(
            kind="email.message",
            relative_path=context.relative_path,
            source_id=f"{context.source_id_prefix}#email-message",
            name="email message",
            target=message_key,
            metadata={
                "format": context.metadata_format,
                "parser": PARSER,
                "file_key": f"file:{context.relative_path}",
                "source_key": context.message_parent_key,
                "mailbox_file_key": context.mailbox_file_key,
                "mbox_message_ordinal": context.mbox_message_ordinal,
                "mbox_message_identity": identity["identity"]
                if context.metadata_format == "mbox"
                else None,
                "message_id_hash": identity["message_id_hash"],
                "message_id_present": message_id is not None,
                "message_id_valid": identity["message_id_valid"],
                "date": parsed_date,
                "date_parse_status": date_status,
                "subject_present": subject is not None,
                "subject_hash": _hash_text(subject or ""),
                "subject_preview_redacted": "<redacted>" if subject else None,
                "from_count": address_counts["from"],
                "to_count": address_counts["to"],
                "cc_count": address_counts["cc"],
                "bcc_count": address_counts["bcc"],
                "reply_to_count": address_counts["reply_to"],
                "sender_count": address_counts["sender"],
                "return_path_count": address_counts["return_path"],
                "text_plain_part_count": part_summary["text_plain_part_count"],
                "text_html_part_count": part_summary["text_html_part_count"],
                "attachment_count": part_summary["attachment_count"],
                "has_text_plain": part_summary["text_plain_part_count"] > 0,
                "has_text_html": part_summary["text_html_part_count"] > 0,
                "has_attachments": part_summary["attachment_count"] > 0,
                "has_remote_references": bool(unsubscribe_references),
                "header_byte_count": header_bytes,
                "redacted": redacted,
                "redaction_reason": "subject-or-header-redaction" if redacted else None,
                "identity_strength": identity["identity_strength"],
            },
        )
    )

    observations.extend(header_observations)
    observations.extend(address_observations)
    observations.extend(part_observations)
    observations.extend(thread_observations)
    observations.extend(reference_observations)
    observations.extend(unsubscribe_references)

    if not identity["message_id_valid"]:
        observations.append(
            _parse_error(
                context,
                "missing-or-invalid-message-id",
                "Message-ID header is missing or invalid; structural identity used",
                recovered=True,
            )
        )
    if header_bytes > MAX_HEADER_BYTES:
        observations.append(
            _parse_error(
                context,
                "header-size-limit",
                "EML headers exceed static parser header byte limit",
                recovered=True,
            )
        )
    for defect in getattr(message, "defects", ()):
        observations.append(
            _parse_error(
                context,
                "parser-defect",
                defect.__class__.__name__,
                recovered=True,
            )
        )

    return tuple(observation for observation in observations if observation is not None)


def _message_identity(
    context: _MessageContext,
    message_id: str | None,
    message: Any,
) -> dict[str, Any]:
    normalized = _normalize_message_id(message_id)
    if normalized is not None:
        digest = _hash_text(normalized)
        return {
            "identity": f"message:{digest}",
            "message_id_hash": digest,
            "message_id_valid": True,
            "identity_strength": "message_id",
        }
    structural_basis = "|".join(
        (
            context.relative_path,
            str(context.mbox_message_ordinal or ""),
            _hash_text(message.get("Date") or ""),
            _hash_text(message.get("From") or ""),
            _hash_text(message.get("To") or ""),
            _hash_text(message.get("Subject") or ""),
        )
    )
    digest = _hash_text(structural_basis)
    return {
        "identity": f"structural:{digest}",
        "message_id_hash": None,
        "message_id_valid": False,
        "identity_strength": "structural",
    }


def _mailbox_observation(
    *,
    relative_path: str,
    mailbox_key: str,
    message_count: int,
    limited: bool,
    status: str,
    limit_reason: str | None,
    byte_count: int,
    content: bytes,
) -> RawObservation:
    return _observation(
        kind="email.mailbox",
        relative_path=relative_path,
        source_id=f"{relative_path}#email-mailbox",
        name="email mailbox",
        target=mailbox_key,
        metadata={
            "format": "mbox",
            "parser": PARSER,
            "file_key": f"file:{relative_path}",
            "mailbox_message_count": message_count,
            "mailbox_message_count_limited": limited,
            "mailbox_byte_count": byte_count,
            "mailbox_parse_status": status,
            "mailbox_limit_reason": limit_reason,
            "mailbox_digest": _hash_bytes(content),
            "identity_strength": "file_key",
        },
    )


def _split_mbox_messages(content: bytes) -> tuple[list[bytes], bool]:
    messages: list[bytes] = []
    current: list[bytes] | None = None
    has_separator = False
    for line in content.splitlines(keepends=True):
        if line.startswith(b"From "):
            has_separator = True
            if current is not None:
                messages.append(b"".join(current))
            current = []
            continue
        if current is not None:
            current.append(line)
    if current is not None:
        messages.append(b"".join(current))
    return messages, has_separator


def _normalize_message_id(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    matches = MESSAGE_ID_RE.findall(value)
    if len(matches) != 1:
        return None
    return matches[0].strip().lower()


def _message_ids(value: str | None) -> list[str]:
    if not isinstance(value, str):
        return []
    return [match.strip().lower() for match in MESSAGE_ID_RE.findall(value)]


def _header_byte_count(message: Any) -> int:
    total = 0
    for name, value in message.raw_items():
        total += len(name.encode("utf-8", errors="replace"))
        total += len(str(value).encode("utf-8", errors="replace"))
    return total


def _header_observations(context: _MessageContext, message: Any) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for header_name in HEADER_NAMES:
        values = message.get_all(header_name, [])
        if not values:
            continue
        metadata: dict[str, Any] = {
            "format": context.metadata_format,
            "parser": PARSER,
            "header_name": header_name,
            "header_present": True,
            "header_count": len(values),
        }
        if header_name == "List-Unsubscribe":
            metadata["redacted"] = True
            metadata["redaction_reason"] = "header-url-redacted"
            redacted_values = [_redact_url_text(value) for value in values]
            metadata["raw_value_summary"] = "; ".join(redacted_values)[:160]
        observations.append(
            _observation(
                kind="email.header",
                relative_path=context.relative_path,
                source_id=(
                    f"{context.source_id_prefix}#email-header:"
                    f"{_header_slug(header_name)}"
                ),
                name=header_name,
                metadata=metadata,
            )
        )
    return observations

def _address_observations(
    context: _MessageContext,
    message: Any,
    message_key: str,
) -> tuple[list[RawObservation], dict[str, int]]:
    observations: list[RawObservation] = []
    counts = {role: 0 for _header, role in ADDRESS_HEADERS}
    for header_name, role in ADDRESS_HEADERS:
        values = message.get_all(header_name, [])
        for display_name, address in getaddresses(values):
            normalized = _normalize_address(address)
            if normalized is None:
                continue
            address_hash = _hash_text(normalized)
            domain = normalized.rsplit("@", 1)[1]
            counts[role] += 1
            observations.append(
                _observation(
                    kind="email.address",
                    relative_path=context.relative_path,
                    source_id=(
                        f"{context.source_id_prefix}#email-address:"
                        f"{role}:{address_hash[:16]}"
                    ),
                    name=f"{role}:{domain}",
                    target=email_address_key(f"addrhash:{address_hash}"),
                    metadata={
                        "format": context.metadata_format,
                        "parser": PARSER,
                        "source_key": message_key,
                        "address_role": role,
                        "address_domain": domain,
                        "address_hash": address_hash,
                        "address_display_name_redacted": (
                            "<redacted>" if display_name else None
                        ),
                        "redacted": True,
                        "redaction_reason": "email-address-hashed",
                    },
                )
            )
    return observations, counts


def _normalize_address(address: str) -> str | None:
    if not isinstance(address, str) or "@" not in address:
        return None
    normalized = address.strip().strip("<>").lower()
    local, _separator, domain = normalized.rpartition("@")
    if not local or not domain:
        return None
    return f"{local}@{domain}"


def _thread_observations(
    context: _MessageContext,
    message: Any,
    message_key: str,
) -> tuple[list[RawObservation], list[RawObservation]]:
    hints: list[RawObservation] = []
    references: list[RawObservation] = []
    entries: list[tuple[str, str]] = []
    entries.extend(("in_reply_to", message_id) for message_id in _message_ids(message.get("In-Reply-To")))
    entries.extend(("references", message_id) for message_id in _message_ids(message.get("References")))
    for ordinal, (kind, normalized_message_id) in enumerate(entries, start=1):
        digest = _hash_text(normalized_message_id)
        pointer = f"/thread/{kind.replace('_', '-')}/{ordinal}"
        hint_key = email_thread_hint_key(message_key, pointer)
        target_key = unknown_key("email-message", f"message:{digest[:24]}")
        metadata = {
            "format": context.metadata_format,
            "parser": PARSER,
            "source_key": message_key,
            "thread_hint_kind": kind,
            "reference_kind": kind,
            "referenced_message_id_hash": digest,
            "not_fetched": True,
            "identity_strength": "header-message-id",
        }
        hints.append(
            _observation(
                kind="email.thread_hint",
                relative_path=context.relative_path,
                source_id=f"{context.source_id_prefix}#email-thread-hint:{ordinal}",
                name=pointer,
                target=hint_key,
                metadata=metadata,
            )
        )
        references.append(
            _observation(
                kind="email.reference",
                relative_path=context.relative_path,
                source_id=f"{context.source_id_prefix}#email-reference:{kind}:{ordinal}",
                name=kind,
                target=target_key,
                metadata=metadata,
            )
        )
    return hints, references


def _list_unsubscribe_references(
    context: _MessageContext,
    message: Any,
    message_key: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for index, value in enumerate(message.get_all("List-Unsubscribe", []), start=1):
        for url in _urls_in_header(value):
            redacted_url = _redact_url(url)
            observations.append(
                _observation(
                    kind="email.reference",
                    relative_path=context.relative_path,
                    source_id=(
                        f"{context.source_id_prefix}#email-reference:"
                        f"list-unsubscribe:{index}"
                    ),
                    name="list-unsubscribe",
                    target=external_url_key(redacted_url),
                    metadata={
                        "format": context.metadata_format,
                        "parser": PARSER,
                        "source_key": message_key,
                        "reference_kind": "list_unsubscribe",
                        "raw_value_summary": redacted_url,
                        "not_fetched": True,
                        "redacted": True,
                        "redaction_reason": "header-url-redacted",
                    },
                )
            )
    return observations
