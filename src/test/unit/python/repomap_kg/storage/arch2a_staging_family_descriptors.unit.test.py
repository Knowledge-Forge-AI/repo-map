from __future__ import annotations

import inspect
from pathlib import Path
import re

from repomap_kg.storage import canonical_staging_merge, staging_merge
from repomap_kg.storage.staging import STAGING_FAMILIES
from repomap_kg.storage.staging_copy import STAGING_COPY_TABLES
from repomap_kg.storage.staging_family_contracts import (
    ChecksumStrategy,
    DuplicatePolicy,
    PrivacyClassification,
    ProposalPolicy,
    RetentionPolicy,
    STAGING_FAMILY_DESCRIPTORS,
    ValidationRule,
)


def _migration_text() -> str:
    migration_name = "2026/07/14-001-scale1-create_staging_contract.sql"
    for parent in Path(__file__).resolve().parents:
        migration = parent / "src/main/resources/rdbms" / migration_name
        if migration.is_file():
            return migration.read_text(encoding="utf-8")
    raise AssertionError("staging migration is unavailable")


def _ddl_columns(table_name: str) -> tuple[tuple[str, ...], frozenset[str]]:
    match = re.search(
        rf"CREATE TABLE {re.escape(table_name)} \((.*?)\n\);",
        _migration_text(),
        flags=re.DOTALL,
    )
    assert match is not None
    lines = match.group(1).splitlines()
    columns: list[str] = []
    nullable: set[str] = set()
    index = 0
    while index < len(lines):
        declaration = re.match(
            r"    ([a-z][a-z0-9_]*) (TEXT|BIGINT|INTEGER|BOOLEAN|JSONB)\b(.*)",
            lines[index],
        )
        if declaration is None:
            index += 1
            continue
        name = declaration.group(1)
        clause = lines[index]
        while not clause.rstrip().endswith(","):
            index += 1
            clause += " " + lines[index].strip()
        columns.append(name)
        if "NOT NULL" not in clause:
            nullable.add(name)
        index += 1
    return tuple(columns), frozenset(nullable)


def test_arch2a_descriptors_are_closed_and_match_existing_mappings() -> None:
    assert tuple(STAGING_FAMILY_DESCRIPTORS) == STAGING_FAMILIES
    assert tuple(STAGING_COPY_TABLES) == STAGING_FAMILIES

    for family, descriptor in STAGING_FAMILY_DESCRIPTORS.items():
        copy_table = STAGING_COPY_TABLES[family]
        assert descriptor.family == family
        assert descriptor.stage_table == copy_table.table_name
        assert descriptor.copy_columns == copy_table.columns
        assert tuple(descriptor.row_type.__annotations__) == copy_table.columns
        assert descriptor.payload_columns == tuple(
            column
            for column in copy_table.columns
            if column != "stage_id" and column not in descriptor.identity_columns
        )
        assert descriptor.checksum_strategy is (
            ChecksumStrategy.TRUSTED_CANONICAL_JSON_SHA256
        )


def test_arch2a_descriptors_match_ddl_order_and_nullability() -> None:
    for descriptor in STAGING_FAMILY_DESCRIPTORS.values():
        columns, nullable = _ddl_columns(descriptor.stage_table)
        assert descriptor.copy_columns == columns
        assert descriptor.nullable_columns == nullable


def test_arch2a_ordinals_are_explicit_and_family_specific() -> None:
    raw = STAGING_FAMILY_DESCRIPTORS["raw_observations"]
    assert raw.technical_ordinal == "source_ordinal"
    assert raw.semantic_ordinal == "source_ordinal"

    for family, descriptor in STAGING_FAMILY_DESCRIPTORS.items():
        if family != "raw_observations":
            assert descriptor.technical_ordinal == "family_ordinal"

    evidence = STAGING_FAMILY_DESCRIPTORS["canonical_evidence"]
    assert evidence.semantic_ordinal == "raw_observation_ordinal"
    for family, descriptor in STAGING_FAMILY_DESCRIPTORS.items():
        if family not in {"raw_observations", "canonical_evidence"}:
            assert descriptor.semantic_ordinal is None


def test_arch2a_policies_and_dependencies_are_exhaustive() -> None:
    prior_families: set[str] = set()
    for descriptor in STAGING_FAMILY_DESCRIPTORS.values():
        assert ValidationRule.ROW_COUNT in descriptor.validation_rules
        assert ValidationRule.DDL_CONSTRAINTS in descriptor.validation_rules
        assert set(descriptor.merge_dependencies) <= prior_families
        assert descriptor.retention_policy is RetentionPolicy.STAGE_LIFETIME
        assert descriptor.privacy_classification is not PrivacyClassification.PUBLIC
        prior_families.add(descriptor.family)

    assert STAGING_FAMILY_DESCRIPTORS["files"].duplicate_policy is (
        DuplicatePolicy.IDENTICAL_ONLY
    )
    assert STAGING_FAMILY_DESCRIPTORS["raw_observations"].duplicate_policy is (
        DuplicatePolicy.SOURCE_ORDINAL_IDEMPOTENT
    )
    for family in ("canonical_node_evidence", "canonical_edge_evidence"):
        descriptor = STAGING_FAMILY_DESCRIPTORS[family]
        assert descriptor.duplicate_policy is DuplicatePolicy.SET_DEDUPLICATED
        assert descriptor.proposal_policy is ProposalPolicy.LOGICAL_SET

    evidence = STAGING_FAMILY_DESCRIPTORS["canonical_evidence"]
    assert ValidationRule.RAW_OBSERVATION_REFERENCE in evidence.validation_rules
    assert evidence.merge_dependencies == ("raw_observations",)


def test_arch2a_every_descriptor_has_existing_merge_and_cleanup_ownership() -> None:
    merge_source = inspect.getsource(staging_merge) + inspect.getsource(
        canonical_staging_merge
    )
    for descriptor in STAGING_FAMILY_DESCRIPTORS.values():
        assert descriptor.stage_table in merge_source
