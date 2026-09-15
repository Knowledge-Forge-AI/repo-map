"""Privacy-safe connector comparison report construction and serialization."""

from __future__ import annotations

import json
import statistics
import sys
from collections.abc import Buffer, Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, SupportsInt, SupportsIndex, TextIO


FIXTURE_LABEL = "psycopg-adapted-family-parity"

FORBIDDEN_REPORT_FIELDS = frozenset(
    {
        "connection_string",
        "database",
        "host",
        "local_runtime",
        "payload",
        "port",
        "private_graph",
        "psql_args",
        "raw_payload",
        "raw_payloads",
        "raw_sql",
        "repository",
        "root",
        "root_path",
        "secret",
        "socket",
        "sql",
        "state_file",
        "token",
        "user",
        "username",
    }
)

JsonPayload = Mapping[str, Any] | list[Any]

QueryPayload = Callable[[], JsonPayload]

class ConnectorComparisonError(RuntimeError):
    """Raised when the local connector comparison cannot produce a safe report."""

def elapsed_summary(values: Sequence[float]) -> dict[str, float]:
    """Return compact aggregate timing fields without absolute pass/fail gates."""

    if not values:
        raise ConnectorComparisonError("at least one elapsed value is required")
    return {
        "elapsed_seconds_min": _rounded(min(values)),
        "elapsed_seconds_median": _rounded(statistics.median(values)),
        "elapsed_seconds_max": _rounded(max(values)),
        "elapsed_seconds_mean": _rounded(statistics.fmean(values)),
        "elapsed_seconds_total": _rounded(sum(values)),
    }

def report_row(
    *,
    connector: str,
    operation: str,
    iterations: int,
    elapsed_seconds: Sequence[float],
    payload: JsonPayload,
    parity: bool,
) -> dict[str, object]:
    """Build one privacy-safe report row for a connector and operation."""

    encoded_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "connector": connector,
        "operation": operation,
        "iterations": iterations,
        **elapsed_summary(elapsed_seconds),
        "payload_bytes": len(encoded_payload),
        **safe_context_fields(payload),
        "fixture": FIXTURE_LABEL,
        "parity": parity,
    }

def safe_context_fields(payload: JsonPayload) -> dict[str, object]:
    object_payload = payload if isinstance(payload, Mapping) else {}
    record_payloads = payload if isinstance(payload, list) else []
    edge_kinds = {
        str(record.get("edge_kind"))
        for record in record_payloads
        if isinstance(record, Mapping) and record.get("edge_kind") is not None
    }
    evidence = object_payload.get("evidence", [])
    return {
        "runs": _payload_int(object_payload.get("runs", 0)),
        "files": _payload_int(object_payload.get("files", 0)),
        "raw_observations": _payload_int(object_payload.get("raw_observations", 0)),
        "canonical_nodes": _payload_int(object_payload.get("canonical_nodes", 0)),
        "canonical_edges": _payload_int(object_payload.get("canonical_edges", 0)),
        "record_count": len(record_payloads),
        "file_node_count": sum(
            1
            for record in record_payloads
            if isinstance(record, Mapping) and record.get("kind") == "file"
        ),
        "edge_kind_count": len(edge_kinds),
        "has_edge": object_payload.get("edge") is not None,
        "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
    }

def assert_payload_parity(
    operation: str,
    psql_payload: JsonPayload,
    psycopg_payload: JsonPayload,
) -> None:
    if psql_payload != psycopg_payload:
        raise ConnectorComparisonError(
            f"{operation} payload mismatch between psql and psycopg"
        )

def serialize_report(
    rows: Sequence[Mapping[str, object]],
    *,
    private_values: Iterable[str] = (),
) -> str:
    _validate_report_fields(rows)
    report_text = json.dumps(
        list(rows),
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    )
    _validate_report_text(report_text, private_values=private_values)
    return report_text

def format_text_report(
    rows: Sequence[Mapping[str, object]],
    *,
    private_values: Iterable[str] = (),
) -> str:
    _validate_report_fields(rows)
    headers = (
        "connector",
        "operation",
        "iterations",
        "elapsed_seconds_min",
        "elapsed_seconds_median",
        "elapsed_seconds_max",
        "payload_bytes",
        "parity",
        "fixture",
    )
    lines = ["\t".join(headers)]
    for row in rows:
        lines.append("\t".join(str(row[header]) for header in headers))
    report_text = "\n".join(lines)
    _validate_report_text(report_text, private_values=private_values)
    return report_text

def emit_report(
    report_text: str,
    *,
    output_path: Path | None,
    stdout: TextIO | None = None,
) -> None:
    if output_path is None:
        print(report_text, file=stdout if stdout is not None else sys.stdout)
        return
    output_path.write_text(report_text + "\n", encoding="utf-8")

def _validate_report_fields(rows: Sequence[Mapping[str, object]]) -> None:
    for row in rows:
        forbidden = FORBIDDEN_REPORT_FIELDS.intersection(row)
        if forbidden:
            names = ", ".join(sorted(forbidden))
            raise ConnectorComparisonError(f"forbidden field in report: {names}")

def _validate_report_text(
    report_text: str,
    *,
    private_values: Iterable[str],
) -> None:
    for private_value in private_values:
        if private_value and private_value in report_text:
            raise ConnectorComparisonError("report contains private value")

def _payload_int(value: str | Buffer | SupportsInt | SupportsIndex | None) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

def _rounded(value: float) -> float:
    return round(float(value), 6)
