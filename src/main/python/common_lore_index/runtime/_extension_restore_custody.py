"""Held lifecycle authority, target identity custody and intent ledger for D9-B extension_v2.

The canonical maintenance key is held exclusively on the maintenance database for the
whole invocation and on each created target through a dedicated connection. While
that connection exists, cooperating actors cannot drop or rename the target, so its
name-to-OID binding is pinned until a forced drop issued under the same custody.
Unsettled container commands without a created target are kept in a separate durable
typed execution record; either record refuses later restore attempts.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Sequence
from contextlib import ExitStack, suppress
from dataclasses import asdict, dataclass, field as dataclass_field
from pathlib import Path
from typing import Any

from common_lore_index.ops.config import load_ops_config_home
from common_lore_index.runtime._backup_operations import psycopg
from common_lore_index.runtime._backup_provenance import runtime_postgres_password
from common_lore_index.runtime._extension_restore_exec import ContainerExecCustody, chain_cleanup_failure
from common_lore_index.runtime._extension_restore_native import write_all
from common_lore_index.runtime._extension_restore_template import (
    parse_template_baseline,
    template_baseline_sql,
)
from common_lore_index.runtime.backup_records import LocalDbBackupError
from common_lore_index.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan
from common_lore_index.runtime.postgres_route import execution_postgres

STAMP_PREFIX = "repomap-restore-invocation:"
INTENT_LEDGER_PREFIX = ".restore-intents-"
EXEC_RECORD_PREFIX = ".restore-exec-record-"
EXEC_RECORD_TYPE = "repomap-extension-exec-record-v1"
_CONNECT_OPTIONS = "-c lock_timeout=30000 -c statement_timeout=30000"
_IDENTITY_SQL = (
    "SELECT d.oid::bigint, coalesce(shobj_description(d.oid, 'pg_database'), ''), "
    "(SELECT system_identifier::text FROM pg_control_system()), EXISTS (SELECT 1 FROM pg_locks l WHERE l.locktype = 'advisory' "
    "AND l.pid = pg_backend_pid() AND l.database = d.oid AND l.classid = 0 AND l.objid = %s::oid AND l.objsubid = 1 "
    "AND l.granted AND l.mode = 'ExclusiveLock') FROM pg_database d WHERE d.datname = current_database()"
)


@dataclass
class DatabaseCreationIntent:
    """Mutable creation-intent ledger record for one target database."""

    database: str
    invocation_token: str
    state: str = "not_created"
    expected_oid: int | None = None
    expected_system_identifier: str | None = None
    expected_container_id: str | None = None
    expected_image_id: str | None = None
    exec_unknown: list[dict[str, str]] = dataclass_field(default_factory=list)

    @property
    def stamp(self) -> str:
        return f"{STAMP_PREFIX}{self.invocation_token}"


def _err(code: str, field: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError((LocalRuntimeDiagnostic("error", code, field, message),))


def refuse_outstanding_restore_state(plan: LocalRuntimePlan, field: str) -> None:
    """Refuse while an intent ledger or an unsettled execution record awaits intervention."""
    names = [p.name for p in plan.runtime_dir.iterdir()] if plan.runtime_dir.exists() else []
    if any(name.startswith(INTENT_LEDGER_PREFIX) for name in names):
        raise _err(
            "restore-target-ownership-unknown",
            field,
            "stale restore intent ledger exists in runtime directory; operator cleanup required",
        )
    if any(name.startswith(EXEC_RECORD_PREFIX) for name in names):
        raise _err(
            "restore-exec-outcome-unknown",
            field,
            "an earlier restore container command outcome is unknown; operator inspection required",
        )


def persist_exec_record(
    plan: LocalRuntimePlan, *, phase: str, container_id: str, outcomes: Sequence[dict[str, str]]
) -> Path:
    """Durably record unsettled container commands; no database is represented as owned."""
    invocation = uuid.uuid4().hex
    record = {
        "container_id": container_id,
        "exec_unknown": list(outcomes),
        "invocation": invocation,
        "owned_targets": [],
        "phase": phase,
        "record_type": EXEC_RECORD_TYPE,
    }
    path = plan.runtime_dir / f"{EXEC_RECORD_PREFIX}{invocation[:12]}" / "record.json"
    _write_private_json(path, (json.dumps(record, sort_keys=True) + "\n").encode("utf-8"))
    return path


def retain_unknown_commands(
    plan: LocalRuntimePlan, custody: ContainerExecCustody, primary: BaseException | None, field: str
) -> BaseException | None:
    """Durably record unsettled preflight commands with every retained control path; return the exception to raise."""
    if not custody.unknown:
        return primary
    if primary is None:
        primary = _err(
            "restore-exec-outcome-unknown", field, "a preflight container command outcome is unknown; retained"
        )
    try:
        persist_exec_record(
            plan,
            phase="preflight",
            container_id=custody.container_id,
            outcomes=[outcome.record() for outcome in custody.retained],
        )
    except BaseException as secondary:
        return chain_cleanup_failure(
            primary,
            "restore-exec-record-failed",
            field,
            f"unsettled preflight command record could not be written ({type(secondary).__name__})",
        )
    return primary


def persist_intent_ledger(ledger_path: Path, intents: Sequence[DatabaseCreationIntent]) -> None:
    payload = (json.dumps([asdict(i) for i in intents], sort_keys=True) + "\n").encode("utf-8")
    _write_private_json(ledger_path, payload)


def _write_private_json(ledger_path: Path, payload: bytes) -> None:
    """Atomically replace a 0600 file inside its private 0700 directory and fsync both."""
    ledger_dir = ledger_path.parent
    if ledger_dir.is_symlink() or ledger_path.is_symlink():
        raise _err(
            "restore-intent-ledger-failed",
            ledger_path.name,
            "restore intent ledger path cannot be a symlink",
        )
    ledger_dir.mkdir(mode=0o700, parents=False, exist_ok=True)
    ledger_dir.chmod(0o700)
    tmp_path = ledger_dir / f".{ledger_path.name}.{uuid.uuid4().hex}.tmp"
    fd = os.open(
        str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        os.fchmod(fd, 0o600)
        write_all(fd, payload)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        with suppress(OSError):
            tmp_path.unlink()
        raise
    os.close(fd)
    os.replace(tmp_path, ledger_path)
    dir_fd = os.open(str(ledger_dir), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def remove_intent_ledger(ledger_path: Path) -> None:
    try:
        with suppress(FileNotFoundError):
            ledger_path.unlink()
        with suppress(FileNotFoundError):
            ledger_path.parent.rmdir()
    except OSError as exc:
        raise _err(
            "restore-intent-ledger-cleanup-failed",
            ledger_path.name,
            "failed to remove completed restore intent ledger",
        ) from exc


class RestoreLifecycleAuthority:
    """Exclusive canonical-key custody over the maintenance database and every created target."""

    def __init__(
        self, plan: LocalRuntimePlan, connect: Callable[[str], Any], *, namespace: str
    ) -> None:
        self._plan, self._connect, self._namespace = plan, connect, namespace
        self._stack = ExitStack()
        self._maintenance: Any = None
        self._targets: dict[str, tuple[Any, ExitStack]] = {}

    def __enter__(self) -> RestoreLifecycleAuthority:
        # maintenance imports the driver; resolve it on PostgreSQL use, outside the
        # wrapping below, so SQLite Local startup stays driver-free and a missing
        # driver still surfaces as itself.
        from common_lore_index.runtime.maintenance import MaintenanceUnavailableError, maintenance_window

        try:
            self._maintenance = self._connect(self._plan.maintenance_database)
            conn = self._maintenance
            self._stack.enter_context(maintenance_window(lambda: conn))
        except (psycopg.Error, MaintenanceUnavailableError, OSError) as exc:
            self._stack.close()
            raise _err(
                "backup-maintenance-window-unavailable",
                self._plan.maintenance_database,
                "could not acquire the canonical restore maintenance lock",
            ) from exc
        return self

    def __exit__(self, *exc_info: object) -> None:
        # Release in reverse acquisition order so each custody pop matches its own binding.
        for database in reversed(list(self._targets)):
            self.release(database)
        self._stack.close()

    def held(self, database: str) -> bool:
        return database in self._targets

    def target_absent(self, database: str) -> bool:
        return (
            self._maintenance.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (database,)
            ).fetchone()
            is None
        )

    def oid_absent(self, oid: int) -> bool:
        return (
            self._maintenance.execute(
                "SELECT 1 FROM pg_database WHERE oid = %s::oid", (oid,)
            ).fetchone()
            is None
        )

    def hold_target(self, intent: DatabaseCreationIntent, *, control: bool) -> None:
        """Lock a just-created target, bind its OID and system identifier, and stamp it."""
        from common_lore_index.runtime.maintenance import (
            MaintenanceUnavailableError,
            bind_maintenance_custody,
            maintenance_window,
        )

        per_target = ExitStack()
        try:
            conn = self._connect(intent.database)
            per_target.enter_context(maintenance_window(lambda: conn))
            per_target.enter_context(
                bind_maintenance_custody(
                    mode="direct-advisory-lock-window",
                    control_database=intent.database if control else None,
                    databases=(intent.database,),
                    authority_namespace=self._namespace,
                )
            )
        except (psycopg.Error, MaintenanceUnavailableError, OSError) as exc:
            per_target.close()
            raise _err(
                "restore-target-ownership-unknown",
                intent.database,
                "created target could not be locked; ownership requires intervention",
            ) from exc
        self._targets[intent.database] = (conn, per_target)
        oid, stamp, system_identifier, locked = self._identity(intent.database)
        if not locked or stamp or system_identifier != intent.expected_system_identifier:
            raise _err(
                "restore-target-ownership-mismatch",
                intent.database,
                "created target identity, lock or stamp state is not invocation-owned",
            )
        conn.execute(
            psycopg.sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                psycopg.sql.Identifier(intent.database), psycopg.sql.Literal(intent.stamp)
            )
        )
        intent.expected_oid = oid

    def verify_baseline(self, intent: DatabaseCreationIntent, expected_baseline: str) -> None:
        """Observe the created target's own logical baseline before any installation."""
        conn, _ = self._targets[intent.database]
        digest = parse_template_baseline(
            str(conn.execute(template_baseline_sql()).fetchone()[0]), field=intent.database
        )
        if digest != expected_baseline:
            raise _err(
                "restore-template-baseline-mismatch",
                intent.database,
                "created target does not carry the qualified template1 baseline",
            )

    def _identity(self, database: str) -> tuple[int, str, str, bool]:
        from common_lore_index.runtime.maintenance import MAINTENANCE_LOCK_KEY

        conn, _ = self._targets[database]
        row = conn.execute(_IDENTITY_SQL, (MAINTENANCE_LOCK_KEY,)).fetchone()
        if row is None:
            raise _err(
                "restore-target-ownership-unknown",
                database,
                "held target identity could not be observed",
            )
        return int(row[0]), str(row[1]), str(row[2]), row[3] is True

    def verify(self, intent: DatabaseCreationIntent, *, finalized: bool = False) -> bool:
        """Revalidate OID, system identifier, held lock and stamp through the held target connection."""
        if intent.database not in self._targets or intent.expected_oid is None:
            return False
        try:
            oid, stamp, system_identifier, locked = self._identity(intent.database)
        except (psycopg.Error, LocalDbBackupError, OSError):
            return False
        return (
            locked
            and oid == intent.expected_oid
            and system_identifier == intent.expected_system_identifier
            and stamp == ("" if finalized else intent.stamp)
        )

    def finalize(self, intents: Sequence[DatabaseCreationIntent]) -> None:
        """Clear every stamp atomically while all targets remain held and verified."""
        if any(not self.verify(i) for i in intents):
            raise _err(
                "restore-target-ownership-mismatch",
                "restore finalization",
                "target ownership changed before finalizing restore",
            )
        statements = [
            psycopg.sql.SQL("COMMENT ON DATABASE {} IS NULL").format(
                psycopg.sql.Identifier(i.database)
            )
            for i in intents
        ]
        with self._maintenance.transaction():
            for statement in statements:
                self._maintenance.execute(statement)

    def release(self, database: str) -> None:
        held = self._targets.pop(database, None)
        if held is not None:
            held[1].close()


def canonical_restore_authority(plan: LocalRuntimePlan) -> RestoreLifecycleAuthority:
    """Resolve the canonical endpoint and namespace; refuse rather than bind a pretend window."""
    from common_lore_index.runtime.maintenance import runtime_maintenance_namespace

    try:
        endpoint = execution_postgres(load_ops_config_home(plan.repo_map_home))
        password = runtime_postgres_password(plan)
    except Exception as exc:
        raise _err(
            "backup-maintenance-window-unavailable",
            plan.maintenance_database,
            "could not resolve the Postgres endpoint for restore custody",
        ) from exc
    namespace = runtime_maintenance_namespace(
        plan.repo_map_home, host=endpoint.host, port=endpoint.port
    )

    def connect(database: str) -> Any:
        return psycopg.connect(
            host=endpoint.host,
            port=endpoint.port,
            user=plan.user,
            dbname=database,
            password=password,
            connect_timeout=10,
            options=_CONNECT_OPTIONS,
            autocommit=True,
        )

    return RestoreLifecycleAuthority(plan, connect, namespace=namespace)
