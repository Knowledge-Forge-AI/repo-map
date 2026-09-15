from __future__ import annotations

import pytest

from repomap_kg.storage.canonical_staging_merge import (
    build_canonical_merge_statements,
)
from repomap_kg.storage.staged_ingestion import (
    _refresh_canonical_node_evidence_statistics,
)
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.staging_merge import MergeContext, MergeContractError
from repomap_kg.storage.staging_ownership import StageOwner


def context() -> MergeContext:
    return MergeContext(
        stage_id="stage-canonical-001",
        owner=StageOwner(
            repository_id=7,
            operation_id=OperationId("operation-stage-canonical-001"),
            attempt=AttemptNumber(1),
            execution_mode="direct",
            source_generation="sg1:source",
            config_generation="cg1:config",
            extractor_generation="eg1:extractor",
            canonicalizer_generation="kg1:canonicalizer",
        ),
        run_id=11,
    )


def test_canonical_builder_reuses_validated_context() -> None:
    assert len(build_canonical_merge_statements(context())) == 11

    with pytest.raises(MergeContractError):
        build_canonical_merge_statements(
            MergeContext(stage_id="unsafe/source", owner=context().owner, run_id=11)
        )


def test_canonical_builder_is_caller_owned_and_set_based() -> None:
    statements = build_canonical_merge_statements(context())
    sql = "\n".join(statements)

    assert all("BEGIN;" not in statement and "COMMIT;" not in statement for statement in statements)
    assert sql.count("DISTINCT ON") >= 4
    assert "stage_canonical_nodes" in sql
    assert "stage_canonical_edges" in sql
    assert "stage_canonical_evidence" in sql
    assert "stage_canonical_node_evidence" in sql
    assert "stage_canonical_edge_evidence" in sql
    assert "ON CONFLICT (repository_id, graph_key_version, canonical_key)" in sql
    assert "ON CONFLICT (run_id, graph_key_version, evidence_key)" in sql
    assert "ON CONFLICT DO NOTHING" in sql


def test_canonical_builder_rejects_order_dependent_proposals_and_missing_references() -> None:
    statements = build_canonical_merge_statements(context())
    sql = "\n".join(statements)
    edge_reference_guard = statements[5]
    node_evidence_reference_guard = statements[7]

    assert sql.count("COUNT(DISTINCT (") >= 3
    assert "SCALE4 stage validation conflict" in sql
    assert "SCALE4 raw observation reference is missing" in sql
    assert "SCALE4 canonical edge reference is missing" in sql
    assert "SCALE4 canonical node-evidence reference is missing" in sql
    assert "SCALE4 canonical edge-evidence reference is missing" in sql
    assert "family_ordinal" in sql
    assert "ORDER BY s.graph_key_version" in sql
    assert "NOT EXISTS" in edge_reference_guard
    assert "LEFT JOIN canonical_nodes" not in edge_reference_guard
    assert node_evidence_reference_guard.count("FULL JOIN") == 2
    assert node_evidence_reference_guard.count("IF EXISTS") == 2
    assert "NOT EXISTS" not in node_evidence_reference_guard
    assert "LEFT JOIN canonical_nodes" not in node_evidence_reference_guard
    assert "LEFT JOIN canonical_evidence" not in node_evidence_reference_guard


def test_node_evidence_guard_uses_narrow_spill_capable_identity_checks() -> None:
    guard = build_canonical_merge_statements(context())[7]

    assert "SELECT staged.graph_key_version, staged.canonical_key" in guard
    assert "SELECT node.graph_key_version, node.canonical_key" in guard
    assert "SELECT staged.graph_key_version, staged.evidence_key" in guard
    assert "SELECT evidence.graph_key_version, evidence.evidence_key" in guard
    assert "COALESCE(staged.canonical_key, '') <> ''" in guard
    assert "COALESCE(staged.evidence_key, '') <> ''" in guard
    assert "node.canonical_key IS NULL" in guard
    assert "evidence.evidence_key IS NULL" in guard
    assert "link_kind" not in guard
    assert "metadata_json" not in guard
    assert "display_name" not in guard


def test_node_evidence_merge_deduplicates_staged_logical_identities() -> None:
    merge = build_canonical_merge_statements(context())[8]

    assert "WITH staged_links AS MATERIALIZED" in merge
    assert "GROUP BY s.graph_key_version, s.canonical_key, s.evidence_key, s.link_kind" in merge
    assert "FROM staged_links s" in merge
    assert "evidence.id AS canonical_evidence_id" in merge
    assert "SELECT DISTINCT\n" not in merge
    assert "SELECT DISTINCT ON" not in merge
    assert "ORDER BY" not in merge
    assert "family_ordinal" not in merge
    assert "ON CONFLICT DO NOTHING" in merge


def test_node_evidence_statistics_refresh_is_single_and_targeted() -> None:
    statements: list[str] = []

    class Connection:
        def execute(self, statement: str) -> None:
            statements.append(statement)

    _refresh_canonical_node_evidence_statistics(Connection())

    assert statements == ["ANALYZE stage_canonical_node_evidence"]


def test_canonical_builder_preserves_complete_owner_literals_and_no_private_data() -> None:
    sql = "\n".join(build_canonical_merge_statements(context()))

    assert "'stage-canonical-001'" in sql
    assert "repository_id = 7" in sql
    assert "run_id = 11" in sql
    assert "operation-stage-canonical-001" in sql
    assert "sg1:source" in sql
    assert "/private" not in sql
