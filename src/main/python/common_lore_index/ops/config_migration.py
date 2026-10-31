"""Explicit CLOE configuration filename apply, rollback and finalize (ADR 0114).

Every command acts only on an explicitly supplied owner-private home, through
descriptor-relative no-follow operations, and returns a public-safe result
mapping: stable codes and basenames, never values, hashes, inodes or paths.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import os
import secrets
import stat
from typing import Any

from common_lore_index.ops.config_layout import classify_config_filename, plan_cloe_config_filenames, portable_config_name
from common_lore_index.ops.config_migration_fs import (
    MAX_CONFIG_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, OPERATION_DIRECTORY,
    Home, MigrationRefusal, backup_name, ident, owned_regular, platform_supported, snapshot, valid_name,
)
from common_lore_index.ops.config_migration_journal import build_journal, effective_sha256, write_journal
from common_lore_index.ops.config_migration_recovery import (
    ROLLBACK_STATES, load_operation, preview_rollback, prove_sources, prove_targets, roll_back, teardown,
)

RESULT_SCHEMA = "cloe-config-migration-result-v1"
SUCCESS_RESULTS = frozenset((
    "would-apply", "applied", "already-converted", "already-applied",
    "would-roll-back", "rolled-back", "would-discard", "discarded", "nothing-to-recover",
    "would-finalize", "finalized", "nothing-to-finalize",
))


@dataclass(frozen=True)
class _Source:
    name: str
    data: bytes
    info: os.stat_result

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def mode(self) -> int:
        return stat.S_IMODE(self.info.st_mode)


class _Outcome:
    """Mutable result fields assembled while a command runs."""

    def __init__(self, operation: str, dry_run: bool) -> None:
        self.operation, self.dry_run = operation, dry_run
        self.changes: list[dict[str, str]] = []
        self.source_order: list[str] = []
        self.proposed_order: list[str] = []
        self.journal_state: str | None = None
        self.retained = False

    def describe(self, mapping: dict[str, Any]) -> None:
        self.changes = [{key: item[key] for key in ("source", "target", "layer")} for item in mapping["changes"]]
        self.source_order = list(mapping["source_order"])
        self.proposed_order = list(mapping["proposed_order"])

    def describe_journal(self, journal: dict[str, Any] | None) -> None:
        if journal is not None:
            self.describe({"changes": journal["entries"], **journal})
        self.journal_state = None if journal is None else journal["state"]

    def result(self, result: str, writes: int, refusals: list[dict[str, str]] | None = None) -> dict[str, Any]:
        state = self.journal_state
        return {
            "schema": RESULT_SCHEMA, "operation": self.operation, "result": result, "dry_run": self.dry_run,
            "writes_performed": writes, "changes": self.changes, "source_order": self.source_order,
            "proposed_order": self.proposed_order, "journal_state": state, "refusals": refusals or [],
            "rollback_available": state == "applied", "finalize_pending": state == "applied",
            "operation_directory_retained": self.retained,
        }


class _Recovered(MigrationRefusal):
    def __init__(self, result: str, refusals: list[dict[str, str]]) -> None:
        super().__init__(refusals[0]["code"], refusals[0]["file"], more=tuple(refusals[1:]))
        self.result = result


def _run(
    operation: str, home: str | os.PathLike[str] | None, confirmed: bool, dry_run: bool,
    action: Callable[[Home, _Outcome], str],
) -> dict[str, Any]:
    outcome = _Outcome(operation, dry_run)
    if home is None or not os.fspath(home):
        return outcome.result("refused", 0, [{"code": "repo-map-home-required", "file": ""}])
    if confirmed and dry_run:
        return outcome.result("refused", 0, [{"code": "confirmation-conflict", "file": ""}])
    if not confirmed and not dry_run:
        return outcome.result("refused", 0, [{"code": "confirmation-required", "file": ""}])
    if not platform_supported():
        return outcome.result("refused", 0, [{"code": "config-migration-platform-unsupported", "file": ""}])
    try:
        opened = Home.open(home)
    except MigrationRefusal as refusal:
        return outcome.result("refused", 0, refusal.refusals)
    try:
        return outcome.result(action(opened, outcome), opened.writes)
    except _Recovered as recovered:
        return outcome.result(recovered.result, opened.writes, recovered.refusals)
    except MigrationRefusal as refusal:
        return outcome.result("refused", opened.writes, refusal.refusals)
    except OSError:
        return outcome.result("failed", opened.writes, [{"code": "config-migration-io-error", "file": ""}])
    finally:
        opened.close()


def apply_cloe_config_migration(
    home: str | os.PathLike[str] | None, *, confirmed: bool = False, dry_run: bool = False,
) -> dict[str, Any]:
    """Convert one explicit legacy home's configuration filenames to CLOE, recoverably."""
    return _run("apply", home, confirmed, dry_run, _apply)


