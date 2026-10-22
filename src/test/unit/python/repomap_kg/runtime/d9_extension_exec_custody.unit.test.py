"""Unit tests for D9-B container-side command custody, settlement and outcome retention.

These are orchestration and parser proofs with an injected bounded runner. The real
container process, session and control-path boundaries are owned by
``d9_extension_exec_custody.int.test.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, cast

import pytest

from repomap_kg.runtime import _extension_restore_exec as exec_mod
from repomap_kg.runtime import _extension_restore_preflight as preflight_mod
from repomap_kg.runtime._backup_process import BoundedProcessError, ProcessRetirement
from repomap_kg.runtime._backup_provenance import DEFAULT_TOC_TIMEOUT_SECONDS, MAX_TOC_OUTPUT_BYTES, provenance_error
from repomap_kg.runtime._extension_restore_compensation import cleanup_extension_restore_intents
from repomap_kg.runtime._extension_restore_custody import DatabaseCreationIntent, retain_unknown_commands
from repomap_kg.runtime._extension_restore_exec import ExecOutcome, bound_exec_custody
from repomap_kg.runtime._extension_restore_exec_control import (
    SETTLE_PROCESS_SH,
    SUPERVISOR_SH,
    parse_process_settlement,
    parse_session_settlement,
    split_container_exec,
    supervised_command,
)
from repomap_kg.runtime._extension_restore_lifecycle import _reconcile_failed_create
from repomap_kg.runtime._extension_restore_native import run_bounded_ext_command
from repomap_kg.runtime._extension_restore_preflight import _list_archive_toc
from repomap_kg.runtime.backup_commands import planned_psql_command, planned_psql_stdin_command
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import LocalRuntimeDiagnostic, build_local_runtime_plan, setup_local_runtime

CONTAINER_ID = "c" * 64


def _plan(tmp_path: Path) -> Any:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    setup_local_runtime(home)
    (home / "runtime").chmod(0o700)
    plan = build_local_runtime_plan(home)
    plan.env_file.chmod(0o600)
    return plan


def _timeout() -> LocalDbBackupError:
    error = provenance_error("local-db-command-failed", "pg_restore", "provenance command timed out")
    error.__cause__ = BoundedProcessError("provenance command timed out")
    return error


class _Bounded:
    """Injected bounded runner: one scripted response per supervised, process or session call."""

    def __init__(
        self, command: Any, process: Any = b"REMOTE killed\nCONTROL removed\nDESCENDANTS none\n", sessions: Any = b"0\n0\n",
        *, retire: bool = True,
    ) -> None:
        self.responses = {"command": command, "process": process, "sessions": sessions}
        self.calls: list[tuple[str, list[str]]] = []
        self.kwargs: list[dict[str, Any]] = []
        self.retire = retire

    def __call__(self, command: list[str], **kwargs: Any) -> bytes:
        joined = " ".join(command)
        kind = "process" if SETTLE_PROCESS_SH in command else "sessions" if "pg_terminate_backend" in joined else "command"
        self.calls.append((kind, command))
        self.kwargs.append(kwargs)
        retirement = kwargs.get("retirement")
        if kind == "command" and retirement is not None:
            retirement.state = "retired" if self.retire else "started"  # the runner's typed observation
        response = self.responses[kind]
        if isinstance(response, BaseException):
            raise response
        return response


def _psql(plan: Any) -> list[str]:
    return list(planned_psql_command(plan, plan.maintenance_database, "-c", "SELECT 1"))


def test_container_exec_argv_binds_immutable_id_private_control_and_session_identity(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    options, inner = split_container_exec(plan, planned_psql_stdin_command(plan, "g1")) or ([], [])
    assert options == ["-i", "-e", "PGPASSWORD"] and inner[0].endswith("psql")
    assert split_container_exec(plan, [plan.container_runtime, "inspect", "x"]) is None
    with pytest.raises(ValueError):
        split_container_exec(plan, [plan.container_runtime, "exec", "-u", "root", plan.identity.postgres_container, "sh"])
    argv = supervised_command(plan, CONTAINER_ID, options, inner, token="a" * 32)
    assert plan.identity.postgres_container not in argv and argv[argv.index("-e", 4) + 1] == "REPOMAP_EXT_INVOCATION=" + "a" * 32
    assert argv[argv.index(CONTAINER_ID) + 1 : argv.index(CONTAINER_ID) + 4] == ["sh", "-c", SUPERVISOR_SH]
    assert argv[argv.index(SUPERVISOR_SH) + 2] == f"/tmp/repomap-ext-exec-{plan.identity.home_hash}-{'a' * 32}" and argv[-len(inner):] == inner
    for invariant in ('mkdir -m 0700 "$c"', "umask 0177; set -C", 'PGAPPNAME="repomap-ext-$REPOMAP_EXT_INVOCATION"', 'exec "$@"'):
        assert invariant in SUPERVISOR_SH, invariant
    # Descendant retention and exact leader retirement are exercised behaviorally by d9_extension_exec_reaping.
    for invariant in ('grep -Fqx "REPOMAP_EXT_INVOCATION=$k"', '[ "$tok" = "$k" ] || held unknown', "/proc/[0-9]*/environ", '[ "$q" = "$$" ] && continue'):
        assert invariant in SETTLE_PROCESS_SH, invariant


def test_settlement_parsers_accept_only_exact_observations() -> None:
    assert parse_process_settlement("REMOTE killed\nCONTROL removed\nDESCENDANTS none\n") == ("killed", "removed", "none")
    assert parse_process_settlement("REMOTE killed\nCONTROL removed\nDESCENDANTS killed\n") == ("killed", "removed", "unknown"), "descendants are never killed"
    assert parse_process_settlement("UNAVAILABLE grep\n") == ("unavailable", "retained", "unknown")
    for garbage in ("", "REMOTE killed\nCONTROL removed\n", "REMOTE gone\nCONTROL removed\nDESCENDANTS none\n",
                    "REMOTE killed\nCONTROL removed\nDESCENDANTS gone\n", "REMOTE killed\nCONTROL removed\nDESCENDANTS none\nextra\n"):
        assert "unknown" in parse_process_settlement(garbage), garbage
    assert parse_session_settlement("1\n0\n") == "none" and parse_session_settlement("0\n2\n") == "remaining"
    assert parse_session_settlement("0\n") == "unknown" and parse_session_settlement("x\ny\n") == "unknown"


def test_container_command_refuses_without_bound_immutable_container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(tmp_path)
    bounded = _Bounded(b"1\n")
    monkeypatch.setattr(exec_mod, "run_bounded_popen", bounded)
    for binding in (None, "short-id"):
        with pytest.raises(LocalDbBackupError) as exc:
            if binding is None:
                run_bounded_ext_command(plan, _psql(plan), subprocess.run, field="probe")
            else:
                with bound_exec_custody(binding):
                    run_bounded_ext_command(plan, _psql(plan), subprocess.run, field="probe")
        assert exc.value.diagnostics[0].code == "restore-exec-custody-unavailable"
    with pytest.raises(LocalDbBackupError) as shape_exc, bound_exec_custody(CONTAINER_ID):
        run_bounded_ext_command(plan, [plan.container_runtime, "exec", "-u", "root", plan.identity.postgres_container, "sh"], subprocess.run, field="probe")
    assert shape_exc.value.diagnostics[0].code == "restore-exec-custody-unavailable" and bounded.calls == []


def test_timeout_settles_exact_process_and_sessions_and_keeps_primary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(tmp_path)
    primary = _timeout()
    bounded = _Bounded(primary)
    monkeypatch.setattr(exec_mod, "run_bounded_popen", bounded)
    with bound_exec_custody(CONTAINER_ID) as custody:
        with pytest.raises(LocalDbBackupError) as exc:
            run_bounded_ext_command(plan, _psql(plan), subprocess.run, field="pg_restore")
        assert exc.value is primary, "a fully settled failure re-raises the initiating error unchanged"
        assert [kind for kind, _ in bounded.calls] == ["command", "process", "sessions"]
        assert all(CONTAINER_ID in cmd and plan.identity.postgres_container not in cmd for _, cmd in bounded.calls)
        [outcome] = custody.outcomes
        assert (outcome.host, outcome.remote, outcome.sessions, outcome.control, outcome.descendants) == ("retired", "killed", "none", "removed", "none")
        assert outcome.settled and custody.unknown == []
        session_cmd = bounded.calls[2][1]
        assert any(f"application_name = 'repomap-ext-{outcome.token}'" in tok for tok in session_cmd), "only this invocation's sessions"
        assert any("usename = current_user" in tok for tok in session_cmd)


@pytest.mark.parametrize(
    ("process", "sessions", "host_unproven"),
    [
        (b"REMOTE mismatch\nCONTROL retained\nDESCENDANTS unknown\n", b"0\n0\n", False),
        (b"REMOTE alive\nCONTROL retained\nDESCENDANTS unknown\n", b"0\n0\n", False),
        (b"UNAVAILABLE grep\n", b"0\n0\n", False),
        (b"REMOTE killed\nCONTROL removed\nDESCENDANTS none\n", b"0\n1\n", False),
        (b"REMOTE killed\nCONTROL retained\nDESCENDANTS remaining\n", b"0\n0\n", False),
        (b"REMOTE killed\nCONTROL removed\nDESCENDANTS none\n", b"0\n0\n", True),
    ],
)
def test_unsettled_outcome_is_retained_and_refuses_later_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, process: bytes, sessions: bytes, host_unproven: bool
) -> None:
    plan = _plan(tmp_path)
    primary = _timeout()
    bounded = _Bounded(primary, process=process, sessions=sessions, retire=not host_unproven)
    monkeypatch.setattr(exec_mod, "run_bounded_popen", bounded)
    with bound_exec_custody(CONTAINER_ID) as custody:
        with pytest.raises(LocalDbBackupError) as exc:
            run_bounded_ext_command(plan, _psql(plan), subprocess.run, field="pg_restore")
        assert [d.code for d in exc.value.diagnostics] == ["local-db-command-failed", "restore-exec-outcome-unknown"]
        assert exc.value.__cause__ is primary and len(custody.unknown) == 1
        terminated = [kind for kind, _ in bounded.calls] == ["command", "process", "sessions"]
        assert terminated == (b"DESCENDANTS none" in process), "sessions are terminated only once no descendant remains"
        calls_before = len(bounded.calls)
        with pytest.raises(LocalDbBackupError) as refused:
            run_bounded_ext_command(plan, _psql(plan), subprocess.run, field="database drop")
        assert refused.value.diagnostics[0].code == "restore-exec-outcome-unknown" and len(bounded.calls) == calls_before


def test_interruption_preserves_original_base_exception_with_bounded_notes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(tmp_path)
    interrupt = KeyboardInterrupt("operator interrupt")
    bounded = _Bounded(interrupt, process=KeyboardInterrupt("second interrupt"))
    monkeypatch.setattr(exec_mod, "run_bounded_popen", bounded)
    with bound_exec_custody(CONTAINER_ID) as custody:
        with pytest.raises(KeyboardInterrupt) as exc:
            run_bounded_ext_command(plan, _psql(plan), subprocess.run, field="pg_restore")
    notes = getattr(exc.value, "__notes__", [])
    assert exc.value is interrupt, "the initiating interruption is the raised object"
    assert any(n.startswith("restore-exec-outcome-unknown") for n in notes) and any("settlement-interrupted" in n for n in notes), notes
    assert custody.unknown and custody.outcomes[0].remote == "unknown"


def test_interrupted_host_retirement_is_unknown_not_inferred_from_missing_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scripted runner: client output was complete, then retirement was interrupted (no ``__context__``)."""
    plan = _plan(tmp_path)
    interrupt = KeyboardInterrupt("retirement interrupted")
    assert interrupt.__context__ is None
    bounded = _Bounded(interrupt, process=b"REMOTE exited\nCONTROL removed\nDESCENDANTS none\n", retire=False)
    monkeypatch.setattr(exec_mod, "run_bounded_popen", bounded)
    with bound_exec_custody(CONTAINER_ID) as custody:
        with pytest.raises(KeyboardInterrupt) as exc:
            run_bounded_ext_command(plan, _psql(plan), subprocess.run, field="probe")
    assert exc.value is interrupt and isinstance(bounded.kwargs[0].get("retirement"), ProcessRetirement)
    [outcome] = custody.outcomes
    assert outcome.host == "unknown", "only the runner's typed observation may report host retirement"
    assert custody.unknown == [outcome] and any(n.startswith("restore-exec-outcome-unknown") for n in getattr(exc.value, "__notes__", []))


