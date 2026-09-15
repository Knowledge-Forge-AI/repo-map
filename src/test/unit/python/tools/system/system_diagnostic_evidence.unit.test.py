"""Unit tests for diagnostic evidence capture, redaction, and schema validation."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from repomap_kg.storage.publication import RunPublicationReceipt
from tools.system.report import _snapshot_details, write_system_diagnostic
from tools.system.scenario_journal import (
    ScenarioJournal,
    _build_control_diagnostic_sql,
    _build_publication_diagnostic_sql,
    _redact_log_text,
    _safe_diagnostic_error,
)


def test_redact_log_text_credential_canaries() -> None:
    raw_log = (
        "connect to postgres://user:secretpass@host:5432/repomap_control "
        "and postgresql://admin:token123@10.0.0.1/repomap with password=supersecret "
        "and token=tok999 and secret=sec888 and api_key=key777"
    )
    redacted = _redact_log_text(raw_log)
    for canary in ("secretpass", "token123", "supersecret", "tok999", "sec888", "key777"):
        assert canary not in redacted
    assert "postgres://[REDACTED]:[REDACTED]@" in redacted
    assert "postgresql://[REDACTED]:[REDACTED]@" in redacted
    assert "password=[REDACTED]" in redacted


def test_redact_log_text_exact_utf8_boundary() -> None:
    # 4-byte UTF-8 emoji repeated 2000 times = 8000 bytes
    multibyte_str = "🚀" * 2000
    redacted = _redact_log_text(multibyte_str)
    encoded = redacted.encode("utf-8")
    assert len(encoded) <= 4096
    assert "[TRUNCATED_AT_4096_BYTES]" in redacted
    # Verify the decoded text is valid and does not have replacement characters from broken multibyte
    assert "\ufffd" not in redacted


def test_safe_diagnostic_error_utf8_boundary() -> None:
    multibyte_err = ValueError("€" * 500)
    safe_err = _safe_diagnostic_error(multibyte_err, max_bytes=64)
    assert safe_err["error_class"] == "ValueError"
    msg_bytes = safe_err["message"].encode("utf-8")
    assert len(msg_bytes) <= 64
    assert safe_err["message"].endswith(" [TRUNCATED]")
    assert "\ufffd" not in safe_err["message"]


def test_snapshot_details_safe_projection() -> None:
    cyclic: dict[str, Any] = {"name": "cyclic"}
    cyclic["self"] = cyclic

    data = {
        "nan_val": float("nan"),
        "pos_inf": float("inf"),
        "neg_inf": float("-inf"),
        "cyclic": cyclic,
        "set_val": {"zebra", "apple", "mango"},
        "long_str": "x" * 5000,
        "user_dict_with_key": {"__truncated_items__": 99, "preserved": "ok"},
        "large_list": list(range(120)),
        (1, 2): "tuple_key",
        1: "int_one",
        "1": "str_one",
        None: "none_val",
        "null": "str_null",
    }
    projected = _snapshot_details(data)
    assert projected["nan_val"] == {"__nonfinite__": "nan"}
    assert projected["pos_inf"] == {"__nonfinite__": "inf"}
    assert projected["neg_inf"] == {"__nonfinite__": "-inf"}
    assert projected["cyclic"]["self"] == {"__cyclic_ref__": True}
    assert projected["set_val"] == ["apple", "mango", "zebra"]
    assert "[TRUNCATED]" in projected["long_str"]
    assert len(projected["long_str"].encode("utf-8")) <= 4096
    assert projected["user_dict_with_key"]["__truncated_items__"] == 99
    assert projected["user_dict_with_key"]["preserved"] == "ok"
    assert len(projected["large_list"]) == 101
    assert projected["large_list"][-1] == {"__truncated_items__": 20}
    tuple_keys = [k for k in projected if k.startswith("__key_tuple_")]
    assert len(tuple_keys) == 1
    assert projected[tuple_keys[0]] == "tuple_key"
    assert "1" in projected and "1__collision_1__" in projected
    assert "null" in projected and "null__collision_1__" in projected


def test_write_system_diagnostic_independent_destinations(tmp_path: Path) -> None:
    report_dir = tmp_path / "valid_report"
    evidence_dir = tmp_path / "read_only_evidence"
    evidence_dir.mkdir()
    dummy_file = evidence_dir / "repomap-system-gate-diagnostic.json"
    dummy_file.mkdir()

    written = write_system_diagnostic(
        {"status": "failure", "error_message": "test error"},
        report_dir=report_dir,
        evidence_dir=evidence_dir,
    )
    assert written is not None
    assert written.exists()
    assert report_dir.exists()
    saved = json.loads(written.read_text(encoding="utf-8"))
    assert saved["status"] == "failure"


def test_write_system_diagnostic_raises_on_all_destinations_failure(tmp_path: Path) -> None:
    unwritable = tmp_path / "blocked"
    unwritable.write_text("file not dir")
    with pytest.raises(OSError, match="diagnostic write failed across all destinations"):
        write_system_diagnostic(
            {"status": "fail"},
            report_dir=unwritable,
            evidence_dir=unwritable,
        )


def test_system_step_result_journal_safe_projection_under_failure(tmp_path: Path) -> None:
    report_dir = tmp_path / "rep"
    evidence_dir = tmp_path / "evi"
    journal = ScenarioJournal(report_dir=report_dir, evidence_dir=evidence_dir)

    nested_cyclic: dict[str, Any] = {}
    malformed_details: dict[object, object] = {
        "__truncated_items__": "malformed_string_marker",
        "nan_metric": float("nan"),
        "nested_cyclic": nested_cyclic,
        1: "colliding_int",
        "1": "colliding_str",
    }
    nested_cyclic["loop"] = malformed_details
    details_arg: Any = malformed_details

    fail_step = journal.record_failure(
        "step_fail",
        "primary database claim failed",
        duration_seconds=2.5,
        details=details_arg,
    )
    assert fail_step.message == "primary database claim failed"

    journal.record_step(fail_step)
    assert journal._step_results[0].message == "primary database claim failed"
    assert journal._step_results[0].status == "failed"

    diag_path = journal.preserve_diagnostics(
        compose_dir=tmp_path / "nonexistent",
        error_message="primary database claim failed",
    )
    assert diag_path is not None
    assert diag_path.exists()
    diag_data = json.loads(diag_path.read_text(encoding="utf-8"))
    assert diag_data["error_message"] == "primary database claim failed"


def _parse_ddl_table_schemas(ddl_text: str) -> dict[str, set[str]]:
    table_schemas: dict[str, set[str]] = {}
    for create_match in re.finditer(r"CREATE\s+TABLE\s+([a-zA-Z0-9_]+)\s*\((.*?)\);", ddl_text, re.DOTALL | re.IGNORECASE):
        table_name = create_match.group(1)
        body = create_match.group(2)
        cols: set[str] = set()
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("--"):
                continue
            first_word = line.split()[0].upper().rstrip(",")
            if first_word in {"CONSTRAINT", "CHECK", "UNIQUE", "PRIMARY", "FOREIGN"}:
                continue
            col_match = re.match(r"^([a-zA-Z0-9_]+)\b", line)
            if col_match:
                cols.add(col_match.group(1))
        table_schemas[table_name] = cols

    for alter_match in re.finditer(r"ALTER\s+TABLE\s+([a-zA-Z0-9_]+)(.*?);", ddl_text, re.DOTALL | re.IGNORECASE):
        t_name = alter_match.group(1)
        body = alter_match.group(2)
        for add_match in re.finditer(r"ADD\s+COLUMN\s+([a-zA-Z0-9_]+)", body, re.IGNORECASE):
            c_name = add_match.group(1)
            table_schemas.setdefault(t_name, set()).add(c_name)

    return table_schemas


def _validate_query_against_table_schemas(sql: str, schemas: dict[str, set[str]], aliases: dict[str, str]) -> None:
    for match in re.finditer(r"\b([a-z]+)\.([a-z0-9_]+)\b", sql):
        alias, col = match.groups()
        if alias in aliases:
            table = aliases[alias]
            assert table in schemas, f"Table '{table}' for alias '{alias}' not in DDL schemas"
            if col not in schemas[table]:
                raise AssertionError(f"Column '{col}' is not a valid column for table '{table}' (alias '{alias}')")


def test_control_sql_identifiers_match_liquibase_ddl() -> None:
    ddl_path = ROOT / "src/main/resources/coordinator-rdbms/2026/07/13-001-async2-create-control-schema.sql"
    assert ddl_path.exists()
    schemas = _parse_ddl_table_schemas(ddl_path.read_text(encoding="utf-8"))
    aliases = {
        "j": "jobs", "a": "job_attempts", "gl": "graph_leases",
        "ci": "coordinator_instances", "cs": "coalescing_state", "spm": "synthetic_publication_markers",
    }
    sql = _build_control_diagnostic_sql()
    _validate_query_against_table_schemas(sql, schemas, aliases)

    # Load-bearing regression check: mutating column name in production query fails
    mutated_sql = sql.replace("j.job_id", "j.nonexistent_control_col")
    with pytest.raises(AssertionError, match="nonexistent_control_col"):
        _validate_query_against_table_schemas(mutated_sql, schemas, aliases)

    # Load-bearing regression check: using a column on the wrong table alias fails
    mutated_alias = sql.replace("j.job_id", "j.coordinator_instance_id")
    with pytest.raises(AssertionError, match="coordinator_instance_id"):
        _validate_query_against_table_schemas(mutated_alias, schemas, aliases)


def test_publication_sql_identifiers_match_liquibase_and_receipt_contract() -> None:
    graph_ddl_paths = [
        ROOT / "src/main/resources/rdbms/2026/06/28-001-core-create_graph_tables.sql",
        ROOT / "src/main/resources/rdbms/2026/07/13-001-core-add-run-publication-generations.sql",
        ROOT / "src/main/resources/rdbms/2026/07/13-002-core-add-run-publication-attempts.sql",
        ROOT / "src/main/resources/rdbms/2026/09/02-001-str-pub5-add-portable-publication-binding.sql",
    ]
    combined_ddl = "\n".join(p.read_text(encoding="utf-8") for p in graph_ddl_paths)
    schemas = _parse_ddl_table_schemas(combined_ddl)
    aliases = {"r": "runs"}
    sql = _build_publication_diagnostic_sql()

    # Validate against RunPublicationReceipt.field_names()
    receipt_fields = RunPublicationReceipt.field_names()
    for field in receipt_fields:
        assert f"'{field}', {field}" in sql or f"r.{field}" in sql

    _validate_query_against_table_schemas(sql, schemas, aliases)

    # Load-bearing regression check: mutating column name in production query fails
    mutated_sql = sql.replace("r.id", "r.nonexistent_runs_col")
    with pytest.raises(AssertionError, match="nonexistent_runs_col"):
        _validate_query_against_table_schemas(mutated_sql, schemas, aliases)

    # Load-bearing regression check: using a column from another table fails
    mutated_wrong = sql.replace("r.id", "r.error_category")
    with pytest.raises(AssertionError, match="error_category"):
        _validate_query_against_table_schemas(mutated_wrong, schemas, aliases)
