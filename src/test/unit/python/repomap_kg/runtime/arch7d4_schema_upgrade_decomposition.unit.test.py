"""Focused negative, error, and boundary tests for schema upgrade decomposition."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from repomap_kg.runtime._schema_upgrade_ledger import (
    GraphSchemaUpgradeResult,
    _reference_database_name,
    _upgrade_error,
    apply_forward_schema,
    bootstrap_schema_ledger,
    format_graph_schema_upgrade_table,
    query_schema_ledger,
    schema_ledger_exists,
)
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import LocalRuntimePlan
from repomap_kg.storage import StorageSchemaError


def test_upgrade_error_formats_diagnostic_structure() -> None:
    error = _upgrade_error("test-code", "test-message")
    assert isinstance(error, LocalDbBackupError)
    assert len(error.diagnostics) == 1
    diagnostic = error.diagnostics[0]
    assert diagnostic.code == "test-code"
    assert diagnostic.path == "schema-upgrade"
    assert diagnostic.message == "test-message"


def test_reference_database_name_sanitizes_timestamp() -> None:
    ref = _reference_database_name("20260909T053000Z")
    assert ref == "repomap_schema_ref_20260909_053000"
    assert "T" not in ref
    assert "Z" not in ref


def test_schema_upgrade_result_to_jsonable_and_format_table() -> None:
    result = GraphSchemaUpgradeResult(
        result="success",
        schema_before="current-path-keyed",
        schema_after="current-stable-identity",
        backup_id="backup-123",
        backup_verified=True,
        rollback_available=True,
        reference_cleaned=False,
        planned_actions=("action1", "action2"),
    )
    payload = result.to_jsonable()
    assert payload["command"] == "upgrade-schema"
    assert payload["result"] == "success"
    assert payload["backup_id"] == "backup-123"
    assert payload["planned_actions"] == ["action1", "action2"]

    table = format_graph_schema_upgrade_table(result)
    assert "result=success" in table
    assert "backup_id=backup-123" in table
    assert "planned_actions=action1,action2" in table


def test_apply_forward_schema_translates_storage_error() -> None:
    plan = Mock(
        spec=LocalRuntimePlan,
        container_runtime="docker",
        identity=SimpleNamespace(postgres_container="postgres"),
        user="repo_map_test",
        env_file=Path("/tmp"),
    )
    with patch(
        "repomap_kg.runtime._schema_upgrade_ledger._default_graph_schema_forward_sql",
        side_effect=StorageSchemaError("no migration files found"),
    ):
        with pytest.raises(LocalDbBackupError, match="no migration files found"):
            apply_forward_schema(plan, "test_db", 0, Mock(side_effect=AssertionError("unexpected command execution")))


def test_bootstrap_schema_ledger_translates_storage_error() -> None:
    plan = Mock(
        spec=LocalRuntimePlan,
        container_runtime="docker",
        identity=SimpleNamespace(postgres_container="postgres"),
        user="repo_map_test",
        env_file=Path("/tmp"),
    )
    with patch(
        "repomap_kg.runtime._schema_upgrade_ledger._default_graph_schema_ledger_bootstrap_sql",
        side_effect=StorageSchemaError("bootstrap template missing"),
    ):
        with pytest.raises(LocalDbBackupError, match="bootstrap template missing"):
            bootstrap_schema_ledger(plan, "test_db", Mock(side_effect=AssertionError("unexpected command execution")))


def test_schema_ledger_exists_returns_boolean() -> None:
    plan = Mock(
        spec=LocalRuntimePlan,
        container_runtime="docker",
        identity=SimpleNamespace(postgres_container="postgres"),
        user="repo_map_test",
        env_file=Path("/tmp"),
    )
    with patch(
        "repomap_kg.runtime._schema_upgrade_ledger._default_run_container_command",
        return_value=subprocess.CompletedProcess([], 0, stdout=b"f\n", stderr=b""),
    ):
        assert schema_ledger_exists(plan, "test_db", Mock(side_effect=AssertionError("unexpected command execution"))) is False


def test_query_schema_ledger_rejects_malformed_rows() -> None:
    plan = Mock(
        spec=LocalRuntimePlan,
        container_runtime="docker",
        identity=SimpleNamespace(postgres_container="postgres"),
        user="repo_map_test",
        env_file=Path("/tmp"),
    )
    # Output with non-digit ordinal
    with patch(
        "repomap_kg.runtime._schema_upgrade_ledger._default_run_container_command",
        return_value=subprocess.CompletedProcess(
            [], 0, stdout=b"not_a_digit\tchange\tpath\thash\n", stderr=b""
        ),
    ):
        with pytest.raises(LocalDbBackupError, match="invalid row"):
            query_schema_ledger(plan, "test_db", Mock(side_effect=AssertionError("unexpected command execution")))

    # Output with missing fields
    with patch(
        "repomap_kg.runtime._schema_upgrade_ledger._default_run_container_command",
        return_value=subprocess.CompletedProcess(
            [], 0, stdout=b"1\tchange\n", stderr=b""
        ),
    ):
        with pytest.raises(LocalDbBackupError, match="invalid row"):
            query_schema_ledger(plan, "test_db", Mock(side_effect=AssertionError("unexpected command execution")))