@pytest.mark.parametrize(
    ("command", "process", "kinds"),
    [
        (_timeout(), b"REMOTE killed\nCONTROL removed\nDESCENDANTS none\n", ["command", "process", "sessions"]),
        (_timeout(), b"REMOTE exited\nCONTROL removed\nDESCENDANTS none\n", ["command", "process", "sessions"]),
        (b"ok\n", b"REMOTE exited\nCONTROL removed\nDESCENDANTS none\n", ["command", "process"]),
    ],
)
def test_inherited_sessions_are_settled_only_once_no_descendant_remains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: Any, process: bytes, kinds: list[str]
) -> None:
    """Scripted settlement reports; the real script is exercised by d9_extension_exec_reaping and the containerized owner."""
    plan = _plan(tmp_path)
    bounded = _Bounded(command, process=process)
    monkeypatch.setattr(exec_mod, "run_bounded_popen", bounded)
    with bound_exec_custody(CONTAINER_ID) as custody:
        try:
            run_bounded_ext_command(plan, [plan.container_runtime, "exec", plan.identity.postgres_container, "sh", "-uc", "true"], subprocess.run, field="toc")
        except LocalDbBackupError as exc:
            assert exc is command, "a fully settled failure keeps the initiating error"
    assert [kind for kind, _ in bounded.calls] == kinds, "a shell leader's children may have held sessions under the inherited application_name"
    [outcome] = custody.outcomes
    assert outcome.settled and outcome.sessions == ("none" if "sessions" in kinds else "not-applicable")
    assert outcome.control_path == f"/tmp/repomap-ext-exec-{plan.identity.home_hash}-{outcome.token}"


