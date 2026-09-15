from __future__ import annotations

from typing import TYPE_CHECKING

import repomap_kg.storage as storage
if TYPE_CHECKING:
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.observations import RawObservation
from repomap_kg.storage import main as storage_main
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_kg.storage.staging_copy import STAGING_COPY_TABLES
from repomap_kg.storage.staging_family_catalog import merge_operations_for_scope
from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS
from repomap_kg.storage.staging_merge_operations import MergeOperation, MergeScope


_ACTIVE_FAMILIES = (
    "files",
    "raw_observations",
    "canonical_nodes",
    "canonical_edges",
    "canonical_evidence",
    "canonical_node_evidence",
    "canonical_edge_evidence",
)


def test_arch4c_removes_receiptless_programmatic_mutation_primitives() -> None:
    assert not hasattr(storage, "load_file_observations")
    assert not hasattr(storage, "load_canonical_observations")
    assert not hasattr(storage_main, "load_file_observations")
    assert not hasattr(storage_main, "load_canonical_observations")


def test_arch4c_active_staging_catalog_excludes_legacy_graph_families() -> None:
    assert tuple(STAGING_FAMILY_DESCRIPTORS) == _ACTIVE_FAMILIES
    assert tuple(STAGING_COPY_TABLES) == _ACTIVE_FAMILIES
    assert tuple(
        binding.operation
        for binding in merge_operations_for_scope(MergeScope.SOURCE_INDEX)
    ) == (MergeOperation.FILES, MergeOperation.RAW_OBSERVATIONS)


def test_arch4c_staged_rows_do_not_construct_legacy_graph_projections() -> None:
    prepared = build_staged_rows(
        (
            RawObservation(
                kind="file",
                source_id="README.md",
                path="README.md",
                confidence="extracted",
                extractor="fixture",
                extractor_version="1.0.0",
                metadata={"language": "markdown", "role": "documentation"},
            ),
        ),
        repository_name="fixture",
        stage_id="stage-arch4c",
    )

    assert tuple(prepared.family_rows) == _ACTIVE_FAMILIES
    assert not {"legacy_nodes", "legacy_edges", "legacy_evidence"} & set(
        prepared.row_counts
    )
