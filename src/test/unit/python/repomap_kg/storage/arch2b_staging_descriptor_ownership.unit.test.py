from __future__ import annotations

import inspect

from repomap_kg.storage import (
    publication_fencing,
    staged_rows,
    staged_validation,
    staging_cleanup,
    staging_copy,
)
from repomap_kg.storage.staging import STAGING_FAMILIES
from repomap_kg.storage.staging_checksums import checksum_family
from repomap_kg.storage.staging_family_catalog import (
    family_privacy_classifications,
    merge_operations_for_scope,
)
from repomap_kg.storage.staging_family_contracts import (
    PrivacyClassification,
    STAGING_FAMILY_DESCRIPTORS,
)
from repomap_kg.storage.staging_merge_operations import MergeOperation, MergeScope


def test_arch2b_registry_owns_family_copy_and_privacy_catalogs() -> None:
    assert STAGING_FAMILIES == tuple(STAGING_FAMILY_DESCRIPTORS)
    assert tuple(staging_copy.STAGING_COPY_TABLES) == STAGING_FAMILIES
    assert family_privacy_classifications() == {
        family: descriptor.privacy_classification
        for family, descriptor in STAGING_FAMILY_DESCRIPTORS.items()
    }
    assert all(
        classification is not PrivacyClassification.PUBLIC
        for classification in family_privacy_classifications().values()
    )

    for family, descriptor in STAGING_FAMILY_DESCRIPTORS.items():
        table = staging_copy.STAGING_COPY_TABLES[family]
        assert table.descriptor is descriptor
        assert table.table_name == descriptor.stage_table
        assert table.columns == descriptor.copy_columns
        assert table.ordinal_column == descriptor.technical_ordinal


def test_arch2b_generic_row_adaptation_uses_explicit_descriptor_ordinal() -> None:
    files = STAGING_FAMILY_DESCRIPTORS["files"]
    file_row = staged_rows._stage_row(
        files,
        "stage-owned",
        4,
        {column: None for column in files.copy_columns[2:]},
    )
    assert tuple(file_row) == files.copy_columns
    assert file_row["family_ordinal"] == 4

    raw = STAGING_FAMILY_DESCRIPTORS["raw_observations"]
    raw_payload: dict[str, object] = {column: None for column in raw.copy_columns[2:]}
    raw_payload["source_ordinal"] = 9
    raw_row = staged_rows._stage_row(raw, "stage-owned", 4, raw_payload)
    assert tuple(raw_row) == raw.copy_columns
    assert raw_row["source_ordinal"] == 9
    assert "family_ordinal" not in raw_row


def test_arch2b_merge_operations_are_descriptor_owned_and_ordered() -> None:
    legacy = tuple(
        binding.operation
        for binding in merge_operations_for_scope(MergeScope.SOURCE_INDEX)
    )
    canonical = tuple(
        binding.operation
        for binding in merge_operations_for_scope(MergeScope.CANONICAL)
    )

    assert legacy == (
        MergeOperation.FILES,
        MergeOperation.RAW_OBSERVATIONS,
    )
    assert canonical == (
        MergeOperation.CANONICAL_RAW_REFERENCE,
        MergeOperation.CANONICAL_NODES,
        MergeOperation.CANONICAL_EVIDENCE,
        MergeOperation.CANONICAL_EDGE_REFERENCE,
        MergeOperation.CANONICAL_EDGES,
        MergeOperation.CANONICAL_NODE_EVIDENCE_REFERENCE,
        MergeOperation.CANONICAL_NODE_EVIDENCE,
        MergeOperation.CANONICAL_EDGE_EVIDENCE_REFERENCE,
        MergeOperation.CANONICAL_EDGE_EVIDENCE,
    )


def test_arch2b_same_count_mutation_changes_trusted_transfer_receipt() -> None:
    descriptor = STAGING_FAMILY_DESCRIPTORS["files"]
    first = checksum_family(
        ({"path": "a", "payload": "first"},),
        identity_fields=descriptor.identity_columns,
    )
    mutated = checksum_family(
        ({"path": "a", "payload": "other"},),
        identity_fields=descriptor.identity_columns,
    )

    assert first.row_count == mutated.row_count == 1
    assert first.stable_key_digest == mutated.stable_key_digest
    assert first.payload_digest != mutated.payload_digest


def test_arch2b_runtime_modules_do_not_recreate_family_metadata() -> None:
    assert not hasattr(staged_rows, "_IDENTITY_FIELDS")
    assert not hasattr(staged_rows, "_raw_indexed")
    assert "_CATALOG_TABLE_NAMES" not in inspect.getsource(staging_copy)
    assert "STAGING_COPY_TABLES" not in inspect.getsource(staged_validation)
    assert 'f"stage_{family}"' not in inspect.getsource(staging_cleanup)
    assert 'f"stage_{family}"' not in inspect.getsource(publication_fencing)
