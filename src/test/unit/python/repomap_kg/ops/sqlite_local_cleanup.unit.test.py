"""SQLite Local ``cleanup_local_graph``: attempts, dry run, refusal, durability (LOCAL9).

Temporary SQLite homes with retained attempt records written through the
maintained retention helpers. Only expired terminal attempts are removed, in
the graph's own namespace and in the pre-LOCAL3 shared directory; unsettled
(armed or not) and record-less attempts survive ``--yes`` byte-identical and
are reported, the shared ones as manual recovery with no graph attribution. Any
unsafe item refuses the whole run before anything is removed or synced. A dry
run changes nothing, creates no lock file and syncs nothing. ``--yes`` syncs
exactly ``state/`` and then the home, and a failed sync is never success. The
payload carries counts and codes only. Orphan classification is owned by the
``storage/sqlite_local_orphans`` unit owner; process-level proofs by the
containerized cleanup integration owner.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.ops import _portable_retention, local_refresh
from repomap_kg.ops._portable_retention import _annotate_retained_attempt, _mark_retained_terminal
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from repomap_kg.ops.local_cleanup import LocalCleanupError, cleanup_local_graph
from repomap_kg.ops.local_refresh import ATTEMPT_BLOCK, attempts_namespace
from repomap_kg.ops.portable_refresh import portable_attempts_parent
from repomap_kg.storage.sqlite_local import durability
from repomap_kg.storage.sqlite_local.connection import lock_path, publisher_lock
from repomap_kg.storage.sqlite_local.durability import DURABILITY_FAILED
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
from repomap_test_support.host_read_store_config import fail_if_reached
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_sqlite_home

GRAPH = "one"
EXPIRED = 1_000


def _config(tmp_path: Path, *, initialize: bool = True) -> LocalSqliteConfig:
    source = tmp_path / "src"
    source.mkdir(exist_ok=True)
    home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, source))
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    if initialize:
        assert local_refresh.initialize_local_graph(config, GRAPH)["result"] == "initialized"
    return config


def _attempt(
    config: LocalSqliteConfig,
    namespace: str | None,
    retention: str | None = "publication-reconciliation",
    *,
    expires: object = EXPIRED,
    block: bool = False,
) -> Path:
    """One attempt directory with workspace debris and (unless ``None``) a record."""
    root = portable_attempts_parent(config, namespace) / secrets.token_hex(32)
    (root / "objects" / "sha256").mkdir(mode=0o700, parents=True)
    (root / "objects" / "sha256" / "blob").write_bytes(b"artifact")
    if retention is None:
        return root
    record = root / "portable-result.json"
    descriptor = os.open(record, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, json.dumps({"manifest_id": "m", "retention_class": "publication-reconciliation"}).encode())
    finally:
        os.close(descriptor)
    if block:
        _annotate_retained_attempt(record, ATTEMPT_BLOCK, {"graph_id": GRAPH})
    if retention != "publication-reconciliation":
        _mark_retained_terminal(record, retention)
        payload = json.loads(record.read_bytes())
        payload["expires_at_epoch"] = expires
        _portable_retention._replace_retention_payload(record, payload)
    return root


def _graph_ns() -> str:
    return attempts_namespace(GRAPH)


def _tree(root: Path) -> dict[str, tuple[int, int, str]]:
    """Every entry under ``root``: type bits, mode and content digest (links by target)."""
    snapshot: dict[str, tuple[int, int, str]] = {}
    for path in sorted(root.rglob("*")):
        details = path.lstat()
        if stat.S_ISLNK(details.st_mode):
            content = os.readlink(path)
        elif stat.S_ISREG(details.st_mode):
            content = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            content = ""
        snapshot[str(path.relative_to(root))] = (stat.S_IFMT(details.st_mode), stat.S_IMODE(details.st_mode), content)
    return snapshot


def _without_live_sidecars(tree: dict[str, tuple[int, int, str]]) -> dict[str, tuple[int, int, str]]:
    live = f"{GRAPH}.sqlite3"
    return {name: value for name, value in tree.items() if not name.endswith((f"{live}-wal", f"{live}-shm"))}


def _sync_recorder(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    synced: list[Path] = []
    monkeypatch.setattr(durability, "fsync_directory", synced.append)
    return synced


def _populated(tmp_path: Path) -> tuple[LocalSqliteConfig, dict[str, Path]]:
    config = _config(tmp_path)
    attempts = {
        "graph-expired": _attempt(config, _graph_ns(), "terminal-accepted"),
        "graph-retained": _attempt(config, _graph_ns(), "terminal-failed", expires=2**40),
        "graph-armed": _attempt(config, _graph_ns(), block=True),
        "graph-unarmed": _attempt(config, _graph_ns()),
        "graph-incomplete": _attempt(config, _graph_ns(), None),
        "legacy-expired-accepted": _attempt(config, None, "terminal-accepted"),
        "legacy-expired-failed": _attempt(config, None, "terminal-failed"),
        "legacy-unresolved": _attempt(config, None),
        "legacy-incomplete": _attempt(config, None, None),
    }
    return config, attempts


def test_dry_run_reports_everything_and_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _ = _populated(tmp_path)
    home = config.control_root
    lock = lock_path(config.graph_store_root / f"{GRAPH}.sqlite3")
    lock.unlink()
    before = _tree(home)
    monkeypatch.setattr(durability, "fsync_directory", fail_if_reached)
    payload = cleanup_local_graph(config, GRAPH, execute=False)
    assert _tree(home) == before and not lock.exists(), "a dry run wrote, removed or created something"
    assert (payload["result"], payload["dry_run"], payload["changed"], payload["durability"]) == (
        "dry-run", True, False, "not-attempted",
    )
    assert payload["graph_attempts"] == {
        "expired_terminal_found": 1, "expired_terminal_removed": 0, "retained_terminal": 1,
        "unsettled_preserved": 2, "incomplete_preserved": 1, "unsafe": 0,
    }, payload
    assert payload["legacy_shared_attempts"] == {
        "expired_terminal_found": 2, "expired_terminal_removed": 0, "retained_terminal": 0,
        "unresolved_preserved": 1, "incomplete_preserved": 1, "unsafe": 0,
    }, payload
    assert payload["warnings"] == [
        "graph-attempt-incomplete", "graph-attempt-unsettled", "legacy-incomplete-attempt", "legacy-unresolved-attempt",
    ] and payload["warning_count"] == 4
    assert payload["manual_recovery_required"] is True and payload["refusals"] == []
    assert payload["final_database"] == "not-inspected", "no orphan, so the database is never opened"


def test_yes_removes_only_expired_terminal_attempts_and_syncs_state_then_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, attempts = _populated(tmp_path)
    kept = {name: _tree(path) for name, path in attempts.items() if "expired" not in name}
    database = config.graph_store_root / f"{GRAPH}.sqlite3"
    live = database.read_bytes()
    synced = _sync_recorder(monkeypatch)
    payload = cleanup_local_graph(config, GRAPH, execute=True)
    assert (payload["result"], payload["changed"], payload["durability"]) == ("cleaned", True, "established")
    assert payload["graph_attempts"]["expired_terminal_removed"] == 1
    assert payload["legacy_shared_attempts"]["expired_terminal_removed"] == 2
    for name, path in attempts.items():
        assert path.exists() == ("expired" not in name), name
        if name in kept:
            assert _tree(path) == kept[name], f"{name} changed under --yes"
    home = config.control_root.resolve()
    assert synced == [home / "state", home], synced
    assert database.read_bytes() == live
    again = cleanup_local_graph(config, GRAPH, execute=True)
    assert (again["result"], again["changed"]) == ("cleaned", False), "unresolved evidence survives every rerun"
    assert again["legacy_shared_attempts"]["unresolved_preserved"] == 1 and again["manual_recovery_required"]


def test_graph_local_unsettled_attempts_still_reconcile_through_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    unarmed = _attempt(config, _graph_ns())
    assert cleanup_local_graph(config, GRAPH, execute=True)["graph_attempts"]["unsettled_preserved"] == 1

    class _Captured(Exception):
        pass

    def captured(*_args: object, **_kwargs: object) -> Any:
        raise _Captured

    monkeypatch.setattr(local_refresh, "capture_portable_candidate", captured)
    with pytest.raises(_Captured):
        local_refresh.refresh_local_graph(config, GRAPH)
    record = json.loads((unarmed / "portable-result.json").read_bytes())
    assert record["retention_class"] == "terminal-failed", "refresh reconciliation is unchanged"


def _unsafe_cases(config: LocalSqliteConfig, tmp_path: Path) -> dict[str, tuple[Path, str]]:
    legacy = portable_attempts_parent(config, None)
    cases: dict[str, tuple[Path, str]] = {}
    malformed = _attempt(config, None)
    (malformed / "portable-result.json").chmod(0o600)
    (malformed / "portable-result.json").write_bytes(b"{not json")
    cases["malformed"] = (malformed, "unsafe-legacy-attempt")
    loose = _attempt(config, None, "terminal-failed")
    (loose / "portable-result.json").chmod(0o644)
    cases["record-mode"] = (loose, "unsafe-legacy-attempt")
    boolean = _attempt(config, None, "terminal-failed", expires=True)
    cases["boolean-expiry"] = (boolean, "unsafe-legacy-attempt")
    nested = _attempt(config, None, "terminal-accepted")
    (nested / "objects" / "escape").symlink_to(tmp_path / "outside")
    cases["nested-symlink"] = (nested, "unsafe-legacy-attempt")
    linked = _attempt(config, None, "terminal-accepted")
    os.link(linked / "objects" / "sha256" / "blob", tmp_path / "second-link")
    cases["multi-link"] = (linked, "unsafe-legacy-attempt")
    target = _attempt(config, None, "terminal-accepted")
    (legacy / ("b" * 64)).symlink_to(target)
    cases["symlinked-attempt"] = (legacy / ("b" * 64), "unsafe-legacy-attempt")
    (legacy / "stray-file").write_bytes(b"")
    cases["non-directory"] = (legacy / "stray-file", "unsafe-legacy-attempt")
    unknown = _attempt(config, _graph_ns(), "terminal-failed")
    record = json.loads((unknown / "portable-result.json").read_bytes())
    record["retention_class"] = "archived"
    _portable_retention._replace_retention_payload(unknown / "portable-result.json", record)
    cases["unknown-class"] = (unknown, "unsafe-graph-attempt")
    return cases


def test_any_unsafe_item_refuses_before_anything_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    for name, (path, code) in _unsafe_cases(config, tmp_path).items():
        expired = _attempt(config, None, "terminal-accepted")
        before = _tree(config.control_root)
        monkeypatch.setattr(durability, "fsync_directory", fail_if_reached)
        payload = cleanup_local_graph(config, GRAPH, execute=True)
        assert (payload["result"], payload["changed"], payload["durability"]) == ("refused", False, "not-attempted"), name
        assert code in payload["refusals"] and payload["refusal_count"] >= 1, (name, payload)
        assert _without_live_sidecars(_tree(config.control_root)) == _without_live_sidecars(before), name
        for leftover in (path, expired):
            if leftover.is_symlink() or not leftover.is_dir():
                leftover.unlink()
            else:
                shutil.rmtree(leftover)
    monkeypatch.undo()
    assert cleanup_local_graph(config, GRAPH, execute=True)["result"] == "cleaned"


def test_failures_after_validation_are_incomplete_never_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    expired = _attempt(config, None, "terminal-accepted")

    def failing_sync(path: Path) -> None:
        if path.name == "state":
            raise LocalStoreError(DURABILITY_FAILED, "directory sync failed")

    monkeypatch.setattr(durability, "fsync_directory", failing_sync)
    payload = cleanup_local_graph(config, GRAPH, execute=True)
    assert (payload["result"], payload["durability"], payload["failures"]) == (
        "incomplete", DURABILITY_FAILED, [DURABILITY_FAILED],
    ), payload
    assert not expired.exists() and payload["changed"] is True

    stuck = _attempt(config, None, "terminal-failed")

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("portable cleanup encountered unexpected node")

    monkeypatch.setattr(_portable_retention, "_remove_attempt_root", refuse)
    monkeypatch.setattr(durability, "fsync_directory", lambda _path: None)
    payload = cleanup_local_graph(config, GRAPH, execute=True)
    assert (payload["result"], payload["failures"], payload["durability"]) == (
        "incomplete", ["attempt-removal-failed"], "established",
    ), payload
    assert stuck.exists() and payload["legacy_shared_attempts"]["expired_terminal_removed"] == 0


def test_a_held_publisher_lock_refuses_both_modes(tmp_path: Path) -> None:
    config = _config(tmp_path)
    expired = _attempt(config, None, "terminal-accepted")
    with publisher_lock(config.graph_store_root / f"{GRAPH}.sqlite3"):
        for execute in (False, True):
            with pytest.raises(LocalStoreError) as caught:
                cleanup_local_graph(config, GRAPH, execute=execute)
            assert caught.value.code == "graph-publication-in-progress"
    assert expired.exists()


@pytest.mark.parametrize("level", ["state", "portable-publication", "sqlite-local", "attempts", "graphs"])
def test_a_symlinked_namespace_level_refuses_the_whole_command(tmp_path: Path, level: str) -> None:
    config = _config(tmp_path)
    _attempt(config, _graph_ns(), "terminal-accepted")
    _attempt(config, None, "terminal-accepted")
    state = config.control_root / "state"
    target = {
        "state": state,
        "portable-publication": state / "portable-publication",
        "sqlite-local": state / "portable-publication" / "sqlite-local",
        "attempts": state / "portable-publication" / "attempts",
        "graphs": state / "sqlite-local" / "graphs",
    }[level]
    moved = tmp_path / "moved" / level
    moved.parent.mkdir()
    target.rename(moved)
    target.symlink_to(moved)
    before = _tree(tmp_path / "moved")
    with pytest.raises(LocalStoreError) as caught:
        cleanup_local_graph(config, GRAPH, execute=True)
    assert str(caught.value) == "sqlite-cleanup-layout-invalid: a Local state level is not a private directory"
    assert _tree(tmp_path / "moved") == before


def test_uninitialized_home_and_unknown_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path, initialize=False)
    monkeypatch.setattr(durability, "fsync_directory", fail_if_reached)
    payload = cleanup_local_graph(config, GRAPH, execute=True)
    assert (payload["result"], payload["durability"], payload["final_database"]) == (
        "cleaned", "not-applicable", "not-inspected",
    )
    assert not (config.control_root / "state").exists(), "cleanup never creates state"
    with pytest.raises(LocalCleanupError, match="unknown graph_id: nope"):
        cleanup_local_graph(config, "nope", execute=False)


def test_payload_is_path_and_token_free(tmp_path: Path) -> None:
    config, attempts = _populated(tmp_path)
    store = config.graph_store_root
    orphan = store / f".{GRAPH}.sqlite3.init-{secrets.token_hex(8)}"
    orphan.write_bytes(b"")
    orphan.chmod(0o600)
    for execute in (False, True):
        text = json.dumps(cleanup_local_graph(config, GRAPH, execute=execute))
        for forbidden in (str(tmp_path), str(tmp_path.resolve()), orphan.name, *(path.name for path in attempts.values())):
            assert forbidden not in text, forbidden
        assert not re.search(r"[0-9a-f]{16}", text), text
    assert not orphan.exists()
