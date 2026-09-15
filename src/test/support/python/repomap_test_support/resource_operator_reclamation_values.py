"""Values, contracts, and exceptions for operator reclamation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

PROJECT = "repo-map_dev"
OPERATOR_DELETION_MAX_SECONDS = 1800
CONFIRMATION_LITERAL = (
    "IRREVERSIBLY RECLAIM ALL CONTENTS OF THE SELECTED SCRATCH RUN DIRECTORY "
    "INCLUDING NON-REPOMAP AND RETAINED EVIDENCE"
)
PREFLIGHT_CATEGORIES = frozenset(
    {
        "scratch_root_authority_unavailable",
        "maintenance_authority_unavailable",
        "index_authority_unavailable",
        "admission_barrier_unavailable",
        "inventory_authority_unavailable",
        "inventory_identity_changed",
        "liveness_authority_unavailable",
        "protection_authority_unavailable",
        "monitoring_authority_unavailable",
        "index_record_authority_unavailable",
        "operator_evidence_authority_unavailable",
    }
)
T = TypeVar("T")


class OperatorReclamationPreflightError(RuntimeError):
    """A structurally pre-record stage failed with a closed public category."""

    def __init__(self, category: str) -> None:
        if category not in PREFLIGHT_CATEGORIES:
            raise ValueError("operator preflight category is invalid")
        super().__init__(category)
        self.category = category


class OperatorReclamationInterrupted(BaseException):
    """A persisted partial result whose Python interruption remains primary."""

    def __init__(
        self,
        result: OperatorReclamationResult,
        *,
        interruption_kind: str,
        exit_code: int,
    ) -> None:
        self.result = result
        self.interruption_kind = interruption_kind
        self.exit_code = exit_code
        self.cleanup_error: BaseException | None = None
        super().__init__(interruption_kind)


@dataclass(frozen=True)
class OperatorReclamationRequest:
    confirmation: str | None
    force_live: bool
    override_pins: bool


@dataclass(frozen=True)
class OperatorReclamationResult:
    outcome: str
    scope_class: str
    force_live: bool
    override_pins: bool
    entry_count: int
    allocated_bytes: int
    inode_count: int
    live_count: int
    unknown_count: int
    pin_count: int
    markers_written: int
    removed_entry_count: int
    removed_allocated_bytes: int
    removed_inode_count: int
    point_of_no_return: bool
    physical_mutation_performed: bool
    identity_replacement_refused: bool
    categories: dict[str, int]
    operation_id: str
    inventory_digest: str
    operation_path: Path
    public_log_path: Path
    barrier_released: bool
    partial_reason: str | None
    partial_failure_category: str | None


def replace_dict(payload: dict[str, object], **changes: object) -> dict[str, object]:
    return {**payload, **changes}


def categories_from_payload(payload: dict[str, object]) -> dict[str, int]:
    values = payload.get("categories", {})
    return dict(values) if isinstance(values, dict) else {}


__all__ = [
    "CONFIRMATION_LITERAL",
    "OPERATOR_DELETION_MAX_SECONDS",
    "PREFLIGHT_CATEGORIES",
    "PROJECT",
    "T",
    "OperatorReclamationInterrupted",
    "OperatorReclamationPreflightError",
    "OperatorReclamationRequest",
    "OperatorReclamationResult",
    "categories_from_payload",
    "replace_dict",
]