def rollback_cloe_config_migration(
    home: str | os.PathLike[str] | None, *, confirmed: bool = False, dry_run: bool = False,
) -> dict[str, Any]:
    """Recover an interrupted apply, or revert an applied migration before finalize."""
    return _run("rollback", home, confirmed, dry_run, _rollback)


def finalize_cloe_config_migration(
    home: str | os.PathLike[str] | None, *, confirmed: bool = False, dry_run: bool = False,
) -> dict[str, Any]:
    """Discard proved retained recovery data for an applied migration; rollback ends here."""
    return _run("finalize", home, confirmed, dry_run, _finalize)


def _bind_operation(
    home: Home, outcome: _Outcome, *, exclusive: bool,
) -> tuple[dict[str, Any] | None, int | None]:
    """Bind the existing operation directory, lock it (or only probe) and load its journal."""
    home.open_operation_directory()
    load_operation(home)  # refuse unowned residue before the lock can be created
    lock = None
    if exclusive:
        lock = home.acquire_lock()
    else:
        home.probe_lock()
    try:
        journal = load_operation(home)
    except BaseException:
        if lock is not None:
            os.close(lock)
        raise
    outcome.describe_journal(journal)
    return journal, lock


def _preflight(home: Home) -> tuple[list[str], list[_Source], dict[str, Any], str] | None:
    """Descriptor-read the legacy sources; ``None`` means the home is already CLOE."""
    names = home.names()
    portable_operation = portable_config_name(OPERATION_DIRECTORY)
    for name in names:
        if name != OPERATION_DIRECTORY and portable_config_name(name) == portable_operation:
            raise MigrationRefusal("config-migration-alias-collision", name)
    classified = [(name, kind) for name in names if (kind := classify_config_filename(name)) is not None]
    if not classified:
        raise MigrationRefusal("config-home-empty")
    families = {kind[0] for _, kind in classified}
    if len(families) > 1:
        raise MigrationRefusal("config-home-mixed-format")
    if families == {"cloe"}:
        return None
    if len(classified) > MAX_CONFIG_FILES:
        raise MigrationRefusal("config-migration-limit-exceeded")
    ordered = [name for name, _ in sorted(classified, key=lambda item: (item[1][1], item[0]))]
    sources: list[_Source] = []
    total = 0
    for name in ordered:
        if not valid_name(name):
            raise MigrationRefusal("config-filename-unsupported", name)
        info = home.lstat(name)
        if not owned_regular(info):
            raise MigrationRefusal("config-entry-unsafe", name)
        if info is not None and (info.st_size > MAX_FILE_BYTES or total + info.st_size > MAX_TOTAL_BYTES):
            raise MigrationRefusal("config-migration-limit-exceeded", name)
        data, read = home.read(name, MAX_FILE_BYTES, "config-entry-unsafe")
        if not owned_regular(read):
            raise MigrationRefusal("config-entry-unsafe", name)
        sources.append(_Source(name, data, read))
        total += len(data)
    digest = effective_sha256([(source.name, source.data) for source in sources])
    plan = plan_cloe_config_filenames(ordered, occupied_names=names)
    for change in plan["changes"]:
        if not valid_name(change["target"]):
            raise MigrationRefusal("config-filename-unsupported", change["source"])
    return names, sources, plan, digest


def _inspect_existing(home: Home, outcome: _Outcome) -> str:
    """Apply never resumes or repeats over an operation directory; it only reports it."""
    journal, _ = _bind_operation(home, outcome, exclusive=False)
    if journal is None or journal["state"] != "applied":
        raise MigrationRefusal("config-migration-recovery-required")
    try:
        prove_targets(home, journal)
    except MigrationRefusal as refusal:
        raise MigrationRefusal("config-migration-recovery-required", more=tuple(refusal.refusals)) from None
    return "already-applied"


def _apply(home: Home, outcome: _Outcome) -> str:
    if OPERATION_DIRECTORY in home.names():
        return _inspect_existing(home, outcome)
    prepared = _preflight(home)
    if prepared is None:
        return "already-converted"
    names, sources, plan, digest = prepared
    outcome.describe(plan)
    if plan["refusals"]:
        raise MigrationRefusal(plan["refusals"][0]["code"], plan["refusals"][0]["file"], more=tuple(plan["refusals"][1:]))
    if outcome.dry_run:
        return "would-apply"
    return _publish(home, outcome, names, sources, plan, digest)


def _revalidate(home: Home, names: list[str], sources: list[_Source]) -> None:
    if set(home.names()) != set(names) | {OPERATION_DIRECTORY}:
        raise MigrationRefusal("config-migration-stale")
    for source in sources:
        info = home.lstat(source.name)
        if info is None or snapshot(info) != snapshot(source.info):
            raise MigrationRefusal("config-migration-stale", source.name)
        if home.read(source.name, MAX_FILE_BYTES, "config-migration-stale")[0] != source.data:
            raise MigrationRefusal("config-migration-stale", source.name)


