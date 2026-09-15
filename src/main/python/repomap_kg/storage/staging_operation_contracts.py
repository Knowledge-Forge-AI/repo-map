"""Closed public-safe operation identities for staged publication."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from repomap_kg.storage.staging_family_contracts import (
    STAGING_FAMILY_DESCRIPTORS,
)
from repomap_kg.storage.staging_family_rows import StageFamily
from repomap_kg.storage.staging_merge_operations import MergeOperation


__all__ = (
    "STAGING_OPERATION_DESCRIPTORS",
    "StagingOperationDescriptor",
    "StagingOperationGroup",
    "operation_descriptor",
    "operation_code_for_merge",
)

_SCHEMA_VERSION = 1
_TRANSACTION_SCOPES = frozenset(
    {"stage_preparation", "final_publication", "cleanup"}
)
_REPEAT_POLICIES = frozenset({"once_per_attempt", "once_per_family"})


class StagingOperationGroup(StrEnum):
    """Closed logical groups used for live publication attribution."""

    STAGE_STATISTICS = "stage_statistics"
    COMPLETENESS_VALIDATION = "completeness_validation"
    SEMANTIC_GUARD = "semantic_guard"
    MERGE = "merge"
    RECEIPT = "receipt"
    CLEANUP = "cleanup"
    TRANSACTION_CONTROL = "transaction_control"


@dataclass(frozen=True)
class StagingOperationDescriptor:
    """One source-owned operation with a safe public projection."""

    schema_version: int
    operation_code: str
    operation_group: StagingOperationGroup
    family: StageFamily | None
    transaction_scope: str
    expected_parent: str | None
    repeat_policy: str
    cancellable: bool
    public_description_category: str
    source_module: str
    source_symbol: str

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError("staging operation schema version is invalid")
        if not self.operation_code or self.operation_code.strip() != self.operation_code:
            raise ValueError("staging operation code is invalid")
        if not isinstance(self.operation_group, StagingOperationGroup):
            raise ValueError("staging operation group is invalid")
        if self.family is not None and self.family not in STAGING_FAMILY_DESCRIPTORS:
            raise ValueError("staging operation family is invalid")
        if self.transaction_scope not in _TRANSACTION_SCOPES:
            raise ValueError("staging operation transaction scope is invalid")
        if self.expected_parent is not None:
            raise ValueError("nested staging operations are not supported")
        if self.repeat_policy not in _REPEAT_POLICIES:
            raise ValueError("staging operation repeat policy is invalid")
        if not isinstance(self.cancellable, bool):
            raise ValueError("staging operation cancellation flag is invalid")
        if self.public_description_category != self.operation_group.value:
            raise ValueError("staging operation description category is invalid")
        if not self.source_module.startswith("repomap_kg.storage."):
            raise ValueError("staging operation source module is invalid")
        if not self.source_symbol or self.source_symbol.strip() != self.source_symbol:
            raise ValueError("staging operation source symbol is invalid")

    def to_public_payload(self) -> dict[str, object]:
        """Return only structural fields safe for public profile output."""

        return {
            "schema_version": self.schema_version,
            "operation_code": self.operation_code,
            "operation_group": self.operation_group.value,
            "family": self.family,
            "transaction_scope": self.transaction_scope,
            "expected_parent": self.expected_parent,
            "repeat_policy": self.repeat_policy,
            "cancellable": self.cancellable,
            "public_description_category": self.public_description_category,
        }


def _descriptor(
    code: str,
    group: StagingOperationGroup,
    *,
    family: StageFamily | None = None,
    scope: str = "final_publication",
    repeat_policy: str = "once_per_attempt",
    source_module: str,
    source_symbol: str,
) -> StagingOperationDescriptor:
    return StagingOperationDescriptor(
        _SCHEMA_VERSION,
        code,
        group,
        family,
        scope,
        None,
        repeat_policy,
        True,
        group.value,
        source_module,
        source_symbol,
    )


_DESCRIPTORS = (
    _descriptor(
        "statistics.canonical_node_evidence",
        StagingOperationGroup.STAGE_STATISTICS,
        family="canonical_node_evidence",
        scope="stage_preparation",
        source_module="repomap_kg.storage.staged_ingestion",
        source_symbol="_refresh_canonical_node_evidence_statistics",
    ),
    *(
        _descriptor(
            f"completeness.{family}",
            StagingOperationGroup.COMPLETENESS_VALIDATION,
            family=family,
            scope="stage_preparation",
            repeat_policy="once_per_family",
            source_module="repomap_kg.storage.staged_validation",
            source_symbol="validate_stage",
        )
        for family in STAGING_FAMILY_DESCRIPTORS
    ),
    _descriptor(
        "guard.publication_prepare",
        StagingOperationGroup.SEMANTIC_GUARD,
        source_module="repomap_kg.storage.publication_fencing",
        source_symbol="build_publication_prepare_statements",
    ),
    _descriptor(
        "transaction.mark_merging",
        StagingOperationGroup.TRANSACTION_CONTROL,
        source_module="repomap_kg.storage.publication_fencing",
        source_symbol="build_publication_prepare_statements",
    ),
    _descriptor(
        "guard.source_index_stage",
        StagingOperationGroup.SEMANTIC_GUARD,
        source_module="repomap_kg.storage.staging_merge",
        source_symbol="_stage_guard",
    ),
    _descriptor(
        "guard.source_index_proposals",
        StagingOperationGroup.SEMANTIC_GUARD,
        source_module="repomap_kg.storage.staging_merge",
        source_symbol="_proposal_guard",
    ),
    _descriptor(
        "merge.files",
        StagingOperationGroup.MERGE,
        family="files",
        source_module="repomap_kg.storage.staging_merge",
        source_symbol="_files_merge",
    ),
    _descriptor(
        "merge.raw_observations",
        StagingOperationGroup.MERGE,
        family="raw_observations",
        source_module="repomap_kg.storage.staging_merge",
        source_symbol="_raw_merge",
    ),
    _descriptor(
        "guard.canonical_stage",
        StagingOperationGroup.SEMANTIC_GUARD,
        source_module="repomap_kg.storage.staging_merge",
        source_symbol="_stage_guard",
    ),
    _descriptor(
        "guard.canonical_proposals",
        StagingOperationGroup.SEMANTIC_GUARD,
        source_module="repomap_kg.storage.canonical_staging_merge",
        source_symbol="_proposal_guard",
    ),
    _descriptor(
        "guard.canonical_raw_reference",
        StagingOperationGroup.SEMANTIC_GUARD,
        family="canonical_evidence",
        source_module="repomap_kg.storage.canonical_staging_merge",
        source_symbol="_raw_reference_guard",
    ),
    _descriptor(
        "merge.canonical_nodes",
        StagingOperationGroup.MERGE,
        family="canonical_nodes",
        source_module="repomap_kg.storage.canonical_staging_merge",
        source_symbol="_canonical_nodes_merge",
    ),
    _descriptor(
        "merge.canonical_evidence",
        StagingOperationGroup.MERGE,
        family="canonical_evidence",
        source_module="repomap_kg.storage.canonical_staging_merge",
        source_symbol="_canonical_evidence_merge",
    ),
    _descriptor(
        "guard.canonical_edge_reference",
        StagingOperationGroup.SEMANTIC_GUARD,
        family="canonical_edges",
        source_module="repomap_kg.storage.canonical_staging_merge",
        source_symbol="_canonical_edge_reference_guard",
    ),
    _descriptor(
        "merge.canonical_edges",
        StagingOperationGroup.MERGE,
        family="canonical_edges",
        source_module="repomap_kg.storage.canonical_staging_merge",
        source_symbol="_canonical_edges_merge",
    ),
    _descriptor(
        "guard.canonical_node_evidence_reference",
        StagingOperationGroup.SEMANTIC_GUARD,
        family="canonical_node_evidence",
        source_module="repomap_kg.storage.canonical_staging_merge",
        source_symbol="_canonical_node_evidence_reference_guard",
    ),
    _descriptor(
        "merge.canonical_node_evidence",
        StagingOperationGroup.MERGE,
        family="canonical_node_evidence",
        source_module="repomap_kg.storage.canonical_staging_merge",
        source_symbol="_canonical_node_evidence_merge",
    ),
    _descriptor(
        "guard.canonical_edge_evidence_reference",
        StagingOperationGroup.SEMANTIC_GUARD,
        family="canonical_edge_evidence",
        source_module="repomap_kg.storage.canonical_staging_merge",
        source_symbol="_canonical_edge_evidence_reference_guard",
    ),
    _descriptor(
        "merge.canonical_edge_evidence",
        StagingOperationGroup.MERGE,
        family="canonical_edge_evidence",
        source_module="repomap_kg.storage.canonical_staging_merge",
        source_symbol="_canonical_edge_evidence_merge",
    ),
    _descriptor(
        "guard.publication_finalize",
        StagingOperationGroup.SEMANTIC_GUARD,
        source_module="repomap_kg.storage.publication_fencing",
        source_symbol="build_publication_finalize_statements",
    ),
    _descriptor(
        "receipt.finalize",
        StagingOperationGroup.RECEIPT,
        source_module="repomap_kg.storage.publication_fencing",
        source_symbol="build_publication_finalize_statements",
    ),
    _descriptor(
        "transaction.commit",
        StagingOperationGroup.TRANSACTION_CONTROL,
        source_module="repomap_kg.storage.staged_ingestion",
        source_symbol="_run_staged_full_refresh_admitted",
    ),
    _descriptor(
        "cleanup.stage",
        StagingOperationGroup.CLEANUP,
        scope="cleanup",
        source_module="repomap_kg.storage.staging_cleanup",
        source_symbol="execute_stage_cleanup",
    ),
)

STAGING_OPERATION_DESCRIPTORS: Mapping[
    str, StagingOperationDescriptor
] = MappingProxyType(
    {descriptor.operation_code: descriptor for descriptor in _DESCRIPTORS}
)

_MERGE_OPERATION_CODES: Mapping[MergeOperation, str] = MappingProxyType(
    {
        MergeOperation.FILES: "merge.files",
        MergeOperation.RAW_OBSERVATIONS: "merge.raw_observations",
        MergeOperation.CANONICAL_RAW_REFERENCE: (
            "guard.canonical_raw_reference"
        ),
        MergeOperation.CANONICAL_NODES: "merge.canonical_nodes",
        MergeOperation.CANONICAL_EVIDENCE: "merge.canonical_evidence",
        MergeOperation.CANONICAL_EDGE_REFERENCE: (
            "guard.canonical_edge_reference"
        ),
        MergeOperation.CANONICAL_EDGES: "merge.canonical_edges",
        MergeOperation.CANONICAL_NODE_EVIDENCE_REFERENCE: (
            "guard.canonical_node_evidence_reference"
        ),
        MergeOperation.CANONICAL_NODE_EVIDENCE: (
            "merge.canonical_node_evidence"
        ),
        MergeOperation.CANONICAL_EDGE_EVIDENCE_REFERENCE: (
            "guard.canonical_edge_evidence_reference"
        ),
        MergeOperation.CANONICAL_EDGE_EVIDENCE: (
            "merge.canonical_edge_evidence"
        ),
    }
)


def operation_descriptor(operation_code: str) -> StagingOperationDescriptor:
    """Return one exact descriptor or fail closed for an unknown code."""

    try:
        return STAGING_OPERATION_DESCRIPTORS[operation_code]
    except (KeyError, TypeError) as error:
        raise ValueError("staging operation code is invalid") from error


def operation_code_for_merge(operation: MergeOperation) -> str:
    """Return the exact operation code for one descriptor merge binding."""

    try:
        return _MERGE_OPERATION_CODES[operation]
    except (KeyError, TypeError) as error:
        raise ValueError("staging merge operation is invalid") from error
