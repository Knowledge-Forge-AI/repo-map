"""Reverse-order compensation of invocation-created targets for D9-B extension_v2 restore.

Only held, stamped and re-verified targets are dropped. Unknown creation outcomes,
lost custody, replaced targets and unknown container command outcomes are retained in
the private intent ledger for operator intervention. Command outcomes are re-read before
each target and before the ledger write, so an outcome first raised by a drop counts.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from common_lore_index.runtime._extension_restore_custody import (
    DatabaseCreationIntent,
    RestoreLifecycleAuthority,
    persist_intent_ledger,
    remove_intent_ledger,
)
from common_lore_index.runtime._extension_restore_exec import active_exec_custody
from common_lore_index.runtime._extension_restore_native import run_bounded_ext_command
from common_lore_index.runtime.backup_commands import (
    CommandRunner,
    planned_psql_command,
    quote_sql_identifier,
)
from common_lore_index.runtime.backup_records import LocalDbBackupError
from common_lore_index.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan

_RETAINED_STATES = frozenset({"outcome_unknown", "created_unheld"})
_TERMINAL_STATES = ("not_created", "completed", "cleaned")


def _diag(code: str, field: str, message: str) -> LocalRuntimeDiagnostic:
    return LocalRuntimeDiagnostic("error", code, field, message)


def _unknown_records(*, retained: bool = False) -> list[dict[str, str]]:
    """Records of unsettled outcomes, or with ``retained`` also of retained control paths."""
    custody = active_exec_custody()
    if custody is None:
        return []
    return [o.record() for o in (custody.retained if retained else custody.unknown)]


def cleanup_extension_restore_intents(
    plan: LocalRuntimePlan,
    authority: RestoreLifecycleAuthority,
    intents: Sequence[DatabaseCreationIntent],
    command_runner: CommandRunner,
    *,
    primary_error: BaseException,
    coordinated: bool,
    ledger_path: Path,
) -> NoReturn:
    """Compensate in reverse order only for held, stamped and re-verified targets; retain everything else."""
    cleanup_diags: list[LocalRuntimeDiagnostic] = []
    interrupted = False
    for intent in reversed(intents):
        if intent.state in _TERMINAL_STATES:
            continue
        if _unknown_records():
            # A container command may still be running or its effect is unobserved: retain.
            cleanup_diags.append(
                _diag(
                    "restore-exec-outcome-unknown",
                    intent.database,
                    "a container command outcome is unknown; compensation refused and target retained",
                )
            )
            continue
        if interrupted:
            cleanup_diags.append(
                _diag(
                    "restore-target-ownership-unknown",
                    intent.database,
                    "compensation was interrupted before this target; retained for operator intervention",
                )
            )
            continue
        if (
            intent.state in _RETAINED_STATES
            or not authority.held(intent.database)
            or intent.expected_oid is None
        ):
            cleanup_diags.append(
                _diag(
                    "restore-target-ownership-unknown",
                    intent.database,
                    "target creation outcome or custody is unknown; retained for operator intervention",
                )
            )
            continue
        verified: bool | None = None
        detail = ""
        try:
            verified = authority.verify(intent)
        except Exception as exc:
            detail = f"held target identity could not be verified ({type(exc).__name__}); retained"
        except BaseException as secondary:
            interrupted = True
            detail = f"compensation interrupted by {type(secondary).__name__} during identity verification; retained"
        if verified is None:
            cleanup_diags.append(_diag("restore-target-ownership-unknown", intent.database, detail))
            continue
        if not verified:
            cleanup_diags.append(
                _diag(
                    "restore-target-ownership-mismatch",
                    intent.database,
                    "held target identity, lock or stamp changed; refusing to drop a replaced target",
                )
            )
            continue
        try:
            drop = planned_psql_command(
                plan,
                plan.maintenance_database,
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                f"DROP DATABASE {quote_sql_identifier(intent.database)} WITH (FORCE);",
            )
            run_bounded_ext_command(plan, drop, command_runner, field="database drop")
            if not authority.oid_absent(intent.expected_oid):
                raise RuntimeError("dropped target OID is still present")
            intent.state = "cleaned"
        except Exception:
            cleanup_diags.append(
                _diag(
                    "failed-target-cleanup-failed",
                    intent.database,
                    "restore failed and the proven invocation-created target could not be removed",
                )
            )
        except BaseException as secondary:
            # Keep the initiating error; a secondary interruption stops further drops and is reported.
            interrupted = True
            cleanup_diags.append(
                _diag(
                    "failed-target-cleanup-failed",
                    intent.database,
                    f"compensation interrupted by {type(secondary).__name__}; drop outcome unknown, target retained",
                )
            )
    unknown, retained = _unknown_records(), _unknown_records(retained=True)
    for intent in intents:
        intent.exec_unknown = retained
    if unknown and not any(d.code == "restore-exec-outcome-unknown" for d in cleanup_diags):
        cleanup_diags.append(
            _diag(
                "restore-exec-outcome-unknown",
                "restore",
                "a container command outcome is unknown; retained for operator intervention",
            )
        )
    try:
        if cleanup_diags:
            persist_intent_ledger(ledger_path, intents)
        else:
            remove_intent_ledger(ledger_path)
    except LocalDbBackupError as ledger_exc:
        cleanup_diags.extend(ledger_exc.diagnostics)
    except BaseException as ledger_exc:
        cleanup_diags.append(
            _diag(
                "restore-intent-ledger-failed",
                ledger_path.name,
                f"restore intent ledger update failed with {type(ledger_exc).__name__}",
            )
        )
    if not cleanup_diags:
        raise primary_error
    summary_code, summary_field = (
        ("coordinated-restore-cleanup-failed", "coordinated restore")
        if coordinated
        else ("failed-target-cleanup-failed", intents[0].database if intents else "provisioning")
    )
    summary = _diag(
        summary_code,
        summary_field,
        "restore failed and one or more targets require cleanup or operator intervention",
    )
    if not isinstance(primary_error, Exception):
        for diag in (*cleanup_diags, summary):
            primary_error.add_note(f"{diag.code} ({diag.path}): {diag.message}")
        raise primary_error
    head = (
        primary_error.diagnostics
        if isinstance(primary_error, LocalDbBackupError)
        else (_diag("local-db-command-failed", summary_field, str(primary_error)[:512]),)
    )
    raise LocalDbBackupError((*head, *cleanup_diags, summary)) from primary_error
