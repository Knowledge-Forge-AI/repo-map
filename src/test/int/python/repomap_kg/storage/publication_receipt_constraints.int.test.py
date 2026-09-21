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
