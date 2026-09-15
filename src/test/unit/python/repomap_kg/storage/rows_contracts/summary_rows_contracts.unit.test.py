from __future__ import annotations


import pytest

from repomap_kg.storage.errors import StorageSchemaError


def test_storage_summary_from_payload_and_load_summary_from_payload_contracts_remain_stable() -> None:
    import repomap_kg.storage.summary_rows_storage as summary_rows_storage
    load_summary = summary_rows_storage.load_summary_from_payload(
        {"repository_id": "7", "run_id": "11", "files": "13"}
    )
    assert load_summary == summary_rows_storage.LoadSummary(
        repository_id=7,
        run_id=11,
        files=13,
    )

    canonical_load_summary = summary_rows_storage.canonical_load_summary_from_payload(
        {
            "repository_id": "7",
            "run_id": "11",
            "raw_observations": "13",
            "canonical_nodes": "21",
            "canonical_edges": "34",
            "canonical_evidence": "55",
            "canonical_node_evidence_links": "89",
            "canonical_edge_evidence_links": "144",
        }
    )
    assert canonical_load_summary == summary_rows_storage.CanonicalLoadSummary(
        repository_id=7,
        run_id=11,
        raw_observations=13,
        canonical_nodes=21,
        canonical_edges=34,
        canonical_evidence=55,
        canonical_node_evidence_links=89,
        canonical_edge_evidence_links=144,
    )

    canonical_storage_summary = (
        summary_rows_storage.canonical_storage_summary_from_payload(
            {
                "root_path": "/tmp/repo's root",
                "repository_name": "repo-map",
                "latest_run_id": "11",
                "runs": "3",
                "files": "13",
                "raw_observations": "89",
                "latest_run_raw_observations": "34",
                "canonical_nodes": "233",
                "canonical_edges": "377",
                "canonical_evidence": "610",
            }
        )
    )
    assert canonical_storage_summary.to_dict() == {
        "root_path": "/tmp/repo's root",
        "repository_name": "repo-map",
        "latest_run_id": 11,
        "runs": 3,
        "files": 13,
        "raw_observations": 89,
        "canonical_nodes": 233,
        "canonical_edges": 377,
        "canonical_evidence": 610,
        "raw_observations_total": 89,
        "latest_run_raw_observations": 34,
    }

    canonical_storage_summary_with_total = (
        summary_rows_storage.canonical_storage_summary_from_payload(
            {
                "root_path": "/tmp/repo",
                "repository_name": None,
                "latest_run_id": None,
                "runs": "3",
                "files": "13",
                "raw_observations": "34",
                "raw_observations_total": "89",
                "latest_run_raw_observations": None,
                "canonical_nodes": "21",
                "canonical_edges": "13",
                "canonical_evidence": "8",
            }
        )
    )
    assert canonical_storage_summary_with_total.to_dict()[
        "raw_observations_total"
    ] == 89

def test_storage_summary_rows_core_private_helpers_remain_internal() -> None:
    import repomap_kg.storage.summary_rows as summary_rows
    import repomap_kg.storage.summary_rows_core as summary_rows_core
    assert summary_rows._count_from_mapping is summary_rows_core._count_from_mapping
    assert (
        summary_rows._required_count_map_from_mapping
        is summary_rows_core._required_count_map_from_mapping
    )
    assert "_count_from_mapping" not in summary_rows.__all__
    assert "_required_count_map_from_mapping" not in summary_rows.__all__

    assert summary_rows_core._count_from_mapping(
        {"items": "3"},
        "items",
        label="unit summary",
    ) == 3
    assert summary_rows_core._required_count_map_from_mapping(
        {"counts": {"first": "1", "second": 2}},
        "counts",
        ("first", "second"),
        label="unit summary",
    ) == {"first": 1, "second": 2}
    with pytest.raises(
        StorageSchemaError,
        match="psql returned a malformed unit summary: missing",
    ):
        summary_rows_core._count_from_mapping(
            {},
            "missing",
            label="unit summary",
        )


@pytest.mark.parametrize(
    "parser,label",
    (
        ("canonical_storage_summary_from_payload", "canonical storage summary"),
        ("load_summary_from_payload", "load summary"),
        ("canonical_load_summary_from_payload", "canonical load summary"),
    ),
)
def test_storage_summary_payload_parsers_reject_non_mapping_payloads(
    parser: str,
    label: str,
) -> None:
    import repomap_kg.storage.summary_rows_storage as summary_rows_storage
    with pytest.raises(
        StorageSchemaError,
        match=f"psql returned a malformed {label}",
    ):
        getattr(summary_rows_storage, parser)([])
