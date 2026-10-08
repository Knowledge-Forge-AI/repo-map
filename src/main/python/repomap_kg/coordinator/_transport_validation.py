"""Pure validation of bounded coordinator transport requests and results."""

from __future__ import annotations

from collections.abc import Mapping
import re
import unicodedata

from repomap_kg.coordinator.contracts import is_public_safe_text
from repomap_kg.coordinator.job_listing import validate_job_list_options
from repomap_kg.coordinator.limits import valid_admission_number

_PROHIBITED_KEYS = frozenset(
    {"root", "database", "sql", "command", "connector", "credential", "backup"}
)


def truncate_diagnostic_bytes(text: str, max_bytes: int = 256) -> str:
    """Truncate without splitting a UTF-8 code point."""
    return text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def sanitize_diagnostic_summary(value: object) -> str | None:
    """Share worker persistence and status sanitation; never forward a trace."""
    from repomap_kg.ops.report_records import _redact_text

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return None
    if value.lstrip().startswith("Traceback ") or any(
        unicodedata.category(char).startswith("C") or char in "\u2028\u2029"
        for char in value
    ):
        return "diagnostic_withheld"
    sanitized = re.sub(
        r"(?:[a-zA-Z]:\\|[/\\])[a-zA-Z0-9_.\-/\\]+", "[path]", value.strip()
    )
    return truncate_diagnostic_bytes(_redact_text(sanitized))


def valid_diagnostic_summary(value: object) -> bool:
    """Validate the optional public field without broadening wire authority."""
    return (
        isinstance(value, str)
        and is_public_safe_text(value, maximum=256)
        and len(value.encode("utf-8")) <= 256
        and not _contains_prohibited_authority(value)
        and sanitize_diagnostic_summary(value) == value
    )


def public_diagnostic_summary(value: object) -> str | None:
    """Withhold only an unsafe field, preserving the surrounding job status."""
    sanitized = sanitize_diagnostic_summary(value)
    if sanitized is None or valid_diagnostic_summary(sanitized):
        return sanitized
    return "diagnostic_withheld"


def _valid_public_result(value: object, *, depth: int = 0) -> bool:
    if depth > 8:
        return False
    if value is None or isinstance(value, (bool, int)):
        return not isinstance(value, int) or abs(value) <= 2**63 - 1
    if isinstance(value, str):
        return is_public_safe_text(value, maximum=4096)
    if isinstance(value, list):
        return len(value) <= 32 and all(
            _valid_public_result(item, depth=depth + 1) for item in value
        )
    if isinstance(value, dict):
        return (
            len(value) <= 32
            and not _contains_prohibited_authority(value)
            and all(
                isinstance(key, str)
                and 0 < len(key) <= 128
                and (key != "diagnostic_summary" or valid_diagnostic_summary(child))
                and _valid_public_result(child, depth=depth + 1)
                for key, child in value.items()
            )
        )
    return False


def validate_public_result(value: object) -> bool:
    """Return whether a client-visible result satisfies transport bounds."""

    return _valid_public_result(value)


def _contains_prohibited_authority(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or key.lower() in _PROHIBITED_KEYS:
                return True
            if _contains_prohibited_authority(child):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_prohibited_authority(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return "/" in value or "\\" in value or "://" in lowered
    return False


def _valid_operation_payload(operation: str, payload: Mapping[str, object]) -> bool:
    if operation == "health":
        return not payload
    if operation == "submit":
        return (set(payload) == {"request", "admission_deadline"}
                and isinstance(payload["request"], dict)
                and valid_admission_number(payload["admission_deadline"]))
    if operation in {"status", "wait", "cancel"}:
        return (
            set(payload) == {"job_id"}
            and isinstance(payload["job_id"], str)
            and 0 < len(payload["job_id"]) <= 128
        )
    if operation == "list":
        if not set(payload) <= {"limit", "graph_id", "cursor"} or "limit" not in payload:
            return False
        limit = payload["limit"]
        if isinstance(limit, bool) or not isinstance(limit, int):
            return False
        graph_id = payload.get("graph_id")
        if graph_id is not None and not isinstance(graph_id, str):
            return False
        cursor = payload.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            return False
        try:
            validate_job_list_options(limit=limit, graph_id=graph_id, cursor=cursor)
        except ValueError:
            return False
        return True
    return False
