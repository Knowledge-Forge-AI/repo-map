"""First-use delta for a guarded SQLite Local mixed-v1 home.

LOCAL6 owns the generic no-Psycopg CLI initialization, refresh, MCP and
failure-preservation path.  This owner adds mixed-v1 context selection/pack,
source-blind reads across a generation change, pinned-selection staleness,
recovery after a refused refresh, in-process resource reports, and the
operator ``--resource-report`` file plus offline ``resource-report check``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from common_lore_index.ops.local_refresh import refresh_local_graph
from common_lore_index.ops.resource_view import ResourceObserver
from common_lore_index.ops.resource_view._projections import project_compact_context
from repomap_test_support.context_assertions import assert_valid_context_packet
from repomap_test_support.first_use_workflow import (
    first_use_expectations,
    guard_first_use_root,
)
from repomap_test_support.resource_report_cli_files import private_directory, report_payload
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_BINDINGS,
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.sqlite_local_harness import LocalHarness


def _json(completed: Any) -> dict[str, Any]:
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def _resource_payload(
    observer: ResourceObserver,
    *,
    operation: str,
    backend: str,
    outcome: str,
    instrumentation: str = "complete",
) -> dict[str, Any]:
    payload = observer.report().to_payload()
    assert payload["schema"] == "cloe-resource-view-v1"
    assert payload["operation"] == operation
    assert payload["backend"] == backend
    assert payload["outcome"] == outcome
    assert payload["instrumentation"] == instrumentation
    assert "mixed-v1" not in json.dumps(payload, sort_keys=True)
    assert_canary_free(payload)
    return payload


def _context_payload(
    harness: LocalHarness,
    home: Path,
    selection: Path,
    *,
    query: str = "RetrievalExecutionPipeline",
    intent: str = "implementation",
) -> dict[str, Any]:
    completed = harness.run(
        "ops", "context-pack", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
        "--mode", "ranked_discovery", "--query", query, "--intent", intent,
        "--selection", str(selection),
    )
    assert completed.returncode in {0, 1, 3}, completed.stderr
    packet = json.loads(completed.stdout)
    assert isinstance(packet, dict)
    assert_valid_context_packet(packet)
    assert_canary_free(packet)
    view = project_compact_context(packet).to_payload()
    assert view["schema"] == "cloe-resource-view-v1"
    assert view["operation"] == "compact_context"
    assert view["backend"] == "sqlite"
    assert view["outcome"] == packet["status"]
    assert view["instrumentation"] == "complete"
    assert "mixed-v1" not in json.dumps(view, sort_keys=True)
    return packet


def _select_all(
    harness: LocalHarness,
    home: Path,
    output: Path,
    *,
    expected_generation: int = 1,
) -> dict[str, Any]:
    completed = harness.run(
        "ops", "context-select", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
        *sum((["--binding", binding_id_for_alias(alias)] for alias in MIXED_V1_BINDINGS), []),
        "--pin-publication", "--output", str(output),
    )
    assert completed.returncode == 0, completed.stderr
    record = json.loads(completed.stdout)
    assert isinstance(record, dict)
    assert record["schema"] == "cloe-source-selection-v1"
    assert record["backend"] == "sqlite"
    assert {item["binding_id"] for item in record["bindings"]} == {
        binding_id_for_alias(alias) for alias in MIXED_V1_BINDINGS
    }
    assert record["expected_publication"]["generation"] == expected_generation
    assert_canary_free(record)
    return record


def test_first_use_local_mixed_v1_context_pin_stale_recovery_and_reports(tmp_path: Path) -> None:
    expectations = {item.alias: item for item in first_use_expectations(MIXED_V1_BINDINGS)}
    assert expectations["core"].lexical_treatment == "eligible"
    assert expectations["feeds"].body_treatment == "metadata-only"
    assert expectations["mailbox"].privacy == "private-memory"

    work_root = tmp_path / "workflow"
    work_root.mkdir()
    working_copy = guard_first_use_root(work_root / "working-copy", work_root)
    materialize_mixed_v1_working_copy(working_copy, generation=1)
    home = guard_first_use_root(work_root / "home", work_root)
    write_mixed_v1_sqlite_home(home, working_copy)
    harness = LocalHarness(work_root / "guarded", block_psycopg=True)

    # LOCAL6 owns the generic init/refresh mechanics; use them as setup.
    _json(harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID, "--json"))
    _json(harness.run("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID, "--json"))
    selection = work_root / "selection-v1.json"
    record = _select_all(harness, home, selection)
    assert all(item["snapshot_id"] for item in record["bindings"])

    # Context is metadata-only and source-blind: hide every source after the
    # accepted publication, then pack through the pinned selection.
    hidden = work_root / "working-copy-hidden"
    working_copy.rename(hidden)
    first_packet = _context_payload(harness, home, selection)
    assert first_packet["status"] in {"complete", "partial"}
    assert_valid_context_packet(first_packet)
    locations = [loc for item in first_packet["items"] for loc in item["locations"]]
    assert locations
    assert {loc["source_binding_id"] for loc in locations} <= {
        binding_id_for_alias(alias) for alias in MIXED_V1_BINDINGS
    }
    hidden.rename(working_copy)

    # Generation 2 is the in-process Local delta and is observed without
    # changing the CLI JSON contract.
    guard_first_use_root(working_copy, work_root)
    materialize_mixed_v1_working_copy(working_copy, generation=2)
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    observer_g2 = ResourceObserver()
    result_g2 = refresh_local_graph(config, MIXED_V1_GRAPH_ID, resource_observer=observer_g2)
    assert result_g2.generation == 2
    _resource_payload(
        observer_g2, operation="local_refresh", backend="sqlite",
        outcome="published",
    )

    stale_packet = _context_payload(harness, home, selection)
    assert stale_packet["status"] == "stale"
    assert stale_packet["reason"] == "selection_publication_advanced"

    # A missing source is a refused attempt.  This owner binds the report,
    # reads the accepted generation back through the existing selection
    # contract, and then proves that restoring the root permits the next one.
    (working_copy / "companion").rename(work_root / "companion-missing")
    refused_observer = ResourceObserver()
    try:
        refresh_local_graph(config, MIXED_V1_GRAPH_ID, resource_observer=refused_observer)
    except ValueError:
        _resource_payload(
            refused_observer, operation="local_refresh", backend="sqlite",
            outcome="not_recorded", instrumentation="incomplete",
        )
    else:
        raise AssertionError("missing mixed-v1 source unexpectedly refreshed")

    # Selecting the current publication after refusal binds the preservation
    # claim without duplicating LOCAL6's lower-level failure fixture.
    after_refusal = _select_all(
        harness, home, work_root / "selection-after-refusal.json", expected_generation=2
    )
    assert after_refusal["expected_publication"]["generation"] == 2

    guard_first_use_root(working_copy, work_root)
    materialize_mixed_v1_working_copy(working_copy, generation=2)
    # The operator path: one guarded CLI child writes a private report file
    # outside every configured root, then offline inspection validates it.
    reports = private_directory(work_root / "reports")
    recovered = _json(harness.run(
        "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID, "--json",
        "--resource-report", str(reports / "recovery.json"),
    ))
    assert recovered["accepted_generation"] == 3
    report = report_payload(
        reports / "recovery.json", operation="local_refresh", backend="sqlite", outcome="published",
        instrumentation="complete", forbidden=(home, working_copy, "mixed-v1"),
    )
    assert_canary_free(report)
    checked = harness.run("ops", "resource-report", "check", "--input", str(reports / "recovery.json"))
    assert checked.returncode == 0 and checked.stdout.startswith("valid cloe-resource-view-v1"), checked.stderr
    assert harness.forbidden_events() == [], harness.forbidden_events()
    assert harness.shim_invocations() == "", harness.shim_invocations()
