from __future__ import annotations

import contextlib
import io
import json
import os
from types import SimpleNamespace

import pytest

import compare_pg_connectors as compare_pg_connectors
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV


def load_tool_module():
    return compare_pg_connectors


def test_psycopg21_elapsed_summary_reports_min_median_max_mean_total() -> None:
    tool = load_tool_module()

    summary = tool.elapsed_summary([0.30, 0.10, 0.20])

    assert summary == {
        "elapsed_seconds_min": 0.10,
        "elapsed_seconds_median": 0.20,
        "elapsed_seconds_max": 0.30,
        "elapsed_seconds_mean": 0.20,
        "elapsed_seconds_total": 0.60,
    }


def test_psycopg21_report_row_uses_safe_context_fields() -> None:
    tool = load_tool_module()

    row = tool.report_row(
        connector="psql",
        operation="canonical_edge_records",
        iterations=2,
        elapsed_seconds=[0.40, 0.20],
        payload=[
            {"source_key": "file:src/app.py", "edge_kind": "imports"},
            {"source_key": "file:src/app.py", "edge_kind": "runs"},
        ],
        parity=True,
    )

    assert row == {
        "connector": "psql",
        "operation": "canonical_edge_records",
        "iterations": 2,
        "elapsed_seconds_min": 0.20,
        "elapsed_seconds_median": 0.30,
        "elapsed_seconds_max": 0.40,
        "elapsed_seconds_mean": 0.30,
        "elapsed_seconds_total": 0.60,
        "payload_bytes": 108,
        "runs": 0,
        "files": 0,
        "raw_observations": 0,
        "canonical_nodes": 0,
        "canonical_edges": 0,
        "record_count": 2,
        "file_node_count": 0,
        "edge_kind_count": 2,
        "has_edge": False,
        "evidence_count": 0,
        "fixture": "psycopg-adapted-family-parity",
        "parity": True,
    }

    serialized = json.dumps(row, sort_keys=True)
    assert "source_key" not in serialized
    assert "file:src/app.py" not in serialized


def test_psycopg21_serialization_rejects_private_values_and_forbidden_fields() -> None:
    tool = load_tool_module()
    row = tool.report_row(
        connector="psycopg",
        operation="storage_summary",
        iterations=1,
        elapsed_seconds=[0.01],
        payload={"runs": 1, "files": 2, "raw_observations": 4},
        parity=True,
    )

    assert "storage_summary" in tool.serialize_report([row])

    with pytest.raises(tool.ConnectorComparisonError, match="private value"):
        tool.serialize_report(
            [row | {"fixture": "psycopg-adapted-family-parity:/private/root"}],
            private_values=("/private/root",),
        )

    with pytest.raises(tool.ConnectorComparisonError, match="forbidden field"):
        tool.serialize_report([row | {"database": "postgres"}])


def test_psycopg21_parity_failure_raises_before_reporting() -> None:
    tool = load_tool_module()

    with pytest.raises(tool.ConnectorComparisonError, match="payload mismatch"):
        tool.assert_payload_parity(
            "canonical_node_records",
            [{"canonical_key": "file:a.py"}],
            [{"canonical_key": "file:b.py"}],
        )


def test_psycopg59_legacy_payload_mismatch_raises_before_reporting() -> None:
    tool = load_tool_module()

    with pytest.raises(tool.ConnectorComparisonError, match="payload mismatch"):
        tool.assert_payload_parity(
            "legacy_node_records",
            [{"node_stable_key": "node:a", "name": "first"}],
            [{"node_stable_key": "node:a", "name": "second"}],
        )


def test_comparison_operations_use_only_current_canonical_readback(
    monkeypatch,
) -> None:
    tool = load_tool_module()
    postgres = SimpleNamespace(
        psql_args=["-d", "postgres"],
        psql_command="custom-psql",
    )
    selected_edge = SimpleNamespace(
        source_key="file:src/app.py",
        edge_kind="imports",
        target_key="python-module:json",
        identity_metadata_hash="fixture-hash",
        graph_key_version=1,
    )
    monkeypatch.setattr(tool, "_select_connector", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tool,
        "query_canonical_edge_records",
        lambda *_args, **_kwargs: (selected_edge,),
    )

    operations = tool.comparison_operations(postgres)

    assert tuple(operation for operation, _query_payload in operations) == (
        "canonical_storage_summary",
        "canonical_node_records",
        "canonical_edge_records",
        "canonical_edge_explanation",
    )
    assert not hasattr(tool, "query_node_records")
    assert not hasattr(tool, "query_edge_records")


def test_psycopg21_emit_report_writes_only_with_explicit_output(tmp_path) -> None:
    tool = load_tool_module()
    output = tmp_path / "report.json"
    stdout = io.StringIO()

    tool.emit_report("[]", output_path=None, stdout=stdout)

    assert stdout.getvalue() == "[]\n"
    assert not output.exists()

    with contextlib.redirect_stdout(io.StringIO()):
        tool.emit_report("[]", output_path=output, stdout=io.StringIO())

    assert output.read_text(encoding="utf-8") == "[]\n"


def test_psycopg26_comparison_run_clears_pg_connector_selector(monkeypatch) -> None:
    tool = load_tool_module()
    observed_pg_connector_values: list[str | None] = []

    class _FakeTemporaryPostgres:
        def __enter__(self):
            observed_pg_connector_values.append(os.environ.get(PG_CONNECTOR_ENV))
            return SimpleNamespace(psql_args=[], psql_command="psql")

        def __exit__(self, _exc_type, _exc, _traceback):
            return False

    def comparison_operations(_postgres):
        observed_pg_connector_values.append(os.environ.get(PG_CONNECTOR_ENV))
        return ()

    def collect_report_rows(_postgres, *, operations, iterations):
        assert operations == ()
        assert iterations == 1
        observed_pg_connector_values.append(os.environ.get(PG_CONNECTOR_ENV))
        return []

    monkeypatch.setenv(PG_CONNECTOR_ENV, "psycopg")
    monkeypatch.setattr(tool, "temporary_postgres", _FakeTemporaryPostgres)
    monkeypatch.setattr(tool, "apply_migrations", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tool,
            "publish_observation_generation",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        tool,
        "_private_values_for_postgres",
        lambda _postgres: (),
    )
    monkeypatch.setattr(tool, "comparison_operations", comparison_operations)
    monkeypatch.setattr(tool, "collect_report_rows", collect_report_rows)

    rows, private_values = tool.run_connector_comparison(
        iterations=1,
        pg_container_port=55433,
        pg_container_runtime="docker",
    )

    assert rows == []
    assert private_values == ()
    assert observed_pg_connector_values == [None, None, None]
    assert os.environ[PG_CONNECTOR_ENV] == "psycopg"
