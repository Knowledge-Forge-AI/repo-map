"""Derived runtime views over the closed staging-family descriptors."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from repomap_kg.storage.staging_family_contracts import (
    PrivacyClassification,
    STAGING_FAMILY_DESCRIPTORS,
    StageFamilyDescriptor,
)
from repomap_kg.storage.staging_family_rows import StageFamily
from repomap_kg.storage.staging_merge_operations import MergeOperation, MergeScope


@dataclass(frozen=True)
class StageMergeBinding:
    """One descriptor-owned operation in stable merge order."""

    descriptor: StageFamilyDescriptor
    operation: MergeOperation


def merge_operations_for_scope(scope: MergeScope) -> tuple[StageMergeBinding, ...]:
    """Return the descriptor-owned operation sequence for one merge pipeline."""

    bindings = (
        StageMergeBinding(descriptor, operation)
        for descriptor in STAGING_FAMILY_DESCRIPTORS.values()
        for operation in descriptor.merge_operations
        if operation.scope is scope
    )
    return tuple(sorted(bindings, key=lambda binding: binding.operation.order))


def descriptors_for_merge_scope(
    scope: MergeScope,
) -> tuple[StageFamilyDescriptor, ...]:
    """Return each descriptor participating in a merge pipeline once."""

    return tuple(
        descriptor
        for descriptor in STAGING_FAMILY_DESCRIPTORS.values()
        if any(operation.scope is scope for operation in descriptor.merge_operations)
    )


def family_privacy_classifications() -> Mapping[StageFamily, PrivacyClassification]:
    """Return the descriptor-owned private payload classification catalog."""

    return MappingProxyType(
        {
            family: descriptor.privacy_classification
            for family, descriptor in STAGING_FAMILY_DESCRIPTORS.items()
        }
    )
