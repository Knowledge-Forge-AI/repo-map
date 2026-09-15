"""Closed descriptors for the retained staging families."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from repomap_kg.storage.staging_family_rows import (
    StageCanonicalEdgeEvidenceRow,
    StageCanonicalEdgeRow,
    StageCanonicalEvidenceRow,
    StageCanonicalNodeEvidenceRow,
    StageCanonicalNodeRow,
    StageFamily,
    StageFileRow,
    StageRawObservationRow,
)
from repomap_kg.storage.staging_merge_operations import MergeOperation


class ChecksumStrategy(Enum):
    """Client-side transfer receipt strategy used before COPY."""

    TRUSTED_CANONICAL_JSON_SHA256 = "trusted_canonical_json_sha256"


class DuplicatePolicy(Enum):
    """Accepted duplicate identity behavior within one stage."""

    IDENTICAL_ONLY = "identical_only"
    LATEST_PROPOSAL = "latest_proposal"
    SOURCE_ORDINAL_IDEMPOTENT = "source_ordinal_idempotent"
    SET_DEDUPLICATED = "set_deduplicated"


class ProposalPolicy(Enum):
    """How staged proposals become one final mutation input."""

    IDENTITY_COLLAPSE = "identity_collapse"
    LATEST_BY_ORDINAL = "latest_by_ordinal"
    SOURCE_ORDER = "source_order"
    LOGICAL_SET = "logical_set"


class ValidationRule(Enum):
    """Family-specific validation required before final mutation."""

    ROW_COUNT = "row_count"
    DDL_CONSTRAINTS = "ddl_constraints"
    IDENTITY_CONFLICT = "identity_conflict"
    EXISTING_PAYLOAD_HASH = "existing_payload_hash"
    RAW_OBSERVATION_REFERENCE = "raw_observation_reference"
    NODE_REFERENCE = "node_reference"
    EDGE_REFERENCE = "edge_reference"
    EVIDENCE_REFERENCE = "evidence_reference"


class RetentionPolicy(Enum):
    """Stage-row retention authority."""

    STAGE_LIFETIME = "stage_lifetime"


class PrivacyClassification(Enum):
    """Highest-sensitivity payload class carried by a family."""

    PUBLIC = "public"
    SOURCE_INDEX = "source_index"
    LEGACY_GRAPH = "legacy_graph"
    RAW_SOURCE = "raw_source"
    CANONICAL_GRAPH = "canonical_graph"
    CANONICAL_PROVENANCE = "canonical_provenance"


@dataclass(frozen=True)
class StageFamilyDescriptor:
    """One exhaustive, immutable staging-family contract."""

    family: StageFamily
    row_type: type
    stage_table: str
    copy_columns: tuple[str, ...]
    technical_ordinal: str
    semantic_ordinal: str | None
    identity_columns: tuple[str, ...]
    payload_columns: tuple[str, ...]
    nullable_columns: frozenset[str]
    checksum_strategy: ChecksumStrategy
    duplicate_policy: DuplicatePolicy
    proposal_policy: ProposalPolicy
    validation_rules: tuple[ValidationRule, ...]
    merge_dependencies: tuple[StageFamily, ...]
    merge_operations: tuple[MergeOperation, ...]
    retention_policy: RetentionPolicy
    privacy_classification: PrivacyClassification

    def __post_init__(self) -> None:
        columns = self.copy_columns
        if not columns or columns[0] != "stage_id" or len(set(columns)) != len(columns):
            raise ValueError("invalid staging family columns")
        if tuple(self.row_type.__annotations__) != columns:
            raise ValueError("staging row type does not match COPY columns")
        if self.technical_ordinal not in columns:
            raise ValueError("staging technical ordinal is missing")
        if self.semantic_ordinal is not None and self.semantic_ordinal not in columns:
            raise ValueError("staging semantic ordinal is missing")
        if not set(self.identity_columns) <= set(columns):
            raise ValueError("staging identity columns are invalid")
        expected_payload = tuple(
            column
            for column in columns
            if column != "stage_id" and column not in self.identity_columns
        )
        if self.payload_columns != expected_payload:
            raise ValueError("staging payload columns are invalid")
        if not self.nullable_columns <= set(columns):
            raise ValueError("staging nullable columns are invalid")
        if len(set(self.merge_dependencies)) != len(self.merge_dependencies):
            raise ValueError("staging merge dependencies are invalid")
        if self.family in self.merge_dependencies:
            raise ValueError("staging family cannot depend on itself")
        if not self.merge_operations or len(set(self.merge_operations)) != len(
            self.merge_operations
        ):
            raise ValueError("staging merge operations are invalid")
        required_rules = {ValidationRule.ROW_COUNT, ValidationRule.DDL_CONSTRAINTS}
        if not required_rules <= set(self.validation_rules):
            raise ValueError("staging validation rules are incomplete")


def _descriptor(
    family: StageFamily,
    row_type: type,
    *,
    stage_table: str,
    technical_ordinal: str,
    semantic_ordinal: str | None,
    identity_columns: tuple[str, ...],
    nullable_columns: frozenset[str],
    duplicate_policy: DuplicatePolicy,
    proposal_policy: ProposalPolicy,
    validation_rules: tuple[ValidationRule, ...],
    merge_dependencies: tuple[StageFamily, ...],
    merge_operations: tuple[MergeOperation, ...],
    privacy_classification: PrivacyClassification,
) -> StageFamilyDescriptor:
    columns = tuple(row_type.__annotations__)
    return StageFamilyDescriptor(
        family=family,
        row_type=row_type,
        stage_table=stage_table,
        copy_columns=columns,
        technical_ordinal=technical_ordinal,
        semantic_ordinal=semantic_ordinal,
        identity_columns=identity_columns,
        payload_columns=tuple(
            column
            for column in columns
            if column != "stage_id" and column not in identity_columns
        ),
        nullable_columns=nullable_columns,
        checksum_strategy=ChecksumStrategy.TRUSTED_CANONICAL_JSON_SHA256,
        duplicate_policy=duplicate_policy,
        proposal_policy=proposal_policy,
        validation_rules=validation_rules,
        merge_dependencies=merge_dependencies,
        merge_operations=merge_operations,
        retention_policy=RetentionPolicy.STAGE_LIFETIME,
        privacy_classification=privacy_classification,
    )


_BASE_VALIDATION = (ValidationRule.ROW_COUNT, ValidationRule.DDL_CONSTRAINTS)
_IDENTITY_VALIDATION = (*_BASE_VALIDATION, ValidationRule.IDENTITY_CONFLICT)


STAGING_FAMILY_DESCRIPTORS: Mapping[StageFamily, StageFamilyDescriptor] = (
    MappingProxyType(
        {
            "files": _descriptor(
                "files",
                StageFileRow,
                stage_table="stage_files",
                technical_ordinal="family_ordinal",
                semantic_ordinal=None,
                identity_columns=("path",),
                nullable_columns=frozenset({"content_hash"}),
                duplicate_policy=DuplicatePolicy.IDENTICAL_ONLY,
                proposal_policy=ProposalPolicy.IDENTITY_COLLAPSE,
                validation_rules=_IDENTITY_VALIDATION,
                merge_dependencies=(),
                merge_operations=(MergeOperation.FILES,),
                privacy_classification=PrivacyClassification.SOURCE_INDEX,
            ),
            "raw_observations": _descriptor(
                "raw_observations",
                StageRawObservationRow,
                stage_table="stage_raw_observations",
                technical_ordinal="source_ordinal",
                semantic_ordinal="source_ordinal",
                identity_columns=("source_ordinal",),
                nullable_columns=frozenset(),
                duplicate_policy=DuplicatePolicy.SOURCE_ORDINAL_IDEMPOTENT,
                proposal_policy=ProposalPolicy.SOURCE_ORDER,
                validation_rules=(
                    *_BASE_VALIDATION,
                    ValidationRule.EXISTING_PAYLOAD_HASH,
                ),
                merge_dependencies=(),
                merge_operations=(MergeOperation.RAW_OBSERVATIONS,),
                privacy_classification=PrivacyClassification.RAW_SOURCE,
            ),
            "canonical_nodes": _descriptor(
                "canonical_nodes",
                StageCanonicalNodeRow,
                stage_table="stage_canonical_nodes",
                technical_ordinal="family_ordinal",
                semantic_ordinal=None,
                identity_columns=("graph_key_version", "canonical_key"),
                nullable_columns=frozenset(),
                duplicate_policy=DuplicatePolicy.IDENTICAL_ONLY,
                proposal_policy=ProposalPolicy.IDENTITY_COLLAPSE,
                validation_rules=_IDENTITY_VALIDATION,
                merge_dependencies=(),
                merge_operations=(MergeOperation.CANONICAL_NODES,),
                privacy_classification=PrivacyClassification.CANONICAL_GRAPH,
            ),
            "canonical_edges": _descriptor(
                "canonical_edges",
                StageCanonicalEdgeRow,
                stage_table="stage_canonical_edges",
                technical_ordinal="family_ordinal",
                semantic_ordinal=None,
                identity_columns=(
                    "graph_key_version",
                    "source_canonical_key",
                    "edge_kind",
                    "target_canonical_key",
                    "identity_metadata_hash",
                ),
                nullable_columns=frozenset(),
                duplicate_policy=DuplicatePolicy.IDENTICAL_ONLY,
                proposal_policy=ProposalPolicy.IDENTITY_COLLAPSE,
                validation_rules=(
                    *_IDENTITY_VALIDATION,
                    ValidationRule.NODE_REFERENCE,
                ),
                merge_dependencies=("canonical_nodes",),
                merge_operations=(
                    MergeOperation.CANONICAL_EDGE_REFERENCE,
                    MergeOperation.CANONICAL_EDGES,
                ),
                privacy_classification=PrivacyClassification.CANONICAL_GRAPH,
            ),
            "canonical_evidence": _descriptor(
                "canonical_evidence",
                StageCanonicalEvidenceRow,
                stage_table="stage_canonical_evidence",
                technical_ordinal="family_ordinal",
                semantic_ordinal="raw_observation_ordinal",
                identity_columns=("graph_key_version", "evidence_key"),
                nullable_columns=frozenset({"start_line", "end_line"}),
                duplicate_policy=DuplicatePolicy.IDENTICAL_ONLY,
                proposal_policy=ProposalPolicy.IDENTITY_COLLAPSE,
                validation_rules=(
                    *_IDENTITY_VALIDATION,
                    ValidationRule.RAW_OBSERVATION_REFERENCE,
                ),
                merge_dependencies=("raw_observations",),
                merge_operations=(
                    MergeOperation.CANONICAL_RAW_REFERENCE,
                    MergeOperation.CANONICAL_EVIDENCE,
                ),
                privacy_classification=(
                    PrivacyClassification.CANONICAL_PROVENANCE
                ),
            ),
            "canonical_node_evidence": _descriptor(
                "canonical_node_evidence",
                StageCanonicalNodeEvidenceRow,
                stage_table="stage_canonical_node_evidence",
                technical_ordinal="family_ordinal",
                semantic_ordinal=None,
                identity_columns=(
                    "graph_key_version",
                    "canonical_key",
                    "evidence_key",
                    "link_kind",
                ),
                nullable_columns=frozenset(),
                duplicate_policy=DuplicatePolicy.SET_DEDUPLICATED,
                proposal_policy=ProposalPolicy.LOGICAL_SET,
                validation_rules=(
                    *_BASE_VALIDATION,
                    ValidationRule.NODE_REFERENCE,
                    ValidationRule.EVIDENCE_REFERENCE,
                ),
                merge_dependencies=("canonical_nodes", "canonical_evidence"),
                merge_operations=(
                    MergeOperation.CANONICAL_NODE_EVIDENCE_REFERENCE,
                    MergeOperation.CANONICAL_NODE_EVIDENCE,
                ),
                privacy_classification=PrivacyClassification.CANONICAL_GRAPH,
            ),
            "canonical_edge_evidence": _descriptor(
                "canonical_edge_evidence",
                StageCanonicalEdgeEvidenceRow,
                stage_table="stage_canonical_edge_evidence",
                technical_ordinal="family_ordinal",
                semantic_ordinal=None,
                identity_columns=(
                    "graph_key_version",
                    "source_canonical_key",
                    "edge_kind",
                    "target_canonical_key",
                    "identity_metadata_hash",
                    "evidence_key",
                    "link_kind",
                ),
                nullable_columns=frozenset(),
                duplicate_policy=DuplicatePolicy.SET_DEDUPLICATED,
                proposal_policy=ProposalPolicy.LOGICAL_SET,
                validation_rules=(
                    *_BASE_VALIDATION,
                    ValidationRule.EDGE_REFERENCE,
                    ValidationRule.EVIDENCE_REFERENCE,
                ),
                merge_dependencies=("canonical_edges", "canonical_evidence"),
                merge_operations=(
                    MergeOperation.CANONICAL_EDGE_EVIDENCE_REFERENCE,
                    MergeOperation.CANONICAL_EDGE_EVIDENCE,
                ),
                privacy_classification=PrivacyClassification.CANONICAL_GRAPH,
            ),
        }
    )
)
