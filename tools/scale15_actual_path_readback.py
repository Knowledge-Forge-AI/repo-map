"""Canonical receipt and seven-family terminal readback for SCALE15."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import select
import sys
from time import monotonic
from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.pq import abc as pq_abc

from repomap_kg.storage.authority import PublicationGenerations
from repomap_kg.storage.publication import (
    RunPublicationReceipt,
    publication_receipt_from_mapping,
)
from repomap_kg.storage.publication_readback import (
    read_latest_receipt_bearing_publication,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.run_authority import (
    read_run_authority,
)
from semantic_digest_readback import (
    empty_semantic_digest as _empty_semantic_digest,
    read_semantic_digest,
)
from scale15_terminal_contracts import (
    ExpectedRefreshAuthority,
    FINAL_FAMILY_CODES,
    TerminalReadback,
)
from scale15_readback_records import (
    StageTerminalEvidence,
    TerminalBackendReadTimeout,
    TerminalStorageEvidence,
)
from scale15_readback_contracts import (
    _empty_family_counts,
    _semantic_run_id,
    classify_terminal_evidence,
)

_TERMINAL_BACKEND_QUERY = (
    b"SELECT count(*) FROM pg_stat_activity "
    b"WHERE datname = current_database() AND pid <> pg_backend_pid()"
)


def read_scale15_terminal_state(
    psql_args: Sequence[str],
    expected: ExpectedRefreshAuthority,
    *,
    psql_command: str = "psql",
    pre_binding: bool = False,
    pre_stage: bool = False,
) -> TerminalReadback:
    """Read and classify one exact dedicated graph database terminal state."""

    expected.validate()
    authority = read_run_authority(
        psql_args,
        expected.repository_name,
        psql_command=psql_command,
    )
    canonical = read_latest_receipt_bearing_publication(
        psql_args,
        psql_command=psql_command,
    )
    params = _psycopg_connection_params_from_psql_args(psql_args)
    with psycopg.connect(
        host=params.get("host"), port=params.get("port"),
        user=params.get("user"), dbname=params.get("dbname"),
    ) as connection:
        repository = connection.execute(
            "SELECT id, repository_identity FROM repositories "
            "WHERE name = %s ORDER BY id DESC LIMIT 1",
            (expected.repository_name,),
        ).fetchone()
        if repository is None:
            evidence = TerminalStorageEvidence(
                False, authority, canonical, None, False, None,
                _empty_family_counts(), _empty_semantic_digest(), False,
            )
            return classify_terminal_evidence(
                expected, evidence,
                pre_binding=pre_binding, pre_stage=pre_stage,
            )
        repository_id = int(repository[0])
        identity_matches = repository[1] == expected.repository_identity
        latest_receipt, malformed = _latest_run_receipt(
            connection, repository_id
        )
        stage = _latest_stage(connection, repository_id)
        semantic_run_id = _semantic_run_id(authority)
        family_counts, digest = (
            (_empty_family_counts(), _empty_semantic_digest())
            if semantic_run_id is None
            else _read_semantic_digest(
                connection, repository_id, semantic_run_id,
            )
        )
    evidence = TerminalStorageEvidence(
        identity_matches, authority, canonical,
        latest_receipt, malformed, stage,
        family_counts, digest,
    )
    return classify_terminal_evidence(
        expected, evidence,
        pre_binding=pre_binding, pre_stage=pre_stage,
    )


def read_terminal_backend_summary(
    psql_args: Sequence[str],
    *,
    timeout_seconds: float = 0.5,
) -> dict[str, int]:
    """Use one fresh observer and classify every other graph-database backend."""

    if not 0 < timeout_seconds <= 0.5:
        raise ValueError("terminal backend read deadline is invalid")
    params = _psycopg_connection_params_from_psql_args(psql_args)
    conninfo = make_conninfo(**params).encode("utf-8")
    deadline = monotonic() + timeout_seconds
    connection: pq_abc.PGconn | None = None
    try:
        connection = _start_terminal_connection(conninfo)
        _poll_terminal_connection(connection, deadline)
        connection.nonblocking = 1
        _require_terminal_authority(deadline, "query_execution")
        connection.send_query(_TERMINAL_BACKEND_QUERY)
        _require_terminal_authority(deadline, "query_execution")
        _flush_terminal_query(connection, deadline)
        _consume_terminal_query(connection, deadline)
        other = _fetch_terminal_count(connection, deadline)
        return {
            "observer": 1,
            "unknown": other,
        }
    finally:
        if connection is not None:
            active_error = sys.exc_info()[0] is not None
            try:
                connection.finish()
            except Exception:
                if not active_error:
                    raise
            if not active_error and monotonic() >= deadline:
                raise TerminalBackendReadTimeout("connection_settlement")


def _start_terminal_connection(conninfo: bytes) -> pq_abc.PGconn:
    """Start one libpq connection without waiting for acquisition."""

    return psycopg.pq.PGconn.connect_start(conninfo)


def _wait_terminal_io(
    socket_fd: int,
    *,
    readable: bool,
    writable: bool,
    timeout_seconds: float,
) -> bool:
    """Wait for one nonblocking libpq transition under caller authority."""

    ready_read, ready_write, _ = select.select(
        [socket_fd] if readable else (),
        [socket_fd] if writable else (),
        (),
        timeout_seconds,
    )
    return bool(ready_read or ready_write)


def _require_terminal_authority(deadline: float, stage: str) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TerminalBackendReadTimeout(stage)
    return remaining


def _wait_for_terminal_transition(
    connection: pq_abc.PGconn,
    deadline: float,
    stage: str,
    *,
    readable: bool = False,
    writable: bool = False,
) -> None:
    remaining = _require_terminal_authority(deadline, stage)
    if not _wait_terminal_io(
        connection.socket,
        readable=readable,
        writable=writable,
        timeout_seconds=remaining,
    ):
        raise TerminalBackendReadTimeout(stage)


def _poll_terminal_connection(
    connection: pq_abc.PGconn,
    deadline: float,
) -> None:
    while True:
        _require_terminal_authority(deadline, "connection_acquisition")
        if connection.status == psycopg.pq.ConnStatus.BAD:
            raise psycopg.OperationalError(
                "terminal backend connection acquisition failed"
            )
        status = connection.connect_poll()
        _require_terminal_authority(deadline, "connection_acquisition")
        if status == psycopg.pq.PollingStatus.OK:
            return
        if status == psycopg.pq.PollingStatus.FAILED:
            raise psycopg.OperationalError(
                "terminal backend connection acquisition failed"
            )
        if status not in {
            psycopg.pq.PollingStatus.READING,
            psycopg.pq.PollingStatus.WRITING,
        }:
            raise psycopg.OperationalError(
                "terminal backend connection polling failed"
            )
        _wait_for_terminal_transition(
            connection,
            deadline,
            "connection_acquisition",
            readable=status == psycopg.pq.PollingStatus.READING,
            writable=status == psycopg.pq.PollingStatus.WRITING,
        )


def _flush_terminal_query(
    connection: pq_abc.PGconn,
    deadline: float,
) -> None:
    while True:
        _require_terminal_authority(deadline, "query_execution")
        status = connection.flush()
        _require_terminal_authority(deadline, "query_execution")
        if status == 0:
            return
        if status != 1:
            raise psycopg.OperationalError("terminal backend query dispatch failed")
        _wait_for_terminal_transition(
            connection,
            deadline,
            "query_execution",
            writable=True,
        )


def _consume_terminal_query(
    connection: pq_abc.PGconn,
    deadline: float,
) -> None:
    _require_terminal_authority(deadline, "result_fetch")
    while connection.is_busy():
        _wait_for_terminal_transition(
            connection,
            deadline,
            "result_fetch",
            readable=True,
        )
        _require_terminal_authority(deadline, "result_fetch")
        connection.consume_input()
        _require_terminal_authority(deadline, "result_fetch")


def _fetch_terminal_count(
    connection: pq_abc.PGconn,
    deadline: float,
) -> int:
    results = []
    while True:
        _require_terminal_authority(deadline, "result_fetch")
        result = connection.get_result()
        _require_terminal_authority(deadline, "result_fetch")
        if result is None:
            break
        results.append(result)
    if (
        len(results) != 1
        or results[0].status != psycopg.pq.ExecStatus.TUPLES_OK
    ):
        raise psycopg.OperationalError("terminal backend query failed")
    result = results[0]
    if result.ntuples != 1 or result.nfields != 1:
        raise ValueError("terminal backend result is invalid")
    _require_terminal_authority(deadline, "result_fetch")
    value = result.get_value(0, 0)
    _require_terminal_authority(deadline, "result_fetch")
    if value is None:
        raise ValueError("terminal backend result is invalid")
    return int(value)


def _latest_run_receipt(
    connection: psycopg.Connection[Any], repository_id: int
) -> tuple[RunPublicationReceipt | None, bool]:
    fields = RunPublicationReceipt.field_names()
    row = connection.execute(
        "SELECT " + ", ".join(fields) + " FROM runs "
        "WHERE repository_id = %s ORDER BY id DESC LIMIT 1",
        (repository_id,),
    ).fetchone()
    if row is None:
        return None, False
    payload = dict(zip(fields, row, strict=True))
    try:
        return publication_receipt_from_mapping(payload), False
    except (TypeError, ValueError):
        return None, True


def _latest_stage(
    connection: psycopg.Connection[Any], repository_id: int
) -> StageTerminalEvidence | None:
    row = connection.execute(
        "SELECT state, merge_status, publication_reconciliation_state, "
        "cleanup_eligibility, execution_mode, COALESCE(job_id, operation_id), "
        "attempt, source_generation, config_generation, extractor_generation, "
        "canonicalizer_generation, expires_at < now() FROM ingestion_stages "
        "WHERE repository_id = %s ORDER BY created_at DESC, stage_id DESC LIMIT 1",
        (repository_id,),
    ).fetchone()
    if row is None:
        return None
    return StageTerminalEvidence(
        str(row[0]), str(row[1]), str(row[2]),
        str(row[3]), str(row[4]), str(row[5]),
        int(row[6]),
        PublicationGenerations(
            str(row[7]), str(row[8]), str(row[9]), str(row[10])
        ).validate(),
        bool(row[11]),
    )


def _read_semantic_digest(
    connection: psycopg.Connection[Any],
    repository_id: int,
    run_id: int,
    *,
    cancellation_check: Callable[[], None] | None = None,
) -> tuple[dict[str, int], str]:
    counts, digest = read_semantic_digest(
        connection,
        repository_id,
        run_id,
        cancellation_check=cancellation_check,
    )
    return {family: counts[family] for family in FINAL_FAMILY_CODES}, digest


__all__ = [
    "StageTerminalEvidence",
    "TerminalBackendReadTimeout",
    "TerminalStorageEvidence",
    "classify_terminal_evidence",
    "read_scale15_terminal_state",
    "read_terminal_backend_summary",
]
