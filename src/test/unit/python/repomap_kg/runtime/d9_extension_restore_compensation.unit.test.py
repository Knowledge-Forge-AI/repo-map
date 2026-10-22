"""Unit tests for D9-B compensation error preservation, ledger custody and release ordering."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from repomap_kg.runtime import _extension_restore_compensation as compensation_mod
from repomap_kg.runtime import _extension_restore_lifecycle as lifecycle_mod
from repomap_kg.runtime._extension_restore_custody import (
    DatabaseCreationIntent,
    RestoreLifecycleAuthority,
)
from repomap_kg.runtime._extension_restore_exec import (
    ExecOutcome,
    active_exec_custody,
    bound_exec_custody,
)
from repomap_kg.runtime._extension_restore_lifecycle import (
    cleanup_extension_restore_intents,
    execute_extension_v2_restore_set,
)
from repomap_kg.runtime._extension_restore_policy import TrustedOptionalCapabilityContract
from repomap_kg.runtime._extension_restore_steps import verify_restored_database
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import (
    LocalRuntimeDiagnostic,
    build_local_runtime_plan,
    setup_local_runtime,
)
from repomap_kg.runtime.maintenance import held_maintenance_custody_for


def _plan(tmp_path: Path) -> Any:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    setup_local_runtime(home)
    (home / "runtime").chmod(0o700)
    plan = build_local_runtime_plan(home)
    plan.env_file.chmod(0o600)
    return plan


def _primary() -> LocalDbBackupError:
    return LocalDbBackupError(
        (LocalRuntimeDiagnostic("error", "local-db-command-failed", "pg_restore", "boom"),)
    )


class _HeldAuthority:
    """Every named target is held and verified; dropped OIDs are reported absent."""

    def __init__(self, names: set[str]) -> None:
        self._names = names

    def held(self, database: str) -> bool:
        return database in self._names

    def verify(self, intent: DatabaseCreationIntent, *, finalized: bool = False) -> bool:
        return intent.database in self._names

    def oid_absent(self, oid: int) -> bool:
        return True


def test_secondary_interrupt_stops_compensation_and_preserves_primary(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    ledger = plan.runtime_dir / ".restore-intents-int" / "intents.json"
    intents = [
        DatabaseCreationIntent("g_a", "inv-0", "created", 16384, "sys"),
        DatabaseCreationIntent("g_b", "inv-1", "created", 16385, "sys"),
    ]
    calls: list[list[str]] = []

    def interrupted_drop(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(cmd)
        raise KeyboardInterrupt("second ctrl-c")

    primary = _primary()
    authority: Any = _HeldAuthority({"g_a", "g_b"})
    with pytest.raises(LocalDbBackupError) as exc:
        cleanup_extension_restore_intents(
            plan,
            authority,
            intents,
            interrupted_drop,
            primary_error=primary,
            coordinated=True,
            ledger_path=ledger,
        )
    assert exc.value.__cause__ is primary, "the initiating error remains the cause"
    assert len(calls) == 1, f"compensation stops after a secondary interruption: {calls!r}"
    diags = [(d.code, d.path) for d in exc.value.diagnostics]
    assert diags == [
        ("local-db-command-failed", "pg_restore"),
        ("failed-target-cleanup-failed", "g_b"),
        ("restore-target-ownership-unknown", "g_a"),
        ("coordinated-restore-cleanup-failed", "coordinated restore"),
    ], diags
    assert "KeyboardInterrupt" in exc.value.diagnostics[1].message
    recorded = json.loads(ledger.read_text(encoding="utf-8"))
    assert [i["state"] for i in recorded] == ["created", "created"], "both targets are retained"


def test_ledger_update_failure_is_reported_without_replacing_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(tmp_path)
    ledger = plan.runtime_dir / ".restore-intents-x" / "intents.json"
    retained = [DatabaseCreationIntent("g_lost", "inv-0", "outcome_unknown")]

    def interrupted_persist(path: Path, intents: Any) -> None:
        raise KeyboardInterrupt("ledger write interrupted")

    monkeypatch.setattr(compensation_mod, "persist_intent_ledger", interrupted_persist)
    primary = _primary()
    nothing_held: Any = _HeldAuthority(set())
    with pytest.raises(LocalDbBackupError) as exc:
        cleanup_extension_restore_intents(
            plan,
            nothing_held,
            retained,
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, b"", b""),
            primary_error=primary,
            coordinated=False,
            ledger_path=ledger,
        )
    codes = [d.code for d in exc.value.diagnostics]
    assert exc.value.__cause__ is primary and codes == [
        "local-db-command-failed",
        "restore-target-ownership-unknown",
        "restore-intent-ledger-failed",
        "failed-target-cleanup-failed",
    ], codes


def test_unknown_outcome_first_raised_by_a_drop_is_refreshed_before_later_drops_and_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(tmp_path)
    ledger = plan.runtime_dir / ".restore-intents-drop" / "intents.json"
    intents = [
        DatabaseCreationIntent("g_a", "inv-0", "created", 16384, "sys"),
        DatabaseCreationIntent("g_b", "inv-1", "created", 16385, "sys"),
    ]
    drops: list[str] = []

    def drop_with_unknown_outcome(plan: Any, command: Any, runner: Any, *, field: str, **kwargs: Any) -> bytes:
        drops.append(next(tok for tok in command if "DROP DATABASE" in tok))
        custody = active_exec_custody()
        assert custody is not None
        custody.outcomes.append(ExecOutcome("database drop", "d" * 32, "retired", "mismatch", "none", "retained"))
        raise LocalDbBackupError((LocalRuntimeDiagnostic("error", "restore-exec-outcome-unknown", field, "not settled"),))

    monkeypatch.setattr(compensation_mod, "run_bounded_ext_command", drop_with_unknown_outcome)
    primary = _primary()
    authority: Any = _HeldAuthority({"g_a", "g_b"})
    with bound_exec_custody("c" * 64), pytest.raises(LocalDbBackupError) as exc:
        cleanup_extension_restore_intents(
            plan, authority, intents, subprocess.run, primary_error=primary, coordinated=False, ledger_path=ledger,
        )
    assert drops == ['DROP DATABASE "g_b" WITH (FORCE);'], f"no further drop after an outcome first became unknown: {drops!r}"
    assert exc.value.__cause__ is primary
    assert [(d.code, d.path) for d in exc.value.diagnostics] == [
        ("local-db-command-failed", "pg_restore"), ("failed-target-cleanup-failed", "g_b"),
        ("restore-exec-outcome-unknown", "g_a"), ("failed-target-cleanup-failed", "g_a"),
    ]
    recorded = json.loads(ledger.read_text(encoding="utf-8"))
    assert [i["state"] for i in recorded] == ["created", "created"]
    assert all([(r["label"], r["remote"]) for r in i["exec_unknown"]] == [("database drop", "mismatch")] for i in recorded)


@pytest.mark.parametrize("failure", [KeyboardInterrupt("verify interrupted"), RuntimeError("identity query failed")])
def test_held_identity_verification_failure_is_guarded_and_keeps_the_primary(tmp_path: Path, failure: BaseException) -> None:
    plan = _plan(tmp_path)
    ledger = plan.runtime_dir / ".restore-intents-verify" / "intents.json"
    intents = [
        DatabaseCreationIntent("g_a", "inv-0", "created", 16384, "sys"),
        DatabaseCreationIntent("g_b", "inv-1", "created", 16385, "sys"),
    ]
    verified: list[str] = []

    class _FailingVerify(_HeldAuthority):
        def verify(self, intent: DatabaseCreationIntent, *, finalized: bool = False) -> bool:
            verified.append(intent.database)
            raise failure

    drops: list[list[str]] = []

    def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        drops.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    primary = _primary()
    authority: Any = _FailingVerify({"g_a", "g_b"})
    with pytest.raises(LocalDbBackupError) as exc:
        cleanup_extension_restore_intents(
            plan, authority, intents, runner, primary_error=primary, coordinated=False, ledger_path=ledger,
        )
    assert exc.value.__cause__ is primary and drops == [], "an unverified target is never dropped"
    interrupted = isinstance(failure, KeyboardInterrupt)
    assert verified == (["g_b"] if interrupted else ["g_b", "g_a"]), "an interruption stops later ownership checks"
    diags = [(d.code, d.path) for d in exc.value.diagnostics]
    assert diags[0] == ("local-db-command-failed", "pg_restore") and diags[-1] == ("failed-target-cleanup-failed", "g_a")
    assert ("restore-target-ownership-unknown", "g_b") in diags and ("restore-target-ownership-unknown", "g_a") in diags
    assert type(failure).__name__ in exc.value.diagnostics[1].message
    assert [i["state"] for i in json.loads(ledger.read_text(encoding="utf-8"))] == ["created", "created"]


class _LockConn:
    """Minimal connection double: accepts the canonical lock and answers identity queries."""

    def __init__(self, oid: int) -> None:
        self.oid = oid

    @contextmanager
    def cursor(self) -> Iterator[Any]:
        yield SimpleNamespace(execute=lambda sql, params=None: None)

    def execute(self, statement: Any, params: Any = None) -> Any:
        return SimpleNamespace(fetchone=lambda: (self.oid, "", "7001", True))

    def close(self) -> None:
        return None


_NS = "runtime-endpoint:test"


class _CheckingAuthority(RestoreLifecycleAuthority):
    """Records, after every release, whether each still-held target keeps its custody binding."""

    observed: list[tuple[str, bool]]

    def release(self, database: str) -> None:
        super().release(database)
        for remaining in ("g1", "g2"):
            if self.held(remaining):
                bound = held_maintenance_custody_for(remaining, authority_namespace=_NS)
                self.observed.append((remaining, bound is not None))


def test_release_keeps_each_remaining_target_custody_bound(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    oids = iter(range(16400, 16410))
    authority = _CheckingAuthority(plan, lambda db: _LockConn(next(oids)), namespace=_NS)
    authority.observed = []
    with authority:
        for name in ("g1", "g2"):
            authority.hold_target(
                DatabaseCreationIntent(name, f"tok-{name}", expected_system_identifier="7001"),
                control=False,
            )
        assert held_maintenance_custody_for("g2", authority_namespace=_NS) is not None
    assert authority.observed == [("g1", True)], (
        f"a held target lost custody: {authority.observed!r}"
    )
    assert held_maintenance_custody_for("g1", authority_namespace=_NS) is None
    assert held_maintenance_custody_for("g2", authority_namespace=_NS) is None


def test_initial_ledger_failure_leaves_no_blocking_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(tmp_path)

    @contextmanager
    def authority_window(_plan: Any) -> Iterator[Any]:
        yield SimpleNamespace()

    def failing_persist(path: Path, intents: Any) -> None:
        path.parent.mkdir(mode=0o700)
        raise OSError("disk full")

    monkeypatch.setattr(lifecycle_mod, "canonical_restore_authority", authority_window)
    monkeypatch.setattr(lifecycle_mod, "persist_intent_ledger", failing_persist)
    set_pre: Any = SimpleNamespace(
        target_system_identifier="7001",
        container=SimpleNamespace(container_id="c"),
        engine_image_id="sha256:" + "0" * 64,
    )
    with pytest.raises(OSError, match="disk full"):
        execute_extension_v2_restore_set(
            plan, set_pre, restore_order=["g1"], command_runner=subprocess.run, coordinated=False
        )
    leftovers = [
        p.name for p in plan.runtime_dir.iterdir() if p.name.startswith(".restore-intents-")
    ]
    assert leftovers == [], f"an unused ledger directory would block later restores: {leftovers!r}"


def test_optional_grants_require_held_custody_first(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    opt = TrustedOptionalCapabilityContract(
        capability_id="cap",
        experimental_context="adr0077-disposable-pgvector",
        extension_schema="repomap_vector",
        enrichment_reader_role="cap_reader",
        enrichment_writer_role="cap_writer",
    )
    role = {
        "rolcanlogin": True,
        **dict.fromkeys(
            ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls"), False
        ),
        "rolinherit": False,
        **dict.fromkeys(("owned_objects_count", "member_of_count", "members_count"), 0),
    }
    roles = [{"rolname": name, **role} for name in ("cap_reader", "cap_writer")]
    commands: list[list[str]] = []

    def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, json.dumps(roles).encode(), b"")

    class _LostCustody:
        def verify(self, intent: DatabaseCreationIntent, *, finalized: bool = False) -> bool:
            return False

    db_pre: Any = SimpleNamespace(
        database="g1",
        database_role="graph",
        database_catalog={"non_system_schemas": []},
        ordered_extensions=[({}, SimpleNamespace(optional_capability=opt))],
    )
    intent = DatabaseCreationIntent("g1", "tok", "created", 16400, "7001")
    lost: Any = _LostCustody()
    unused_set: Any = SimpleNamespace()
    with pytest.raises(LocalDbBackupError) as exc:
        verify_restored_database(plan, lost, intent, unused_set, db_pre, runner)
    assert exc.value.diagnostics[0].code == "restore-target-ownership-mismatch"
    assert len(commands) == 1, f"only the read-only role observation may run: {commands!r}"