def test_success_path_requires_settled_exit_and_control_removal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(tmp_path)
    bounded = _Bounded(b"1\n", process=b"REMOTE exited\nCONTROL removed\nDESCENDANTS none\n")
    monkeypatch.setattr(exec_mod, "run_bounded_popen", bounded)
    with bound_exec_custody(CONTAINER_ID) as custody:
        assert run_bounded_ext_command(plan, _psql(plan), subprocess.run, field="probe") == b"1\n"
        assert [kind for kind, _ in bounded.calls] == ["command", "process"], "no session settlement after a completed command"
        bounded.responses["process"] = b"REMOTE exited\nCONTROL retained\nDESCENDANTS none\n"
        with pytest.raises(LocalDbBackupError) as residue:
            run_bounded_ext_command(plan, _psql(plan), subprocess.run, field="probe")
        assert residue.value.diagnostics[0].code == "restore-exec-cleanup-failed" and custody.unknown == []
        bounded.responses["process"] = b"REMOTE not-started\nCONTROL fence-retained\nDESCENDANTS none\n"
        bounded.responses["command"] = _timeout()
        with pytest.raises(LocalDbBackupError) as fenced:
            run_bounded_ext_command(plan, _psql(plan), subprocess.run, field="probe")
        assert [d.code for d in fenced.value.diagnostics] == ["local-db-command-failed", "restore-exec-cleanup-failed"]
        assert custody.outcomes[-1].sessions == "not-applicable" and custody.unknown == [], "a fenced command never ran"
        bounded.responses["command"] = b"1\n"
        bounded.responses["process"] = b"UNAVAILABLE rmdir\n"
        with pytest.raises(LocalDbBackupError) as unavailable:
            run_bounded_ext_command(plan, _psql(plan), subprocess.run, field="probe")
        assert unavailable.value.diagnostics[0].code == "restore-exec-outcome-unknown" and len(custody.unknown) == 1


