"""Parent-owned SQLite Local publication of one validated seven-family bundle.

The publisher consumes the same validated logical families the PostgreSQL
staged publisher consumes and applies the same logical merge rules
(``storage.staging_merge`` and ``storage.canonical_staging_merge``):

* files: upserted by path, the last ``family_ordinal`` proposal wins, and
  ``last_seen_run_id`` advances;
* raw observations and canonical evidence: stored per run;
* canonical nodes and edges: upserted by identity, the first proposal wins,
  ``first_seen_run_id`` is kept and ``last_seen_run_id`` advances;
* evidence links: set-deduplicated, existing links kept;
* identity conflicts and missing raw/node/edge/evidence references refuse.

Rows are staged in connection-local TEMP tables and checked before the write
transaction starts. The graph contents, the run record, the graph binding's
repository name and the accepted-publication marker then change in one
``BEGIN IMMEDIATE`` transaction, fenced on the generation the caller read at
attempt start. Readers therefore see either the previous accepted generation
or the next one, never a mix. The publisher never calls the PostgreSQL
publisher and never reads PostgreSQL.

Commit outcome (LOCAL3). Every exception leaving :func:`publish_generation`
carries one tag. ``is_not_committed``: COMMIT was never attempted; only this
lets a caller settle its attempt failed. ``is_commit_unknown``: COMMIT was
attempted and no clean readback proved this publication; process-control
exceptions (non-``Exception`` types) always propagate so tagged, and a readback
error never reads as "not committed". An ordinary post-COMMIT exception returns
success only when readback shows the expected next generation with this
attempt's bundle id, job id and attempt. Nothing is rolled back or rewritten
once COMMIT was attempted (a failed COMMIT's open transaction holds only
uncommitted work). Raw ``sqlite3`` errors become bounded codes; a failing
cleanup ROLLBACK never replaces the original error.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

from repomap_kg.storage.publication import RunPublicationReceipt
from repomap_kg.storage.sqlite_local.connection import classify_write_error, open_writer
from repomap_kg.storage.sqlite_local.merge_sql import family_statements
from repomap_kg.storage.sqlite_local.schema import (
    GENERATION_ADVANCED,
    PUBLICATION_REJECTED,
    LocalGraphBinding,
    LocalStoreError,
    accepted_identity,
)
from repomap_kg.storage.staging_family_contracts import (
    STAGING_FAMILY_DESCRIPTORS,
    DuplicatePolicy,
)
from repomap_kg.storage.staging_family_rows import StageFamily

PUBLISHER = "sqlite-local-direct-v1"
FAMILY_ORDER: tuple[StageFamily, ...] = (
    "files",
    "raw_observations",
    "canonical_nodes",
    "canonical_evidence",
    "canonical_edges",
    "canonical_node_evidence",
    "canonical_edge_evidence",
)
_MAX_RAW_ORDINAL = 2_147_483_647
NOT_COMMITTED = "is_not_committed"
COMMIT_UNKNOWN = "is_commit_unknown"


def _fault_point(name: str) -> None:
    """No-op seam; tests replace it to fail or pause at a named point."""
    return None


@dataclass(frozen=True)
class LocalPublication:
    """Everything the publisher commits besides the family rows."""

    binding: LocalGraphBinding
    repository_name: str
    receipt: RunPublicationReceipt
    privacy: str


@dataclass(frozen=True)
class LocalPublicationResult:
    generation: int
    run_id: int
    previous_run_id: int | None
    family_counts: Mapping[str, int]


def utc_timestamp(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def accepted_generation(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT generation FROM accepted_publication").fetchone()
    return 0 if row is None else int(row[0])


def read_accepted_generation(path: Path, binding: LocalGraphBinding) -> int:
    """Writer-side read of the accepted generation at attempt start."""
    connection = open_writer(path, binding)
    try:
        return accepted_generation(connection)
    except sqlite3.Error as error:
        raise classify_write_error(error) from None
    finally:
        connection.close()


def publication_not_committed(error: BaseException) -> bool:
    """True only when ``publish_generation`` proved COMMIT was never attempted."""
    return getattr(error, NOT_COMMITTED, False) is True


def publish_generation(
    path: Path,
    publication: LocalPublication,
    families: Mapping[StageFamily, Iterable[Mapping[str, object]]],
    *,
    expected_generation: int,
    clock: Callable[[], str] = utc_timestamp,
) -> LocalPublicationResult:
    """Publish one validated bundle as the next accepted generation."""
    connection: sqlite3.Connection | None = None
    commit_attempted = False
    counts: dict[str, int] = {}
    try:
        receipt = publication.receipt.validate()
        if receipt.portable is None or set(families) != set(FAMILY_ORDER):
            raise LocalStoreError(PUBLICATION_REJECTED, "incomplete publication input")
        connection = open_writer(path, publication.binding)
        counts = _stage(connection, families)
        _stage_guards(connection)
        started_at = clock()
        connection.execute("BEGIN IMMEDIATE")
        generation = accepted_generation(connection)
        if generation != expected_generation:
            raise LocalStoreError(GENERATION_ADVANCED)
        merged = _merge(connection, publication, generation, started_at, clock)
        _fault_point("before_commit")
        commit_attempted = True
        connection.execute("COMMIT")
        _fault_point("after_commit")
        result = LocalPublicationResult(
            merged.generation, merged.run_id, merged.previous_run_id, dict(counts)
        )
    except BaseException as error:
        if connection is not None:
            _discard_open_transaction(connection)
        if not commit_attempted or connection is None or not isinstance(error, Exception):
            _raise_tagged(error, commit_attempted=commit_attempted)
        result = _confirmed(connection, publication.receipt, expected_generation, counts, error)
    finally:
        if connection is not None:
            # Cleanup only: the outcome is already decided above.
            with suppress(sqlite3.Error):
                connection.close()
    return result


def _discard_open_transaction(connection: sqlite3.Connection) -> None:
    """Best-effort ROLLBACK of uncommitted work; never masks the original error."""
    if connection.in_transaction:
        with suppress(sqlite3.Error):
            connection.execute("ROLLBACK")


def _raise_tagged(error: BaseException, *, commit_attempted: bool) -> NoReturn:
    """Raise ``error`` (bounded if it is a raw ``sqlite3`` error) with its outcome tag."""
    tagged: BaseException = error
    if isinstance(error, sqlite3.Error):
        tagged = classify_write_error(error)
        if commit_attempted:
            tagged = LocalStoreError(tagged.code, "publication outcome unknown")
    setattr(tagged, COMMIT_UNKNOWN if commit_attempted else NOT_COMMITTED, True)
    if tagged is error:
        raise error
    raise tagged from None


def _confirmed(
    connection: sqlite3.Connection,
    receipt: RunPublicationReceipt,
    expected: int,
    counts: Mapping[str, int],
    error: Exception,
) -> LocalPublicationResult:
    """Success after an ordinary post-COMMIT error needs positive durable readback."""
    try:
        identity = accepted_identity(connection)
    except Exception:
        identity = None  # a failed readback proves nothing either way
    except BaseException as interrupt:
        _raise_tagged(interrupt, commit_attempted=True)
    portable, attempt = receipt.portable, receipt.attempt
    if identity is not None and portable is not None and identity.generation == expected + 1 and (
        identity.publication_bundle_id, identity.publication_job_id, identity.publication_attempt
    ) == (portable.publication_bundle_id, attempt.job_id, attempt.attempt):
        return LocalPublicationResult(
            identity.generation, identity.run_id, identity.previous_run_id, dict(counts)
        )
    _raise_tagged(error, commit_attempted=True)


def _columns(family: StageFamily) -> tuple[str, ...]:
    return tuple(
        column
        for column in STAGING_FAMILY_DESCRIPTORS[family].copy_columns
        if column != "stage_id"
    )


def _stage_table(family: StageFamily) -> str:
    return f"temp.stage_{family}"


def _encode(value: object) -> object:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return value


def _stage(
    connection: sqlite3.Connection,
    families: Mapping[StageFamily, Iterable[Mapping[str, object]]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    connection.execute("BEGIN")
    try:
        for family in FAMILY_ORDER:
            columns = _columns(family)
            table = _stage_table(family)
            connection.execute(f"DROP TABLE IF EXISTS {table}")
            connection.execute(f"CREATE TEMP TABLE stage_{family} ({', '.join(columns)})")
            placeholders = ", ".join("?" for _ in columns)
            count = 0
            batch: list[tuple[object, ...]] = []
            for row in families[family]:
                try:
                    batch.append(tuple(_encode(row[column]) for column in columns))
                except KeyError as error:
                    raise LocalStoreError(
                        PUBLICATION_REJECTED, f"{family} row is malformed"
                    ) from error
                if len(batch) >= 1000:
                    connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", batch)
                    count += len(batch)
                    batch.clear()
            if batch:
                connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", batch)
                count += len(batch)
            counts[family] = count
        connection.execute("COMMIT")
    except BaseException:
        _discard_open_transaction(connection)
        raise
    return counts


def _exists(connection: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> bool:
    return connection.execute(f"SELECT EXISTS ({sql})", params).fetchone()[0] == 1


def _stage_guards(connection: sqlite3.Connection) -> None:
    """Stage-local validation shared with the PostgreSQL duplicate guards."""
    for family in FAMILY_ORDER:
        descriptor = STAGING_FAMILY_DESCRIPTORS[family]
        identity = ", ".join(descriptor.identity_columns)
        payload = ", ".join(
            column
            for column in descriptor.payload_columns
            if column != descriptor.technical_ordinal
        )
        if descriptor.duplicate_policy in (
            DuplicatePolicy.IDENTICAL_ONLY,
            DuplicatePolicy.SOURCE_ORDINAL_IDEMPOTENT,
        ) and _exists(
            connection,
            f"SELECT 1 FROM (SELECT DISTINCT {identity}, {payload} FROM "
            f"{_stage_table(family)}) GROUP BY {identity} HAVING count(*) > 1",
        ):
            raise LocalStoreError(PUBLICATION_REJECTED, f"{family} stage validation conflict")
    if _exists(
        connection,
        "SELECT 1 FROM temp.stage_raw_observations WHERE source_ordinal > ?",
        (_MAX_RAW_ORDINAL,),
    ):
        raise LocalStoreError(PUBLICATION_REJECTED, "raw ordinal exceeds final schema")


def _merge(
    connection: sqlite3.Connection,
    publication: LocalPublication,
    previous_generation: int,
    started_at: str,
    clock: Callable[[], str],
) -> LocalPublicationResult:
    run = previous_generation + 1
    previous = previous_generation or None
    _insert_run(connection, publication, run, previous, started_at, clock())
    _fault_point("after_run_insert")
    for family in FAMILY_ORDER:
        for statement, guard in family_statements(family):
            if guard is not None:
                if _exists(connection, statement, (run,) * statement.count("?")):
                    raise LocalStoreError(PUBLICATION_REJECTED, guard)
            else:
                connection.execute(statement, {"run": run})
        _fault_point(f"after_family:{family}")
    connection.execute(
        "UPDATE graph_binding SET repository_name = ? WHERE singleton = 1",
        (publication.repository_name,),
    )
    connection.execute(
        "INSERT INTO accepted_publication(singleton, generation, run_id) VALUES (1, ?, ?) "
        "ON CONFLICT(singleton) DO UPDATE SET generation = excluded.generation, "
        "run_id = excluded.run_id",
        (run, run),
    )
    return LocalPublicationResult(run, run, previous, {})


def _insert_run(
    connection: sqlite3.Connection,
    publication: LocalPublication,
    run: int,
    previous: int | None,
    started_at: str,
    finished_at: str,
) -> None:
    receipt = publication.receipt
    portable = receipt.portable
    assert portable is not None
    mapping = portable.to_mapping()
    generations = receipt.generations
    connection.execute(
        "INSERT INTO runs(id, previous_run_id, status, started_at, finished_at, publisher, "
        "execution_route, portable_protocol_version, snapshot_manifest_id, "
        "snapshot_vector_json, extraction_receipt_id, publication_bundle_id, "
        "graph_candidate_id, resolver_identity, portable_canonicalizer_identity, "
        "semantic_contract_identity, quality_rule_identity, worker_capability_identity, "
        "portable_stage_id, portable_execution_mode, source_generation, config_generation, "
        "extractor_generation, canonicalizer_generation, publication_job_id, "
        "publication_attempt, family_receipts_json, privacy) VALUES "
        "(?, ?, 'complete', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?)",
        (
            run, previous, started_at, finished_at, PUBLISHER,
            mapping["execution_route"], mapping["portable_protocol_version"],
            mapping["snapshot_manifest_id"], mapping["snapshot_vector_json"],
            mapping["extraction_receipt_id"], mapping["publication_bundle_id"],
            mapping["graph_candidate_id"], mapping["resolver_identity"],
            mapping["portable_canonicalizer_identity"], mapping["semantic_contract_identity"],
            mapping["quality_rule_identity"], mapping["worker_capability_identity"],
            mapping["portable_stage_id"], mapping["portable_execution_mode"],
            generations.source_generation, generations.config_generation,
            generations.extractor_generation, generations.canonicalizer_generation,
            receipt.attempt.job_id, receipt.attempt.attempt,
            mapping["family_receipts_json"], publication.privacy,
        ),
    )


__all__ = (
    "COMMIT_UNKNOWN",
    "FAMILY_ORDER",
    "LocalPublication",
    "LocalPublicationResult",
    "NOT_COMMITTED",
    "PUBLISHER",
    "accepted_generation",
    "publication_not_committed",
    "publish_generation",
    "read_accepted_generation",
    "utc_timestamp",
)
