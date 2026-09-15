from __future__ import annotations

from pathlib import Path
from threading import Condition

from psycopg.conninfo import conninfo_to_dict

import scale28_preparation_resources as preparation_resources
from scale28_preparation_resources import (
    PreparationResourceSpecification,
    prepare_resources,
)
from repomap_test_support.process_boundary import RecordingProcessBoundary


class _Connection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_slow_resource_reads_start_concurrently_and_settle_before_return(
    monkeypatch,
) -> None:
    condition = Condition()
    started = 0

    def read(value):
        nonlocal started
        with condition:
            started += 1
            condition.notify_all()
            assert condition.wait_for(lambda: started == 4, timeout=1)
        return value

    connection = _Connection()
    monkeypatch.setattr(
        preparation_resources,
        "read_allocated_tree_bytes",
        lambda _path: read(120),
    )
    monkeypatch.setattr(
        preparation_resources,
        "read_backing_free_bytes",
        lambda _path: read(1_000),
    )
    monkeypatch.setattr(
        preparation_resources,
        "read_process_rss_bytes",
        lambda _pid: read(200),
    )
    monkeypatch.setattr(
        preparation_resources,
        "read_container_rss_upper_bound",
        lambda _runtime, _container: read(300),
    )
    def connect(*, conninfo: str, autocommit: bool) -> _Connection:
        assert autocommit is True
        assert conninfo_to_dict(conninfo) == {
            "host": "127.0.0.1", "dbname": "public", "port": "55433",
            "sslmode": "disable",
            "application_name": "public preparation probe",
            "connect_timeout": "2",
            "options": "-c search_path=public -c statement_timeout=4000ms",
        }
        return connection

    monkeypatch.setattr(preparation_resources.psycopg, "connect", connect)
    monkeypatch.setattr(
        preparation_resources,
        "read_database_temporary_bytes",
        lambda _connection: 0,
    )
    monkeypatch.setattr(
        preparation_resources,
        "read_cluster_wal_bytes",
        lambda _connection: 0,
    )
    specification = PreparationResourceSpecification.create(
        pgdata_root=Path("/private/tmp/public-pgdata"),
        pgdata_baseline_bytes=100,
        client_pid=1,
        container_runtime="docker",
        postgres_container="public-postgres",
        connection_parameters={
            "host": "127.0.0.1", "dbname": "public", "port": 55433,
            "sslmode": "disable",
            "application_name": "public preparation probe",
            "options": "-c search_path=public", "connect_timeout": 99,
        },
    )

    resources = prepare_resources(specification)

    assert resources.baseline.allocated_delta_bytes == 20
    assert resources.baseline.backing_free_bytes == 1_000
    assert resources.baseline.client_peak_rss_bytes == 200
    assert resources.baseline.postgresql_container_rss_upper_bound == 300
    resources.close()
    assert connection.closed is True


def test_complete_preparation_resource_read_creates_no_host_process(
    monkeypatch,
) -> None:
    connection = _Connection()
    monkeypatch.setattr(
        preparation_resources,
        "read_allocated_tree_bytes",
        lambda _path: 120,
    )
    monkeypatch.setattr(
        preparation_resources,
        "read_backing_free_bytes",
        lambda _path: 1_000,
    )
    monkeypatch.setattr(
        preparation_resources,
        "read_process_rss_bytes",
        lambda _pid: 200,
    )
    monkeypatch.setattr(
        preparation_resources,
        "read_container_rss_upper_bound",
        lambda _runtime, _container: 300,
    )
    monkeypatch.setattr(
        preparation_resources.psycopg,
        "connect",
        lambda **_parameters: connection,
    )
    monkeypatch.setattr(
        preparation_resources,
        "read_database_temporary_bytes",
        lambda _connection: 0,
    )
    monkeypatch.setattr(
        preparation_resources,
        "read_cluster_wal_bytes",
        lambda _connection: 0,
    )
    boundary = RecordingProcessBoundary().install(monkeypatch)
    specification = PreparationResourceSpecification.create(
        pgdata_root=Path("/private/tmp/public-pgdata"),
        pgdata_baseline_bytes=100,
        client_pid=1,
        container_runtime="docker",
        postgres_container="public-postgres",
        connection_parameters={"host": "127.0.0.1", "dbname": "public"},
    )

    resources = prepare_resources(specification)

    assert boundary.host_process_count == 0
    assert boundary.nested_psql_intent_count == 0
    resources.close()
