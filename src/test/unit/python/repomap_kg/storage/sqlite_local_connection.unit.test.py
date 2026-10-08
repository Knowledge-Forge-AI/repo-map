"""SQLite Local crash-safe initialization and connection error classification.

REPOMAP-PRODUCT3-SQLITE-LOCAL2-RECOVERY-AUTHORITY1 (A3, A4). Hermetic temporary
SQLite files only. Initialization builds the current schema in a sibling temporary file
and hard-links it to the final path, so a failure before install never leaves
a final file, an existing target is never replaced, and a store that cannot
hard-link refuses instead of overwriting. A write through a read-only
connection is a bounded read-only refusal, distinct from unavailability.
Process-kill proofs are owned by the containerized recovery owner.
LOCAL7 durability: the completed temporary file and the requested store
ancestors are synced before the link and the store directory after it; a sync
failure is a bounded refusal (never success) that leaves either no final path
or the complete database. Sync failures are injected with fakes.
"""

from __future__ import annotations

import errno
import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.storage.sqlite_local import connection
from repomap_kg.storage.sqlite_local.connection import (
    graph_database_uri,
    initialize_graph_database,
    publisher_lock,
    read_transaction,
)
from repomap_kg.storage.sqlite_local.durability import DURABILITY_FAILED, DURABILITY_UNAVAILABLE
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
from repomap_test_support.sqlite_local_fixtures import local_binding

BINDING = local_binding()
PRE_INSTALL = ("init:temporary-created", "init:schema-applied", "init:before-install")
POST_INSTALL = ("init:installed", "init:after-install")


def _database(tmp_path: Path) -> Path:
    store = tmp_path / "graphs"
    store.mkdir(mode=0o700)
    return store / "portable-fixture.sqlite3"


def _init(path: Path) -> str:
    return initialize_graph_database(path, BINDING, applied_at="2026-09-29T00:00:00Z")


def _names(path: Path) -> list[str]:
    return sorted(item.name for item in path.parent.iterdir())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raise_at(point: str, error: type[BaseException]) -> Any:
    def fault(name: str) -> None:
        if name == point:
            raise error("injected")

    return fault


