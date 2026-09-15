from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
import time

import psycopg

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staging_operation_contracts import (
    STAGING_OPERATION_DESCRIPTORS,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.scale12_supervision_policy import (
    OperationArmedElapsedMonitor,
    attribution_qualification_monitor,
)
from scale12_event_transport import Scale12EventChannel
from scale12_profile_supervisor import (
    Scale12ProfileSupervisor,
    _ThresholdMonitor,
    start_profile_child,
)
from scale12_resource_sampling import (
    Scale12ResourceSampler,
    host_free_bytes,
    read_process_rss_bytes,
)


def _migrate(postgres) -> None:
    apply_migrations(
        default_rdbms_root(),
        postgres.psql_args,
        psql_command=postgres.psql_command,
    )


def _run(postgres, *, repetition: int, delay: str | None = None):
    parent_socket, child_socket = socket.socketpair()
    process = start_profile_child(
        sys.executable,
        postgres.psql_args,
        profile="mixed",
        work_items=32,
        repetition=repetition,
        event_socket=child_socket,
        delay_operation_code=delay,
        delay_seconds=2.0 if delay is not None else None,
    )
    child_socket.close()
    sampler = Scale12ResourceSampler(
        {
            "client_peak_rss_bytes": lambda: read_process_rss_bytes(process.pid),
            "host_free_bytes": lambda: host_free_bytes(Path.cwd()),
        }
    )
    monitor: _ThresholdMonitor = attribution_qualification_monitor()
    if delay is not None:
        monitor = OperationArmedElapsedMonitor(delay, delay_seconds=1)
    supervisor = Scale12ProfileSupervisor(
        process,
        Scale12EventChannel(parent_socket),
        sampler,
        monitor=monitor,
        signal_grace_seconds=10.0,
    )
    primary_exc: BaseException | None = None
    try:
        return supervisor.run()
    except BaseException as error:
        primary_exc = error
        raise
    finally:
        try:
            process.wait(timeout=60)
        finally:
            supervisor.settle(primary_exc=primary_exc)


def _wait_for_no_other_backends(connection, *, timeout_seconds: float = 2.0) -> int:
    deadline = time.monotonic() + timeout_seconds
    while True:
        count = connection.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid()"
        ).fetchone()[0]
        if count == 0 or time.monotonic() >= deadline:
            return count
        time.sleep(0.05)


def test_supervised_current_publication_is_stable_complete_and_private() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _migrate(postgres)
        first = _run(postgres, repetition=1)
        second = _run(postgres, repetition=2)

    expected_sequence = tuple(
        code for code in STAGING_OPERATION_DESCRIPTORS if code != "cleanup.stage"
    )
    assert first.terminal_category == "completed", first
    assert first.child_exit_code == 0
    assert first.signal_count == 0
    assert first.operation_sequence == expected_sequence
    assert second.operation_sequence == expected_sequence
    assert first.profile_summary is not None
    assert second.profile_summary is not None
    assert first.profile_summary["receipt_complete"] is True
    assert first.profile_summary["cleanup_complete"] is True
    assert first.profile_summary["family_row_counts"] == second.profile_summary[
        "family_row_counts"
    ]
    assert first.profile_summary["structural_digest"] == second.profile_summary[
        "structural_digest"
    ]
    encoded = json.dumps(first.profile_summary, sort_keys=True)
    assert len(encoded.encode("utf-8")) < 65_536
    assert postgres.host not in encoded
    assert not any(
        metric.crossed_before_cancel
        for metric in first.threshold_evaluation.metrics
    )


def test_delayed_merge_is_exactly_attributed_and_cancelled_without_receipt() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _migrate(postgres)
        result = _run(postgres, repetition=1, delay="merge.files")
        assert result.terminal_category == "cancelled"
        assert result.child_exit_code == 130
        assert result.signal_count == 1
        assert result.primary_stop_active_operation == "merge.files"
        assert result.cancelled_operation_sequence == ("merge.files",)
        assert result.crossing_to_signal_seconds is not None
        assert result.crossing_to_signal_seconds <= 2.0
        assert result.signal_to_child_exit_seconds is not None
        assert result.signal_to_child_exit_seconds <= 60.0
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(psycopg.conninfo.make_conninfo(**params)) as connection:
            repository_row = connection.execute(
                "SELECT id FROM repositories WHERE name = %s",
                ("scale11-public-fixture-mixed-32",),
            ).fetchone()
            assert repository_row is not None
            repository_id = repository_row[0]
            complete_receipts_row = connection.execute(
                "SELECT count(*) FROM runs WHERE repository_id = %s "
                "AND status = 'complete'",
                (repository_id,),
            ).fetchone()
            assert complete_receipts_row is not None
            complete_receipts = complete_receipts_row[0]
            final_files_row = connection.execute(
                "SELECT count(*) FROM files WHERE repository_id = %s",
                (repository_id,),
            ).fetchone()
            assert final_files_row is not None
            final_files = final_files_row[0]
            stage_state = connection.execute(
                "SELECT state, merge_status, publication_reconciliation_state, "
                "cleanup_eligibility "
                "FROM ingestion_stages"
            ).fetchone()
            other_backends = _wait_for_no_other_backends(connection)

    assert complete_receipts == 0
    assert final_files == 0
    assert stage_state == ("failed", "rolled_back", "reconciled", "eligible")
    assert other_backends == 0
