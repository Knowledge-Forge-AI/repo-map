"""Per-database extension_v2 restore execution under held custody, readiness proof and exact compensation."""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from repomap_kg.runtime._backup_provenance import _STDLIB_SUBPROCESS_RUN

from repomap_kg.runtime._extension_restore_compensation import (
    cleanup_extension_restore_intents,
)
from repomap_kg.runtime._extension_restore_custody import (
    DatabaseCreationIntent,
    RestoreLifecycleAuthority,
    canonical_restore_authority,
    persist_intent_ledger,
    refuse_outstanding_restore_state,
    remove_intent_ledger,
)
from repomap_kg.runtime._extension_restore_exec import (
    ContainerExecCustody,
    active_exec_custody,
    bound_exec_custody,
)
from repomap_kg.runtime._extension_restore_native import run_bounded_ext_command
from repomap_kg.runtime._extension_restore_preflight import (
    ExtensionRestoreSetPreflight,
)
from repomap_kg.runtime._extension_restore_qualification import (
    TARGET_TEMPLATE,
)
from repomap_kg.runtime._extension_restore_steps import (
    install_extensions,
    require_custody,
    verify_restored_database,
)
from repomap_kg.runtime._extension_restore_target import (
    observe_engine_identity,
)
from repomap_kg.runtime._extension_restore_template import (
    observe_template_baseline_digest,
)
from repomap_kg.runtime._extension_restore_toc_custody import (
    private_derived_toc_custody,
)
from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    planned_pg_restore_command,
    planned_psql_command,
)
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.backup_streaming import describe_dump_file
from repomap_kg.runtime.database_roles import (
    reconcile_control_database_roles,
    reconcile_graph_database_roles,
)
from repomap_kg.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan

def _diag(code: str, field: str, message: str) -> LocalRuntimeDiagnostic:
    return LocalRuntimeDiagnostic("error", code, field, message)


