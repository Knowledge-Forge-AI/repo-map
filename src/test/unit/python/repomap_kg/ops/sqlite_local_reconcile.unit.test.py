"""SQLite Local retained-attempt reconciliation against the accepted marker.

REPOMAP-PRODUCT3-SQLITE-LOCAL3 (R2). Real temporary SQLite databases published
with the maintained fixture bundles, and armed retained attempt records written
through the existing retention helpers. A confirmed accepted attempt is settled
and replayed without sources, capture or a new generation; a confirmed
uncommitted attempt is settled failed and the refresh proceeds; every
ambiguous state refuses before capture and leaves the record untouched.
Real worker capture and process interruption are owned by the containerized
``sqlite_local_recovery`` integration owner. LOCAL7: Local record
replacement fsyncs the attempt directory and every retention namespace level
through ``state/``, including a namespace the first capture created (a failure
at any level refuses settlement with ``attempt-record-unwritable``); a
non-Local layout refuses before any write; the shared default used by the
PostgreSQL route does not sync directories.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from repomap_kg.artifacts.bundle import PublicationBundle
from repomap_kg.ops import _portable_retention, local_refresh
from repomap_kg.ops import portable_refresh
from repomap_kg.ops._portable_retention import (
    PortableRefreshError,
    _annotate_retained_attempt,
    _mark_retained_terminal,
    _read_retention_payload,
)
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home, local_graph_binding
from repomap_kg.ops.local_refresh import ATTEMPT_BLOCK, attempts_namespace, refresh_local_graph
from repomap_kg.ops.portable_refresh import portable_attempts_parent
from repomap_kg.storage.sqlite_local import durability, investigation_queries, publisher
from repomap_kg.storage.sqlite_local.connection import publisher_lock, read_transaction
from repomap_kg.storage.sqlite_local.publisher import LocalPublication, publish_generation
from repomap_kg.storage.sqlite_local.durability import DURABILITY_FAILED
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.host_read_store_config import fail_if_reached
from repomap_test_support.sqlite_local_fixtures import (
    generation_bundle,
    graph_toml,
    publication_for,
    write_sqlite_home,
)

GRAPH = "one"
REQUIRED = "graph-publication-reconciliation-required"


class _CaptureReached(Exception):
    """Raised by a capture double to prove a normal refresh continued."""


def _capture_reached(*_args: object, **_kwargs: object) -> Any:
    raise _CaptureReached


def _home(tmp_path: Path) -> tuple[LocalSqliteConfig, Path]:
    source = tmp_path / "src"
    source.mkdir()
    home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, source))
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    assert local_refresh.initialize_local_graph(config, GRAPH)["result"] == "initialized"
    return config, config.graph_store_root / f"{GRAPH}.sqlite3"


def _publication(config: LocalSqliteConfig, bundle: PublicationBundle) -> LocalPublication:
    return replace(publication_for(bundle, GRAPH), binding=local_graph_binding(config.graphs[0]))


def _publish(config: LocalSqliteConfig, path: Path, bundle: PublicationBundle, expected: int) -> None:
    publish_generation(path, _publication(config, bundle), bundle.families, expected_generation=expected)


def _block(config: LocalSqliteConfig, bundle: PublicationBundle, expected: int, **changes: object) -> dict[str, object]:
    attempt = _publication(config, bundle).receipt.attempt
    block: dict[str, object] = {
        "graph_id": GRAPH, "expected_generation": expected, "publication_bundle_id": bundle.bundle_id,
        "publication_job_id": attempt.job_id, "publication_attempt": attempt.attempt,
    }
    block.update(changes)
    return block


def _record(
    config: LocalSqliteConfig,
    block: dict[str, object] | None,
    retention: str = "publication-reconciliation",
    *,
    namespace: str | None = attempts_namespace(GRAPH),
) -> Path:
    parent = portable_attempts_parent(config, namespace)
    root = parent / secrets.token_hex(8)
    root.mkdir(mode=0o700, parents=True)
    record = root / "portable-result.json"
    payload = {"manifest_id": "manifest1:fixture", "retention_class": "publication-reconciliation"}
    descriptor = os.open(record, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, json.dumps(payload).encode())
    finally:
        os.close(descriptor)
    if block is not None:
        _annotate_retained_attempt(record, ATTEMPT_BLOCK, block)
    if retention != "publication-reconciliation":
        _mark_retained_terminal(record, retention)
    return record


def _retention(record: Path) -> object:
    return _read_retention_payload(record)["retention_class"]


def _runs(config: LocalSqliteConfig, path: Path) -> int:
    with read_transaction(path, local_graph_binding(config.graphs[0])) as connection:
        return int(connection.execute("SELECT count(*) FROM runs").fetchone()[0])


def _status_publication(config: LocalSqliteConfig, path: Path) -> Any:
    with read_transaction(path, local_graph_binding(config.graphs[0])) as connection:
        return investigation_queries.status_fields(connection)["publication"]


def test_confirmed_accepted_attempt_replays_without_sources_capture_or_new_generation(tmp_path: Path) -> None:
    config, path = _home(tmp_path)
    _publish(config, path, generation_bundle(1), 0)
    _publish(config, path, generation_bundle(2), 1)
    record = _record(config, _block(config, generation_bundle(2), 1))
    shutil.rmtree(tmp_path / "src")
    with patch.object(local_refresh, "capture_portable_candidate", fail_if_reached):
        result = refresh_local_graph(config, GRAPH)
    assert result.reconciled is True
    assert (result.generation, result.run_id, result.previous_run_id) == (2, 2, 1), result
    assert result.publication == _status_publication(config, path)
    assert dict(result.family_counts) == generation_bundle(2).family_counts
    assert "reconciled" not in result.to_jsonable()
    assert _retention(record) == "terminal-accepted" and _runs(config, path) == 2


def test_cli_replay_keeps_the_stdout_shape_and_notes_the_reconciliation(tmp_path: Path) -> None:
    config, path = _home(tmp_path)
    _publish(config, path, generation_bundle(1), 0)
    record = _record(config, _block(config, generation_bundle(1), 0))
    shutil.rmtree(tmp_path / "src")
    with patch.object(local_refresh, "capture_portable_candidate", fail_if_reached):
        code, stdout, stderr = run_repo_map_in_process(
            "ops", "refresh-graph", "--repo-map-home", str(config.config_home), "--graph", GRAPH, "--json"
        )
    assert code == 0, stderr
    payload = json.loads(stdout)
    assert (payload["accepted_generation"], payload["previous_run_id"], payload["result"]) == (1, None, "success")
    assert "reconciled" not in payload
    assert "NOTE: sqlite-local-attempt-reconciled: accepted generation 1" in stderr, stderr
    assert _retention(record) == "terminal-accepted" and _runs(config, path) == 1


def test_uncommitted_attempt_settles_failed_and_the_refresh_proceeds(tmp_path: Path) -> None:
    config, path = _home(tmp_path)
    _publish(config, path, generation_bundle(1), 0)
    record = _record(config, _block(config, generation_bundle(2), 1))
    with patch.object(local_refresh, "capture_portable_candidate", _capture_reached):
        with pytest.raises(_CaptureReached):
            refresh_local_graph(config, GRAPH)
    assert _retention(record) == "terminal-failed"


def test_commit_unknown_publication_is_reconciled_as_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, path = _home(tmp_path)
    _publish(config, path, generation_bundle(1), 0)
    record = _record(config, _block(config, generation_bundle(2), 1))  # armed as local_refresh arms it

    def late(name: str) -> None:
        if name == "after_commit":
            raise RuntimeError("ordinary failure after COMMIT")

    monkeypatch.setattr(publisher, "_fault_point", late)
    monkeypatch.setattr(publisher, "accepted_identity", lambda _connection: None)
    with pytest.raises(RuntimeError) as caught:
        _publish(config, path, generation_bundle(2), 1)
    assert getattr(caught.value, "is_commit_unknown", False) is True
    monkeypatch.undo()
    shutil.rmtree(tmp_path / "src")
    with patch.object(local_refresh, "capture_portable_candidate", fail_if_reached):
        result = refresh_local_graph(config, GRAPH)
    assert (result.reconciled, result.generation) == (True, 2)
    assert _retention(record) == "terminal-accepted" and _runs(config, path) == 2


def _garbage(path: Path) -> None:
    for sidecar in (path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        sidecar.unlink(missing_ok=True)
    path.write_bytes(b"not a database, just public-safe bytes" * 200)


@pytest.mark.parametrize(
    ("case", "reason"),
    (
        ("identity-conflict", "publication-identity-conflict"),
        ("generation-advanced", "accepted-generation-mismatch"),
        ("unreadable", "graph-database-unrecognized"),
        ("invalid-types", "attempt-record-invalid"),
        ("other-graph", "attempt-record-invalid"),
        ("two-armed", "multiple-unsettled-attempts"),
        ("stray-entry", "attempt-record-invalid"),
    ),
)
def test_ambiguous_state_refuses_before_capture_and_preserves_the_attempt(
    tmp_path: Path, case: str, reason: str
) -> None:
    config, path = _home(tmp_path)
    _publish(config, path, generation_bundle(1), 0)
    _publish(config, path, generation_bundle(2), 1)
    good = _block(config, generation_bundle(2), 1)
    blocks = {
        "identity-conflict": [dict(good, publication_bundle_id="bundle1:" + "0" * 64)],
        "generation-advanced": [_block(config, generation_bundle(1), 0)],
        "unreadable": [good],
        "invalid-types": [dict(good, expected_generation="1")],
        "other-graph": [dict(good, graph_id="two")],
        "two-armed": [good, good],
        "stray-entry": [good],
    }[case]
    records = [_record(config, block) for block in blocks] + [_record(config, None)]  # plus one unarmed
    if case == "unreadable":
        _garbage(path)
    if case == "stray-entry":
        (records[0].parent.parent / "stray").write_text("x", encoding="utf-8")
    before = [record.read_bytes() for record in records]
    with patch.object(local_refresh, "capture_portable_candidate", fail_if_reached):
        with pytest.raises(LocalStoreError) as caught:
            refresh_local_graph(config, GRAPH)
    assert str(caught.value) == f"{REQUIRED}: {reason}", str(caught.value)
    assert [record.read_bytes() for record in records] == before
    assert str(tmp_path) not in str(caught.value)


def test_unarmed_records_settle_failed_and_terminal_records_are_ignored(tmp_path: Path) -> None:
    config, path = _home(tmp_path)
    _publish(config, path, generation_bundle(1), 0)
    unarmed = _record(config, None)
    done = _record(config, _block(config, generation_bundle(1), 0), retention="terminal-accepted")
    done_bytes = done.read_bytes()
    with patch.object(local_refresh, "capture_portable_candidate", _capture_reached):
        with pytest.raises(_CaptureReached):
            refresh_local_graph(config, GRAPH)
    assert _retention(unarmed) == "terminal-failed"
    assert done.read_bytes() == done_bytes


def test_unwritable_settlement_refuses_instead_of_replaying_forever(tmp_path: Path) -> None:
    config, path = _home(tmp_path)
    _publish(config, path, generation_bundle(1), 0)
    record = _record(config, _block(config, generation_bundle(1), 0))

    def unwritable(_path: Path, _retention_class: str, *, sync_directory: bool) -> None:
        assert sync_directory is True
        raise OSError("read-only file system")

    with patch.object(local_refresh, "_mark_retained_terminal", unwritable), patch.object(
        local_refresh, "capture_portable_candidate", fail_if_reached
    ):
        with pytest.raises(LocalStoreError) as caught:
            refresh_local_graph(config, GRAPH)
    assert str(caught.value) == f"{REQUIRED}: attempt-record-unwritable", str(caught.value)
    assert _retention(record) == "publication-reconciliation"


def _local_chain(record: Path) -> list[Path]:
    attempt = record.parent.resolve()
    return [attempt, *list(attempt.parents)[:5]]


def _settle_by_refresh(config: LocalSqliteConfig, record: Path) -> None:
    with patch.object(local_refresh, "capture_portable_candidate", _capture_reached):
        with pytest.raises(_CaptureReached):
            refresh_local_graph(config, GRAPH)
    assert _retention(record) == "terminal-failed", "the armed attempt settles failed"


def test_first_namespace_settlement_syncs_every_local_retention_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, path = _home(tmp_path)
    _publish(config, path, generation_bundle(1), 0)
    root = portable_attempts_parent(config).parent
    state = root.parent
    assert not root.exists(), "no retention namespace exists before the first record"
    record = _record(config, _block(config, generation_bundle(2), 1))  # creates it unsynced
    synced: list[Path] = []
    monkeypatch.setattr(durability, "fsync_directory", synced.append)
    _settle_by_refresh(config, record)
    names = [level.name for level in synced[1:]]
    assert names == ["attempts", GRAPH, "sqlite-local", "portable-publication", "state"], names
    assert synced == _local_chain(record) and synced[-1] == state, synced
    home = config.control_root.resolve()
    assert home not in synced and tmp_path.resolve() not in synced, "the home and above are never synced"

    second = _record(config, _block(config, generation_bundle(2), 1))

    def failing_deep(level: Path) -> None:
        synced.append(level)
        if level.name == "portable-publication":
            raise LocalStoreError(DURABILITY_FAILED, "directory sync failed")

    synced.clear()
    monkeypatch.setattr(durability, "fsync_directory", failing_deep)
    with patch.object(local_refresh, "capture_portable_candidate", fail_if_reached):
        with pytest.raises(LocalStoreError) as caught:
            refresh_local_graph(config, GRAPH)
    assert str(caught.value) == f"{REQUIRED}: attempt-record-unwritable", str(caught.value)
    assert synced == _local_chain(second)[:5], "the deep failure is reached, not swallowed"
    # The replace happened but its durability is unconfirmed, so this run refuses;
    # a lost replace re-settles identically on the next refresh.
    assert _retention(second) == "terminal-failed"


def test_existing_namespace_settlement_does_not_broaden_the_synced_levels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, path = _home(tmp_path)
    _publish(config, path, generation_bundle(1), 0)
    _settle_by_refresh(config, _record(config, _block(config, generation_bundle(2), 1)))
    state = portable_attempts_parent(config).parent.parent
    second = _record(config, _block(config, generation_bundle(2), 1))
    synced: list[Path] = []
    monkeypatch.setattr(durability, "fsync_directory", synced.append)
    _settle_by_refresh(config, second)
    assert synced == _local_chain(second), synced
    assert all(level == state or level.is_relative_to(state) for level in synced), synced


def test_default_record_replacement_keeps_the_postgres_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _home(tmp_path)
    monkeypatch.setattr(_portable_retention, "fsync_directory_chain", fail_if_reached)
    record = _record(config, _block(config, generation_bundle(1), 0))
    _mark_retained_terminal(record, "terminal-failed")
    assert _retention(record) == "terminal-failed"
    shared = _record(config, None, namespace=None)  # the PostgreSQL-route layout
    before = shared.read_bytes()
    with pytest.raises(PortableRefreshError):
        _mark_retained_terminal(shared, "terminal-failed", sync_directory=True)
    assert shared.read_bytes() == before, "a refused record is not rewritten"
    assert sorted(entry.name for entry in shared.parent.iterdir()) == ["portable-result.json"], "no temp left"
    synced: list[tuple[Path, int]] = []
    monkeypatch.setattr(
        _portable_retention, "fsync_directory_chain", lambda leaf, levels: synced.append((leaf, levels))
    )
    other = _record(config, None)
    _annotate_retained_attempt(other, "block", {"key": "value"}, sync_directory=True)
    _mark_retained_terminal(other, "terminal-accepted", sync_directory=True)
    assert synced == [(other.parent.resolve(), 5)] * 2, synced


def test_a_locked_graph_refuses_before_reconciliation(tmp_path: Path) -> None:
    config, path = _home(tmp_path)
    _publish(config, path, generation_bundle(1), 0)
    record = _record(config, _block(config, generation_bundle(1), 0))
    with publisher_lock(path), patch.object(local_refresh, "capture_portable_candidate", fail_if_reached):
        with pytest.raises(LocalStoreError) as caught:
            refresh_local_graph(config, GRAPH)
    assert caught.value.code == "graph-publication-in-progress"
    assert _retention(record) == "publication-reconciliation"


def test_attempt_namespace_is_per_graph_and_every_level_is_private(tmp_path: Path) -> None:
    config, _ = _home(tmp_path)
    root = portable_attempts_parent(config).parent
    parent = portable_attempts_parent(config, attempts_namespace(GRAPH))
    assert parent.relative_to(root).parts == ("sqlite-local", GRAPH, "attempts")
    previous = os.umask(0o022)
    try:
        with patch.object(portable_refresh, "seal_configured_sources", _capture_reached):
            with pytest.raises(_CaptureReached):
                portable_refresh.capture_portable_candidate(
                    config, config.graphs[0], authority=None, attempts_namespace=attempts_namespace(GRAPH)
                )
    finally:
        os.umask(previous)
    for level in (root, root / "sqlite-local", root / "sqlite-local" / GRAPH, parent):
        assert level.stat().st_mode & 0o777 == 0o700, level.relative_to(root.parent)
    assert not (root / "attempts").exists(), "the shared PostgreSQL-route parent is untouched"
