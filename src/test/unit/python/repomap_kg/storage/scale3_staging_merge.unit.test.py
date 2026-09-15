from __future__ import annotations

import pytest

from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.staging_merge import (
    MergeContractError,
    MergeContext,
    build_source_index_merge_statements,
)
from repomap_kg.storage.staging_ownership import StageOwner


def context() -> MergeContext:
    return MergeContext(
        stage_id="stage-merge-001",
        owner=StageOwner(
            repository_id=7,
            operation_id=OperationId("operation-stage-merge-001"),
            attempt=AttemptNumber(1),
            execution_mode="direct",
            source_generation="sg1:source",
            config_generation="cg1:config",
            extractor_generation="eg1:extractor",
            canonicalizer_generation="kg1:canonicalizer",
        ),
        run_id=11,
    )


def test_merge_context_requires_safe_stage_and_positive_database_ids() -> None:
    assert context().validate() == context()

    with pytest.raises(MergeContractError):
        MergeContext(
            stage_id="/synthetic-source", owner=context().owner, run_id=11
        ).validate()
    with pytest.raises(MergeContractError):
        MergeContext(
            stage_id="stage-merge-001",
            owner=StageOwner(
                repository_id=0,
                operation_id=OperationId("operation-stage-merge-001"),
                attempt=AttemptNumber(1),
                execution_mode="direct",
                source_generation="sg1:source",
                config_generation="cg1:config",
                extractor_generation="eg1:extractor",
                canonicalizer_generation="kg1:canonicalizer",
            ),
            run_id=11,
        ).validate()
    with pytest.raises(MergeContractError):
        MergeContext(stage_id="stage-merge-001", owner=context().owner, run_id=0).validate()


def test_merge_builder_returns_caller_owned_set_based_statements() -> None:
    statements = build_source_index_merge_statements(context())

    assert len(statements) == 4
    assert all("BEGIN;" not in statement and "COMMIT;" not in statement for statement in statements)
    assert any("DISTINCT ON (s.path)" in statement for statement in statements)
    assert any("ON CONFLICT (repository_id, path)" in statement for statement in statements)
    assert any("ON CONFLICT (run_id, ordinal)" in statement for statement in statements)


def test_merge_builder_has_duplicate_and_reference_guards() -> None:
    statements = build_source_index_merge_statements(context())
    sql = "\n".join(statements)

    assert "COUNT(DISTINCT (" in sql
    assert "family_ordinal" in sql
    assert "payload_hash" in sql
    assert "SCALE3 stage validation conflict" in sql
    assert "SCALE3 raw ordinal exceeds final schema" in sql
    assert "operation-stage-merge-001" in sql
    assert "sg1:source" in sql


def test_merge_builder_preserves_last_write_ordinal_selection() -> None:
    sql = "\n".join(build_source_index_merge_statements(context()))

    assert "ORDER BY s.path, s.family_ordinal DESC" in sql
    assert "ORDER BY s.source_ordinal" in sql


def test_merge_builder_uses_literal_context_without_private_values() -> None:
    sql = "\n".join(build_source_index_merge_statements(context()))

    assert "'stage-merge-001'" in sql
    assert "repository_id = 7" in sql
    assert "run_id = 11" in sql
    assert "/private" not in sql
