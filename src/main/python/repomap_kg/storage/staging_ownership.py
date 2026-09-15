"""Stage owner identity and fencing validation."""

from __future__ import annotations

from dataclasses import dataclass
import re

from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId

__all__ = ("StageOwner", "StageOwnershipError", "require_stage_owner")

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_GENERATION_PATTERNS = {
    "source_generation": re.compile(r"sg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}\Z"),
    "config_generation": re.compile(r"cg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}\Z"),
    "extractor_generation": re.compile(
        r"eg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}\Z"
    ),
    "canonicalizer_generation": re.compile(
        r"kg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}\Z"
    ),
}


class StageOwnershipError(ValueError):
    """A stage operation does not match its durable owner."""


@dataclass(frozen=True)
class StageOwner:
    """Immutable graph/job/attempt authority carried by every stage operation."""

    repository_id: int
    operation_id: OperationId
    attempt: AttemptNumber
    execution_mode: str
    source_generation: str
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str
    job_id: JobId | None = None
    coordinator_instance_id: str | None = None
    singleton_fencing_epoch: int = 0
    graph_lease_fencing_epoch: int = 0

    def validate(self) -> "StageOwner":
        valid = (
            isinstance(self.repository_id, int)
            and not isinstance(self.repository_id, bool)
            and self.repository_id > 0
            and _safe_identifier(self.operation_id)
            and _valid_attempt(self.attempt)
            and self.execution_mode in {"direct", "coordinator"}
            and _valid_generations(self)
            and _valid_mode_owner(self)
        )
        if not valid:
            raise StageOwnershipError("invalid stage owner")
        return self


def require_stage_owner(expected: StageOwner, actual: StageOwner) -> None:
    """Reject any operation whose complete owner tuple differs from the header."""

    expected.validate()
    actual.validate()
    if expected != actual:
        raise StageOwnershipError("stage owner mismatch")


def _valid_attempt(value: object) -> bool:
    """Validate runtime input even when a caller violates its nominal annotation."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _safe_identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER_PATTERN.fullmatch(value) is not None


def _valid_generations(owner: StageOwner) -> bool:
    return all(
        pattern.fullmatch(getattr(owner, field_name) or "") is not None
        for field_name, pattern in _GENERATION_PATTERNS.items()
    )


def _valid_mode_owner(owner: StageOwner) -> bool:
    # Coordinator custody requires equal textual identities across nominal ID types.
    operation_id: str = owner.operation_id
    job_id: str | None = owner.job_id
    if owner.execution_mode == "direct":
        return (
            owner.job_id is None
            and owner.coordinator_instance_id is None
            and owner.singleton_fencing_epoch == 0
            and owner.graph_lease_fencing_epoch == 0
        )
    return (
        owner.job_id is not None
        and _safe_identifier(owner.job_id)
        and operation_id == job_id
        and owner.coordinator_instance_id is not None
        and _safe_identifier(owner.coordinator_instance_id)
        and isinstance(owner.singleton_fencing_epoch, int)
        and owner.singleton_fencing_epoch > 0
        and isinstance(owner.graph_lease_fencing_epoch, int)
        and owner.graph_lease_fencing_epoch > 0
    )
