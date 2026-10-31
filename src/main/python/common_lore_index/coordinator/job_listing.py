"""Bounded contracts for recent durable coordinator job listing."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re


_GRAPH_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_JOB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z")


@dataclass(frozen=True)
class JobListCursor:
    """Newest-first keyset boundary for one submitted job."""

    submitted_at: str
    job_id: str


def encode_job_cursor(cursor: JobListCursor) -> str:
    """Encode one validated keyset boundary as an opaque public cursor."""

    _validate_cursor(cursor)
    raw = json.dumps(
        [cursor.submitted_at, cursor.job_id], separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_job_cursor(value: str) -> JobListCursor:
    """Decode one strict bounded opaque keyset cursor."""

    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 512:
            raise ValueError
        padding = "=" * (-len(value) % 4)
        raw = base64.b64decode(value + padding, altchars=b"-_", validate=True)
        decoded = json.loads(raw)
        if (
            not isinstance(decoded, list)
            or len(decoded) != 2
            or not all(isinstance(item, str) for item in decoded)
        ):
            raise ValueError
        cursor = JobListCursor(decoded[0], decoded[1])
        _validate_cursor(cursor)
        if encode_job_cursor(cursor) != value:
            raise ValueError
        return cursor
    except (UnicodeError, ValueError, json.JSONDecodeError):
        raise ValueError("job list cursor is invalid") from None


def validate_job_list_options(
    *, limit: int, graph_id: str | None, cursor: str | None
) -> tuple[int, str | None, JobListCursor | None]:
    """Validate the complete public listing option set."""

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 32
        or (
            graph_id is not None
            and (not isinstance(graph_id, str) or _GRAPH_ID.fullmatch(graph_id) is None)
        )
        or (cursor is not None and not isinstance(cursor, str))
    ):
        raise ValueError("job list options are invalid")
    try:
        decoded = None if cursor is None else decode_job_cursor(cursor)
    except ValueError:
        raise ValueError("job list options are invalid") from None
    return limit, graph_id, decoded


def format_utc_timestamp(value: datetime) -> str:
    """Format a database timestamp as the exact public cursor representation."""

    if value.tzinfo is None:
        raise ValueError("job list timestamp is invalid")
    return value.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def _validate_cursor(cursor: JobListCursor) -> None:
    if (
        _TIMESTAMP.fullmatch(cursor.submitted_at) is None
        or _JOB_ID.fullmatch(cursor.job_id) is None
    ):
        raise ValueError("job list cursor is invalid")
    try:
        datetime.strptime(cursor.submitted_at, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise ValueError("job list cursor is invalid") from None


__all__ = [
    "JobListCursor",
    "decode_job_cursor",
    "encode_job_cursor",
    "format_utc_timestamp",
    "validate_job_list_options",
]
