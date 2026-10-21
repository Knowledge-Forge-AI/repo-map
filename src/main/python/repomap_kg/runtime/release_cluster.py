"""Container-native initialization and status for the release cluster."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple, Protocol

import psycopg
from psycopg import sql

from repomap_kg.coordinator._lifecycle_authority import _MaintenanceWindowAuthority, _maintenance_window
from repomap_kg.coordinator.local_lifecycle import (
    LocalControlAuthority, coordinator_control_status, initialize_coordinator_control, upgrade_coordinator_control,
)
from repomap_kg.ops.config_loading import load_ops_config_home
from repomap_kg.ops.resolved_config import resolve_ops_config
from repomap_kg.runtime._backup_support import (
    build_and_verify_release_cluster_upgrade_manifest,
    evaluate_release_cluster_upgrade_artifact,
    load_and_verify_release_cluster_upgrade_artifact,
    observe_connection_provenance,
)
from repomap_kg.runtime.backup_commands import timestamp_utc
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.backup_streaming import (
    atomic_private_backup_directory, stream_pg_dump_to_file, write_private_text,
)
from repomap_kg.runtime.database_role_contract import read_role_secrets
from repomap_kg.runtime.database_roles import render_database_role_sql
from repomap_kg.runtime.maintenance import runtime_maintenance_namespace
from repomap_kg.runtime.plan import build_local_runtime_plan
from repomap_kg.runtime.postgres_route import execution_postgres
from repomap_kg.runtime.release import PACKAGED_PG_DUMP, PACKAGED_PG_RESTORE
from repomap_kg.storage import (
    discover_migrations, graph_schema_forward_sql, graph_schema_initialization_sql,
)


class ReleaseClusterError(RuntimeError):
    """Bounded release-cluster lifecycle failure."""


class GraphOperator(Protocol):
    databases: tuple[str, ...]
    expected_count: int

    def database_exists(self, database: str) -> bool: ...
    def create_database(self, database: str) -> None: ...
    def schema_state(self, database: str) -> tuple[str, int]: ...
    def initialize_schema(self, database: str) -> None: ...
    def upgrade_schema(self, database: str, applied_count: int) -> None: ...
    def reconcile_roles(self, database: str) -> None: ...
    def drop_created_database(self, database: str) -> None: ...


class _ControlBackupPlan(NamedTuple):
    backup_path: Path


class _ControlDumpResult(NamedTuple):
    plan: _ControlBackupPlan


class _ControlInspectResult(NamedTuple):
    checksum_verified: bool
    dump_summaries: tuple[object, ...]
    manifest: dict[str, object]


def _initialize_or_upgrade_control(repo_map_home: str | Path) -> dict[str, object]:
    authority = LocalControlAuthority(repo_map_home)
    if not authority.database_exists() or authority.control_store().schema_readiness().status.value != "preledger":
        return initialize_coordinator_control(repo_map_home, authority_factory=lambda _home: authority)

    operator = ReleaseGraphOperator(repo_map_home)
    verified_backups: set[Path] = set()
    target_home = repo_map_home

    def dump_control(
        repo_map_home: str | Path | None, *, database: str, reason: str | None = None, timestamp: str | None = None,
    ) -> _ControlDumpResult:
        del reason, timestamp
        backup_path = _backup_graph_before_upgrade(repo_map_home or target_home, operator, database)
        verified_backups.add(backup_path)
        return _ControlDumpResult(plan=_ControlBackupPlan(backup_path=backup_path))

    def inspect_control(repo_map_home: str | Path | None, backup_id_or_path: str | Path) -> _ControlInspectResult:
        del repo_map_home
        backup_path = Path(backup_id_or_path)
        if backup_path not in verified_backups:
            raise ReleaseClusterError("release_cluster_control_backup_unverified")
        target_db = str(getattr(authority, "database_name", "repomap_control"))
        try:
            verified_manifest, _eval = load_and_verify_release_cluster_upgrade_artifact(
                backup_path, database=target_db, verify_dump_on_disk=True
            )
        except LocalDbBackupError:
            raise ReleaseClusterError("release_cluster_control_backup_unverified") from None
        summary = verified_manifest.pop("_verified_toc_summary", None)
        return _ControlInspectResult(
            checksum_verified=True,
            dump_summaries=(summary,) if summary is not None else (),
            manifest=verified_manifest,
        )

    return upgrade_coordinator_control(
        repo_map_home, backup_first=True, confirmed=True, dry_run=False,
        reason="release-cluster-control-upgrade", authority_factory=lambda _home: authority,
        dump_function=dump_control, inspect_function=inspect_control,
    )


def initialize_release_cluster(
    repo_map_home: str | Path,
    *,
    operator_factory: Callable[[str | Path], GraphOperator] | None = None,
    control_initializer: Callable[[str | Path], dict[str, object]] = _initialize_or_upgrade_control,
    authority_factory: Callable[[str | Path], _MaintenanceWindowAuthority] = LocalControlAuthority,
    backup_function: Callable[[str | Path, GraphOperator, str], object] | None = None,
    control_cleanup: Callable[[str | Path], None] | None = None,
) -> dict[str, object]:
    """Initialize or backup-first advance the complete owned release topology."""

    factory = operator_factory or ReleaseGraphOperator
    backup = backup_function or _backup_graph_before_upgrade
    cleanup_control = control_cleanup or _cleanup_created_control
    operator: GraphOperator | None = None
    created_databases: list[str] = []
    control_created = False
    try:
        operator = factory(repo_map_home)
        missing: list[str] = []
        upgrades: list[tuple[str, int]] = []
        current = 0
        for database in operator.databases:
            if not operator.database_exists(database):
                missing.append(database)
                continue
            state, applied_count = operator.schema_state(database)
            if state == "uninitialized":
                raise ReleaseClusterError("release_cluster_graph_adoption_refused")
            elif state == "behind":
                upgrades.append((database, applied_count))
            elif state == "current":
                current += 1
            else:
                raise ReleaseClusterError("release_cluster_graph_schema_refused")

        control = control_initializer(repo_map_home)
        control_created = bool(control.get("database_created"))
        for database in missing:
            operator.create_database(database)
            created_databases.append(database)
            operator.initialize_schema(database)

        if upgrades:
            authority = authority_factory(repo_map_home)
            targets = tuple(database for database, _count in upgrades)
            with _maintenance_window(authority, graph_databases=targets):
                for database, applied_count in upgrades:
                    backup_path = backup(repo_map_home, operator, database)
                    if not isinstance(backup_path, Path):
                        raise ReleaseClusterError("release_cluster_upgrade_backup_invalid")
                    try:
                        load_and_verify_release_cluster_upgrade_artifact(backup_path, database=database, verify_dump_on_disk=True)
                    except LocalDbBackupError as exc:
                        raise ReleaseClusterError("release_cluster_upgrade_backup_invalid") from exc
                    operator.upgrade_schema(database, applied_count)

        for database in operator.databases:
            operator.reconcile_roles(database)
            state, applied_count = operator.schema_state(database)
            if state != "current" or applied_count != operator.expected_count:
                raise ReleaseClusterError("release_cluster_graph_not_ready")
        return {
            "command": "release-cluster-init", "result": "ready",
            "control_created": control_created,
            "graph_database_count": len(operator.databases),
            "graph_database_created_count": len(created_databases),
            "graph_schema_initialized_count": len(created_databases),
            "graph_schema_upgraded_count": len(upgrades),
            "graph_schema_current_count": current,
            "backup_first_upgrade_count": len(upgrades),
        }
    except Exception as error:
        cleanup_failed = False
        if operator is not None:
            for database in reversed(created_databases):
                try:
                    operator.drop_created_database(database)
                except Exception:
                    cleanup_failed = True
        if control_created:
            try:
                cleanup_control(repo_map_home)
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            raise ReleaseClusterError("release_cluster_cleanup_failed") from None
        if isinstance(error, ReleaseClusterError):
            raise
        raise ReleaseClusterError("release_cluster_initialization_failed") from None


def _cleanup_created_control(repo_map_home: str | Path) -> None:
    LocalControlAuthority(repo_map_home).drop_created_database()


def release_cluster_status(
    repo_map_home: str | Path,
    *,
    operator_factory: Callable[[str | Path], GraphOperator] | None = None,
    control_status: Callable[[str | Path], dict[str, object]] = coordinator_control_status,
) -> dict[str, object]:
    """Return bounded exact-current status without database identities."""

    factory = operator_factory or ReleaseGraphOperator
    try:
        operator = factory(repo_map_home)
        control = control_status(repo_map_home)
        current = 0
        unavailable = 0
        for database in operator.databases:
            if not operator.database_exists(database):
                unavailable += 1
                continue
            state, applied_count = operator.schema_state(database)
            if state == "current" and applied_count == operator.expected_count:
                current += 1
            else:
                unavailable += 1
        ready = control.get("result") == "ready" and unavailable == 0
        return {
            "command": "release-cluster-status", "result": "ready" if ready else "not_ready",
            "control_schema_ready": control.get("result") == "ready",
            "graph_database_count": len(operator.databases),
            "graph_schema_ready_count": current,
            "graph_schema_unavailable_count": unavailable,
        }
    except ReleaseClusterError:
        raise
    except Exception:
        raise ReleaseClusterError("release_cluster_status_failed") from None


class ReleaseGraphOperator:
    """Direct installed-resource graph lifecycle for one isolated container."""

    def __init__(self, repo_map_home: str | Path) -> None:
        self.home = Path(repo_map_home)
        self.plan = build_local_runtime_plan(self.home)
        self.config = load_ops_config_home(self.home)
        resolved = resolve_ops_config(self.config)
        self.databases = tuple(sorted(str(graph.database) for graph in resolved.graphs))
        self.control_database = str(resolved.control_database)
        self.maintenance_database = str(resolved.maintenance_database)
        self.expected = tuple(
            (m.ordinal, m.changeset_id, m.relative_path, m.checksum)
            for m in discover_migrations()
        )
        self.expected_count = len(self.expected)
        self.password = _runtime_password(self.plan.env_file)
        self.role_secrets = read_role_secrets(self.plan.env_file)
        ep = execution_postgres(self.config)
        self.authority_namespace = runtime_maintenance_namespace(self.home, host=ep.host, port=ep.port)

    def database_exists(self, database: str) -> bool:
        with self._connect(self.maintenance_database) as connection:
            row = connection.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = %s)", (database,)
            ).fetchone()
        return bool(row and row[0])

    def create_database(self, database: str) -> None:
        stmt = sql.SQL(
            "CREATE DATABASE {} WITH TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C'"
        )
        with self._connect(self.maintenance_database, autocommit=True) as connection:
            connection.execute(stmt.format(sql.Identifier(database)))

    def schema_state(self, database: str) -> tuple[str, int]:
        with self._connect(database) as connection:
            ledger = connection.execute(
                "SELECT to_regclass('public.repomap_schema_migrations')"
            ).fetchone()
            if not ledger or ledger[0] is None:
                row = connection.execute(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                ).fetchone()
                return ("uninitialized", 0) if row and row[0] == 0 else ("refused", 0)
            rows = connection.execute(
                "SELECT ordinal, changeset_id, migration_path, checksum "
                "FROM repomap_schema_migrations ORDER BY ordinal"
            ).fetchall()
        applied = tuple((row[0], row[1], row[2], row[3]) for row in rows)
        if applied == self.expected:
            return "current", len(applied)
        if applied and applied == self.expected[: len(applied)]:
            return "behind", len(applied)
        return "refused", len(applied)

    def initialize_schema(self, database: str) -> None:
        with self._connect(database, autocommit=True) as connection:
            connection.execute(graph_schema_initialization_sql())

    def upgrade_schema(self, database: str, applied_count: int) -> None:
        with self._connect(database, autocommit=True) as connection:
            connection.execute(graph_schema_forward_sql(applied_count))

    def reconcile_roles(self, database: str) -> None:
        role_sql = render_database_role_sql(
            database=database,
            owner_role=self.plan.user,
            database_kind="graph",
            secrets=self.role_secrets,
        )
        with self._connect(database, autocommit=True) as connection:
            connection.execute(role_sql)

    def drop_created_database(self, database: str) -> None:
        if database not in self.databases:
            raise ReleaseClusterError("release_cluster_cleanup_refused")
        with self._connect(self.maintenance_database, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))

    def pg_dump_command(self, database: str) -> tuple[str, ...]:
        p = self.config.postgres
        ep = execution_postgres(self.config)
        return (
            PACKAGED_PG_DUMP, "-Fc", "-h", ep.host, "-p", str(ep.port),
            "-U", p.user, "-d", database,
        )

    def _connect(self, database: str, *, autocommit: bool = False):
        p = self.config.postgres
        ep = execution_postgres(self.config)
        return psycopg.connect(
            host=ep.host, port=ep.port, user=p.user, dbname=database,
            password=self.password, autocommit=autocommit, connect_timeout=10,
        )


def _backup_graph_before_upgrade(
    repo_map_home: str | Path,
    operator: GraphOperator,
    database: str,
) -> Path:
    del repo_map_home
    if not isinstance(operator, ReleaseGraphOperator) or not getattr(operator, "authority_namespace", None):
        raise ReleaseClusterError("release_cluster_backup_operator_invalid")
    admin_root = Path(os.environ.get("REPOMAP_ADMIN_ROOT", "/repo-map-admin"))
    stamp = timestamp_utc().replace(":", "-")
    final = admin_root / "schema-upgrades" / stamp / database
    with atomic_private_backup_directory(final, backups_root=admin_root) as staging:
        try:
            before_obs = observe_connection_provenance(operator, database)
            dump = stream_pg_dump_to_file(
                operator.plan, operator.pg_dump_command(database), subprocess.run, staging / "database.dump"
            )
            env = os.environ.copy()
            env["PGPASSWORD"] = operator.password
            manifest = build_and_verify_release_cluster_upgrade_manifest(
                operator=operator, database=database, dump=dump, dump_path=staging / dump.name,
                restore_client=PACKAGED_PG_RESTORE, command_runner=subprocess.run, env=env, before_obs=before_obs,
            )
            write_private_text(
                staging / "schema-upgrade.json",
                json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            )
            evaluate_release_cluster_upgrade_artifact(manifest, database=database)
        except LocalDbBackupError as exc:
            raise ReleaseClusterError("release_cluster_upgrade_backup_invalid") from exc
    return final


def _runtime_password(env_file: Path) -> str:
    values = dict(
        line.split("=", 1) for line in env_file.read_text(encoding="utf-8").splitlines() if "=" in line
    )
    password = values.get("REPOMAP_PG_PASSWORD") or values.get("POSTGRES_PASSWORD")
    if not password or len(password) > 256:
        raise ReleaseClusterError("release_cluster_credential_unavailable")
    return password


__all__ = [
    "ReleaseClusterError", "ReleaseGraphOperator",
    "initialize_release_cluster", "release_cluster_status",
]
