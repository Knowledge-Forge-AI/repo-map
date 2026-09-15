from __future__ import annotations

from pathlib import Path

from repomap_kg.storage.row_spool import RowSpool
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_kg.storage.staging_family_contracts import (
    STAGING_FAMILY_DESCRIPTORS,
)
import scale11_profile_workloads as scale11_profile_workloads

REPO_ROOT = Path(__file__).resolve().parents[5]
EXPECTED_FAMILIES = (
    "files",
    "raw_observations",
    "canonical_nodes",
    "canonical_edges",
    "canonical_evidence",
    "canonical_node_evidence",
    "canonical_edge_evidence",
)


def load_tool_module():
    return scale11_profile_workloads


def test_closed_profiles_and_geometric_bands_are_exact() -> None:
    tool = load_tool_module()

    assert tool.FAMILIES == EXPECTED_FAMILIES
    assert tool.MEASURED_SIZE_BANDS == (128, 512, 2_048, 8_192)
    assert tool.WARMUP_SIZE == 32
    assert tool.PROFILES == (
        "file_raw_heavy",
        "canonical_node_evidence_heavy",
        "canonical_edge_evidence_heavy",
        "duplicate_proposal_heavy",
        "payload_heavy",
        "mixed",
    )


def test_workloads_are_deterministic_public_safe_and_reference_valid() -> None:
    tool = load_tool_module()

    for profile in tool.PROFILES:
        first = tool.build_workload(profile, 32)
        second = tool.build_workload(profile, 32)
        assert first == second
        assert first.work_items == 32
        assert first.normalized_bytes > 0
        assert first.observations
        assert all(observation.path.startswith("fixture/") for observation in first.observations)
        assert all("/Users/" not in observation.to_json_line() for observation in first.observations)

        prepared = build_staged_rows(
            first.observations,
            repository_name="scale11-public-fixture",
            stage_id="00000000-0000-0000-0000-000000000011",
        )
        try:
            assert tuple(prepared.row_counts) == EXPECTED_FAMILIES
            assert all(prepared.row_counts[family] > 0 for family in EXPECTED_FAMILIES)
        finally:
            prepared.close()


def test_largest_band_activates_multiple_family_spools() -> None:
    tool = load_tool_module()
    workload = tool.build_workload("mixed", tool.MEASURED_SIZE_BANDS[-1])

    prepared = build_staged_rows(
        workload.observations,
        repository_name="scale11-public-fixture",
        stage_id="00000000-0000-0000-0000-000000000011",
    )
    try:
        spooled = tuple(
            family
            for family, rows in prepared.family_rows.items()
            if isinstance(rows, RowSpool)
        )
        assert len(spooled) >= 2
        assert "raw_observations" in spooled
        assert "canonical_evidence" in spooled
    finally:
        prepared.close()


def test_duplicate_profile_collapses_canonical_proposals() -> None:
    tool = load_tool_module()
    workload = tool.build_workload("duplicate_proposal_heavy", 128)

    prepared = build_staged_rows(
        workload.observations,
        repository_name="scale11-public-fixture",
        stage_id="00000000-0000-0000-0000-000000000011",
    )
    try:
        assert prepared.row_counts["raw_observations"] > prepared.row_counts["canonical_edges"] * 3
        assert prepared.row_counts["canonical_edge_evidence"] > prepared.row_counts["canonical_edges"]
    finally:
        prepared.close()


def test_invalid_profile_and_size_are_rejected() -> None:
    tool = load_tool_module()

    for profile, size in (("unknown", 32), ("mixed", 0), ("mixed", 8_193), ("mixed", True)):
        try:
            tool.build_workload(profile, size)
        except tool.Scale11WorkloadError:
            continue
        raise AssertionError("invalid workload input was accepted")


def test_active_manifest_has_exactly_seven_families_and_no_legacy_runtime_work() -> None:
    assert tuple(STAGING_FAMILY_DESCRIPTORS) == EXPECTED_FAMILIES
    assert {
        descriptor.stage_table
        for descriptor in STAGING_FAMILY_DESCRIPTORS.values()
    } == {
        "stage_files",
        "stage_raw_observations",
        "stage_canonical_nodes",
        "stage_canonical_edges",
        "stage_canonical_evidence",
        "stage_canonical_node_evidence",
        "stage_canonical_edge_evidence",
    }
    active_contract = repr(tuple(STAGING_FAMILY_DESCRIPTORS.values())).lower()
    for legacy_token in (
        "stage_nodes'",
        "stage_edges'",
        "stage_evidence'",
        "legacy_graph",
        "legacy_node",
        "legacy_edge",
        "legacy_evidence",
    ):
        assert legacy_token not in active_contract

    profiler_source = (
        REPO_ROOT / "tools" / "scale11_profile_normalized_ingestion.py"
    ).read_text(encoding="utf-8")
    assert "publish_observation_generation" not in profiler_source
    assert "fallback" not in profiler_source.lower()
