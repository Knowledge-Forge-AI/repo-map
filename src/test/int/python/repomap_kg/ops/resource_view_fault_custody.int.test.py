"""Observed faults preserve real publication custody and context snapshot values."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

import pytest

from common_lore_index.ops import lexical_service, portable_refresh
from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_service import build_graph_lexical_generation
from common_lore_index.ops.local_refresh import initialize_local_graph, refresh_local_graph
from common_lore_index.ops.refresh import query_graph_summary, refresh_graph
from common_lore_index.ops.resource_view import ResourceObserver, begin
from common_lore_index.ops.resource_view._projections import project_compact_context
from common_lore_index.retrieval.context_assembly import build_compact_context
from common_lore_index.retrieval.context_contracts import ContextRequest
from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.storage import apply_migrations, default_rdbms_root
from common_lore_index.storage.sqlite_local import publisher
from repomap_test_support.context_fixture import (
    BINDING_CORE, BINDING_DOCS, CTX_GRAPH_ID, build_sqlite_context_fixture,
)
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID, binding_id_for_alias, materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home, write_mixed_v1_sqlite_home,
)


def _accepted_local(database: Path) -> tuple[int, int]:
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        row = connection.execute("SELECT generation, run_id FROM accepted_publication").fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def _private(payload: dict[str, Any]) -> None:
    assert_canary_free(payload)
    encoded = json.dumps(payload, sort_keys=True)
    assert "mixed-v1" not in encoded
    assert "private-clock-detail" not in encoded


def test_local_post_commit_clock_error_degrades_report_without_rejecting_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    working = materialize_mixed_v1_working_copy(tmp_path / "working")
    home = write_mixed_v1_sqlite_home(tmp_path / "home", working)
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    initialize_local_graph(config, MIXED_V1_GRAPH_ID)
    armed = False

    def after_commit(point: str) -> None:
        nonlocal armed
        if point == "after_commit":
            armed = True

    def clock() -> int:
        if armed:
            raise ValueError("private-clock-detail")
        return time.monotonic_ns()

    monkeypatch.setattr(publisher, "_fault_point", after_commit)
    observer = ResourceObserver(_monotonic_ns=clock)
    result = refresh_local_graph(config, MIXED_V1_GRAPH_ID, resource_observer=observer)
    database = home / "state/sqlite-local/graphs" / f"{MIXED_V1_GRAPH_ID}.sqlite3"
    assert armed and _accepted_local(database) == (result.generation, result.run_id)
    assert result.generation == 1 and result.reconciled is False
    payload: dict[str, Any] = observer.report().to_payload()
    assert payload["outcome"] == "not_recorded" and payload["instrumentation"] == "degraded"
    assert all(row["value"] is None for row in payload["metrics"])
    rows = {row["name"]: row for row in payload["metrics"]}
    assert rows["operation_process_cpu"]["basis"] == "process_clock_inclusive"
    assert rows["sealed_manifest_bytes"]["basis"] == "accepted_manifest_total"
    assert rows["worker_peak_rss"]["basis"] is None
    _private(payload)


def test_reused_observer_degrades_while_both_local_refreshes_publish(tmp_path: Path) -> None:
    working = materialize_mixed_v1_working_copy(tmp_path / "working")
    home = write_mixed_v1_sqlite_home(tmp_path / "home", working)
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    initialize_local_graph(config, MIXED_V1_GRAPH_ID)
    observer = ResourceObserver()
    first = refresh_local_graph(config, MIXED_V1_GRAPH_ID, resource_observer=observer)
    second = refresh_local_graph(config, MIXED_V1_GRAPH_ID, resource_observer=observer)
    assert (first.generation, second.generation) == (1, 2)
    assert second.previous_run_id == first.run_id
    database = home / "state/sqlite-local/graphs" / f"{MIXED_V1_GRAPH_ID}.sqlite3"
    assert _accepted_local(database) == (2, second.run_id)
    payload: dict[str, Any] = observer.report().to_payload()
    assert payload["instrumentation"] == "degraded"
    assert payload["outcome"] == "not_recorded"
    assert all(row["applies_this_call"] is None for row in payload["limits"])
    _private(payload)


def test_local_survives_caller_poisoned_unsupported_begin(tmp_path: Path) -> None:
    working = materialize_mixed_v1_working_copy(tmp_path / "working")
    home = write_mixed_v1_sqlite_home(tmp_path / "home", working)
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    initialize_local_graph(config, MIXED_V1_GRAPH_ID)
    observer = ResourceObserver()
    begin(observer, "compact_context", "sqlite")

    result = refresh_local_graph(config, MIXED_V1_GRAPH_ID, resource_observer=observer)
    database = home / "state/sqlite-local/graphs" / f"{MIXED_V1_GRAPH_ID}.sqlite3"
    assert result.generation == 1 and result.reconciled is False
    assert _accepted_local(database) == (result.generation, result.run_id)
    payload: dict[str, Any] = observer.report().to_payload()
    assert payload["operation"] is None and payload["backend"] is None
    assert payload["outcome"] == "not_recorded"
    assert payload["instrumentation"] == "degraded"
    _private(payload)


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_server_finish_interrupt_propagates_after_accepted_commit_without_relabeling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_type: type[BaseException],
) -> None:
    working = materialize_mixed_v1_working_copy(tmp_path / "working")
    with temporary_postgres() as postgres:
        home = write_mixed_v1_postgres_home(
            tmp_path / "home", working, host=postgres.host, port=postgres.port,
            database=postgres.database, user=postgres.user, password=postgres.password,
        )
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        apply_migrations(default_rdbms_root(), config.postgres.psql_args_for_database(postgres.database),
                         psql_command=postgres.psql_command)
        publish = portable_refresh.run_staged_portable_refresh
        committed: list[int] = []
        error = error_type("private-clock-detail")

        def record_commit(*args: Any, **kwargs: Any) -> Any:
            result = publish(*args, **kwargs)
            committed.append(result.run_id)
            return result

        def clock() -> int:
            if committed:
                raise error
            return time.monotonic_ns()

        monkeypatch.setattr(portable_refresh, "run_staged_portable_refresh", record_commit)
        observer = ResourceObserver(_monotonic_ns=clock)
        with pytest.raises(error_type) as caught:
            refresh_graph(config, MIXED_V1_GRAPH_ID, psql_command=postgres.psql_command,
                          resource_observer=observer)
        assert caught.value is error
        assert len(committed) == 1
        accepted = query_graph_summary(config, MIXED_V1_GRAPH_ID, psql_command=postgres.psql_command)
        assert accepted.result == "success" and accepted.latest_run_status == "complete"
        assert accepted.latest_run_id == committed[0]
        payload: dict[str, Any] = observer.report().to_payload()
        assert payload["outcome"] == "not_recorded" and payload["instrumentation"] == "incomplete"
        publication = next(row for row in payload["metrics"] if row["name"] == "publication_elapsed")
        assert publication["value"] is None and publication["reason"] == "not_reached"
        _private(payload)


def test_lexical_finish_clock_error_degrades_report_without_relabeling_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    working = materialize_mixed_v1_working_copy(tmp_path / "working")
    with temporary_postgres() as postgres:
        home = write_mixed_v1_postgres_home(
            tmp_path / "home", working,
            host=postgres.host, port=postgres.port, database=postgres.database,
            user=postgres.user, password=postgres.password,
            declared_aliases=("core", "companion"),
        )
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        apply_migrations(
            default_rdbms_root(), config.postgres.psql_args_for_database(postgres.database),
            psql_command=postgres.psql_command,
        )
        published = refresh_graph(config, MIXED_V1_GRAPH_ID, psql_command=postgres.psql_command)
        assert published.result == "success" and published.publication_state == "committed"
        build = lexical_service.build_and_publish_lexical_generation
        completed = False

        def record_completion(*args: Any, **kwargs: Any) -> Any:
            nonlocal completed
            outcome = build(*args, **kwargs)
            completed = True
            return outcome

        monkeypatch.setattr(lexical_service, "build_and_publish_lexical_generation", record_completion)

        def clock() -> int:
            if completed:
                raise ValueError("private-clock-detail")
            return time.monotonic_ns()

        observer = ResourceObserver(_monotonic_ns=clock)
        outcome = build_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID,
            selected_binding_ids=(binding_id_for_alias("core"),),
            authorize_body=True, resource_observer=observer,
        )
        assert outcome.result == "published" and outcome.published is not None
        payload: dict[str, Any] = observer.report().to_payload()
        assert payload["outcome"] == "not_recorded"
        assert payload["instrumentation"] == "degraded"
        assert all(row["value"] is None for row in payload["metrics"])
        assert all(row["applies_this_call"] is None for row in payload["limits"])
        _private(payload)


def test_real_context_uses_lower_selected_controls_and_detached_packet_counters(tmp_path: Path) -> None:
    database, _config, _graph, _binding, adapter = build_sqlite_context_fixture(tmp_path)
    before = _accepted_local(database)
    ledger = WorkLedger(backend="sqlite", deadline_ms=9999, sqlite_progress_callback_limit=249)
    request = ContextRequest(
        graph_id=CTX_GRAPH_ID, mode="ranked_discovery", query="InvoiceService",
        intent="implementation", bindings=(BINDING_CORE, BINDING_DOCS), budget_bytes=16384,
    )
    with adapter:
        packet = build_compact_context(request, adapter, work_ledger=ledger)
    snapshot = deepcopy(packet)
    ledger.logical_read_units += 1  # Projection must read the delivered snapshot, not live counters.
    payload: dict[str, Any] = project_compact_context(packet, work_ledger=ledger).to_payload()
    limits = {row["name"]: row for row in payload["limits"]}
    metrics = {row["name"]: row for row in payload["metrics"]}
    assert limits["wall_clock_deadline"]["value"] == 9999
    assert limits["sqlite_progress_callback_limit"]["value"] == 249
    assert limits["wall_clock_deadline"]["applies_this_call"] is True
    assert limits["sqlite_progress_callback_limit"]["applies_this_call"] is True
    packet_only: dict[str, Any] = project_compact_context(packet).to_payload()
    packet_limits = {row["name"]: row for row in packet_only["limits"]}
    assert packet_limits["wall_clock_deadline"]["value"] == 10000
    assert packet_limits["sqlite_progress_callback_limit"]["value"] == 250
    assert packet_limits["wall_clock_deadline"]["applies_this_call"] is None
    assert packet_limits["sqlite_progress_callback_limit"]["applies_this_call"] is None
    assert packet_only["metrics"] == payload["metrics"]
    assert metrics["logical_read_units"]["value"] == packet["work_ledger"]["logical_read_units"]
    assert metrics["logical_read_units"]["value"] != ledger.logical_read_units
    assert metrics["sqlite_vm_steps_estimate"]["value"] == packet["work_ledger"]["sqlite_vm_steps_estimate"]
    assert packet == snapshot and _accepted_local(database) == before
    _private(payload)
    _private(packet_only)
