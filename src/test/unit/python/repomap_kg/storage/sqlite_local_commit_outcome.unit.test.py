"""SQLite Local commit outcome, rollback preservation and bounded write errors.

REPOMAP-PRODUCT3-SQLITE-LOCAL3 (R1, R3, R4). Hermetic temporary SQLite files
only. Once COMMIT was attempted, only a clean positive readback of this exact
publication is success; everything else is tagged commit-unknown and never
"not committed". A failing cleanup ROLLBACK never replaces the original error,
and raw ``sqlite3`` errors leave the publisher as bounded codes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.artifacts.bundle import PublicationBundle
from repomap_kg.storage.sqlite_local import connection as connection_module
from repomap_kg.storage.sqlite_local import publisher
from repomap_kg.storage.sqlite_local.connection import (
    classify_write_error,
    initialize_graph_database,
    read_transaction,
)
from repomap_kg.storage.sqlite_local.publisher import (
    accepted_generation,
    publication_not_committed,
    publish_generation,
    read_accepted_generation,
)
from repomap_kg.storage.sqlite_local.schema import AcceptedIdentity, LocalStoreError
from repomap_test_support.sqlite_local_fixtures import (
    generation_bundle,
    local_binding,
    publication_for,
)

BINDING = local_binding()
SECRET_TEXT = "INSERT INTO runs VALUES (1) /private/secret/graph.sqlite3"


def _init(tmp_path: Path) -> Path:
    path = tmp_path / "graphs" / "portable-fixture.sqlite3"
    path.parent.mkdir(mode=0o700)
    assert initialize_graph_database(path, BINDING, applied_at="2026-09-29T00:00:00Z") == "initialized"
    return path


def _publish(path: Path, bundle: PublicationBundle, expected: int) -> publisher.LocalPublicationResult:
    return publish_generation(path, publication_for(bundle), bundle.families, expected_generation=expected)


def _dump(path: Path) -> str:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return "\n".join(connection.iterdump())
    finally:
        connection.close()


def _generation(path: Path) -> int:
    with read_transaction(path, BINDING) as connection:
        return accepted_generation(connection)


def _raise_at(point: str, error: BaseException) -> Any:
    def fault(name: str) -> None:
        if name == point:
            raise error

    return fault


def _unknown(error: BaseException) -> bool:
    return getattr(error, "is_commit_unknown", False) is True and not publication_not_committed(error)


def _published_once(tmp_path: Path) -> Path:
    path = _init(tmp_path)
    _publish(path, generation_bundle(1), 0)
    return path


# R1: commit outcome ------------------------------------------------------


def test_readback_error_after_commit_is_commit_unknown_not_a_false_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _published_once(tmp_path)
    original = RuntimeError("after commit")
    monkeypatch.setattr(publisher, "_fault_point", _raise_at("after_commit", original))

    def unreadable(_connection: object) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(publisher, "accepted_identity", unreadable)
    with pytest.raises(RuntimeError) as caught:
        _publish(path, generation_bundle(2), 1)
    assert caught.value is original and _unknown(caught.value), vars(caught.value)
    assert _generation(path) == 2, "the committed generation must stay accepted"


def test_interrupt_during_readback_propagates_tagged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _published_once(tmp_path)
    monkeypatch.setattr(publisher, "_fault_point", _raise_at("after_commit", RuntimeError("x")))

    def interrupted(_connection: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(publisher, "accepted_identity", interrupted)
    with pytest.raises(KeyboardInterrupt) as caught:
        _publish(path, generation_bundle(2), 1)
    assert _unknown(caught.value), vars(caught.value)


@pytest.mark.parametrize(
    "identity",
    (
        None,
        AcceptedIdentity(2, 2, 1, "other-bundle", "job-sqlite-2", 1),
        AcceptedIdentity(3, 3, 2, generation_bundle(2).bundle_id, "job-sqlite-2", 1),
    ),
    ids=("absent", "other-bundle", "other-generation"),
)
def test_non_positive_readback_is_commit_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, identity: AcceptedIdentity | None
) -> None:
    path = _published_once(tmp_path)
    monkeypatch.setattr(publisher, "_fault_point", _raise_at("after_commit", ValueError("late")))
    monkeypatch.setattr(publisher, "accepted_identity", lambda _connection: identity)
    with pytest.raises(ValueError) as caught:
        _publish(path, generation_bundle(2), 1)
    assert _unknown(caught.value), vars(caught.value)


def test_sqlite_error_after_commit_with_positive_readback_is_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _published_once(tmp_path)
    monkeypatch.setattr(publisher, "_fault_point", _raise_at("after_commit", sqlite3.OperationalError(SECRET_TEXT)))
    result = _publish(path, generation_bundle(2), 1)
    assert (result.generation, result.run_id, result.previous_run_id) == (2, 2, 1), result
    assert result.family_counts == generation_bundle(2).family_counts


def test_sqlite_error_after_commit_without_proof_is_bounded_and_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _published_once(tmp_path)
    monkeypatch.setattr(publisher, "_fault_point", _raise_at("after_commit", sqlite3.OperationalError(SECRET_TEXT)))
    monkeypatch.setattr(publisher, "accepted_identity", lambda _connection: None)
    with pytest.raises(LocalStoreError) as caught:
        _publish(path, generation_bundle(2), 1)
    assert str(caught.value) == "graph-database-unavailable: publication outcome unknown", str(caught.value)
    assert _unknown(caught.value) and caught.value.__cause__ is None and caught.value.__suppress_context__


@pytest.mark.parametrize("error", (KeyboardInterrupt(), RuntimeError("before")), ids=("interrupt", "exception"))
def test_failure_before_commit_is_tagged_not_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    path = _published_once(tmp_path)
    before = _dump(path)
    monkeypatch.setattr(publisher, "_fault_point", _raise_at("before_commit", error))
    with pytest.raises(type(error)) as caught:
        _publish(path, generation_bundle(2), 1)
    assert publication_not_committed(caught.value) and not getattr(caught.value, "is_commit_unknown", False)
    assert _dump(path) == before


class _Proxy:
    """Delegating connection whose ROLLBACK (or close) fails on demand."""

    def __init__(self, inner: sqlite3.Connection, *, rollback: bool = True, close: bool = False) -> None:
        self._inner, self._rollback, self._close = inner, rollback, close

    def execute(self, sql: str, *args: Any) -> Any:
        if self._rollback and sql == "ROLLBACK":
            raise sqlite3.OperationalError("cannot rollback: injected cleanup failure")
        return self._inner.execute(sql, *args)

    def close(self) -> None:
        self._inner.close()
        if self._close:
            raise sqlite3.ProgrammingError("injected close failure")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _proxied(monkeypatch: pytest.MonkeyPatch, **options: bool) -> None:
    real = publisher.open_writer
    monkeypatch.setattr(publisher, "open_writer", lambda path, binding: _Proxy(real(path, binding), **options))


def test_close_error_after_a_clean_commit_keeps_the_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _published_once(tmp_path)
    _proxied(monkeypatch, rollback=False, close=True)
    assert _publish(path, generation_bundle(2), 1).generation == 2
    assert _generation(path) == 2


# R3: rollback failure never replaces the original error -----------------


def test_rollback_failure_preserves_the_publication_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _published_once(tmp_path)
    before = _dump(path)
    original = RuntimeError("publication failure")
    monkeypatch.setattr(publisher, "_fault_point", _raise_at("after_family:files", original))
    _proxied(monkeypatch)
    with pytest.raises(RuntimeError) as caught:
        _publish(path, generation_bundle(2), 1)
    assert caught.value is original and publication_not_committed(caught.value)
    assert _dump(path) == before


def test_rollback_failure_inside_staging_preserves_the_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _published_once(tmp_path)
    before = _dump(path)
    bundle = generation_bundle(2)
    families = {family: [dict(row) for row in rows] for family, rows in bundle.families.items()}
    del families["files"][0]["path"]
    _proxied(monkeypatch)
    with pytest.raises(LocalStoreError) as caught:
        publish_generation(path, publication_for(bundle), families, expected_generation=1)
    assert str(caught.value) == "graph-publication-rejected: files row is malformed", str(caught.value)
    assert _dump(path) == before


def test_rollback_failure_keeps_the_original_sqlite_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _published_once(tmp_path)
    before = _dump(path)
    monkeypatch.setattr(publisher, "_fault_point", _raise_at("after_family:files", sqlite3.IntegrityError(SECRET_TEXT)))
    _proxied(monkeypatch)
    with pytest.raises(LocalStoreError) as caught:
        _publish(path, generation_bundle(2), 1)
    assert caught.value.code == "graph-publication-rejected", str(caught.value)  # not the rollback's error
    assert SECRET_TEXT not in str(caught.value) and publication_not_committed(caught.value)
    assert _dump(path) == before


# R4: bounded publisher sqlite3 errors ------------------------------------


def test_real_write_contention_is_bounded_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _published_once(tmp_path)
    before = _dump(path)
    monkeypatch.setattr(connection_module, "WRITE_BUSY_TIMEOUT_SECONDS", 0.05)
    holder = sqlite3.connect(path, autocommit=True)
    try:
        holder.execute("BEGIN IMMEDIATE")
        with pytest.raises(LocalStoreError) as caught:
            _publish(path, generation_bundle(2), 1)
    finally:
        holder.close()
    assert str(caught.value) == "graph-database-busy", str(caught.value)
    assert publication_not_committed(caught.value) and caught.value.__suppress_context__
    assert _dump(path) == before
    assert _publish(path, generation_bundle(2), 1).generation == 2


def test_injected_driver_text_never_escapes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _published_once(tmp_path)
    monkeypatch.setattr(publisher, "_fault_point", _raise_at("after_family:files", sqlite3.OperationalError(SECRET_TEXT)))
    with pytest.raises(LocalStoreError) as caught:
        _publish(path, generation_bundle(2), 1)
    assert str(caught.value) == "graph-database-unavailable", str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert _generation(path) == 1


def test_read_accepted_generation_is_classified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _published_once(tmp_path)

    def broken(_connection: object) -> int:
        raise sqlite3.DatabaseError(SECRET_TEXT)

    monkeypatch.setattr(publisher, "accepted_generation", broken)
    with pytest.raises(LocalStoreError) as caught:
        read_accepted_generation(path, BINDING)
    assert str(caught.value) == "graph-database-unrecognized", str(caught.value)


def _coded(error: sqlite3.Error, code: int) -> sqlite3.Error:
    setattr(error, "sqlite_errorcode", code)
    return error


@pytest.mark.parametrize(
    ("error", "code"),
    (
        (_coded(sqlite3.OperationalError(SECRET_TEXT), 5), "graph-database-busy"),
        (_coded(sqlite3.OperationalError(SECRET_TEXT), 262), "graph-database-busy"),
        (_coded(sqlite3.OperationalError(SECRET_TEXT), 8), "graph-database-read-only"),
        (sqlite3.OperationalError(SECRET_TEXT), "graph-database-unavailable"),
        (sqlite3.DatabaseError(SECRET_TEXT), "graph-database-unrecognized"),
        (sqlite3.IntegrityError(SECRET_TEXT), "graph-publication-rejected"),
        (sqlite3.DataError(SECRET_TEXT), "graph-publication-rejected"),
        (sqlite3.ProgrammingError(SECRET_TEXT), "graph-publication-internal-error"),
        (sqlite3.InterfaceError(SECRET_TEXT), "graph-publication-internal-error"),
    ),
)
def test_write_classification_reuses_the_connection_taxonomy(error: sqlite3.Error, code: str) -> None:
    bounded = classify_write_error(error)
    assert bounded.code == code and SECRET_TEXT not in str(bounded), str(bounded)
