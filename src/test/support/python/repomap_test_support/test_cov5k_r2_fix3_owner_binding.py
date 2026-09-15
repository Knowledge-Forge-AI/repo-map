"""Compatibility facade for typed owner tracing and concrete evidence records."""
from __future__ import annotations

from typing import Callable, TypeVar
from repomap_test_support.test_cov5k_r2_fix2_evidence import OwnerEntryEvidence
from repomap_test_support import test_cov5k_r2_contracts as contracts
from repomap_test_support.test_cov5k_r2_contracts import (
    OwnerBindingError as OwnerBindingError,
    callable_source_digest as callable_source_digest,
    code_object_identity as code_object_identity,
    exact_callable_matches as exact_callable_matches,
)

T = TypeVar("T")


def external_owner_evidence(
    *, executor: Callable[..., object], executable: str,
    owner_entry_count: int, scenario_seam_active: bool,
) -> OwnerEntryEvidence:
    return contracts.external_owner_evidence(
        evidence_factory=OwnerEntryEvidence, executor=executor,
        executable=executable, owner_entry_count=owner_entry_count,
        scenario_seam_active=scenario_seam_active,
    )


def invoke_bound_owner(
    *, executor: Callable[..., object], owner: Callable[..., object],
    scenario_seam_active: bool, operation: Callable[[], T],
    expected_owner_entries: int = 1,
) -> tuple[T, OwnerEntryEvidence, tuple[dict[str, object], ...]]:
    return contracts.invoke_bound_owner(
        evidence_factory=OwnerEntryEvidence, executor=executor, owner=owner,
        scenario_seam_active=scenario_seam_active, operation=operation,
        expected_owner_entries=expected_owner_entries,
    )
