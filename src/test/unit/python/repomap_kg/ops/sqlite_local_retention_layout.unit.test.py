"""SQLite Local retention layout validation before any record write (LOCAL9, H6).

``_local_attempt_directory`` guards every Local record replacement that syncs
directories. The resolved chain must name ``attempts``, ``sqlite-local``,
``portable-publication`` and now ``state``, and the attempt directory must be
its own resolved form, so a symlink below the publication root cannot redirect
the sync chain into another same-shaped tree. Every refusal happens before a
temporary file, a replace or a sync. A symlinked home still works (the
publication root is resolved first). This guard alone still admits a
symlinked ``state`` whose target is itself named ``state``; since LOCAL10 every
Local mutation owner refuses such a ``state`` earlier, before any lock or
record write (``ops/sqlite_local_state_layout``). The PostgreSQL route's
default replacement is untouched.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from repomap_kg.ops import _portable_retention
from repomap_kg.ops._portable_retention import (
    PortableRefreshError,
    _mark_retained_terminal,
    _read_retention_payload,
)
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from repomap_kg.ops.local_refresh import attempts_namespace
from repomap_kg.ops.portable_refresh import portable_attempts_parent
from repomap_test_support.host_read_store_config import fail_if_reached
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_sqlite_home

GRAPH = "one"
TOKEN = "a" * 64


def _write_record(attempt: Path) -> Path:
    attempt.mkdir(mode=0o700, parents=True, exist_ok=True)
    record = attempt / "portable-result.json"
    descriptor = os.open(record, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, json.dumps({"retention_class": "publication-reconciliation"}).encode())
    finally:
        os.close(descriptor)
    return record


def _local_record(root: Path, graph: str = GRAPH) -> Path:
    return _write_record(root / "portable-publication" / "sqlite-local" / graph / "attempts" / TOKEN)


def _refused_untouched(record: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_portable_retention, "fsync_directory_chain", fail_if_reached)
    before = record.read_bytes()
    with pytest.raises(PortableRefreshError) as caught:
        _mark_retained_terminal(record, "terminal-failed", sync_directory=True)
    assert str(caught.value) == "retained portable record is outside the Local retention namespace"
    assert record.read_bytes() == before, "a refused record is never rewritten"
    assert sorted(os.listdir(record.parent)) == ["portable-result.json"], "no temporary file is written"


def _synced(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, int]]:
    synced: list[tuple[Path, int]] = []
    monkeypatch.setattr(
        _portable_retention, "fsync_directory_chain", lambda leaf, levels: synced.append((leaf, levels))
    )
    return synced


def test_the_real_layout_syncs_its_exact_resolved_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = _local_record(tmp_path / "home" / "state")
    synced = _synced(monkeypatch)
    _mark_retained_terminal(record, "terminal-failed", sync_directory=True)
    assert synced == [(record.parent, 5)], synced
    assert [level.name for level in record.parent.parents][:5] == [
        "attempts", GRAPH, "sqlite-local", "portable-publication", "state",
    ]
    assert _read_retention_payload(record)["retention_class"] == "terminal-failed"


def test_a_top_level_not_named_state_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _refused_untouched(_local_record(tmp_path / "home" / "not-state"), monkeypatch)


@pytest.mark.parametrize("level", ["sqlite-local", GRAPH, "attempts", TOKEN])
def test_a_symlinked_level_below_the_publication_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: str
) -> None:
    """The redirect target is a complete same-shaped tree, so names alone would pass."""
    elsewhere = _local_record(tmp_path / "elsewhere" / "state")
    state = tmp_path / "home" / "state"
    chain = ["portable-publication", "sqlite-local", GRAPH, "attempts", TOKEN]
    index = chain.index(level)
    link_parent = state.joinpath(*chain[:index])
    link_parent.mkdir(mode=0o700, parents=True)
    same_shaped = [elsewhere.parent, *elsewhere.parent.parents]  # TOKEN, attempts, graph, ...
    (link_parent / level).symlink_to(same_shaped[len(chain) - 1 - index])
    record = state.joinpath(*chain, "portable-result.json")
    assert record.resolve() == elsewhere.resolve()
    _refused_untouched(record, monkeypatch)


def _config(home: Path, tmp_path: Path) -> LocalSqliteConfig:
    source = tmp_path / "src"
    source.mkdir(exist_ok=True)
    write_sqlite_home(home, graph_toml(GRAPH, source))
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    return config


def test_the_record_guard_alone_admits_a_symlinked_home_and_a_state_named_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real-home"
    _config(real, tmp_path)
    alias = tmp_path / "alias-home"
    alias.symlink_to(real)
    record = _write_record(portable_attempts_parent(_config(alias, tmp_path), attempts_namespace(GRAPH)) / TOKEN)
    synced = _synced(monkeypatch)
    _mark_retained_terminal(record, "terminal-failed", sync_directory=True)
    assert synced == [(record.parent, 5)] and record.is_relative_to(real.resolve())

    moved = tmp_path / "volume" / "state"
    moved.mkdir(mode=0o700, parents=True)
    linked = tmp_path / "linked-home"
    config = _config(linked, tmp_path)
    (linked / "state").symlink_to(moved)
    record = _write_record(portable_attempts_parent(config, attempts_namespace(GRAPH)) / TOKEN)
    _mark_retained_terminal(record, "terminal-accepted", sync_directory=True)
    assert synced[-1] == (moved.resolve() / "portable-publication" / "sqlite-local" / GRAPH / "attempts" / TOKEN, 5)


def test_a_symlinked_state_with_another_name_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    other = tmp_path / "volume" / "repomap-data"
    other.mkdir(mode=0o700, parents=True)
    home = tmp_path / "home"
    config = _config(home, tmp_path)
    (home / "state").symlink_to(other)
    record = _write_record(portable_attempts_parent(config, attempts_namespace(GRAPH)) / TOKEN)
    _refused_untouched(record, monkeypatch)


def test_the_postgres_default_never_checks_or_syncs_the_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_portable_retention, "fsync_directory_chain", fail_if_reached)
    shared = _write_record(tmp_path / "home" / "state" / "portable-publication" / "attempts" / TOKEN)
    _mark_retained_terminal(shared, "terminal-accepted")
    assert _read_retention_payload(shared)["retention_class"] == "terminal-accepted"
    elsewhere = _local_record(tmp_path / "home" / "not-state")
    _mark_retained_terminal(elsewhere, "terminal-failed")
    assert _read_retention_payload(elsewhere)["retention_class"] == "terminal-failed"
