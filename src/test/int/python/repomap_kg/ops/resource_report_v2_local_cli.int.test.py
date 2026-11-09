"""Guarded SQLite Local CLI children with v2 reports, sealing budgets and refusals.

Every child runs with the PostgreSQL driver made unavailable. Reports are read
back through the product reader; values are checked against independent
expectations (stdout, the source tree) rather than copied from the report.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common_lore_index.ops.config_local import (
    LocalSqliteConfig, load_graph_registry_config_home, local_graph_binding, sqlite_graph_database_path,
)
from common_lore_index.storage.sqlite_local.connection import read_transaction
from common_lore_index.storage.sqlite_local.schema import accepted_identity

from repomap_test_support.resource_report_cli_files import (
    limit, metric, private_directory, report_leftovers, report_payload,
)
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home
from repomap_test_support.sqlite_local_harness import LocalHarness

GRAPH = "report-v2-local"
POSTGRES_IMPLEMENTATION = {
    "common_lore_index.coordinator.local_mode", "common_lore_index.storage.staged_ingestion",
    "common_lore_index.runtime.maintenance", "common_lore_index.ops.refresh", "psycopg",
}


def _setup(tmp_path: Path) -> tuple[Path, Path, LocalHarness, Path]:
    source = write_shell_source(tmp_path / "sources" / "one")
    home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, source))
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    _guarded(harness, harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", GRAPH))
    return home, source, harness, private_directory(tmp_path / "reports")


def _guarded(harness: LocalHarness, completed: Any, *, code: int = 0) -> Any:
    assert completed.returncode == code, completed.stderr
    assert harness.forbidden_events() == [], harness.forbidden_events()
    assert not harness.imported_modules() & POSTGRES_IMPLEMENTATION, harness.imported_modules()
    return completed


def _refresh(home: Path, *extra: str) -> tuple[str, ...]:
    return ("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", GRAPH, "--json", *extra)


def _source_bytes(source: Path) -> int:
    return sum(path.stat().st_size for path in source.rglob("*") if path.is_file())


def test_v2_published_report_measures_the_sealing_boundary_and_the_worker(tmp_path: Path) -> None:
    home, source, harness, reports = _setup(tmp_path)
    target = reports / "v2.json"
    completed = _guarded(harness, harness.run(*_refresh(
        home, "--resource-report", str(target), "--resource-report-schema", "2",
    )))
    assert json.loads(completed.stdout)["accepted_generation"] == 1 and completed.stderr == ""
    payload = report_payload(target, operation="local_refresh", backend="sqlite", outcome="published",
                             instrumentation="complete", forbidden=(home, source, tmp_path, GRAPH))
    assert payload["schema"] == "cloe-resource-view-v2" and len(payload["metrics"]) == 31
    total = _source_bytes(source)
    sealed = metric(payload, "sealed_manifest_bytes")["value"]
    assert sealed == total
    read = metric(payload, "sealing_read_bytes")
    assert read["basis"] == "call_meter_exact" and read["value"] > 4 * total
    assert metric(payload, "sealing_copy_read_bytes")["value"] == total
    assert metric(payload, "sealing_discovery_read_bytes")["value"] == 0
    assert metric(payload, "sealing_capture_read_bytes")["value"] == 2 * total
    assert metric(payload, "sealing_classification_read_bytes")["value"] == 0
    assert metric(payload, "planned_min_read_bytes")["reason"] == "not_selected"
    assert metric(payload, "worker_launches")["value"] == 1
    for name in ("worker_cpu", "worker_user_cpu", "worker_peak_rss"):
        row = metric(payload, name)
        assert row["availability"] == "measured" and row["value"] > 0, row
    assert metric(payload, "worker_cpu")["basis"] == "wait4_self_and_waited_descendants"
    system = metric(payload, "worker_system_cpu")
    assert system["availability"] == "measured" and system["value"] >= 0
    assert system["unit"] == "nanoseconds" and system["basis"] == "wait4_self_and_waited_descendants"
    assert metric(payload, "worker_cpu")["value"] == metric(payload, "worker_user_cpu")["value"] + system["value"]
    group = metric(payload, "worker_group_members_after_reap")
    assert group["availability"] == "measured" and group["value"] in (0, 1)
    assert group["basis"] == "process_group_probe"
    assert limit(payload, "sealing_max_read_bytes", )["enforcement"] == "absent"
    assert report_leftovers(reports) == []
    check = _guarded(harness, harness.run("ops", "resource-report", "check", "--input", str(target)))
    assert check.stdout.startswith("valid cloe-resource-view-v2: operation local_refresh, outcome published")


def test_budget_refusal_is_reported_refused_and_leaves_accepted_state_unchanged(tmp_path: Path) -> None:
    home, source, harness, reports = _setup(tmp_path)
    _guarded(harness, harness.run(*_refresh(home)))
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    graph = next(item for item in config.graphs if item.id == GRAPH)
    database = sqlite_graph_database_path(config, graph)
    binding = local_graph_binding(graph)
    with read_transaction(database, binding) as connection:
        accepted_before = accepted_identity(connection)
    assert accepted_before is not None
    target = reports / "refused.json"
    refused = _guarded(harness, harness.run(*_refresh(
        home, "--sealing-max-read-bytes", "1", "--resource-report", str(target), "--resource-report-schema", "2",
    )), code=1)
    assert refused.stdout == ""
    assert refused.stderr == "ERROR: sealing-budget-exceeded:planned_read_bytes\n"
    payload = report_payload(target, operation="local_refresh", backend="sqlite", outcome="refused",
                             instrumentation="incomplete", forbidden=(home, source, tmp_path, GRAPH))
    assert metric(payload, "sealing_read_bytes") == {
        "name": "sealing_read_bytes", "value": 0, "unit": "bytes", "availability": "measured",
        "basis": "call_meter_partial", "reason": None,
    }
    assert metric(payload, "planned_inventory_bytes")["value"] == _source_bytes(source)
    assert metric(payload, "worker_launches")["value"] == 0
    assert metric(payload, "worker_cpu")["reason"] == "not_started"
    assert limit(payload, "sealing_max_read_bytes") == {
        "name": "sealing_max_read_bytes", "value": 1, "unit": "bytes", "enforcement": "call_budget_pre_io",
        "applies_this_call": True,
    }
    assert limit(payload, "sealing_max_directory_entries")["value"] == 100_000
    with read_transaction(database, binding) as connection:
        assert accepted_identity(connection) == accepted_before
    following = json.loads(_guarded(harness, harness.run(*_refresh(home))).stdout)
    assert following["accepted_generation"] == 2, "the refused call published nothing"


def test_budgets_without_a_report_govern_silently_and_large_budgets_publish(tmp_path: Path) -> None:
    home, _source, harness, reports = _setup(tmp_path)
    plain = json.loads(_guarded(harness, harness.run(*_refresh(home))).stdout)
    governed = _guarded(harness, harness.run(*_refresh(
        home, "--sealing-max-read-bytes", "1000000000", "--sealing-max-entries", "1000",
        "--sealing-max-elapsed-ms", "600000",
    )))
    assert set(json.loads(governed.stdout)) == set(plain) and governed.stderr == ""
    entries = _guarded(harness, harness.run(*_refresh(home, "--sealing-max-entries", "1")), code=1)
    assert entries.stderr == "ERROR: sealing-budget-exceeded:directory_entries\n"
    assert list(reports.iterdir()) == []


def test_v1_default_reports_stay_v1_and_conflicts_refuse_before_configuration(tmp_path: Path) -> None:
    home, _source, harness, reports = _setup(tmp_path)
    target = reports / "v1.json"
    _guarded(harness, harness.run(*_refresh(home, "--resource-report", str(target))))
    payload = report_payload(target, operation="local_refresh", backend="sqlite", outcome="published")
    assert payload["schema"] == "cloe-resource-view-v1" and len(payload["metrics"]) == 12
    assert payload["limits"][-1]["name"] == "sealing_io_limit"
    assert metric(payload, "worker_cpu")["reason"] == "not_observed"
    missing_home = tmp_path / "no-such-home"
    for extra, code in (
        (("--sealing-max-opens", "5", "--resource-report", str(reports / "c.json")),
         "sealing-budget-requires-report-schema-2"),
        (("--resource-report-schema", "2"), "resource-report-schema-requires-report"),
        (("--sealing-max-opens", "5", "--mode", "coordinator"), "sealing-budget-unsupported-mode"),
    ):
        completed = harness.run("ops", "refresh-graph", "--repo-map-home", str(missing_home), "--graph", GRAPH,
                                *extra)
        assert completed.returncode == 2 and code in completed.stderr, completed.stderr
        assert str(missing_home) not in completed.stderr
    assert sorted(path.name for path in reports.iterdir()) == ["v1.json"]
