"""Public staged publication, replay, and reconciliation contracts over a database double."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
import signal
from typing import Any, TypedDict
from unittest.mock import patch

import psycopg
import pytest

from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.errors import StorageCommitUnknownError, StorageSchemaError
from repomap_kg.storage.publication import PortablePublicationBinding
from repomap_kg.storage.row_spool import RowSpool
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    new_direct_authority,
    run_staged_full_refresh,
    run_staged_portable_refresh,
    stage_id_for_authority,
)
from repomap_kg.storage.staged_rows import PreparedStageRows, build_staged_rows
from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS

from src.test.unit.python.repomap_kg.storage.scale8_staged_helpers_fixtures import _portable_binding

_CONNECT = "repomap_kg.storage.staged_ingestion.psycopg.connect"
_ROOT = "/fixture/general1-root"
_TABLES = [descriptor.stage_table for descriptor in STAGING_FAMILY_DESCRIPTORS.values()]
class _Generations(TypedDict):
    source_generation: str
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str


_GENERATIONS: _Generations = {
    "source_generation": "sg1:source", "config_generation": "cg1:config",
    "extractor_generation": "eg1:extractor", "canonicalizer_generation": "kg1:canonicalizer",
}
_MARKER = ("complete", 41, *_GENERATIONS.values(), *((None,) * len(PortablePublicationBinding.field_names())))
_FILE = RawObservation(
    kind="file", source_id="README.md", path="README.md", confidence="extracted",
    extractor="repo-discovery", extractor_version="0.1.0",
    metadata={"language": "markdown", "role": "documentation"},
)


class _Cursor:
    def __init__(self, db: _Database, row: tuple[Any, ...] | None = None, rowcount: int = 1) -> None:
        self._db, self._row, self.rowcount = db, row, rowcount

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, _sql: str, _params: Any = None) -> None:
        self._row = (True,)

    def copy(self, _statement: object) -> _Cursor:
        self._db.copied.append([])
        return self

    def write_row(self, row: object) -> None:
        self._db.copied[-1].append(row)


class _Database:
    """Scripted PostgreSQL connection that records every durable interaction."""

    def __init__(self, *, stage_row: tuple[Any, ...] | None = None, run_row: tuple[Any, ...] | None = None,
                 marker_row: tuple[Any, ...] | None = None, lock_ok: bool = True) -> None:
        self.stage_row, self.run_row, self.marker_row, self.lock_ok = stage_row, run_row, marker_row, lock_ok
        self.failures: list[tuple[str, BaseException]] = []
        self.log: list[tuple[str, Any]] = []
        self.copied: list[list[Any]] = []
        self.commit_error: BaseException | None = None
        self.commit_error_at = 0

    def count(self, marker: str) -> int:
        return sum(1 for text, _ in self.log if text == marker)

    def sql(self) -> list[str]:
        return [text for text, _ in self.log]

    def index(self, needle: str) -> int:
        return next(i for i, text in enumerate(self.sql()) if needle in text)

    def has(self, needle: str) -> bool:
        return any(needle in text for text in self.sql())

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        self.log.append(("COMMIT", None))
        if self.commit_error is not None and self.count("COMMIT") == self.commit_error_at:
            raise self.commit_error

    def rollback(self) -> None:
        self.log.append(("ROLLBACK", None))

    def close(self) -> None:
        self.log.append(("CLOSE", None))

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        norm = " ".join(sql.split())
        self.log.append((norm, params))
        for needle, error in self.failures:
            if needle in norm:
                raise error
        if norm.startswith("INSERT INTO repositories"):
            return _Cursor(self, (7,))
        if norm.startswith("INSERT INTO runs"):
            return _Cursor(self, (41,))
        if norm.startswith("SELECT repository_id, operation_id"):
            return _Cursor(self, self.stage_row)
        if norm.startswith("SELECT id, status FROM runs"):
            return _Cursor(self, self.run_row)
        if norm.startswith("SELECT status, id, source_generation"):
            return _Cursor(self, self.marker_row)
        if "pg_try_advisory_xact_lock" in norm:
            return _Cursor(self, (self.lock_ok,))
        counted = re.fullmatch(r"SELECT count\(\*\) FROM (\w+) WHERE stage_id = %s", norm)
        if counted is not None:
            position = _TABLES.index(counted.group(1))
            return _Cursor(self, (len(self.copied[position]) if position < len(self.copied) else 0,))
        return _Cursor(self)


class _Factory:
    def __init__(self, *items: _Database) -> None:
        self._items = list(items)
        self.calls: list[dict[str, object]] = []

    def __call__(self, **params: object) -> _Database:
        self.calls.append(params)
        return self._items.pop(0)


def _admission() -> Any:
    return patch(_CONNECT, return_value=_Database())


def _direct() -> IngestionAuthority:
    return new_direct_authority(**_GENERATIONS)


def _coordinator() -> IngestionAuthority:
    return IngestionAuthority(
        operation_id=OperationId("job-general1"), attempt=AttemptNumber(2), execution_mode="coordinator",
        job_id=JobId("job-general1"), coordinator_instance_id="coord-general1",
        singleton_fencing_epoch=11, graph_lease_fencing_epoch=11, **_GENERATIONS,
    )


def _stage_row(authority: IngestionAuthority, state: str, *, config: str | None = None) -> tuple[Any, ...]:
    o = authority.owner(7)
    return (7, o.operation_id, o.job_id, o.attempt, o.execution_mode, o.coordinator_instance_id,
            o.singleton_fencing_epoch, o.graph_lease_fencing_epoch, o.source_generation,
            config or o.config_generation, o.extractor_generation, o.canonicalizer_generation, state)


def _refresh(factory: _Factory, authority: IngestionAuthority | None = None) -> Any:
    return run_staged_full_refresh(
        ("-d", "fixture"), (_FILE,), repository_name="fixture", root_path=_ROOT,
        authority=authority or _direct(), connect=factory,
    )


def _binding(authority: IngestionAuthority, **changes: Any) -> PortablePublicationBinding:
    fields = {"stage_id": stage_id_for_authority(authority), "singleton_fencing_epoch": 11,
              "graph_lease_fencing_epoch": 11, **changes}
    return replace(_portable_binding(), **fields)


def _spooled(authority: IngestionAuthority, directory: Path) -> tuple[PreparedStageRows, list[RowSpool]]:
    base = build_staged_rows((_FILE,), repository_name="fixture", stage_id=stage_id_for_authority(authority))
    spools = {family: RowSpool.from_rows(rows, dir=directory) for family, rows in base.family_rows.items()}
    return replace(base, family_rows=spools), list(spools.values())


def _portable(factory: _Factory, authority: IngestionAuthority, prepared: PreparedStageRows, **kwargs: Any) -> Any:
    return run_staged_portable_refresh(
        ("-d", "fixture"), prepared_override=prepared, repository_name="fixture", root_path=_ROOT,
        authority=authority, portable_binding=_binding(authority), connect=factory, **kwargs,
    )


def test_unknown_final_commit_is_reconciled_to_the_committed_receipt() -> None:
    authority, db, reconcile = _direct(), _Database(), _Database(marker_row=_MARKER)
    db.commit_error, db.commit_error_at = RuntimeError("socket reset host=db.internal"), 4
    original, factory = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)), _Factory(db, reconcile)

    with _admission():
        summary = _refresh(factory, authority)

    assert (summary.repository_id, summary.run_id, summary.files) == (7, 41, 1)
    assert summary.publication_receipt == authority.receipt()
    assert factory.calls == [{"dbname": "fixture"}] * 2
    assert db.count("CLOSE") == 1 and db.count("ROLLBACK") == 0 and not db.has("SET state = 'failed'")
    assert (reconcile.count("COMMIT"), reconcile.count("CLOSE")) == (1, 1)
    assert not reconcile.has("SET state = 'commit_unknown'")
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == original


@pytest.mark.parametrize("error", [RuntimeError("socket reset host=db.internal"), KeyboardInterrupt()])
def test_unproven_final_commit_is_recorded_as_commit_unknown_without_leaking_driver_detail(error: BaseException) -> None:
    db, reconcile = _Database(), _Database()
    db.commit_error, db.commit_error_at = error, 4
    with _admission(), pytest.raises(StorageCommitUnknownError, match="^staged publication commit is unknown$") as caught:
        _refresh(_Factory(db, reconcile))
    assert caught.value.__cause__ is error and "db.internal" not in str(caught.value)
    assert reconcile.has("state = 'commit_unknown'") and reconcile.count("COMMIT") == 1
    assert reconcile.count("CLOSE") == 1 and not db.has("SET state = 'failed'")


def test_refused_final_lock_marks_stage_failed_without_entering_commit_unknown() -> None:
    db = _Database(lock_ok=False)
    with _admission(), pytest.raises(StorageSchemaError, match="graph publication already active"):
        _refresh(_Factory(db))
    tail = db.sql()[db.index("pg_try_advisory_xact_lock"):]
    assert tail[1] == "ROLLBACK" and tail[-2:] == ["COMMIT", "CLOSE"] and db.count("COMMIT") == 4
    assert db.has("SET state = 'failed'") and db.has("UPDATE runs SET status = 'failed'") and not db.has("commit_unknown")


def test_final_transaction_driver_failure_is_sanitized_and_stage_is_failed() -> None:
    error = psycopg.errors.SerializationFailure("row detail secret")
    db = _Database()
    db.failures.append(("pg_try_advisory_xact_lock", error))
    with _admission(), pytest.raises(StorageSchemaError, match="^staged PostgreSQL operation failed$") as caught:
        _refresh(_Factory(db))
    assert caught.value.__cause__ is error and "secret" not in str(caught.value)
    assert db.has("SET state = 'failed'") and db.sql()[-2:] == ["COMMIT", "CLOSE"]


@pytest.mark.parametrize(("state", "message"), [
    *[(state, "^staged operation is already active$") for state in ("loading", "prepared", "validating", "validated", "merging")],
    *[(state, "^staged operation cannot be replayed$") for state in ("failed", "cancelled", "quarantined")],
])
def test_existing_unpublished_stage_refuses_a_second_writer_without_new_run(state: str, message: str) -> None:
    authority = _direct()
    db = _Database(stage_row=_stage_row(authority, state))
    with _admission(), pytest.raises(StorageSchemaError, match=message):
        _refresh(_Factory(db), authority)
    assert not db.has("INSERT INTO runs") and not db.has("INSERT INTO ingestion_stages") and db.count("COMMIT") == 0
    assert db.count("ROLLBACK") == 1 and db.count("CLOSE") == 1


def test_stage_owned_by_a_different_generation_is_refused() -> None:
    authority = _direct()
    db = _Database(stage_row=_stage_row(authority, "published", config="cg1:other"))
    with _admission(), pytest.raises(StorageSchemaError, match="staged stage ownership mismatch"):
        _refresh(_Factory(db), authority)
    assert not db.has("INSERT INTO runs") and db.count("CLOSE") == 1


def test_published_stage_replays_the_complete_run_without_writing() -> None:
    authority = _direct()
    db = _Database(stage_row=_stage_row(authority, "published"), run_row=(41, "complete"))
    with _admission():
        summary = _refresh(_Factory(db), authority)
    assert (summary.repository_id, summary.run_id, summary.files) == (7, 41, 1)
    assert summary.publication_receipt == authority.receipt() and db.has("AND status = 'complete'")
    assert db.count("ROLLBACK") == 1 and db.count("COMMIT") == 0 and not db.has("INSERT INTO runs")

    missing = _Database(stage_row=_stage_row(authority, "published"))
    with _admission(), pytest.raises(StorageSchemaError, match="staged published receipt is missing"):
        _refresh(_Factory(missing), authority)


def test_commit_unknown_stage_replay_reconciles_once_and_never_republishes() -> None:
    authority = _coordinator()
    db = _Database(stage_row=_stage_row(authority, "commit_unknown"), run_row=(41, "running"))
    reconcile = _Database(marker_row=_MARKER)
    original = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    with _admission():
        summary = _refresh(_Factory(db, reconcile), authority)
    assert (summary.run_id, summary.publication_receipt) == (41, authority.receipt())
    assert not db.has("AND status = 'complete'") and db.count("ROLLBACK") == 1 and not db.has("INSERT INTO runs")
    assert reconcile.count("COMMIT") == 1 and reconcile.count("CLOSE") == 1
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == original

    unproven = _Database(stage_row=_stage_row(authority, "commit_unknown"), run_row=(41, "running"))
    with _admission(), pytest.raises(StorageCommitUnknownError, match="staged publication commit is unknown"):
        _refresh(_Factory(unproven, _Database()), authority)
    absent = _Database(stage_row=_stage_row(authority, "commit_unknown"))
    with _admission(), pytest.raises(StorageSchemaError, match="staged commit-unknown run is missing"):
        _refresh(_Factory(absent), authority)


@pytest.mark.parametrize("changes", [
    {"stage_id": "stage-other"}, {"execution_mode": "direct"},
    {"singleton_fencing_epoch": 12}, {"graph_lease_fencing_epoch": 12},
])
def test_portable_binding_must_match_stage_and_fencing_authority_before_any_connection(changes: dict[str, Any]) -> None:
    authority, factory = _coordinator(), _Factory()
    with _admission() as admit, pytest.raises(StorageSchemaError, match="portable publication authority mismatch"):
        run_staged_portable_refresh(
            ("-d", "fixture"), None, repository_name="fixture", root_path=_ROOT, authority=authority,
            portable_binding=_binding(authority, **changes), connect=factory,
        )
    assert not admit.called and factory.calls == []


@pytest.mark.parametrize("bundle", [None, "not-a-bundle"])
def test_portable_refresh_requires_a_bundle_or_prepared_rows(bundle: Any) -> None:
    authority, factory = _coordinator(), _Factory()
    with _admission() as admit, pytest.raises(ValueError, match="either bundle or prepared_override is required"):
        run_staged_portable_refresh(
            ("-d", "fixture"), bundle, repository_name="fixture", root_path=_ROOT, authority=authority,
            portable_binding=_binding(authority), connect=factory,
        )
    assert not admit.called and factory.calls == []


def test_portable_refresh_publishes_prepared_rows_and_removes_every_spool(tmp_path: Path) -> None:
    authority, db = _coordinator(), _Database()
    prepared, spools = _spooled(authority, tmp_path)
    assert all(spool.path.exists() for spool in spools)

    with _admission():
        summary = _portable(_Factory(db), authority, prepared)

    binding = _binding(authority)
    assert (summary.repository_id, summary.run_id, summary.files) == (7, 41, 1)
    assert summary.publication_receipt.portable == binding
    assert summary.publication_receipt.attempt.job_id == "job-general1"
    assert db.index("arch1c_graph_claim") < db.sql().index("COMMIT")
    assert db.count("COMMIT") == 4 and db.has("pg_try_advisory_xact_lock")
    assert len(db.copied) == len(STAGING_FAMILY_DESCRIPTORS)
    assert len(db.copied[_TABLES.index(STAGING_FAMILY_DESCRIPTORS["files"].stage_table)]) == 1
    assert not any(spool.path.exists() for spool in spools) and list(tmp_path.iterdir()) == []


def test_portable_refresh_failure_still_removes_caller_spools(tmp_path: Path) -> None:
    authority, db = _coordinator(), _Database()
    db.failures.append(("INSERT INTO ingestion_stages", psycopg.errors.CheckViolation("fixture-only detail")))
    prepared, spools = _spooled(authority, tmp_path)

    with _admission(), pytest.raises(StorageSchemaError, match="^staged PostgreSQL operation failed$"):
        _portable(_Factory(db), authority, prepared)

    assert not db.has("SET state = 'failed'") and db.count("COMMIT") == 0
    assert not any(spool.path.exists() for spool in spools) and list(tmp_path.iterdir()) == []