def _err(code: str, field: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError((_diag(code, field, message),))


def _revalidate_environment(
    plan: LocalRuntimePlan,
    set_pre: ExtensionRestoreSetPreflight,
    runner: CommandRunner,
    *,
    field: str,
    template: bool,
) -> None:
    container = observe_engine_identity(plan, runner, set_pre.policy, field=field)
    if (
        container.container_id != set_pre.container.container_id
        or container.image_id != set_pre.engine_image_id
    ):
        raise _err(
            "restore-target-ownership-mismatch",
            field,
            "target container or Engine image changed after preflight",
        )
    if (
        template
        and observe_template_baseline_digest(plan, TARGET_TEMPLATE, runner)
        != set_pre.template_baseline_sha256
    ):
        raise _err(
            "restore-template-baseline-mismatch", field, "target template1 changed after preflight"
        )


def reconcile_restored_roles(
    plan: LocalRuntimePlan, database: str, database_role: str, runner: CommandRunner
) -> None:
    """Reuse the unchanged core role reconciliation; its one container exec runs under custody.

    With the stdlib runner the rendered secret-bearing SQL is piped (never written to
    disk) through the bounded custodied path with the existing observation limits. A
    caller-supplied runner keeps the shared core path.
    """
    reconcile = (
        reconcile_graph_database_roles if database_role == "graph" else reconcile_control_database_roles
    )
    if runner is not _STDLIB_SUBPROCESS_RUN:
        reconcile(plan, database, runner)
        return

    def custodied(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        sql = kwargs.get("input")
        if not isinstance(sql, bytes) or kwargs.get("stdin") is not None:
            raise _err(
                "restore-exec-custody-unavailable", database, "role reconciliation input is not bounded bytes"
            )
        out = run_bounded_ext_command(
            plan, command, runner, field="database role reconciliation", pipe_input=sql
        )
        return subprocess.CompletedProcess(command, 0, out, b"")

    reconcile(plan, database, custodied)


def _reconcile_failed_create(
    authority: RestoreLifecycleAuthority,
    intent: DatabaseCreationIntent,
    custody: ContainerExecCustody | None,
    mark: int,
) -> None:
    """Clear a failed CREATE only after its native outcome is settled and absence observed.

    The maintenance lock is held throughout. An unsettled, unobserved or present target
    keeps the conservative ``outcome_unknown`` state.
    """
    outcome = custody.outcome_since(mark) if custody is not None else None
    if outcome is None or outcome.label != "database create" or not outcome.settled:
        return
    if authority.target_absent(intent.database):
        intent.state = "not_created"


def _restore_one(
    plan: LocalRuntimePlan,
    authority: RestoreLifecycleAuthority,
    set_pre: ExtensionRestoreSetPreflight,
    intent: DatabaseCreationIntent,
    intents: Sequence[DatabaseCreationIntent],
    ledger_path: Path,
    runner: CommandRunner,
) -> None:
    db_pre = set_pre.databases[intent.database]
    _revalidate_environment(plan, set_pre, runner, field=intent.database, template=True)
    if not authority.target_absent(intent.database):
        raise _err(
            "database-already-exists",
            intent.database,
            "target database appeared inside the restore maintenance window",
        )
    intent.state = "outcome_unknown"
    persist_intent_ledger(ledger_path, intents)
    custody = active_exec_custody()
    mark = len(custody.outcomes) if custody is not None else 0
    try:
        run_bounded_ext_command(
            plan,
            planned_psql_command(
                plan,
                plan.maintenance_database,
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                db_pre.create_database_sql,
            ),
            runner,
            field="database create",
        )
    except BaseException as primary:
        try:
            _reconcile_failed_create(authority, intent, custody, mark)
        except BaseException as secondary:
            primary.add_note(
                f"restore-target-ownership-unknown ({intent.database}): creation outcome "
                f"reconciliation failed with {type(secondary).__name__}"
            )
        raise
    intent.state = "created_unheld"
    persist_intent_ledger(ledger_path, intents)
    authority.hold_target(intent, control=db_pre.database_role == "control")
    intent.state = "created"
    persist_intent_ledger(ledger_path, intents)
    authority.verify_baseline(intent, set_pre.template_baseline_sha256)
    install_extensions(plan, authority, intent, db_pre, runner)
    require_custody(authority, intent, "archive replay")
    _revalidate_environment(plan, set_pre, runner, field=intent.database, template=False)
    bounds = set_pre.policy.replay_bounds
    if bounds is None:
        raise _err(
            "backup-extension-restore-unsupported",
            intent.database,
            "extension_v2 replay requires explicit policy replay bounds",
        )
    with private_derived_toc_custody(
        plan,
        db_pre.database,
        db_pre.derived_toc_plan,
        runner,
        invocation_token=intent.invocation_token,
    ) as toc_path:
        restore_cmd = planned_pg_restore_command(
            plan, db_pre.database, exit_on_error=True, use_list_path=toc_path
        )
        run_bounded_ext_command(
            plan,
            restore_cmd,
            runner,
            field="pg_restore",
            max_output_bytes=bounds.max_output_bytes,
            timeout_seconds=float(bounds.timeout_seconds),
            stdin_path=db_pre.dump_path,
        )
    if describe_dump_file(db_pre.dump_path).sha256 != db_pre.dump_sha256:
        raise _err(
            "backup-archive-mutated",
            db_pre.database,
            "backup archive file digest changed during restore",
        )
    require_custody(authority, intent, "role reconciliation")
    reconcile_restored_roles(plan, intent.database, db_pre.database_role, runner)
    verify_restored_database(plan, authority, intent, set_pre, db_pre, runner)


def execute_extension_v2_restore_set(
    plan: LocalRuntimePlan,
    set_preflight: ExtensionRestoreSetPreflight,
    *,
    restore_order: Sequence[str],
    command_runner: CommandRunner,
    coordinated: bool,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    field_label = "coordinated restore" if coordinated else restore_order[0]
    refuse_outstanding_restore_state(plan, field_label)
    prefix = uuid.uuid4().hex[:12]
    ledger_path = plan.runtime_dir / f".restore-intents-{prefix}" / "intents.json"
    intents = [
        DatabaseCreationIntent(
            db,
            f"{prefix}-{idx}",
            expected_system_identifier=set_preflight.target_system_identifier,
            expected_container_id=set_preflight.container.container_id,
            expected_image_id=set_preflight.engine_image_id,
        )
        for idx, db in enumerate(restore_order)
    ]
    with (
        bound_exec_custody(set_preflight.container.container_id),
        canonical_restore_authority(plan) as authority,
    ):
        try:
            persist_intent_ledger(ledger_path, intents)
        except BaseException:
            # Nothing was mutated yet; do not leave an empty ledger that blocks later restores.
            with suppress(LocalDbBackupError):
                remove_intent_ledger(ledger_path)
            raise
        try:
            for intent in intents:
                _restore_one(
                    plan, authority, set_preflight, intent, intents, ledger_path, command_runner
                )
            _revalidate_environment(
                plan, set_preflight, command_runner, field=field_label, template=False
            )
            authority.finalize(intents)
            for intent in intents:
                intent.state = "completed"
        except BaseException as exc:
            cleanup_extension_restore_intents(
                plan,
                authority,
                intents,
                command_runner,
                primary_error=exc,
                coordinated=coordinated,
                ledger_path=ledger_path,
            )
        remove_intent_ledger(ledger_path)
    return tuple(restore_order), tuple(restore_order)