def _link_entry(home: Home, source: _Source, target: str) -> None:
    current = home.lstat(source.name)
    if current is None or snapshot(current) != snapshot(source.info):
        raise MigrationRefusal("config-migration-stale", source.name)
    home.link(source.name, target)
    linked = home.lstat(target)
    if linked is None or ident(linked) != ident(source.info) or linked.st_nlink != 2:
        raise MigrationRefusal("config-migration-drift", target)
    home.sync()
    current = home.lstat(source.name)
    if current is None or ident(current) != ident(source.info) or current.st_nlink != 2:
        raise MigrationRefusal("config-migration-drift", source.name)
    home.unlink(source.name)
    home.sync()


def _publish(
    home: Home, outcome: _Outcome, names: list[str], sources: list[_Source], plan: dict[str, Any], digest: str,
) -> str:
    lock: int | None = None
    journal: dict[str, Any] | None = None
    publishing = False
    try:
        home.mkdir_operation_directory()
        home.sync()
        lock = home.acquire_lock()
        home.probe_links()
        journal = build_journal(home, secrets.token_hex(16), plan, sources, digest)
        write_journal(home, journal)
        for index, source in enumerate(sources):
            home.create(backup_name(index), source.data)
            if home.read(backup_name(index), MAX_FILE_BYTES, "config-migration-io-error", in_op=True)[0] != source.data:
                raise MigrationRefusal("config-migration-io-error", backup_name(index))
        home.sync(in_op=True)
        write_journal(home, journal, "prepared")
        _revalidate(home, names, sources)
        publishing = True
        write_journal(home, journal, "publishing")
        for source, change in zip(sources, plan["changes"]):
            _link_entry(home, source, change["target"])
        prove_targets(home, journal)
        write_journal(home, journal, "applied")
        outcome.journal_state = "applied"
        return "applied"
    except Exception as error:
        refusals = error.refusals if isinstance(error, MigrationRefusal) else [
            {"code": "config-migration-io-error", "file": ""}
        ]
        result = _recover(home, outcome, journal, lock, publishing)
        if result == "refused" and not isinstance(error, MigrationRefusal):
            result = "failed"
        raise _Recovered(result, refusals) from None
    finally:
        if lock is not None:
            os.close(lock)


def _recover(home: Home, outcome: _Outcome, journal: dict[str, Any] | None, lock: int | None, publishing: bool) -> str:
    """Discard pre-publish work, or roll back in-process after names may have changed."""
    if lock is None:
        # Only an empty directory this call created and bound can be removed without the lock.
        removed = home.op is not None and home.remove_operation_directory()
        outcome.retained = not removed and OPERATION_DIRECTORY in home.names()
        return "refused"
    try:
        if publishing and journal is not None:
            roll_back(home, journal)
        outcome.retained = teardown(home, journal)
        outcome.journal_state = None
    except Exception:
        outcome.journal_state = None if journal is None else journal["state"]
        outcome.retained = True
        return "failed-recovery-required" if publishing else "failed"
    return "failed-rolled-back" if publishing else "refused"


def _rollback(home: Home, outcome: _Outcome) -> str:
    if OPERATION_DIRECTORY not in home.names():
        return "nothing-to-recover"
    journal, lock = _bind_operation(home, outcome, exclusive=not outcome.dry_run)
    try:
        state = None if journal is None else journal["state"]
        if state == "finalizing":
            raise MigrationRefusal("config-migration-rollback-unavailable")
        if journal is None or state in ("preparing", "prepared"):
            if outcome.dry_run:
                return "would-discard"
            outcome.retained = teardown(home, journal)
            outcome.journal_state = None
            return "discarded"
        if state == "rolled-back":
            prove_sources(home, journal)
        elif state in ROLLBACK_STATES:
            preview_rollback(home, journal)
            if not outcome.dry_run:
                roll_back(home, journal)
        if outcome.dry_run:
            return "would-roll-back"
        outcome.retained = teardown(home, journal)
        outcome.journal_state = None
        return "rolled-back"
    finally:
        if lock is not None:
            os.close(lock)


def _finalize(home: Home, outcome: _Outcome) -> str:
    if OPERATION_DIRECTORY not in home.names():
        return "nothing-to-finalize"
    journal, lock = _bind_operation(home, outcome, exclusive=not outcome.dry_run)
    try:
        if journal is None:
            if outcome.dry_run:
                return "would-discard"
            outcome.retained = teardown(home, None)
            return "discarded"
        if journal["state"] not in ("applied", "finalizing"):
            raise MigrationRefusal("config-migration-recovery-required")
        prove_targets(home, journal)
        if outcome.dry_run:
            return "would-finalize"
        if journal["state"] == "applied":
            write_journal(home, journal, "finalizing")
        outcome.retained = teardown(home, journal)
        outcome.journal_state = None
        return "finalized"
    finally:
        if lock is not None:
            os.close(lock)
