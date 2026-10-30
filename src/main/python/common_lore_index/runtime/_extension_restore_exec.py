"""Invocation-owned container command custody and outcome settlement for D9-B extension_v2.

A killed host ``docker exec`` client is not proof that its container process or its
PostgreSQL session ended, and a retired shell leader is not proof that its children did.
Settlement never signals those children; it observes them and retains what remains.
Host process, remote process, descendant, PostgreSQL session and control resource outcomes
are recorded separately; host retirement comes only from the runner's typed observation.
An outcome that cannot be settled is kept as a specific unknown record, and every later
command of the same invocation is refused.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

from common_lore_index.runtime import _extension_restore_exec_control as control
from common_lore_index.runtime._backup_process import ProcessRetirement
from common_lore_index.runtime._backup_provenance import provenance_error, run_bounded_popen
from common_lore_index.runtime.backup_records import LocalDbBackupError
from common_lore_index.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan
from common_lore_index.runtime.release import PACKAGED_PSQL

_SETTLED_REMOTE = frozenset({"exited", "killed", "not-started"})
_SETTLED_SESSIONS = frozenset({"none", "not-applicable"})
_SETTLED_DESCENDANTS = frozenset({"none"})


def chain_cleanup_failure(
    primary: BaseException | None, code: str, field: str, detail: str
) -> BaseException:
    """Preserve the initiating error and attach one bounded secondary cleanup diagnostic."""
    cleanup_diag = LocalRuntimeDiagnostic("error", code, field, detail)
    if isinstance(primary, LocalDbBackupError):
        return LocalDbBackupError((*primary.diagnostics, cleanup_diag))
    if primary is not None and not isinstance(primary, Exception):
        primary.add_note(f"{code} ({field}): {detail}")
        return primary
    if primary is not None:
        return LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error", "local-db-command-failed", field, str(primary)[:512]
                ),
                cleanup_diag,
            )
        )
    return LocalDbBackupError((cleanup_diag,))


@dataclass
class ExecOutcome:
    """Separate host, remote process, descendant, session and control resource observations."""

    label: str
    token: str
    host: str = "pending"
    remote: str = "pending"
    sessions: str = "pending"
    control: str = "pending"
    descendants: str = "pending"
    control_path: str = ""

    @property
    def settled(self) -> bool:
        return (
            self.host == "retired"
            and self.remote in _SETTLED_REMOTE
            and self.descendants in _SETTLED_DESCENDANTS
            and self.sessions in _SETTLED_SESSIONS
        )

    def summary(self) -> str:
        return (
            f"host={self.host} remote={self.remote} descendants={self.descendants} "
            f"sessions={self.sessions} control={self.control} path={self.control_path}"
        )

    def record(self) -> dict[str, str]:
        return {
            "control": self.control,
            "control_path": self.control_path,
            "descendants": self.descendants,
            "host": self.host,
            "label": self.label,
            "remote": self.remote,
            "sessions": self.sessions,
            "token": self.token,
        }


@dataclass
class ContainerExecCustody:
    """Per-invocation custody bound to one immutable container ID."""

    container_id: str
    outcomes: list[ExecOutcome] = dataclass_field(default_factory=list)

    @property
    def unknown(self) -> list[ExecOutcome]:
        return [outcome for outcome in self.outcomes if not outcome.settled]

    @property
    def retained(self) -> list[ExecOutcome]:
        """Unsettled outcomes plus settled ones whose exact control path was not removed."""
        return [o for o in self.outcomes if not o.settled or o.control != "removed"]

    def outcome_since(self, mark: int) -> ExecOutcome | None:
        """Return the single outcome recorded after ``mark``, if exactly one exists."""
        later = self.outcomes[mark:]
        return later[0] if len(later) == 1 else None


_ACTIVE_CUSTODY: ContextVar[ContainerExecCustody | None] = ContextVar(
    "repomap_extension_exec_custody", default=None
)


@contextmanager
def bound_exec_custody(container_id: str) -> Iterator[ContainerExecCustody]:
    custody = ContainerExecCustody(container_id)
    reset = _ACTIVE_CUSTODY.set(custody)
    try:
        yield custody
    finally:
        _ACTIVE_CUSTODY.reset(reset)


def active_exec_custody() -> ContainerExecCustody | None:
    return _ACTIVE_CUSTODY.get()


def _err(code: str, field: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError((LocalRuntimeDiagnostic("error", code, field, message),))


def _require_custody(field: str) -> ContainerExecCustody:
    custody = active_exec_custody()
    if custody is None or not control.valid_container_id(custody.container_id):
        raise _err(
            "restore-exec-custody-unavailable",
            field,
            "container command requires invocation-owned custody of an immutable container ID",
        )
    if custody.unknown:
        raise _err(
            "restore-exec-outcome-unknown",
            field,
            "an earlier container command outcome is unknown; further commands are refused",
        )
    return custody


def _host_outcome(retirement: ProcessRetirement) -> str:
    """Only the runner's typed observation proves that the owned host process group retired."""
    return "retired" if retirement.state == "retired" else "unknown"