def test_preflight_archive_listing_runs_under_container_custody_with_toc_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(tmp_path)
    archive = tmp_path / "g1.pgcustom"
    archive.write_bytes(b"PGDMP")
    bounded = _Bounded(b"; toc\n", process=b"REMOTE exited\nCONTROL removed\nDESCENDANTS none\n")
    monkeypatch.setattr(exec_mod, "run_bounded_popen", bounded)
    with bound_exec_custody(CONTAINER_ID) as custody:
        assert _list_archive_toc(plan, archive, subprocess.run) == b"; toc\n"
    [(kind, command), (settle_kind, _)] = bounded.calls
    assert (kind, settle_kind) == ("command", "process"), "the listing is settled like every new container command"
    assert CONTAINER_ID in command and plan.identity.postgres_container not in command and command[-1] == "-l"
    assert {k: bounded.kwargs[0][k] for k in ("error_code", "max_output_bytes", "timeout_seconds", "stdin_path")} == {
        "error_code": "backup-toc-inconsistent", "max_output_bytes": MAX_TOC_OUTPUT_BYTES,
        "timeout_seconds": DEFAULT_TOC_TIMEOUT_SECONDS, "stdin_path": archive,
    }, "the existing TOC limits stay owned by the listing"
    [outcome] = custody.outcomes
    assert outcome.label == archive.name and outcome.settled
    shared: list[Any] = []

    def shared_listing(*args: Any) -> bytes:
        shared.append(args)
        return b"; shared\n"

    def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        raise AssertionError("the shared listing helper owns a caller-supplied runner")

    monkeypatch.setattr(preflight_mod, "_run_pg_restore_list_bytes", shared_listing)
    assert _list_archive_toc(plan, archive, runner) == b"; shared\n" and len(shared) == 1 and len(bounded.calls) == 2


