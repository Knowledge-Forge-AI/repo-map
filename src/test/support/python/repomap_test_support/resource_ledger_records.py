"""Record types, closed enums, and schemas for the private resource ledger."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from repomap_test_support.resource_retention import (
    RetentionClass,
    TerminalOutcome,
)
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    bounded_string,
)

LEDGER_SCHEMA = "repomap-test-resource-ledger-v2"
FACTS = frozenset({"pre_existing_objects_mutated", "foreign_scratch_runs_mutated"})
_FACTS = FACTS
CHECKPOINT_INTEGER_FIELDS = frozenset(
    {
        "allocated_bytes",
        "apparent_bytes",
        "inode_count",
        "retained_evidence_bytes",
        "unsafe_link_count",
    }
)
_CHECKPOINT_INTEGER_FIELDS = CHECKPOINT_INTEGER_FIELDS
CHECKPOINT_FIELDS = CHECKPOINT_INTEGER_FIELDS | frozenset(
    {"largest_owned_subtree_category"}
)
_CHECKPOINT_FIELDS = CHECKPOINT_FIELDS


class ResourceLedgerError(RuntimeError):
    """Ledger evidence is unsafe, malformed, conflicting, or incomplete."""


class ResourceKind(str, Enum):
    SCRATCH_DIRECTORY = "scratch_directory"
    SCRATCH_FILE = "scratch_file"
    SCRATCH_EVIDENCE_GROUP = "scratch_file_or_retained_evidence_group"
    PROCESS = "process"
    UNIX_SOCKET = "unix_socket"
    TCP_PORT = "tcp_port"
    POSTGRES_CLUSTER = "postgres_cluster"
    DOCKER_CONTAINER = "docker_container"
    DOCKER_IMAGE = "docker_image"
    DOCKER_TAG = "docker_tag"
    DOCKER_NETWORK = "docker_network"
    DOCKER_VOLUME = "docker_volume"
    BUILDX_BUILDER = "buildx_builder"
    BUILDKIT_STATE_VOLUME = "buildkit_state_volume"
    BUILD_HISTORY_RECORD = "build_history_record"


class RetainedReason(str, Enum):
    NOT_RETAINED = "not_retained"
    OPERATOR_REVIEW = "operator_review"
    DIAGNOSTIC_EVIDENCE = "diagnostic_evidence"
    FAILURE_EVIDENCE = "failure_evidence"
    REPORT_SOURCE = "report_source"


class CleanupResult(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    REMOVED = "removed"
    ALREADY_ABSENT = "already_absent"
    RETAINED = "retained"
    FAILED = "failed"


class FinalPresence(str, Enum):
    UNOBSERVED = "unobserved"
    PRESENT = "present"
    ABSENT = "absent"


@dataclass(frozen=True)
class RunIdentity:
    project: str
    phase: str
    run_id: str

    def __post_init__(self) -> None:
        try:
            for field_name, value in asdict(self).items():
                bounded_string(value, f"run identity field: {field_name}")
        except HygieneValidationError as error:
            raise ResourceLedgerError(str(error)) from error


@dataclass(frozen=True)
class ResourceRecord:
    kind: ResourceKind
    identity: str
    creation_owner: str
    created_before_run: bool
    creation_observed: bool
    cleanup_required: bool
    cleanup_attempted: bool = False
    cleanup_result: CleanupResult = CleanupResult.NOT_ATTEMPTED
    retained: bool = False
    retained_reason: RetainedReason = RetainedReason.NOT_RETAINED
    final_presence: FinalPresence = FinalPresence.UNOBSERVED
    size_bytes: int = 0
    inode_count: int = 0


@dataclass(frozen=True)
class LedgerLifecycle:
    retention_class: RetentionClass = RetentionClass.ACTIVE
    terminal_outcome: TerminalOutcome | None = None
    terminal_at_seconds: int | None = None


def validate_record(record: ResourceRecord) -> None:
    if record.created_before_run and record.cleanup_required:
        raise ResourceLedgerError("pre-existing resource cannot require cleanup")
    if record.cleanup_required and not record.creation_observed:
        raise ResourceLedgerError("cleanup-required creation must be observed")
    if record.retained and record.retained_reason is RetainedReason.NOT_RETAINED:
        raise ResourceLedgerError("retained resource requires a retained reason")
    if not record.retained and record.retained_reason is not RetainedReason.NOT_RETAINED:
        raise ResourceLedgerError("transient resource cannot have a retained reason")
    if record.retained and record.cleanup_required:
        raise ResourceLedgerError("retained resource cannot require cleanup")
    if record.retained and record.kind not in {
        ResourceKind.SCRATCH_DIRECTORY,
        ResourceKind.SCRATCH_FILE,
        ResourceKind.SCRATCH_EVIDENCE_GROUP,
    }:
        raise ResourceLedgerError("only scratch evidence may be retained")


__all__ = [
    "CHECKPOINT_FIELDS",
    "CHECKPOINT_INTEGER_FIELDS",
    "CleanupResult",
    "FACTS",
    "FinalPresence",
    "LEDGER_SCHEMA",
    "LedgerLifecycle",
    "ResourceKind",
    "ResourceLedgerError",
    "ResourceRecord",
    "RetainedReason",
    "RunIdentity",
    "validate_record",
]
