import io
import socket
import sys
import threading
from typing import Any

import psycopg
import pytest

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage._psql_stream import (
    _BoundedTextCapture,
    _PsqlStreamFailure,
    _is_connection_failure,
    _write_chunks,
    run_psql_stream,
)
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.backend_ownership import ConnectionRole
from repomap_kg.storage.backend_telemetry_contracts import (
    ConnectionTelemetryError,
    ConnectionTelemetryEvent,
    TelemetryEventKind,
)
from repomap_kg.storage.backend_telemetry_events import (
    frame_telemetry_event,
    parse_telemetry_frame,
    read_telemetry_event,
)
from repomap_kg.storage.readback_driver import (
    DiagnosticOptions,
    _resolve_diagnostic_options,
)
from repomap_kg.storage.staging_event_transport import (
    StagingEventChannel,
    StagingEventTransportError,
)
from repomap_test_support.postgres_harness import temporary_postgres


def test_publication_receipt_constraints_are_atomic_and_unique():
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        with psycopg.connect(
            host=postgres.host,
            port=postgres.port,
            user=postgres.user,
            dbname=postgres.database,
            password=postgres.password,
            autocommit=True,
        ) as connection:
            row = connection.execute(
                "INSERT INTO repositories(name, root_path) "
                "VALUES ('fixture', '/public/fixture') RETURNING id"
            ).fetchone()
            assert row is not None
            repository_id = row[0]
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "INSERT INTO runs(repository_id, status, source_generation) "
                    "VALUES (%s, 'complete', 'sg1:partial')",
                    (repository_id,),
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "INSERT INTO runs("
                    "repository_id, status, publication_job_id"
                    ") VALUES (%s, 'complete', 'job-partial')",
                    (repository_id,),
                )
            values = (
                repository_id,
                "job-unique",
                1,
                "sg1:source",
                "cg1:config",
                "eg1:extractor",
                "kg1:canonicalizer",
            )
            sql = (
                "INSERT INTO runs("
                "repository_id, status, publication_job_id, publication_attempt, "
                "source_generation, config_generation, extractor_generation, "
                "canonicalizer_generation) VALUES (%s, 'complete', %s, %s, %s, "
                "%s, %s, %s)"
            )
            connection.execute(sql, values)
            with pytest.raises(psycopg.errors.UniqueViolation):
                connection.execute(sql, values)


def test_staging_event_transport_socketpair_lifecycle():
    server, client = socket.socketpair()
    try:
        with pytest.raises(ValueError):
            StagingEventChannel(server, acknowledgement_timeout_seconds=0)

        chan_s = StagingEventChannel(server, acknowledgement_timeout_seconds=2.0)
        chan_c = StagingEventChannel(client, acknowledgement_timeout_seconds=2.0)

        with pytest.raises(StagingEventTransportError):
            chan_s.send("invalid_cat", {"key": "val"})

        bad_payload: Any = "not_a_dict"
        with pytest.raises(StagingEventTransportError):
            chan_s.send("phase", bad_payload)

        received = []
        receiver_exc: list[BaseException] = []

        def receiver() -> None:
            try:
                frame = chan_c.receive(timeout_seconds=2.0, validator=lambda _f: None)
                received.append(frame)
            except BaseException as exc:
                receiver_exc.append(exc)

        thread = threading.Thread(target=receiver)
        thread.start()
        chan_s.send("phase", {"status": "started"})
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        if receiver_exc:
            raise receiver_exc[0]

        assert len(received) == 1
        assert received[0].category == "phase"
        assert received[0].payload == {"status": "started"}
        assert received[0].sequence == 1

        chan_s.close()
        chan_s.close()
        chan_c.close()
    finally:
        server.close()
        client.close()