@pytest.fixture(autouse=True)
def _forbid_overwriting_installs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any rename onto a graph-store name; other callers are untouched."""
    store = tmp_path / "graphs"
    for name in ("replace", "rename"):
        original = getattr(os, name)

        def guarded(source: Any, target: Any, *args: Any, _original: Any = original, **kwargs: Any) -> Any:
            if Path(os.fsdecode(target)).parent == store:
                raise AssertionError("initialization must never rename over a graph path")
            return _original(source, target, *args, **kwargs)

        monkeypatch.setattr(os, name, guarded)


def test_clean_install_leaves_only_the_complete_final_database(tmp_path: Path) -> None:
    path = _database(tmp_path)
    with publisher_lock(path):
        assert _init(path) == "initialized"
    assert _names(path) == [path.name, f"{path.name}.publish.lock"], _names(path)
    details = path.stat()
    assert (details.st_mode & 0o777, details.st_nlink) == (0o600, 1), details
    with read_transaction(path, BINDING) as reader:
        assert reader.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert reader.execute("SELECT count(*) FROM local_schema_migrations").fetchone() == (2,)


@pytest.mark.parametrize("error", (RuntimeError, KeyboardInterrupt))
@pytest.mark.parametrize("point", PRE_INSTALL)
def test_failure_before_install_leaves_no_final_path_and_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str, error: type[BaseException]
) -> None:
    path = _database(tmp_path)
    monkeypatch.setattr(connection, "_fault_point", _raise_at(point, error))
    with pytest.raises(error):
        _init(path)
    assert _names(path) == [], _names(path)
    monkeypatch.setattr(connection, "_fault_point", lambda _name: None)
    assert _init(path) == "initialized"
    assert _names(path) == [path.name], _names(path)


@pytest.mark.parametrize("error", (RuntimeError, KeyboardInterrupt))
@pytest.mark.parametrize("point", POST_INSTALL)
def test_failure_after_install_keeps_the_complete_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: type[BaseException], point: str
) -> None:
    path = _database(tmp_path)
    monkeypatch.setattr(connection, "_fault_point", _raise_at(point, error))
    with pytest.raises(error):
        _init(path)
    assert _names(path) == [path.name] and path.stat().st_nlink == 1, _names(path)
    monkeypatch.setattr(connection, "_fault_point", lambda _name: None)
    assert _init(path) == "already-current"


def test_init_syncs_file_and_ancestors_before_the_link_and_the_store_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _database(tmp_path)
    events: list[tuple[str, str]] = []

    def name(value: Any) -> str:
        text = Path(os.fsdecode(value)).name
        return "temporary" if ".init-" in text else text

    real_link = os.link

    def link(source: Any, target: Any) -> None:
        events.append(("link", name(target)))
        real_link(source, target)

    monkeypatch.setattr(connection, "fsync_file", lambda target: events.append(("file", name(target))))
    monkeypatch.setattr(
        connection, "fsync_directory_chain", lambda leaf, levels: events.append((f"chain{levels}", name(leaf)))
    )
    monkeypatch.setattr(connection, "fsync_directory", lambda target: events.append(("dir", name(target))))
    monkeypatch.setattr(os, "link", link)
    assert initialize_graph_database(path, BINDING, applied_at="now", durable_ancestors=3) == "initialized"
    assert events == [
        ("file", "temporary"), ("chain3", "graphs"), ("link", path.name), ("dir", "graphs"), ("dir", "graphs"),
    ], events


def test_directory_sync_failure_after_install_is_a_bounded_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _database(tmp_path)
    real = connection.fsync_directory

    def failing(_directory: Path) -> None:
        raise LocalStoreError(DURABILITY_FAILED, "directory sync failed")

    monkeypatch.setattr(connection, "fsync_directory", failing)
    with pytest.raises(LocalStoreError) as caught:
        _init(path)
    assert str(caught.value) == f"{DURABILITY_FAILED}: directory sync failed"
    assert _names(path) == [path.name] and path.stat().st_nlink == 1, _names(path)
    with read_transaction(path, BINDING) as reader:
        assert reader.execute("SELECT count(*) FROM local_schema_migrations").fetchone() == (2,)
    monkeypatch.setattr(connection, "fsync_directory", real)  # keeps the rename guard
    assert _init(path) == "already-current"


def test_unavailable_directory_sync_refuses_before_the_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _database(tmp_path)

    def unavailable(_leaf: Path, _levels: int) -> None:
        raise LocalStoreError(DURABILITY_UNAVAILABLE, "directory sync is not supported")

    monkeypatch.setattr(connection, "fsync_directory_chain", unavailable)
    with pytest.raises(LocalStoreError) as caught:
        _init(path)
    assert caught.value.code == DURABILITY_UNAVAILABLE
    assert _names(path) == [], _names(path)


def test_unrecognized_target_created_before_install_is_never_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _database(tmp_path)
    garbage = b"public-safe unrelated bytes " * 200

    def appear(name: str) -> None:
        if name == "init:before-install":
            path.write_bytes(garbage)

    monkeypatch.setattr(connection, "_fault_point", appear)
    with pytest.raises(LocalStoreError) as caught:
        _init(path)
    assert caught.value.code == "graph-database-unrecognized"
    assert path.read_bytes() == garbage and _names(path) == [path.name], _names(path)


def test_current_target_created_before_install_is_reported_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _database(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    ready = elsewhere / path.name
    assert initialize_graph_database(ready, BINDING, applied_at="earlier") == "initialized"
    expected = _sha(ready)

    def appear(name: str) -> None:
        if name == "init:before-install":
            os.link(ready, path)

    monkeypatch.setattr(connection, "_fault_point", appear)
    assert _init(path) == "already-current"
    assert _sha(path) == expected and _names(path) == [path.name], _names(path)


def test_historical_empty_final_file_is_refused_and_kept(tmp_path: Path) -> None:
    path = _database(tmp_path)
    path.touch(mode=0o600)
    with pytest.raises(LocalStoreError) as caught:
        _init(path)
    assert caught.value.code == "graph-database-unrecognized"
    assert path.stat().st_size == 0 and _names(path) == [path.name], _names(path)


@pytest.mark.parametrize("code", (errno.ENOTSUP, errno.EXDEV, errno.EPERM, errno.EMLINK))
def test_store_without_hard_links_refuses_instead_of_overwriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    path = _database(tmp_path)

    def no_link(*_args: object, **_kwargs: object) -> None:
        raise OSError(code, os.strerror(code))

    monkeypatch.setattr(os, "link", no_link)
    with pytest.raises(LocalStoreError) as caught:
        _init(path)
    assert str(caught.value) == (
        "graph-database-unavailable: graph store does not support atomic no-clobber install"
    )
    assert _names(path) == [], _names(path)


def test_write_through_a_read_transaction_is_a_read_only_refusal(tmp_path: Path) -> None:
    path = _database(tmp_path)
    _init(path)
    before = _sha(path)
    with pytest.raises(LocalStoreError) as caught:
        with read_transaction(path, BINDING) as reader:
            assert reader.execute("PRAGMA query_only").fetchone() == (1,)
            reader.execute("DELETE FROM runs")
    assert str(caught.value) == "graph-database-read-only", str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert _sha(path) == before


def test_write_through_a_bare_mode_ro_connection_classifies_as_read_only(tmp_path: Path) -> None:
    path = _database(tmp_path)
    _init(path)
    uri = graph_database_uri(path, read_only=True)
    assert uri.endswith("?mode=ro"), uri
    reader = sqlite3.connect(uri, uri=True, autocommit=True)
    try:
        with pytest.raises(sqlite3.OperationalError) as raised:
            reader.execute("DELETE FROM runs")
    finally:
        reader.close()
    assert connection._classify(raised.value).code == "graph-database-read-only"


def _operational(code: int | None) -> sqlite3.Error:
    error = sqlite3.OperationalError("synthetic")
    if code is not None:
        error.sqlite_errorcode = code
    return error


@pytest.mark.parametrize(
    ("error", "expected"),
    (
        (_operational(5), "graph-database-busy"),
        (_operational(6), "graph-database-busy"),
        (_operational(261), "graph-database-busy"),
        (_operational(8), "graph-database-read-only"),
        (_operational(264), "graph-database-unavailable"),
        (_operational(520), "graph-database-unavailable"),
        (_operational(776), "graph-database-unavailable"),
        (_operational(1032), "graph-database-unavailable"),
        (_operational(1288), "graph-database-unavailable"),
        (_operational(1544), "graph-database-unavailable"),
        (_operational(None), "graph-database-unavailable"),
        (sqlite3.DatabaseError("file is not a database"), "graph-database-unrecognized"),
    ),
)
def test_classification_adds_only_the_plain_read_only_discriminator(
    error: sqlite3.Error, expected: str
) -> None:
    classified = connection._classify(error)
    assert (classified.code, str(classified)) == (expected, expected)
