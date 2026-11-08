"""Real PostgreSQL Server resource-view outcomes, cancellation, and staging projection."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
import os
import select
from pathlib import Path
import subprocess
import sys
import time
import threading
from typing import Any

import pytest

from common_lore_index.ops import portable_refresh
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.refresh import query_graph_summary, refresh_graph
from common_lore_index.ops.resource_view import ResourceObserver
from common_lore_index.ops.resource_view._projections import project_staging_resources
from common_lore_index.storage import apply_migrations, default_rdbms_root
from common_lore_index.storage.errors import StorageCommitUnknownError
from common_lore_index.storage.staging_observability import StagingMeasurements
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.cli_in_process import module_process_environment
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.sqlite_managed_child import ManagedChild, cleanup_after_failure
from runner_coverage_observer import popen_observed_process

_TEST_CONTROL_ACK = b"resource-view-test-control-ack-v1\n"
_TEST_CONTROL_ACK_REQUEST = b"resource-view-test-control-ack-request-v1\n"


def _setup(tmp_path: Path, postgres: Any) -> tuple[Any, Path, str]:
    working = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
    home = write_mixed_v1_postgres_home(
        tmp_path / "postgres-home", working,
        host=postgres.host, port=postgres.port, database=postgres.database,
        user=postgres.user, password=postgres.password,
    )
    config = load_graph_registry_config_home(home)
    assert isinstance(config, OpsConfig)
    apply_migrations(
        default_rdbms_root(), config.postgres.psql_args_for_database(postgres.database),
        psql_command=postgres.psql_command,
    )
    return config, home, postgres.psql_command


def _report(observer: ResourceObserver, outcome: str) -> dict[str, Any]:
    payload: dict[str, Any] = observer.report().to_payload()
    assert payload["schema"] == "cloe-resource-view-v1"
    assert payload["operation"] == "server_refresh"
    assert payload["backend"] == "postgresql"
    assert payload["outcome"] == outcome
    assert_canary_free(payload)
    workers = {
        item["name"]: item for item in payload["metrics"]
        if item["name"] in {"worker_cpu", "worker_peak_rss"}
    }
    if outcome == "committed":
        assert {row["reason"] for row in workers.values()} == {"not_observed"}
    encoded = json.dumps(payload, sort_keys=True)
    assert "mixed-v1" not in encoded and "TRUNCATABLE_PROSE_PREFIX_MARKER_V1" not in encoded
    return payload


def _wait_child_token(
    child: ManagedChild, expected: bytes, *, deadline_seconds: float = 300.0
) -> None:
    stream = child.stderr
    assert stream is not None
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        readable, _, _ = select.select([stream], [], [], 0.25)
        if not readable:
            if child.poll() is not None:
                _, stderr = child.communicate(timeout=2)
                raise AssertionError(f"owned child exited before readiness: {stderr}")
            continue
        token = stream.readline() if expected.endswith(b"\n") else stream.read(len(expected))
        if token == expected:
            return
        if not token:
            break
    raise AssertionError("owned child did not complete the test-control handshake")


def _send_test_control_ack(child: ManagedChild) -> None:
    """Complete the test-control ACK; this is not backend telemetry proof."""
    _wait_child_token(child, _TEST_CONTROL_ACK_REQUEST)
    stdin = child.stdin
    assert stdin is not None
    stdin.write(_TEST_CONTROL_ACK)
    stdin.flush()


_SERVER_CANCEL_SCRIPT = """
import json, os, signal, sys, time
TEST_CONTROL_ACK = b"resource-view-test-control-ack-v1\\n"
signal.signal(signal.SIGINT, signal.default_int_handler)
from common_lore_index.ops import portable_refresh
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.refresh import refresh_graph
from common_lore_index.ops.resource_view import ResourceObserver
expected_parent = int(sys.argv[3])
sys.stderr.buffer.write(b"resource-view-test-control-ack-request-v1\\n")
sys.stderr.buffer.flush()
if sys.stdin.buffer.read(len(TEST_CONTROL_ACK)) != TEST_CONTROL_ACK:
    raise RuntimeError("test-control ACK is invalid")
if os.getppid() != expected_parent:
    raise RuntimeError("owned child parent relation is invalid")
def wait_for_ack(*args, **kwargs):
    if os.getppid() != expected_parent:
        raise RuntimeError("owned child parent relation is invalid")
    sys.stderr.buffer.write(b"\x01")
    sys.stderr.buffer.flush()
    while True:
        time.sleep(60)
