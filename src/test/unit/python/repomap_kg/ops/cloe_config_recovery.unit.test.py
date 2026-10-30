"""ADR 0114 durable recovery: crash at every mutation boundary, partial states, drift and residue."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import errno
import fcntl
import json
import os
from pathlib import Path
import stat
from typing import Any

import pytest

from repomap_kg.ops import config_migration
from repomap_kg.ops.config_migration import (
    apply_cloe_config_migration as apply, finalize_cloe_config_migration as finalize,
    rollback_cloe_config_migration as rollback,
)
from repomap_kg.ops.config_migration_fs import OPERATION_DIRECTORY, Home

SERVER = 'schema_version = 1\n[postgres]\nhost = "127.0.0.1"\npassword = "recovery-secret-sentinel"\n'
OVERLAY = 'schema_version = 1\n[service]\nlog_level = "debug"\n'
NAMES = {"00-project.rp.toml": "00-project.cloe.toml", "90-machine.rpl.toml": "90-machine.local.cloe.toml"}
_BOUNDARIES = ("mkdir", "open", "write", "fchmod", "fsync", "link", "unlink", "rename", "rmdir")


class Crash(BaseException):
    """A process death at one mutation boundary: no in-process recovery may run."""


def make_home(root: Path) -> Path:
    home = root / "home"
    home.mkdir(parents=True)
    for name, body in zip(NAMES, (SERVER, OVERLAY)):
        (home / name).write_text(body)
        (home / name).chmod(0o644)
    home.chmod(0o700)
    return home


def tree(root: Path) -> dict[str, tuple[int, bytes | None]]:
    found: dict[str, tuple[int, bytes | None]] = {".": (root.lstat().st_mode, None)}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        found[str(path.relative_to(root))] = (info.st_mode, path.read_bytes() if stat.S_ISREG(info.st_mode) else None)
    return found


def converted(home: Path) -> dict[str, tuple[int, bytes | None]]:
    return {NAMES.get(name, name): value for name, value in tree(home).items()}


def codes(result: dict[str, Any]) -> list[str]:
    return [item["code"] for item in result["refusals"]]


@contextmanager
def boundaries(fail_at: int | None = None, error: BaseException | None = None) -> Iterator[list[str]]:
    """Record (and optionally fail at) every mutating os call made by the migration."""
    calls: list[str] = []
    originals = {name: getattr(os, name) for name in _BOUNDARIES}

    def wrap(name: str, function: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if name == "open" and not args[1] & os.O_CREAT:
                return function(*args, **kwargs)
            calls.append(name)
            if len(calls) - 1 == fail_at:
                raise error  # type: ignore[misc]
            return function(*args, **kwargs)
        return wrapper

    for name, function in originals.items():
        setattr(os, name, wrap(name, function))
    try:
        yield calls
    finally:
        for name, function in originals.items():
            setattr(os, name, function)


def trace(root: Path, prepare: Any, operation: Any) -> int:
    home = make_home(root)
    prepare(home)
    with boundaries() as calls:
        assert operation(home, confirmed=True)["refusals"] == []
    return len(calls)


def journal_state(home: Path) -> str | None:
    path = home / OPERATION_DIRECTORY / "journal.json"
    return json.loads(path.read_text())["state"] if path.exists() else None


def applied(home: Path) -> None:
    assert apply(home, confirmed=True)["result"] == "applied"


def test_crash_at_every_apply_boundary_rolls_back_to_the_exact_pre_state(tmp_path: Path) -> None:
    count = trace(tmp_path / "reference", lambda home: None, apply)
    assert count > 20
    for index in range(count):
        home = make_home(tmp_path / f"crash-{index}")
        before = tree(home)
        with pytest.raises(Crash), boundaries(index, Crash()):
            apply(home, confirmed=True)
        result = rollback(home, confirmed=True)
        assert result["result"] in {"rolled-back", "discarded", "nothing-to-recover"}, (index, result)
        assert tree(home) == before, index
        assert rollback(home, confirmed=True)["result"] == "nothing-to-recover"


def test_crash_at_every_rollback_boundary_resumes_to_the_pre_state(tmp_path: Path) -> None:
    def drop_target(home: Path) -> None:
        applied(home)
        (home / "00-project.cloe.toml").unlink()

    for prepare in (applied, drop_target):
        count = trace(tmp_path / f"reference-{prepare.__name__}", prepare, rollback)
        for index in range(count):
            home = make_home(tmp_path / f"{prepare.__name__}-{index}")
            before = tree(home)
            prepare(home)
            with pytest.raises(Crash), boundaries(index, Crash()):
                rollback(home, confirmed=True)
            if (home / OPERATION_DIRECTORY).exists():
                assert apply(home, dry_run=True)["result"] in {"refused", "already-applied"}
            assert rollback(home, confirmed=True)["result"] in {"rolled-back", "discarded", "nothing-to-recover"}
            assert tree(home) == before, (prepare.__name__, index)


def test_crash_at_every_finalize_boundary_resumes_without_reopening_rollback(tmp_path: Path) -> None:
    count = trace(tmp_path / "reference", applied, finalize)
    for index in range(count):
        home = make_home(tmp_path / f"crash-{index}")
        final = converted(home)
        applied(home)
        with pytest.raises(Crash), boundaries(index, Crash()):
            finalize(home, confirmed=True)
        if journal_state(home) == "finalizing":
            snapshot = tree(home)
            assert codes(rollback(home, confirmed=True)) == ["config-migration-rollback-unavailable"]
            assert tree(home) == snapshot
        assert finalize(home, confirmed=True)["result"] in {"finalized", "discarded", "nothing-to-finalize"}
        assert tree(home) == final, index


def test_os_error_at_every_apply_boundary_recovers_in_process(tmp_path: Path) -> None:
    count = trace(tmp_path / "reference", lambda home: None, apply)
    outcomes = set()
    for index in range(count):
        home = make_home(tmp_path / f"error-{index}")
        before = tree(home)
        with boundaries(index, OSError(errno.EIO, "injected")):
            result = apply(home, confirmed=True)
        outcomes.add(result["result"])
        assert result["result"] in {"failed", "refused", "failed-rolled-back"}, (index, result)
        assert not result["operation_directory_retained"] and result["journal_state"] is None
        assert tree(home) == before, index
    assert {"failed", "failed-rolled-back"} <= outcomes


@pytest.mark.parametrize("state", ["dual-link", "partial", "both-missing", "restore-scratch"])
def test_partial_states_are_classified_and_restored(tmp_path: Path, state: str) -> None:
    home = make_home(tmp_path)
    before = tree(home)
    applied(home)
    if state == "dual-link":
        os.link(home / "00-project.cloe.toml", home / "00-project.rp.toml")
    elif state == "partial":
        os.link(home / "90-machine.local.cloe.toml", home / "90-machine.rpl.toml")
        (home / "90-machine.local.cloe.toml").unlink()
    else:
        (home / "00-project.cloe.toml").unlink()
        if state == "restore-scratch":
            (home / OPERATION_DIRECTORY / "restore-0000.tmp").write_bytes(b"partial")
    assert rollback(home, dry_run=True)["result"] == "would-roll-back"
    result = rollback(home, confirmed=True)
    assert result["result"] == "rolled-back" and result["journal_state"] is None
    assert tree(home) == before


def _edit(home: Path, kind: str) -> None:
    if kind == "edited":
        (home / "00-project.cloe.toml").write_text(SERVER.replace("127.0.0.1", "127.0.0.2"))
    elif kind == "replaced":
        (home / "00-project.cloe.toml").unlink()
        (home / "00-project.cloe.toml").write_text(SERVER)
    elif kind == "foreign":
        (home / "zz.cloe.toml").write_text(OVERLAY)
    elif kind == "alias":
        (home / "00-PROJECT.RP.TOML").write_text("user data")
    elif kind == "chmod":
        (home / "00-project.cloe.toml").chmod(0o600)


@pytest.mark.parametrize("kind", ["edited", "replaced", "foreign", "alias", "chmod"])
def test_edits_after_apply_refuse_every_command_and_retain_evidence(tmp_path: Path, kind: str) -> None:
    home = make_home(tmp_path)
    applied(home)
    _edit(home, kind)
    snapshot = tree(home)
    for operation, kwargs in ((rollback, {"dry_run": True}), (rollback, {"confirmed": True}), (finalize, {"confirmed": True})):
        result = operation(home, **kwargs)
        assert result["result"] == "refused" and codes(result) == ["config-migration-drift"], (operation, result)
        assert result["journal_state"] == "applied"
    assert codes(apply(home, confirmed=True))[0] == "config-migration-recovery-required"
    assert tree(home) == snapshot


def test_edit_after_interrupted_publish_refuses_without_clobbering(tmp_path: Path) -> None:
    reference = make_home(tmp_path / "reference")
    with boundaries() as calls:
        applied(reference)
    publish_link = calls.index("link", calls.index("link") + 1)  # the probe link precedes publication
    assert calls[publish_link + 1:publish_link + 3] == ["fsync", "unlink"]
    home = make_home(tmp_path / "home")
    with pytest.raises(Crash), boundaries(publish_link + 2, Crash()):
        apply(home, confirmed=True)
    assert journal_state(home) == "publishing" and (home / "00-project.cloe.toml").stat().st_nlink == 2
    (home / "00-project.rp.toml").write_text(SERVER + "# user edit\n")
    snapshot = tree(home)
    assert codes(rollback(home, confirmed=True)) == ["config-migration-drift"]
    assert tree(home) == snapshot


@pytest.mark.parametrize("change", ["target", "source", "unrelated"])
def test_revalidation_race_refuses_stale_and_discards_owned_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    home = make_home(tmp_path)
    original = config_migration.write_journal

    def racing(target: Home, journal: dict[str, Any], state: str | None = None) -> None:
        original(target, journal, state)
        if state == "prepared":
            if change == "target":
                (home / "00-project.cloe.toml").write_text("racer")
            elif change == "source":
                (home / "00-project.rp.toml").write_text(SERVER.replace("127.0.0.1", "127.0.0.9"))
            else:
                (home / "other.txt").write_text("racer")

    monkeypatch.setattr(config_migration, "write_journal", racing)
    result = apply(home, confirmed=True)
    assert result["result"] == "refused" and codes(result) == ["config-migration-stale"]
    assert not (home / OPERATION_DIRECTORY).exists()
    assert (home / "00-project.rp.toml").exists() and (home / "90-machine.rpl.toml").read_text() == OVERLAY


def test_post_link_identity_mismatch_never_unlinks_the_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = make_home(tmp_path)

    def wrong_link(self: Home, source: str, target: str, *, source_in_op: bool = False) -> None:
        (home / target).write_bytes((home / source).read_bytes())

    monkeypatch.setattr(Home, "link", wrong_link)
    result = apply(home, confirmed=True)
    assert result["result"] == "failed-recovery-required" and result["operation_directory_retained"]
    assert codes(result)[0] == "config-migration-drift" and result["journal_state"] == "publishing"
    assert (home / "00-project.rp.toml").read_text() == SERVER
    assert (home / "00-project.cloe.toml").stat().st_ino != (home / "00-project.rp.toml").stat().st_ino


def test_unsupported_hard_links_refuse_before_any_configuration_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = make_home(tmp_path)
    before = tree(home)

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(errno.EPERM, "links unsupported")

    monkeypatch.setattr(os, "link", refuse)
    result = apply(home, confirmed=True)
    assert result["result"] == "refused" and codes(result) == ["config-migration-link-unsupported"]
    assert tree(home) == before


def test_competing_lock_holder_makes_every_command_busy(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    applied(home)
    snapshot = tree(home)
    holder = os.open(home / OPERATION_DIRECTORY / "lock", os.O_RDONLY)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for operation, kwargs in ((rollback, {"confirmed": True}), (rollback, {"dry_run": True}),
                                  (finalize, {"confirmed": True}), (apply, {"confirmed": True})):
            assert codes(operation(home, **kwargs)) == ["config-migration-busy"]
        assert tree(home) == snapshot
    finally:
        os.close(holder)
    assert finalize(home, confirmed=True)["result"] == "finalized"


@pytest.mark.parametrize("tamper", ["mapping", "extra-key", "home", "oversize", "not-json"])
def test_tampered_journal_is_refused_without_change(tmp_path: Path, tamper: str) -> None:
    home = make_home(tmp_path)
    applied(home)
    path = home / OPERATION_DIRECTORY / "journal.json"
    journal = json.loads(path.read_text())
    if tamper == "mapping":
        journal["entries"][0]["target"] = "other.cloe.toml"
    elif tamper == "extra-key":
        journal["value"] = "x"
    elif tamper == "home":
        journal["home"]["ino"] += 1
    text = json.dumps(journal) + (" " * (300 << 10) if tamper == "oversize" else "")
    path.write_text("{" if tamper == "not-json" else text)
    snapshot = tree(home)
    for operation in (rollback, finalize):
        assert codes(operation(home, confirmed=True)) == ["config-migration-journal-invalid"]
    assert tree(home) == snapshot


@pytest.mark.parametrize("state", ["applied", "both-missing"])
def test_device_number_change_after_reboot_keeps_recovery_available(tmp_path: Path, state: str) -> None:
    home = make_home(tmp_path)
    before = tree(home)
    applied(home)
    if state == "both-missing":
        (home / "00-project.cloe.toml").unlink()
    path = home / OPERATION_DIRECTORY / "journal.json"
    journal = json.loads(path.read_text())
    journal["home"]["dev"] += 1
    for entry in journal["entries"]:
        entry["dev"] += 1
    path.write_text(json.dumps(journal))
    if state == "applied":
        assert apply(home, dry_run=True)["result"] == "already-applied"
        assert finalize(home, dry_run=True)["result"] == "would-finalize"
    assert rollback(home, confirmed=True)["result"] == "rolled-back"
    assert tree(home) == before


@pytest.mark.parametrize("residue", ["unknown", "orphan-backup", "symlink", "broad-mode", "lock-only"])
def test_operation_directory_residue_rules(tmp_path: Path, residue: str) -> None:
    home = make_home(tmp_path)
    operation = home / OPERATION_DIRECTORY
    if residue == "symlink":
        (tmp_path / "elsewhere").mkdir()
        operation.symlink_to(tmp_path / "elsewhere")
    else:
        operation.mkdir(mode=0o700)
        operation.chmod(0o755 if residue == "broad-mode" else 0o700)
        name = {"unknown": "notes.txt", "orphan-backup": "backup-0000.bin"}.get(residue, "lock")
        (operation / name).write_text("")
    snapshot = tree(home)
    assert codes(apply(home, confirmed=True)) in (["config-migration-recovery-required"], ["config-migration-residue-unsafe"])
    if residue == "lock-only":
        assert finalize(home, dry_run=True)["result"] == "would-discard"
        assert rollback(home, confirmed=True)["result"] == "discarded" and not operation.exists()
        return
    for command in (rollback, finalize):
        assert codes(command(home, confirmed=True)) == ["config-migration-residue-unsafe"]
    assert tree(home) == snapshot


def test_lost_directory_removal_is_reported_and_later_discarded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = make_home(tmp_path)
    before = tree(home)
    applied(home)
    monkeypatch.setattr(Home, "remove_operation_directory", lambda self: False)
    result = rollback(home, confirmed=True)
    assert result["result"] == "rolled-back" and result["operation_directory_retained"]
    monkeypatch.undo()
    assert apply(home, dry_run=True)["refusals"][0]["code"] == "config-migration-recovery-required"
    assert rollback(home, confirmed=True)["result"] == "discarded"
    assert tree(home) == before and rollback(home, confirmed=True)["result"] == "nothing-to-recover"


def test_repeated_apply_reports_already_applied_until_finalized_and_after_rollback_reapplies(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    applied(home)
    snapshot = tree(home)
    repeated = apply(home, confirmed=True)
    assert repeated["result"] == "already-applied" and repeated["writes_performed"] == 0 and repeated["finalize_pending"]
    assert tree(home) == snapshot
    assert rollback(home, confirmed=True)["result"] == "rolled-back"
    applied(home)
    assert finalize(home, dry_run=True)["result"] == "would-finalize"
    final = finalize(home, confirmed=True)
    assert final["result"] == "finalized" and not final["rollback_available"]
    assert apply(home, confirmed=True)["result"] == "already-converted"
    assert sorted(p.name for p in home.iterdir()) == sorted(NAMES.values())
