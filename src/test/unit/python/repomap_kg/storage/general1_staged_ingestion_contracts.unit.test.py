"""Public staged-ingestion contracts observed through an injected database double."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import re
import signal
from typing import Any, TypedDict
from unittest.mock import patch

import psycopg
import pytest

from repomap_kg.observations.raw import RawObservation
from repomap_kg.runtime.maintenance import MaintenanceUnavailableError
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    new_direct_authority,
    run_staged_full_refresh,
    stage_id_for_authority,
)
from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS

_CONNECT = "repomap_kg.storage.staged_ingestion.psycopg.connect"
_ROOT = "/fixture/general1-root"
_TABLES = [descriptor.stage_table for descriptor in STAGING_FAMILY_DESCRIPTORS.values()]
_NODE_ANALYZE = "ANALYZE stage_canonical_node_evidence"
class _Generations(TypedDict):
    source_generation: str
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str


_GENERATIONS: _Generations = {
    "source_generation": "sg1:source", "config_generation": "cg1:config",
    "extractor_generation": "eg1:extractor", "canonicalizer_generation": "kg1:canonicalizer",
}
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
        self._row = (self._db.admission_ok,)

    def copy(self, _statement: object) -> _Cursor:
        self._db.copied.append([])
        return self

    def write_row(self, row: object) -> None:
        self._db.copied[-1].append(row)


class _Database:
    """Scripted PostgreSQL connection that records every durable interaction."""

    def __init__(self, *, repository_row: tuple[Any, ...] | None = (7,),
                 run_id_row: tuple[Any, ...] | None = (41,), admission_ok: bool = True) -> None:
        self.repository_row, self.run_id_row, self.admission_ok = repository_row, run_id_row, admission_ok
        self.failures: list[tuple[str, BaseException]] = []
        self.rowcounts: list[tuple[str, int]] = []
        self.hooks: list[tuple[str, Callable[[], None]]] = []
        self.skew: dict[str, int] = {}
        self.log: list[tuple[str, Any]] = []
        self.copied: list[list[Any]] = []
        self.cancels: list[Any] = []
        self.cancel_errors: dict[str, Exception] = {}
        self.rollback_error: Exception | None = None

    def count(self, marker: str) -> int:
        return sum(1 for text, _ in self.log if text == marker)

    def sql(self) -> list[str]:
        return [text for text, _ in self.log]

    def index(self, needle: str) -> int:
        return next(i for i, text in enumerate(self.sql()) if needle in text)

    def has(self, needle: str) -> bool:
        return any(needle in text for text in self.sql())

    def params(self, needle: str) -> Any:
        return self.log[self.index(needle)][1]

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        self.log.append(("COMMIT", None))

    def rollback(self) -> None:
        self.log.append(("ROLLBACK", None))
        if self.rollback_error is not None:
            raise self.rollback_error

    def close(self) -> None:
        self.log.append(("CLOSE", None))

    def cancel_safe(self, *, timeout: float) -> None:
        self.cancels.append(("safe", timeout))
        if "safe" in self.cancel_errors:
            raise self.cancel_errors["safe"]

    def cancel(self) -> None:
        self.cancels.append("cancel")
        if "cancel" in self.cancel_errors:
            raise self.cancel_errors["cancel"]

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        norm = " ".join(sql.split())
        self.log.append((norm, params))
        for needle, hook in self.hooks:
            if needle in norm:
                hook()
        for needle, error in self.failures:
            if needle in norm:
                raise error
        if norm.startswith("INSERT INTO repositories"):
            return _Cursor(self, self.repository_row)
        if norm.startswith("INSERT INTO runs"):
            return _Cursor(self, self.run_id_row)
        if "pg_try_advisory_xact_lock" in norm:
            return _Cursor(self, (True,))
        counted = re.fullmatch(r"SELECT count\(\*\) FROM (\w+) WHERE stage_id = %s", norm)
        if counted is not None:
            position = _TABLES.index(counted.group(1))
            rows = len(self.copied[position]) if position < len(self.copied) else 0
            return _Cursor(self, (rows + self.skew.get(counted.group(1), 0),))
        rowcount = next((count for needle, count in self.rowcounts if needle in norm), 1)
        return _Cursor(self, None, rowcount)


class _Factory:
    def __init__(self, *items: _Database | BaseException) -> None:
        self._items = list(items)
        self.calls: list[dict[str, object]] = []

    def __call__(self, **params: object) -> _Database:
        self.calls.append(params)
        item = self._items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _admission(target: _Database | BaseException | None = None) -> Any:
    target = _Database() if target is None else target
    if isinstance(target, BaseException):
        return patch(_CONNECT, side_effect=target)
    return patch(_CONNECT, return_value=target)


def _direct() -> IngestionAuthority:
    return new_direct_authority(**_GENERATIONS)


def _coordinator(**extra: Any) -> IngestionAuthority:
    return IngestionAuthority(
        operation_id=OperationId("job-general1"), attempt=AttemptNumber(2), execution_mode="coordinator",
        job_id=JobId("job-general1"), coordinator_instance_id="coord-general1",
        singleton_fencing_epoch=11, graph_lease_fencing_epoch=11, **_GENERATIONS, **extra,
    )


def _refresh(factory: _Factory, authority: IngestionAuthority | None = None, *,
             args: tuple[str, ...] = ("-d", "fixture"), **kwargs: Any) -> Any:
    return run_staged_full_refresh(
        args, (_FILE,), repository_name="fixture", root_path=_ROOT,
        authority=authority or _direct(), connect=factory, **kwargs,
    )


def _handlers() -> tuple[Any, Any]:
    return signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)


def test_direct_refresh_stages_validates_publishes_and_releases_everything() -> None:
    authority, db, admission = _direct(), _Database(), _Database()
    during: list[Any] = []
    db.hooks.append((_NODE_ANALYZE, lambda: during.append(_handlers())))
    original, factory = _handlers(), _Factory(db)
    before = datetime.now(timezone.utc)

    with _admission(admission):
        summary = _refresh(factory, authority)

    assert (summary.repository_id, summary.run_id, summary.files) == (7, 41, 1)
    assert summary.publication_receipt == authority.receipt()
    # Publication must follow durable stage validation; intermediate SQL order is not the contract.
    assert db.index("SET state = 'validated'") < db.index("pg_try_advisory_xact_lock")
    assert not db.has("arch1c_graph_claim")
    assert db.count("COMMIT") == 4 and db.count("ROLLBACK") == 0 and db.count("CLOSE") == 1
    assert len(db.copied) == len(STAGING_FAMILY_DESCRIPTORS)
    assert len(db.copied[_TABLES.index(STAGING_FAMILY_DESCRIPTORS["files"].stage_table)]) == 1
    assert not db.has("README.md") and not db.has(_ROOT)
    stage = db.params("INSERT INTO ingestion_stages")
    assert stage[0] == stage_id_for_authority(authority) and stage[5] == "direct" and stage[3] is None
    assert timedelta(hours=23) < stage[13] - before < timedelta(hours=25) and stage[13].tzinfo is not None
    assert during and during[0] != original and _handlers() == original
    assert admission.count("CLOSE") == 1


def test_coordinator_refresh_claims_before_staging_and_runs_publication_hook_last() -> None:
    db = _Database()
    calls: list[str] = []

    def hook() -> None:
        db.log.append(("HOOK", None))
        calls.append("hook")

    with _admission():
        summary = _refresh(_Factory(db), _coordinator(before_publication=hook),
                           stage_id="stage-general1-explicit", stage_ttl=timedelta(hours=1))

    assert (summary.run_id, calls) == (41, ["hook"])
    assert db.index("arch1c_graph_claim") < db.sql().index("COMMIT")
    assert db.index("SET state = 'validated'") < db.sql().index("HOOK") < db.index("pg_try_advisory_xact_lock")
    stage = db.params("INSERT INTO ingestion_stages")
    assert (stage[0], stage[3], stage[6], stage[7], stage[8]) == ("stage-general1-explicit", "job-general1", "coord-general1", 11, 11)
    assert timedelta(minutes=59) < stage[13] - datetime.now(timezone.utc) <= timedelta(hours=1)


def test_publication_hook_failure_rolls_back_marks_stage_failed_and_never_publishes() -> None:
    db = _Database()

    def refuse() -> None:
        raise RuntimeError("hook refused")

    with _admission(), pytest.raises(RuntimeError, match="hook refused"):
        _refresh(_Factory(db), _coordinator(before_publication=refuse))

    assert not db.has("pg_try_advisory_xact_lock") and db.has("UPDATE runs SET status = 'failed'")
    tail = db.sql()[db.index("SET state = 'validated'"):]
    assert tail.index("ROLLBACK") < next(i for i, text in enumerate(tail) if "SET state = 'failed'" in text)
    assert tail[-2:] == ["COMMIT", "CLOSE"]


def test_expiry_authority_and_telemetry_refusals_happen_before_any_connection() -> None:
    invalid = IngestionAuthority(
        operation_id=OperationId("job-general1"), attempt=AttemptNumber(1), execution_mode="coordinator", **_GENERATIONS
    )
    factory = _Factory()
    with _admission() as admit:
        for ttl in (timedelta(0), timedelta(seconds=-1)):
            with pytest.raises(ValueError, match="expiry must be positive"):
                _refresh(factory, stage_ttl=ttl)
        with pytest.raises(ValueError, match="invalid stage owner"):
            _refresh(factory, invalid)
        with pytest.raises(StorageSchemaError, match="requires direct mode"):
            _refresh(factory, _coordinator(), backend_telemetry=object())
    assert not admit.called and factory.calls == []


@pytest.mark.parametrize(("args", "message"), [
    (("--password", "hunter2"), "unsupported psql connection argument"),
    (("-d",), "requires a value"),
    (("-d", "-h"), "requires a value"),
])
def test_unsupported_psql_arguments_are_refused_without_echoing_values(args: tuple[str, ...], message: str) -> None:
    factory = _Factory()
    with _admission() as admit, pytest.raises(StorageSchemaError, match=message) as caught:
        _refresh(factory, args=args)
    assert "hunter2" not in str(caught.value) and not admit.called and factory.calls == []


def test_admission_driver_failure_is_sanitized_and_staged_connection_never_opens() -> None:
    error = psycopg.OperationalError("password=hunter2 refused")
    factory = _Factory()
    with _admission(error), pytest.raises(StorageSchemaError, match="^staged PostgreSQL connection failed$") as caught:
        _refresh(factory)
    assert caught.value.__cause__ is error and "hunter2" not in str(caught.value) and factory.calls == []


def test_active_schema_maintenance_blocks_staging_and_releases_admission() -> None:
    admission, factory = _Database(admission_ok=False), _Factory()
    with _admission(admission), pytest.raises(MaintenanceUnavailableError, match="schema maintenance is active"):
        _refresh(factory)
    assert admission.count("CLOSE") == 1 and factory.calls == []


def test_staged_connection_failures_are_sanitized_or_propagated_unchanged() -> None:
    error = psycopg.OperationalError("host=db.internal refused")
    admission = _Database()
    with _admission(admission), pytest.raises(StorageSchemaError, match="^staged PostgreSQL connection failed$") as caught:
        _refresh(_Factory(error))
    assert caught.value.__cause__ is error and "db.internal" not in str(caught.value)
    with _admission(admission), pytest.raises(KeyboardInterrupt):
        _refresh(_Factory(KeyboardInterrupt()))
    assert admission.count("CLOSE") == 2


def test_repository_identity_selects_identity_upsert_and_rejects_malformed_values() -> None:
    db = _Database()
    with _admission():
        _refresh(_Factory(db), repository_identity="repo1:general1")
    sql, params = db.log[db.index("INSERT INTO repositories")]
    assert "ON CONFLICT (repository_identity)" in sql and params == ("fixture", _ROOT, "repo1:general1")

    bad = _Database()
    with _admission(), pytest.raises(StorageSchemaError, match="stable repository identity is invalid"):
        _refresh(_Factory(bad), repository_identity="not-versioned")
    assert not bad.has("INSERT INTO runs") and bad.count("CLOSE") == 1 and bad.count("COMMIT") == 0


@pytest.mark.parametrize(("kwargs", "message"), [
    ({"repository_row": None}, "staged repository identity was not returned"),
    ({"run_id_row": None}, "staged run identity was not returned"),
])
def test_missing_database_identities_fail_before_any_stage_is_committed(kwargs: dict[str, Any], message: str) -> None:
    db = _Database(**kwargs)
    with _admission(), pytest.raises(StorageSchemaError, match=message):
        _refresh(_Factory(db))
    assert not db.has("INSERT INTO ingestion_stages") and not db.has("SET state = 'failed'")
    assert db.count("COMMIT") == 0 and db.count("ROLLBACK") == 1 and db.count("CLOSE") == 1


@pytest.mark.parametrize(("needle", "message"), [
    ("SET state = 'prepared'", "staged prepared transition failed"),
    ("SET state = 'validating'", "staged validating transition failed"),
    ("SET state = 'validated'", "staged validated transition failed"),
])
def test_rejected_transition_marks_committed_stage_failed_before_publication(needle: str, message: str) -> None:
    db = _Database()
    db.rowcounts.append((needle, 0))
    with _admission(), pytest.raises(StorageSchemaError, match=message):
        _refresh(_Factory(db))
    assert not db.has("pg_try_advisory_xact_lock") and db.has("UPDATE runs SET status = 'failed'")
    assert db.has("SET state = 'failed'") and db.sql()[-2:] == ["COMMIT", "CLOSE"]


def test_incomplete_copy_counts_fail_validation_without_publication() -> None:
    db = _Database()
    db.skew[_TABLES[0]] = 1
    with _admission(), pytest.raises(StorageSchemaError, match="staged family completeness failed"):
        _refresh(_Factory(db))
    assert db.has("SET state = 'failed'") and not db.has("pg_try_advisory_xact_lock")


def test_failure_marker_and_rollback_errors_never_mask_the_original_failure() -> None:
    unmarkable, unrollable = _Database(), _Database()
    unmarkable.rowcounts += [("SET state = 'prepared'", 0), ("SET state = 'failed'", 0)]
    unrollable.rowcounts.append(("SET state = 'prepared'", 0))
    unrollable.rollback_error = RuntimeError("rollback link down")
    for db in (unmarkable, unrollable):
        with _admission(), pytest.raises(StorageSchemaError, match="staged prepared transition failed"):
            _refresh(_Factory(db))
        assert db.count("ROLLBACK") == 2 and db.count("CLOSE") == 1 and db.count("COMMIT") == 1
    assert unmarkable.has("SET state = 'failed'") and not unrollable.has("SET state = 'failed'")


def test_driver_failure_before_stage_commit_is_sanitized_and_leaves_no_failed_marker() -> None:
    error = psycopg.errors.CheckViolation("fixture-only fence detail")
    db = _Database()
    db.failures.append(("INSERT INTO ingestion_stages", error))
    with _admission(), pytest.raises(StorageSchemaError, match="^staged PostgreSQL operation failed$") as caught:
        _refresh(_Factory(db))
    assert caught.value.__cause__ is error and "fence detail" not in str(caught.value)
    assert db.count("ROLLBACK") == 1 and db.count("COMMIT") == 0 and not db.has("SET state = 'failed'")


@pytest.mark.parametrize(("errors", "expected"), [
    ({}, [("safe", 1.0)]),
    ({"safe": RuntimeError("no safe cancel")}, [("safe", 1.0), "cancel"]),
    ({"safe": RuntimeError("no safe cancel"), "cancel": RuntimeError("no cancel")}, [("safe", 1.0), "cancel"]),
])
def test_termination_signal_cancels_server_work_then_fails_stage_and_restores_handlers(
    errors: dict[str, Exception], expected: list[Any]
) -> None:
    db, original = _Database(), _handlers()
    db.cancel_errors = errors
    def terminate() -> None:
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)

    db.hooks.append((_NODE_ANALYZE, terminate))
    with _admission(), pytest.raises(KeyboardInterrupt):
        _refresh(_Factory(db))
    assert db.cancels == expected and _handlers() == original
    assert db.has("SET state = 'failed'") and not db.has("pg_try_advisory_xact_lock")
    assert db.sql()[-2:] == ["COMMIT", "CLOSE"]