portable_refresh.run_staged_portable_refresh = wait_for_ack
observer = ResourceObserver()
result = refresh_graph(
    load_graph_registry_config_home(sys.argv[1]), "mixed-v1",
    psql_command=sys.argv[2], resource_observer=observer,
)
print(json.dumps({
    "result": result.result,
    "publication_state": result.publication_state,
    "report": observer.report().to_payload(),
}), flush=True)
"""


def test_real_server_commit_report_and_no_staging_work_when_unselected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with temporary_postgres() as postgres:
        config, _home, psql_command = _setup(tmp_path, postgres)
        calls: list[object] = []
        import common_lore_index.storage.staged_ingestion as staged_ingestion

        monkeypatch.setattr(
            staged_ingestion, "capture_staging_resources",
            lambda *_args, **_kwargs: calls.append(object()),
        )
        observer = ResourceObserver()
        result = refresh_graph(
            config, MIXED_V1_GRAPH_ID, psql_command=psql_command, resource_observer=observer
        )
        assert result.result == "success" and result.publication_state == "committed"
        _report(observer, "committed")
        assert calls == [], "resource view must not construct or capture staging measurements"


@pytest.mark.parametrize(
    ("error", "expected"),
    ((ValueError("injected server failure"), "failed"),
     (StorageCommitUnknownError("injected commit uncertainty"), "commit_unknown")),
)
def test_server_failure_and_commit_unknown_are_reported_without_error_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException, expected: str
) -> None:
    with temporary_postgres() as postgres:
        config, _home, psql_command = _setup(tmp_path, postgres)

        def fail(*_args: Any, **_kwargs: Any) -> Any:
            raise error

        monkeypatch.setattr(portable_refresh, "run_staged_portable_refresh", fail)
        observer = ResourceObserver()
        result = refresh_graph(
            config, MIXED_V1_GRAPH_ID, psql_command=psql_command, resource_observer=observer
        )
        assert result.result == "failure"
        assert result.publication_state == ("commit_unknown" if expected == "commit_unknown" else "not_started")
        payload = _report(observer, expected)
        assert "injected server" not in json.dumps(payload, sort_keys=True)


def test_server_sigint_is_sent_only_to_owned_child_after_post_ack_byte(tmp_path: Path) -> None:
    with temporary_postgres() as postgres:
        config, home, psql_command = _setup(tmp_path, postgres)
        initial = refresh_graph(config, MIXED_V1_GRAPH_ID, psql_command=psql_command)
        assert initial.result == "success"
        raw = popen_observed_process(
            [
                sys.executable, "-c", _SERVER_CANCEL_SCRIPT,
                str(home), psql_command, str(os.getpid()),
            ],
            family="cli_module",
            cwd=tmp_path,
            env=module_process_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            pid_namespace_relation="shared",
            start_new_session=True,
        )
        child = ManagedChild(raw, group_owned=True)
        try:
            _send_test_control_ack(child)
            _wait_child_token(child, b"\x01")
            child.interrupt()
            stdout, stderr = child.communicate(timeout=300)
            child.verify_dead_and_group()
        except BaseException as error:
            cleanup_after_failure(child, error)
            raise
        assert child.returncode == 0, stderr
        payload = json.loads(stdout)
        assert (payload["result"], payload["publication_state"]) == ("failure", "not_started")
        assert payload["report"]["outcome"] == "cancelled"
        assert payload["report"]["instrumentation"] in {"complete", "incomplete"}
        assert_canary_free(payload["report"])
        encoded = json.dumps(payload["report"], sort_keys=True)
        assert "mixed-v1" not in encoded and str(home) not in encoded
        accepted = query_graph_summary(config, MIXED_V1_GRAPH_ID, psql_command=psql_command)
        assert accepted.result == "success"
        assert accepted.latest_run_status == "complete"
        assert accepted.latest_run_id == initial.run_id
        recovered = refresh_graph(config, MIXED_V1_GRAPH_ID, psql_command=psql_command)
        assert recovered.result == "success" and recovered.publication_state == "committed"


def test_selected_staging_events_project_real_server_events_without_sql_or_sink_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with temporary_postgres() as postgres:
        config, _home, psql_command = _setup(tmp_path, postgres)
        events: list[object] = []
        sink_calls = 0

        def sink(event: object) -> None:
            nonlocal sink_calls
            sink_calls += 1
            events.append(event)

        measurements = StagingMeasurements(sink, event_limit=1024)
        result = refresh_graph(
            config,
            MIXED_V1_GRAPH_ID,
            psql_command=psql_command,
            staging_measurements=measurements,
        )
        assert result.result == "success"
        assert result.publication_state == "committed"
        assert events, "the selected caller sink received no real staging events"
        before = (len(events), sink_calls)

        import common_lore_index.storage.staged_ingestion as staged_ingestion
        import common_lore_index.storage.staging_resource_observability as resource_sampling

        def no_sql(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("staging projection performed a storage sample")

        monkeypatch.setattr(staged_ingestion, "capture_staging_resources", no_sql)
        monkeypatch.setattr(resource_sampling, "capture_staging_resources", no_sql)
        projected = project_staging_resources(tuple(events), measurements_failed=measurements.failed)
        assert (len(events), sink_calls) == before

    values = {item.name: item for item in projected}
    expected_bases = {
        "wal_upper_bound": "shared_upper_bound",
        "temporary_byte_upper_bound": "shared_upper_bound",
        "postgresql_memory": "sampled_max",
        "client_memory": "process_lifetime_peak",
    }
    assert set(values) == set(expected_bases)
    for name, basis in expected_bases.items():
        metric = values[name]
        assert metric.basis == basis
        if metric.availability == "measured":
            assert isinstance(metric.value, int) and metric.value >= 0
        else:
            assert metric.value is None
            assert metric.reason in {"not_observed", "not_emitted", "observer_failed"}


def test_staging_measurement_failure_does_not_relabel_commit(
    tmp_path: Path,
) -> None:
    with temporary_postgres() as postgres:
        config, _home, psql_command = _setup(tmp_path, postgres)
        events: list[object] = []
        sink_calls = 0

        def failing_sink(event: object) -> None:
            nonlocal sink_calls
            sink_calls += 1
            events.append(event)
            raise RuntimeError("injected staging sink failure")

        measurements = StagingMeasurements(failing_sink, event_limit=1024)
        result = refresh_graph(
            config,
            MIXED_V1_GRAPH_ID,
            psql_command=psql_command,
            staging_measurements=measurements,
        )
        assert result.result == "success"
        assert result.publication_state == "committed"
        assert sink_calls == 1
        assert events
        assert measurements.failed is True
        accepted = query_graph_summary(
            config, MIXED_V1_GRAPH_ID, psql_command=psql_command,
        )
        assert accepted.result == "success"
        assert accepted.latest_run_status == "complete"
        assert accepted.latest_run_id == result.run_id

        projected = project_staging_resources(
            tuple(events), measurements_failed=measurements.failed,
        )

    values = {item.name: item for item in projected}
    expected_bases = {
        "wal_upper_bound": "shared_upper_bound",
        "temporary_byte_upper_bound": "shared_upper_bound",
        "postgresql_memory": "sampled_max",
        "client_memory": "process_lifetime_peak",
    }
    assert set(values) == set(expected_bases)
    for name, basis in expected_bases.items():
        metric = values[name]
        assert metric.basis == basis
        assert metric.availability == "unavailable"
        assert metric.value is None
        assert metric.reason == "observer_failed"
    assert_canary_free([item.to_payload() for item in projected])


def test_concurrent_observed_server_refreshes_keep_publication_and_reports_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from common_lore_index.storage import staged_publication

    with temporary_postgres() as postgres:
        config, _home, psql_command = _setup(tmp_path, postgres)
        ready, release = threading.Event(), threading.Event()
        first_thread: list[int] = []
        execute = staged_publication._execute

        def hold_after_real_lock(connection: Any, statements: Any) -> None:
            # execute_final_transaction acquired its real advisory lock before
            # this first statement owner. No accepted-state SQL has run yet.
            if threading.get_ident() in first_thread and not ready.is_set():
                ready.set()
                if not release.wait(120):
                    raise AssertionError("owned publication hold was not released")
            execute(connection, statements)

        def observed_call(hold: bool) -> tuple[Any, dict[str, Any]]:
            if hold:
                first_thread.append(threading.get_ident())
            observer = ResourceObserver()
            result = refresh_graph(
                config, MIXED_V1_GRAPH_ID, psql_command=psql_command,
                resource_observer=observer,
            )
            return result, observer.report().to_payload()

        monkeypatch.setattr(staged_publication, "_execute", hold_after_real_lock)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(observed_call, True)
            try:
                assert ready.wait(120), "first refresh did not acquire its publication lock"
                second_result, second_report = pool.submit(observed_call, False).result(timeout=120)
            finally:
                release.set()
            first_result, first_report = first.result(timeout=120)

        assert first_result.result == "success"
        assert first_result.publication_state == "committed"
        assert first_report["outcome"] == "committed"
        assert first_report["instrumentation"] == "complete"
        assert second_result.result == "failure"
        assert second_report["outcome"] == "failed"
        assert second_report["instrumentation"] == "incomplete"
        assert second_result.run_id is None
        accepted = query_graph_summary(config, MIXED_V1_GRAPH_ID, psql_command=psql_command)
        assert accepted.result == "success" and accepted.latest_run_status == "failed"
        assert accepted.latest_run_id != first_result.run_id
        # Latest recorded attempt and accepted publication are different owners.
        assert postgres.psql_scalar("SELECT id FROM runs WHERE status = 'complete'") == str(first_result.run_id)
        assert postgres.psql_scalar(
            f"SELECT count(*) FROM raw_observations WHERE run_id <> {int(first_result.run_id)}"
        ) == "0"
        for report in (first_report, second_report):
            assert_canary_free(report)
            assert "mixed-v1" not in json.dumps(report, sort_keys=True)
