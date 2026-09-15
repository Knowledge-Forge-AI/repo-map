"""Pure durable contracts for the synthetic coordinator pilot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Mapping

from repomap_kg.storage.authority import RequestId
from repomap_kg.coordinator.limits import (
    DEFAULT_LIMITS,
    CoordinatorLimits,
    valid_counter,
)


class JobState(StrEnum):
    """Exact durable job-state vocabulary."""

    QUEUED = "queued"
    CLAIMED = "claimed"
    STARTING = "starting"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    QUARANTINED = "quarantined"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class PublicationState(StrEnum):
    """Exact publication-state vocabulary, independent of job state."""

    NOT_APPLICABLE = "not_applicable"
    NOT_STARTED = "not_started"
    PREPARED = "prepared"
    TRANSACTION_STARTED = "transaction_started"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    COMMIT_UNKNOWN = "commit_unknown"


TERMINAL_JOB_STATES = frozenset(
    {
        JobState.SUCCEEDED,
        JobState.FAILED,
        JobState.CANCELLED,
        JobState.SUPERSEDED,
        JobState.QUARANTINED,
    }
)

LEGAL_TRANSITIONS: Mapping[JobState, frozenset[JobState]] = MappingProxyType(
    {
        JobState.QUEUED: frozenset(
            {
                JobState.CLAIMED,
                JobState.CANCELLED,
                JobState.SUPERSEDED,
                JobState.QUARANTINED,
            }
        ),
        JobState.CLAIMED: frozenset(
            {
                JobState.STARTING,
                JobState.CANCEL_REQUESTED,
                JobState.RECONCILIATION_REQUIRED,
            }
        ),
        JobState.STARTING: frozenset(
            {
                JobState.RUNNING,
                JobState.FAILED,
                JobState.QUEUED,
                JobState.CANCEL_REQUESTED,
                JobState.RECONCILIATION_REQUIRED,
            }
        ),
        JobState.RUNNING: frozenset(
            {
                JobState.SUCCEEDED,
                JobState.FAILED,
                JobState.QUEUED,
                JobState.CANCEL_REQUESTED,
                JobState.RECONCILIATION_REQUIRED,
            }
        ),
        JobState.CANCEL_REQUESTED: frozenset(
            {
                JobState.CANCELLING,
                JobState.CANCELLED,
                JobState.RECONCILIATION_REQUIRED,
            }
        ),
        JobState.CANCELLING: frozenset(
            {
                JobState.CANCELLED,
                JobState.FAILED,
                JobState.RECONCILIATION_REQUIRED,
            }
        ),
        JobState.RECONCILIATION_REQUIRED: frozenset(
            {
                JobState.SUCCEEDED,
                JobState.FAILED,
                JobState.CANCELLED,
                JobState.QUEUED,
                JobState.QUARANTINED,
            }
        ),
        **{terminal: frozenset() for terminal in TERMINAL_JOB_STATES},
    }
)

_REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "job_kind",
        "graph_id",
        "request_id",
        "idempotency_key",
        "priority",
        "operation_options",
    }
)
_PRIORITIES = frozenset({"automatic", "manual"})
_GRAPH_ID_PATTERN = re.compile(r"synthetic-[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\Z")
_CONFIGURED_GRAPH_ID_PATTERN = re.compile(r"[a-z][a-z0-9._-]{0,127}\Z")
_GENERATION_DIGEST_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_PUBLIC_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_UTC_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z"
)
_PROHIBITED_CONTENT = re.compile(
    r"(?:"
    r"(?:^|[\s\"'=])(?:/|~[/\\]|\.\.?[/\\]|[A-Za-z]:[/\\])"
    r"|\\"
    r"|\b(?:password|passwd|secret|token|api[_-]?key|credential|bearer)\b\s*[:=]"
    r"|\b(?:select|insert|update|delete|drop|alter|create|truncate|grant|revoke)\b\s+\w+"
    r"|\b(?:sh|bash|zsh|pwsh|powershell|cmd)\s+(?:-c|/c)\b"
    r"|\b(?:database|backup|command|connector)\b"
    r"|[;|`]"
    r"|\$\("
    r"|[{}\[\]<>]"
    r"|\braw[_ -]?(?:payload|observation|source)\b"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class JobRequest:
    """Immutable normalized version-1 request envelope."""

    schema_version: int
    job_kind: str
    graph_id: str
    request_id: RequestId
    idempotency_key: str
    priority: str
    operation_options: tuple[tuple[str, str], ...]
    source_generation: str
    config_generation: str
    extractor_generation: str = "eg1:synthetic"
    canonicalizer_generation: str = "kg1:synthetic"

    def semantic_payload(self) -> dict[str, object]:
        """Return deterministic JSON-safe content for replay comparison."""

        return {
            "config_generation": self.config_generation,
            "canonicalizer_generation": self.canonicalizer_generation,
            "extractor_generation": self.extractor_generation,
            "graph_id": self.graph_id,
            "job_kind": self.job_kind,
            "operation_options": dict(self.operation_options),
            "priority": self.priority,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "source_generation": self.source_generation,
        }


def validate_transition(
    current: JobState | str,
    target: JobState | str,
) -> JobState:
    """Validate one transition against the centralized durable state table."""

    try:
        current_state = JobState(current)
        target_state = JobState(target)
    except (TypeError, ValueError) as error:
        raise ValueError("illegal job transition") from error
    if target_state not in LEGAL_TRANSITIONS[current_state]:
        raise ValueError("illegal job transition")
    return target_state


def validate_generation(
    token: object,
    prefix: str,
    *,
    limits: CoordinatorLimits = DEFAULT_LIMITS,
) -> str:
    """Validate one opaque versioned source or configuration generation."""

    if prefix not in {"sg1:", "cg1:", "eg1:", "kg1:"} or not isinstance(token, str):
        raise ValueError("invalid generation")
    if len(token) > limits.max_identifier_chars or not token.startswith(prefix):
        raise ValueError("invalid generation")
    digest = token[len(prefix) :]
    if not _GENERATION_DIGEST_PATTERN.fullmatch(digest):
        raise ValueError("invalid generation")
    return token


def is_public_safe_text(value: object, *, maximum: int) -> bool:
    """Return whether a bounded string contains no private authority content."""

    if (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and _PROHIBITED_CONTENT.search(value) is None
    ):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError:
            return False
        return True
    return False


def normalize_request(
    payload: Mapping[str, object],
    *,
    source_generation: str,
    config_generation: str,
    extractor_generation: str = "eg1:synthetic",
    canonicalizer_generation: str = "kg1:synthetic",
    require_synthetic_graph: bool = True,
    limits: CoordinatorLimits = DEFAULT_LIMITS,
) -> JobRequest:
    """Validate and normalize an exact synthetic version-1 request."""

    if not isinstance(payload, Mapping) or set(payload) != _REQUEST_FIELDS:
        raise ValueError("request fields do not match the version-1 schema")
    if payload["schema_version"] != 1 or isinstance(payload["schema_version"], bool):
        raise ValueError("unsupported schema_version")
    if payload["job_kind"] != "refresh_graph":
        raise ValueError("unsupported job_kind")

    graph_id = _bounded_string(payload["graph_id"], "graph_id", limits)
    graph_pattern = (
        _GRAPH_ID_PATTERN if require_synthetic_graph else _CONFIGURED_GRAPH_ID_PATTERN
    )
    if not graph_pattern.fullmatch(graph_id):
        raise ValueError("graph_id is invalid")
    request_id = _bounded_string(payload["request_id"], "request_id", limits)
    idempotency_key = _bounded_string(
        payload["idempotency_key"], "idempotency_key", limits
    )
    priority = payload["priority"]
    if not isinstance(priority, str) or priority not in _PRIORITIES:
        raise ValueError("unsupported priority")

    raw_options = payload["operation_options"]
    if not isinstance(raw_options, Mapping) or set(raw_options) != {"reason"}:
        raise ValueError("unsupported operation_options")
    reason = _bounded_string(raw_options["reason"], "reason", limits)

    for value in (request_id, idempotency_key, reason):
        if _PROHIBITED_CONTENT.search(value):
            raise ValueError("request value contains prohibited content")

    return JobRequest(
        schema_version=1,
        job_kind="refresh_graph",
        graph_id=graph_id,
        request_id=RequestId(request_id),
        idempotency_key=idempotency_key,
        priority=str(priority),
        operation_options=(("reason", reason),),
        source_generation=validate_generation(source_generation, "sg1:", limits=limits),
        config_generation=validate_generation(config_generation, "cg1:", limits=limits),
        extractor_generation=validate_generation(
            extractor_generation, "eg1:", limits=limits
        ),
        canonicalizer_generation=validate_generation(
            canonicalizer_generation, "kg1:", limits=limits
        ),
    )


_PUBLIC_STATUS_FIELDS = frozenset(
    {
        "job_id",
        "request_id",
        "job_kind",
        "graph_id",
        "priority",
        "submitted_at",
        "started_at",
        "finished_at",
        "state",
        "attempt_count",
        "phase",
        "files",
        "observations",
        "canonical_nodes",
        "canonical_edges",
        "source_generation_match",
        "config_generation_match",
        "extractor_generation_match",
        "canonicalizer_generation_match",
    }
)
_PUBLIC_COUNTER_FIELDS = frozenset(
    {
        "attempt_count",
        "files",
        "observations",
        "canonical_nodes",
        "canonical_edges",
    }
)
_PUBLIC_IDENTIFIER_FIELDS = frozenset({"job_id", "request_id"})
_PUBLIC_TIMESTAMP_FIELDS = frozenset({"submitted_at", "started_at", "finished_at"})
_PUBLIC_BOOLEAN_FIELDS = frozenset(
    {
        "source_generation_match",
        "config_generation_match",
        "extractor_generation_match",
        "canonicalizer_generation_match",
    }
)
_PUBLIC_PHASES = frozenset(
    {
        "waiting",
        "starting",
        "preflight",
        "discovery",
        "extraction",
        "canonicalization",
        "storage_prepare",
        "storage_publish",
        "verification",
        "cleanup",
        "complete",
    }
)
_PUBLIC_ERROR_FIELDS = frozenset({"error_category", "retryable", "summary"})
_PUBLIC_ERROR_SUMMARIES = {
    "cancelled": "operation cancelled",
    "authorization": "request is unauthorized",
    "cancel_failed": "worker cancellation failed",
    "configuration": "configuration is invalid",
    "generation_changed": "requested generation changed",
    "internal": "internal coordinator failure",
    "permanent": "permanent failure",
    "privacy": "privacy policy violation",
    "protocol": "worker protocol failure",
    "publication_unknown": "publication outcome is unknown",
    "source_unavailable": "source is unavailable",
    "source_capture": "source capture failed",
    "storage_unavailable": "storage is unavailable",
    "superseded": "job was superseded",
    "transient": "transient failure",
    "transient_database": "transient database failure",
    "worker_crash": "worker crashed",
    "worker_launch": "worker failed to launch",
    "worker_timeout": "worker timed out",
}


def project_public_status(
    status: Mapping[str, object],
    *,
    limits: CoordinatorLimits = DEFAULT_LIMITS,
) -> dict[str, object]:
    """Return only public-safe status fields, validating bounded counters."""

    public = {key: status[key] for key in sorted(_PUBLIC_STATUS_FIELDS & status.keys())}
    for key, value in public.items():
        if not _valid_public_status_value(key, value, limits):
            raise ValueError(f"invalid public status field: {key}")
    return public


def project_public_error(
    error: Mapping[str, object],
    *,
    limits: CoordinatorLimits = DEFAULT_LIMITS,
) -> dict[str, object]:
    """Return only categorized, bounded public-safe error fields."""

    public = {key: error[key] for key in sorted(_PUBLIC_ERROR_FIELDS & error.keys())}
    category = public.get("error_category")
    if category is not None and (
        not isinstance(category, str) or category not in _PUBLIC_ERROR_SUMMARIES
    ):
        raise ValueError("invalid public error category")
    if "retryable" in public and not isinstance(public["retryable"], bool):
        raise ValueError("invalid retryable")
    if "summary" in public and not isinstance(public["summary"], str):
        raise ValueError("invalid summary")
    if isinstance(category, str):
        public["summary"] = _PUBLIC_ERROR_SUMMARIES[category]
    elif "summary" in public:
        raise ValueError("invalid public error category")
    return public


def _valid_public_status_value(
    key: str,
    value: object,
    limits: CoordinatorLimits,
) -> bool:
    if key in _PUBLIC_COUNTER_FIELDS:
        return valid_counter(value, limits)
    if key in _PUBLIC_IDENTIFIER_FIELDS:
        return (
            isinstance(value, str)
            and len(value) <= limits.max_identifier_chars
            and _PUBLIC_IDENTIFIER_PATTERN.fullmatch(value) is not None
            and _PROHIBITED_CONTENT.search(value) is None
        )
    if key == "job_kind":
        return value == "refresh_graph"
    if key == "graph_id":
        return (
            isinstance(value, str)
            and len(value) <= limits.max_identifier_chars
            and _GRAPH_ID_PATTERN.fullmatch(value) is not None
        )
    if key == "priority":
        return isinstance(value, str) and value in _PRIORITIES
    if key in _PUBLIC_TIMESTAMP_FIELDS:
        return _valid_utc_timestamp(value, limits)
    if key == "state":
        return isinstance(value, str) and value in JobState
    if key == "phase":
        return isinstance(value, str) and value in _PUBLIC_PHASES
    if key in _PUBLIC_BOOLEAN_FIELDS:
        return isinstance(value, bool)
    return False


def _valid_utc_timestamp(value: object, limits: CoordinatorLimits) -> bool:
    if (
        not isinstance(value, str)
        or len(value) > limits.max_identifier_chars
        or _UTC_TIMESTAMP_PATTERN.fullmatch(value) is None
    ):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def _bounded_string(
    value: object,
    name: str,
    limits: CoordinatorLimits,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limits.max_identifier_chars
    ):
        raise ValueError(f"invalid {name}")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError(f"invalid {name}")
    return value