class _AbsenceAuthority:
    def __init__(self, absent: bool) -> None:
        self.absent, self.queries = absent, 0

    def target_absent(self, database: str) -> bool:
        self.queries += 1
        return self.absent


def test_failed_create_is_cleared_only_after_settlement_and_observed_absence() -> None:
    cases = [
        (ExecOutcome("database create", "t", "retired", "exited", "none", "removed", "none"), True, "not_created", 1),
        (ExecOutcome("database create", "t", "retired", "exited", "none", "removed", "none"), False, "outcome_unknown", 1),
        (ExecOutcome("database create", "t", "retired", "mismatch", "none", "retained", "unknown"), True, "outcome_unknown", 0),
        (ExecOutcome("database create", "t", "unknown", "killed", "none", "removed", "none"), True, "outcome_unknown", 0),
        (ExecOutcome("database create", "t", "retired", "exited", "none", "retained", "remaining"), True, "outcome_unknown", 0),
        (ExecOutcome("pg_restore", "t", "retired", "exited", "none", "removed", "none"), True, "outcome_unknown", 0),
    ]
    for outcome, absent, expected, queries in cases:
        intent = DatabaseCreationIntent("g1", "inv-0", "outcome_unknown")
        authority: Any = _AbsenceAuthority(absent)
        with bound_exec_custody(CONTAINER_ID) as custody:
            custody.outcomes.append(outcome)
            _reconcile_failed_create(authority, intent, custody, 0)
        assert (intent.state, authority.queries) == (expected, queries), (outcome, absent)
    intent = DatabaseCreationIntent("g1", "inv-0", "outcome_unknown")
    absence_authority: Any = _AbsenceAuthority(True)
    _reconcile_failed_create(absence_authority, intent, None, 0)
    assert intent.state == "outcome_unknown", "an orchestration runner never proves a native outcome"


class _HeldAuthority:
    def held(self, database: str) -> bool:
        return True

    def verify(self, intent: DatabaseCreationIntent, *, finalized: bool = False) -> bool:
        return True

    def oid_absent(self, oid: int) -> bool:
        return True


