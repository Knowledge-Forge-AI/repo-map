from __future__ import annotations

import json
from types import ModuleType, SimpleNamespace

from psycopg.conninfo import conninfo_to_dict
import pytest

import scale7_measure_ingestion as scale7_measure_ingestion


def load_tool_module() -> ModuleType:
    return scale7_measure_ingestion


def test_connection_preserves_all_parsed_options(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = load_tool_module()
    parameters = {"host": "localhost", "port": "55433", "dbname": "fixture",
                  "user": "fixture", "options": "-c statement_timeout=1000",
                  "application_name": "fixture-measure", "connect_timeout": "3"}
    monkeypatch.setattr(tool, "_psycopg_connection_params_from_psql_args", lambda _: parameters)
    received: list[dict[str, str | int | None]] = []
    sentinel = object()

    def connect(conninfo: str) -> object:
        received.append(conninfo_to_dict(conninfo))
        return sentinel

    monkeypatch.setattr(tool.psycopg, "connect", connect)
    assert tool._connect(SimpleNamespace(psql_args=())) is sentinel
    assert received == [parameters]


def test_copy_text_row_bytes_is_deterministic_and_strict() -> None:
    tool = load_tool_module()

    encoded = tool.copy_text_row_bytes(
        ("alpha", "line\nnext", None, True, {"z": 1, "a": "x"})
    )

    assert encoded == (
        b'alpha\tline\\nnext\t\\N\tt\t{"a":"x","z":1}\n'
    )


def test_sql_statement_count_ignores_literal_semicolons() -> None:
    tool = load_tool_module()

    assert tool.sql_statement_count(
        ("INSERT INTO fixture VALUES ('a;b');\n", "SELECT 1;\n")
    ) == 2


def test_report_is_public_safe_and_has_family_accounting() -> None:
    tool = load_tool_module()

    report = tool.public_measurement_report(
        size=4,
        path="/not-public",
        family_rows={"files": 4, "canonical_nodes": 8},
        statement_count=19,
        encoded_bytes=128,
        elapsed_seconds=0.25,
        client_cpu_seconds=0.10,
        client_max_rss_bytes=1024,
        postgres_stats={"temp_bytes": 0, "wal_bytes": 512},
    )

    serialized = json.dumps(report, sort_keys=True)
    assert report["fixture"] == tool.FIXTURE_LABEL
    assert report["family_rows"]["files"] == 4
    assert report["family_rows"]["canonical_nodes"] == 8
    assert report["statement_count"] == 19
    assert "path" not in serialized
    assert "/not-public" not in serialized
    assert "raw_sql" not in serialized


@pytest.mark.parametrize("value", [b"\x00", "\x00"])
def test_copy_text_row_bytes_rejects_nul(value) -> None:
    tool = load_tool_module()

    with pytest.raises(tool.MeasurementContractError, match="nul"):
        tool.copy_text_row_bytes((value,))