def _settle(
    plan: LocalRuntimePlan,
    custody: ContainerExecCustody,
    outcome: ExecOutcome,
    *,
    failed: bool,
    env: Mapping[str, str],
    secret: str | None,
) -> None:
    """Observe and settle the remote process, observe its descendants, then settle correlated sessions.

    Sessions inherit the exported ``application_name``, so they are settled after any failed
    command, whatever program the leader is, but only once settlement saw no descendant and a
    settled remote process. With remaining, unreaped or unknown descendants they are not
    terminated: a client that exits abnormally once it is or could be adopted would make the
    PID 1 postmaster restart every session, so they stay unknown and retained.
    """
    outcome.remote, outcome.control, outcome.descendants = "unknown", "unknown", "unknown"
    raw = run_bounded_popen(
        control.settle_process_command(plan, custody.container_id, outcome.token),
        max_output_bytes=control.EXEC_CONTROL_OUTPUT_MAX_BYTES,
        timeout_seconds=control.EXEC_SETTLE_TIMEOUT_SECONDS,
        error_code="restore-exec-settlement-failed",
        field=outcome.label,
        secret=secret,
        env=env,
    )
    outcome.remote, outcome.control, outcome.descendants = control.parse_process_settlement(
        raw.decode("utf-8", errors="replace")
    )
    if outcome.descendants not in _SETTLED_DESCENDANTS or outcome.remote not in _SETTLED_REMOTE:
        outcome.sessions = "unknown"
        return
    if not failed or outcome.remote == "not-started":
        outcome.sessions = "not-applicable"
        return
    outcome.sessions = "unknown"
    raw = run_bounded_popen(
        control.settle_sessions_command(plan, custody.container_id, outcome.token, PACKAGED_PSQL),
        max_output_bytes=control.EXEC_CONTROL_OUTPUT_MAX_BYTES,
        timeout_seconds=control.EXEC_SETTLE_TIMEOUT_SECONDS,
        error_code="restore-exec-settlement-failed",
        field=outcome.label,
        secret=secret,
        env=env,
    )
    outcome.sessions = control.parse_session_settlement(raw.decode("utf-8", errors="replace"))


def _settle_or_note(
    plan: LocalRuntimePlan,
    custody: ContainerExecCustody,
    outcome: ExecOutcome,
    *,
    failed: bool,
    env: Mapping[str, str],
    secret: str | None,
) -> BaseException | None:
    """Run settlement; return a settlement interruption, keeping pending fields unknown."""
    try:
        _settle(plan, custody, outcome, failed=failed, env=env, secret=secret)
    except Exception:
        outcome.sessions = "unknown" if outcome.sessions == "pending" else outcome.sessions
    except BaseException as interruption:
        outcome.sessions = "unknown" if outcome.sessions == "pending" else outcome.sessions
        return interruption
    return None


def _settlement_failure(outcome: ExecOutcome) -> tuple[str, str] | None:
    if not outcome.settled:
        return (
            "restore-exec-outcome-unknown",
            f"container command outcome was not settled ({outcome.summary()}); retained",
        )
    if outcome.control != "removed":
        return (
            "restore-exec-cleanup-failed",
            f"container command control resource was not removed ({outcome.summary()})",
        )
    return None


def run_custodied_container_command(
    plan: LocalRuntimePlan,
    options: Sequence[str],
    inner: Sequence[str],
    *,
    field: str,
    error_code: str,
    max_output_bytes: int,
    timeout_seconds: float,
    env: Mapping[str, str],
    secret: str | None,
    stdin_path: Path | None,
    stdin_bytes: bytes | None = None,
) -> bytes:
    """Run one container command under exact remote process and session custody."""
    custody = _require_custody(field)
    token = uuid.uuid4().hex
    outcome = ExecOutcome(label=field, token=token, control_path=control.control_path(plan, token))
    custody.outcomes.append(outcome)
    command = control.supervised_command(
        plan, custody.container_id, options, inner, token=outcome.token
    )
    retirement = ProcessRetirement()
    try:
        output = run_bounded_popen(
            command,
            max_output_bytes=max_output_bytes,
            timeout_seconds=timeout_seconds,
            error_code=error_code,
            field=field,
            secret=secret,
            env=env,
            stdin_path=stdin_path,
            stdin_bytes=stdin_bytes,
            retirement=retirement,
        )
    except BaseException as primary:
        outcome.host = _host_outcome(retirement)
        secondary = _settle_or_note(
            plan, custody, outcome, failed=True, env=env, secret=secret
        )
        failure = _settlement_failure(outcome)
        result: BaseException = primary
        if failure is not None:
            result = chain_cleanup_failure(primary, failure[0], field, failure[1])
        if secondary is not None:
            result.add_note(
                f"restore-exec-settlement-interrupted ({field}): {type(secondary).__name__}"
            )
        if result is primary:
            raise
        raise result from primary
    outcome.host = _host_outcome(retirement)
    secondary = _settle_or_note(
        plan, custody, outcome, failed=False, env=env, secret=secret
    )
    if secondary is not None:
        raise secondary
    failure = _settlement_failure(outcome)
    if failure is not None:
        raise provenance_error(failure[0], field, failure[1])
    return output