def test_unknown_container_outcome_refuses_compensation_and_retains_ledger_record(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    ledger = plan.runtime_dir / ".restore-intents-exec" / "intents.json"
    primary = LocalDbBackupError((LocalRuntimeDiagnostic("error", "local-db-command-failed", "pg_restore", "timed out"),))
    intents = [DatabaseCreationIntent("g_a", "inv-0", "created", 16384, "sys"), DatabaseCreationIntent("g_b", "inv-1", "not_created")]
    drops: list[list[str]] = []

    def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        drops.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    authority: Any = _HeldAuthority()
    with bound_exec_custody(CONTAINER_ID) as custody:
        custody.outcomes.append(ExecOutcome("pg_restore", "b" * 32, "retired", "mismatch", "none", "retained", "unknown", "/tmp/repomap-ext-exec-h-" + "b" * 32))
        with pytest.raises(LocalDbBackupError) as exc:
            cleanup_extension_restore_intents(
                plan, authority, intents, runner, primary_error=primary, coordinated=False, ledger_path=ledger,
            )
    assert drops == [], "no compensation mutation runs while a container outcome is unknown"
    assert exc.value.__cause__ is primary
    assert [(d.code, d.path) for d in exc.value.diagnostics] == [
        ("local-db-command-failed", "pg_restore"), ("restore-exec-outcome-unknown", "g_a"), ("failed-target-cleanup-failed", "g_a"),
    ]
    recorded = json.loads(ledger.read_text(encoding="utf-8"))
    assert [i["state"] for i in recorded] == ["created", "not_created"]
    assert recorded[0]["exec_unknown"] == [{
        "control": "retained", "control_path": "/tmp/repomap-ext-exec-h-" + "b" * 32, "descendants": "unknown", "host": "retired",
        "label": "pg_restore", "remote": "mismatch", "sessions": "none", "token": "b" * 32,
    }]


def test_orphaned_descendants_are_never_signalled_and_their_sessions_stay_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scripted report; the script's orphan handling is d9_extension_exec_reaping's, the native case the containerized owner's."""
    plan = _plan(tmp_path)
    bounded = _Bounded(_timeout(), process=b"REMOTE exited\nCONTROL retained\nDESCENDANTS remaining\n")
    monkeypatch.setattr(exec_mod, "run_bounded_popen", bounded)
    with bound_exec_custody(CONTAINER_ID) as custody, pytest.raises(LocalDbBackupError) as exc:
        run_bounded_ext_command(plan, [plan.container_runtime, "exec", plan.identity.postgres_container, "sh", "-uc", "true"], subprocess.run, field="toc")
    assert [kind for kind, _ in bounded.calls] == ["command", "process"], "a terminated orphaned client would crash the postmaster"
    [outcome] = custody.outcomes
    assert outcome.sessions == "unknown" and custody.unknown == [outcome] and outcome.control_path in exc.value.diagnostics[1].message


def test_durable_records_name_every_retained_control_path(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    fenced = ExecOutcome("database create", "c" * 32, "retired", "not-started", "not-applicable", "fence-retained", "none", "/tmp/f")
    unknown = ExecOutcome("pg_restore", "b" * 32, "retired", "mismatch", "none", "retained", "unknown", "/tmp/u")
    ledger, authority = plan.runtime_dir / ".restore-intents-exec" / "intents.json", cast(Any, _HeldAuthority())
    primary = provenance_error("local-db-command-failed", "pg_restore", "timed out")
    with bound_exec_custody(CONTAINER_ID) as custody:
        custody.outcomes.extend([fenced, unknown])
        assert fenced.settled and custody.unknown == [unknown] and custody.retained == [fenced, unknown]
        assert retain_unknown_commands(plan, custody, primary, "toc") is primary
        with pytest.raises(LocalDbBackupError):
            cleanup_extension_restore_intents(plan, authority, [DatabaseCreationIntent("g", "i", "created", 1, "s")], subprocess.run,
                                              primary_error=primary, coordinated=False, ledger_path=ledger)
    [record] = [json.loads(p.read_text(encoding="utf-8")) for p in plan.runtime_dir.glob(".restore-exec-record-*/record.json")]
    for entries in (record["exec_unknown"], json.loads(ledger.read_text(encoding="utf-8"))[0]["exec_unknown"]):
        assert [(e["control"], e["control_path"]) for e in entries] == [("fence-retained", "/tmp/f"), ("retained", "/tmp/u")]
