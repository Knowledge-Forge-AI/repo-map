"""Stable records and vocabularies used by the Docker operation journal."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DockerOperationKind(str, Enum):
    MANAGED_RUNTIME_LOGICAL_BUILD = "managed_runtime_logical_build"
    DOCKER_BUILD = "docker_build"
    DOCKER_PULL = "docker_pull"
    IMAGE_MATERIALIZATION_COMMIT = "image_materialization_commit"


class DockerAuthorityClass(str, Enum):
    MANAGED_TEST_RUNTIME = "managed_test_runtime"
    MANAGED_SYSTEM_CANDIDATE = "managed_system_candidate"
    MANAGED_EXTERNAL_BASE = "managed_external_base"
    PRODUCT_OR_BUILD_PROFILE = "product_or_build_profile"
    UNMANAGED_FORBIDDEN = "unmanaged_forbidden"


class DockerOperationResult(str, Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUSED = "refused"


_BUILD_KINDS = frozenset(
    {
        DockerOperationKind.DOCKER_BUILD,
        DockerOperationKind.MANAGED_RUNTIME_LOGICAL_BUILD,
    }
)
_EXECUTED = frozenset(
    {
        DockerOperationResult.STARTED,
        DockerOperationResult.SUCCEEDED,
        DockerOperationResult.FAILED,
    }
)

DERIVED_OPERATION_FIELDS = (
    "product_or_build_profile_build_count",
    "managed_test_runtime_image_build_count",
    "managed_system_candidate_image_build_count",
    "managed_runtime_build_intermediate_created_count",
    "managed_runtime_build_intermediate_removed_count",
    "managed_runtime_build_intermediate_residue_count",
    "managed_external_base_pull_count",
    "unmanaged_build_count",
    "unmanaged_pull_count",
)


@dataclass(frozen=True, slots=True)
class DockerOperationEvent:
    """One exact operation identity and its last durably recorded state."""

    ordinal: int
    event_id: str
    kind: DockerOperationKind
    authority: DockerAuthorityClass
    owner: str
    mechanism: str
    request: str
    result: DockerOperationResult
    started: bool
    completed: bool
    image_ids: tuple[str, ...] = ()
    failure_category: str | None = None
    cleanup_disposition: str | None = None

    @property
    def executed(self) -> bool:
        return self.result in _EXECUTED


@dataclass(frozen=True, slots=True)
class MaterializationObservation:
    """One exact observed Engine delta for a managed materialization."""

    event_id: str
    final_image_id: str
    intermediate_created_ids: tuple[str, ...]
    intermediate_removed_ids: tuple[str, ...]

    @property
    def intermediate_terminal_ids(self) -> tuple[str, ...]:
        removed = set(self.intermediate_removed_ids)
        return tuple(x for x in self.intermediate_created_ids if x not in removed)


__all__ = [
    "DERIVED_OPERATION_FIELDS",
    "DockerAuthorityClass",
    "DockerOperationEvent",
    "DockerOperationKind",
    "DockerOperationResult",
    "MaterializationObservation",
]