def test_psql_stream_streaming_and_error_handling():
    assert _is_connection_failure("could not connect to server") is True
    assert _is_connection_failure("syntax error in query") is False

    cap = _BoundedTextCapture(10)
    cap.append(b"0123456789extra")
    assert cap.text() == "56789extra"

    cap2 = _BoundedTextCapture(5)
    cap2.append(b"123")
    cap2.append(b"456")
    assert cap2.text() == "23456"

    sink = io.BytesIO()
    with pytest.raises(ValueError):
        _write_chunks(sink, ["a"], batch_size=0)

    bad_chunks: Any = [123]
    with pytest.raises(TypeError):
        _write_chunks(sink, bad_chunks, batch_size=1)

    count = _write_chunks(sink, ["hello\n", "world\n"], batch_size=1)
    assert count == 2
    assert sink.getvalue() == b"hello\nworld\n"

    cat_cmd = [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"]
    false_cmd = [sys.executable, "-c", "import sys; sys.exit(1)"]

    with pytest.raises(ValueError):
        run_psql_stream(cat_cmd, [], capture_limit=0)

    proc = run_psql_stream(cat_cmd, ["row1\n", "row2\n"])
    assert proc.returncode == 0
    assert proc.stdout == "row1\nrow2\n"

    with pytest.raises(_PsqlStreamFailure) as failure:
        run_psql_stream(false_cmd, ["err\n"])
    assert failure.value.supports_container_fallback is False

    with pytest.raises(StorageSchemaError):
        run_psql_stream(["/path/does/not/exist/psql"], ["x\n"])


def test_storage_readback_diagnostic_options_and_telemetry_framing() -> None:
    opt_none = _resolve_diagnostic_options(None, 500)
    assert opt_none == DiagnosticOptions("-c default_transaction_read_only=on -c statement_timeout=500", 500)
    assert _resolve_diagnostic_options('has"quote', 500) is None
    assert _resolve_diagnostic_options("-c invalid_no_equal", 500) is None
    assert _resolve_diagnostic_options("-c 123badkey=1", 500) is None
    assert _resolve_diagnostic_options("-c k=1 -c k=2", 500) is None
    assert _resolve_diagnostic_options("-c default_transaction_read_only=badval", 500) is None
    assert _resolve_diagnostic_options("-c statement_timeout=badval", 500) is None
    opt_valid = _resolve_diagnostic_options("-c statement_timeout=2s -c default_transaction_read_only=off", 5000)
    assert opt_valid is not None
    assert opt_valid.effective_timeout_ms == 2000

    evt = ConnectionTelemetryEvent(
        schema_version=1,
        connection_sequence=1,
        connection_generation=1,
        connection_role=ConnectionRole.DIRECT_MAINTENANCE_ADMISSION,
        backend_pid=1234,
        event=TelemetryEventKind.CONNECTION_OPENED,
        monotonic_ns=100000,
    )
    wire = frame_telemetry_event(evt)
    parsed = parse_telemetry_frame(wire)
    assert parsed.schema_version == evt.schema_version
    assert parsed.backend_pid == evt.backend_pid

    with pytest.raises(ConnectionTelemetryError):
        parse_telemetry_frame(b"tiny")
    with pytest.raises(ConnectionTelemetryError):
        parse_telemetry_frame(b"\x00\x00\x00\x10bad_payload")

    stream = io.BytesIO(wire)
    read_back = read_telemetry_event(stream)
    assert read_back is not None
    assert read_back.backend_pid == 1234

    empty_stream = io.BytesIO(b"")
    assert read_telemetry_event(empty_stream) is None


def test_staging_event_transport_extended_receive_and_readiness() -> None:
    server, client = socket.socketpair()
    try:
        chan_s = StagingEventChannel(server, acknowledgement_timeout_seconds=2.0)
        chan_c = StagingEventChannel(client, acknowledgement_timeout_seconds=2.0)

        with pytest.raises(ValueError):
            chan_c.receive(timeout_seconds=-1.0)

        ready_called: list[bool] = []

        def on_ready() -> None:
            ready_called.append(True)

        received = []
        receiver_exc: list[BaseException] = []

        def receiver() -> None:
            try:
                frame = chan_c.receive(timeout_seconds=2.0, readiness=on_ready)
                received.append(frame)
            except BaseException as exc:
                receiver_exc.append(exc)

        thread = threading.Thread(target=receiver)
        thread.start()
        chan_s.send("measurement", {"count": 42})
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        if receiver_exc:
            raise receiver_exc[0]
        assert len(received) == 1
        assert ready_called == [True]
        assert received[0].category == "measurement"
        assert received[0].payload == {"count": 42}

        chan_s.close()
        chan_c.close()
    finally:
        server.close()
        client.close()
