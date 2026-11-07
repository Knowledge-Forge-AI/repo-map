"""Observed offline report CLI format/domain boundaries over real private files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from common_lore_index.ops.resource_reports._codec import decode_report, encode_report
from common_lore_index.ops.resource_reports._files import read_report_file
from common_lore_index.ops.resource_view._context_projection import unfinished_compact_context
from repomap_test_support.resource_report_cli_files import private_directory, run_cloe
from repomap_test_support.sqlite_local_harness import LocalHarness


ROOT = Path(__file__).resolve().parents[6]
_POSTGRES_IMPLEMENTATION = frozenset({
    "psycopg", "common_lore_index.storage.staged_ingestion",
    "common_lore_index.ops.refresh", "common_lore_index.runtime.maintenance",
})


def _valid() -> bytes:
    return encode_report(unfinished_compact_context())


def _mutate(old: bytes, new: bytes, data: bytes | None = None) -> bytes:
    source = _valid() if data is None else data
    assert source.count(old) >= 1, old
    return source.replace(old, new, 1)


def _domain(change: Callable[[dict[str, Any]], None]) -> bytes:
    payload = json.loads(_valid())
    payload["limits"] = [{
        "name": "wall_clock_deadline", "value": 1000,
        "unit": "milliseconds", "enforcement": "owner_enforced",
        "applies_this_call": None,
    }]
    change(payload)
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _row_change(group: str, name: str, key: str, value: Any) -> bytes:
    def change(payload: dict[str, Any]) -> None:
        row = next(item for item in payload[group] if item["name"] == name)
        row[key] = value
    return _domain(change)


def _cases() -> tuple[tuple[str, Callable[[], bytes], str], ...]:
    return (
        ("crlf", lambda: _valid()[:-1] + b"\r\n", "not_canonical"),
        ("missing_lf", lambda: _valid()[:-1], "not_canonical"),
        ("extra_lf", lambda: _valid() + b"\n", "not_canonical"),
        ("trailing_document", lambda: _valid()[:-1] + b"{}\n", "malformed_json"),
        ("utf8", lambda: _mutate(b'"schema":"cloe-resource-view-v1"', b'"schema":"cloe-resource-view-v1\xff"'), "not_utf8"),
        ("duplicate_top", lambda: _mutate(b'"backend":null,', b'"backend":null,"backend":null,'), "duplicate_key"),
        ("duplicate_nested", lambda: _mutate(b'"availability":"unavailable"', b'"availability":"unavailable","availability":"unavailable"'), "duplicate_key"),
        ("extra_key", lambda: _mutate(b'{"backend"', b'{"extra":1,"backend"'), "invalid_shape"),
        ("missing_key", lambda: _mutate(b'"backend":null,', b''), "invalid_shape"),
        ("nonfinite", lambda: _mutate(b'"value":null', b'"value":NaN'), "non_integer_number"),
        ("float", lambda: _mutate(b'"value":null', b'"value":1.0'), "non_integer_number"),
        ("bool_count", lambda: _mutate(b'"value":null', b'"value":true'), "invalid_domain"),
        ("minus_zero", lambda: _mutate(b'"value":null', b'"value":-0'), "invalid_domain"),
        ("unknown_closed", lambda: _mutate(b'"outcome":"not_recorded"', b'"outcome":"privatecanary"'), "invalid_domain"),
        ("pair_domain", lambda: _mutate(b'"operation":"compact_context"', b'"operation":"local_refresh"'), "invalid_domain"),
        ("metric_unit_slot", lambda: _row_change("metrics", "actual_bytes", "unit", "count"), "invalid_domain"),
        ("metric_basis_slot", lambda: _row_change("metrics", "actual_bytes", "basis", "estimate"), "invalid_domain"),
        ("metric_unknown_slot", lambda: _row_change("metrics", "actual_bytes", "name", "privatecanary"), "invalid_domain"),
        ("metric_extra_key", lambda: _row_change("metrics", "actual_bytes", "privatecanary", 1), "invalid_shape"),
        ("limit_unit_slot", lambda: _row_change("limits", "wall_clock_deadline", "unit", "count"), "invalid_domain"),
        ("limit_enforcement", lambda: _row_change("limits", "wall_clock_deadline", "enforcement", "observed_only"), "invalid_domain"),
        ("limit_extra_key", lambda: _row_change("limits", "wall_clock_deadline", "basis", "ledger_counter"), "invalid_shape"),
        ("limit_bool", lambda: _row_change("limits", "wall_clock_deadline", "value", True), "invalid_domain"),
        ("limit_applicability_type", lambda: _row_change("limits", "wall_clock_deadline", "applies_this_call", "yes"), "invalid_domain"),
        ("duplicate_metric", lambda: _domain(lambda p: p["metrics"].append(dict(p["metrics"][0]))), "invalid_domain"),
        ("duplicate_limit", lambda: _domain(lambda p: p["limits"].append(dict(p["limits"][0]))), "invalid_domain"),
        ("missing_metric_key", lambda: _domain(lambda p: p["metrics"][0].pop("basis")), "invalid_shape"),
        ("missing_limit_key", lambda: _domain(lambda p: p["limits"][0].pop("enforcement")), "invalid_shape"),
        ("instrumentation", lambda: _domain(lambda p: p.update(instrumentation="privatecanary")), "invalid_domain"),
        ("oversize", lambda: b"x" * 8194, "too_large"),
    )


@pytest.mark.parametrize("name,factory,category", _cases())
def test_observed_offline_cli_rejects_strict_file_bytes(
    tmp_path: Path, name: str, factory: Callable[[], bytes], category: str,
) -> None:
    reports = private_directory(tmp_path / "reports")
    path = reports / f"{name}.json"
    path.write_bytes(factory())
    path.chmod(0o600)
    completed = run_cloe(
        "ops", "resource-report", "check", "--input", str(path), cwd=ROOT,
        extra_env={"CLOE_HOME": str(tmp_path / "absent-home")},
    )
    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr == f"ERROR: resource-report-invalid: {category}\n"
    assert str(tmp_path) not in completed.stderr


def test_observed_offline_cli_round_trip_is_file_only(tmp_path: Path) -> None:
    reports = private_directory(tmp_path / "reports")
    path = reports / "valid.json"
    data = _valid()
    path.write_bytes(data)
    path.chmod(0o600)
    checked = run_cloe("ops", "resource-report", "check", "--input", str(path), cwd=ROOT)
    assert checked.returncode == 0 and checked.stderr == ""
    shown = run_cloe("ops", "resource-report", "show", "--input", str(path), "--json", cwd=ROOT)
    assert shown.returncode == 0 and shown.stdout.encode("utf-8") == data
    text = run_cloe("ops", "resource-report", "show", "--input", str(path), cwd=ROOT)
    assert text.returncode == 0 and "format and domain only" in text.stdout


def test_guarded_local_child_keeps_offline_readback_free_of_product_work(tmp_path: Path) -> None:
    reports = private_directory(tmp_path / "reports")
    path = reports / "valid.json"
    path.write_bytes(_valid())
    path.chmod(0o600)
    harness = LocalHarness(tmp_path / "guarded", block_psycopg=True)
    completed = harness.run("ops", "resource-report", "check", "--input", str(path))
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert harness.forbidden_events() == []
    assert not harness.imported_modules() & _POSTGRES_IMPLEMENTATION
    assert harness.shim_invocations() == ""


def test_offline_cli_reports_are_format_evidence_only(tmp_path: Path) -> None:
    reports = private_directory(tmp_path / "reports")
    path = reports / "valid.json"
    path.write_bytes(_valid())
    path.chmod(0o600)
    shown = run_cloe("ops", "resource-report", "show", "--input", str(path), cwd=ROOT)
    assert shown.returncode == 0
    payload = decode_report(read_report_file(path)).to_payload()
    assert set(payload) == {"schema", "operation", "backend", "outcome", "instrumentation", "metrics", "limits"}
    assert "authenticity" in shown.stdout and "measurement truth" in shown.stdout


def test_version_precedes_offline_file_inspection(tmp_path: Path) -> None:
    missing = tmp_path / "not-a-report.json"
    version = run_cloe("--version", cwd=ROOT)
    selected = run_cloe(
        "--version", "ops", "resource-report", "check", "--input", str(missing), cwd=ROOT,
    )
    assert version.returncode == selected.returncode == 0
    assert version.stdout == selected.stdout and version.stdout.strip()
    assert selected.stderr == version.stderr == ""
    assert not missing.exists()
