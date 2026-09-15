"""Local-runtime command parser construction for the RepoMap CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable


LocalArgumentHelper = Callable[[argparse.ArgumentParser], None]


def add_local_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    add_local_runtime_arguments: LocalArgumentHelper,
) -> None:
    local = subparsers.add_parser(
        "local",
        help="manage the local containerized RepoMap runtime",
    )
    local_subcommands = local.add_subparsers(dest="local_command")
    local_setup = local_subcommands.add_parser(
        "setup",
        help="create local runtime files under REPOMAP_HOME",
    )
    add_local_runtime_arguments(local_setup)
    local_setup.add_argument(
        "--dry-run",
        action="store_true",
        help="show setup plan without creating files",
    )
    local_setup.add_argument(
        "--json",
        action="store_true",
        help="emit local setup result as JSON",
    )
    local_up = local_subcommands.add_parser(
        "up",
        help="start the local containerized RepoMap runtime",
    )
    add_local_runtime_arguments(local_up)
    local_up.add_argument(
        "--dry-run",
        action="store_true",
        help="render planned runtime command without starting containers",
    )
    local_up.add_argument(
        "--json",
        action="store_true",
        help="emit local up result as JSON",
    )
    local_down = local_subcommands.add_parser(
        "down",
        help="stop RepoMap-owned local runtime containers",
    )
    add_local_runtime_arguments(local_down)
    local_down.add_argument(
        "--dry-run",
        action="store_true",
        help="render planned runtime command without stopping containers",
    )
    local_down.add_argument(
        "--json",
        action="store_true",
        help="emit local down result as JSON",
    )
    local_status = local_subcommands.add_parser(
        "status",
        help="report local runtime files and safe connection info",
    )
    add_local_runtime_arguments(local_status)
    local_status.add_argument(
        "--check-containers",
        action="store_true",
        help="check whether the configured container runtime command is available",
    )
    local_status.add_argument(
        "--json",
        action="store_true",
        help="emit local runtime status as JSON",
    )
    local_db = local_subcommands.add_parser(
        "db",
        help="backup-only local runtime database administration",
    )
    local_db_subcommands = local_db.add_subparsers(dest="local_db_command")
    local_db_dump = local_db_subcommands.add_parser(
        "dump",
        help="dump one RepoMap-owned runtime database",
    )
    add_local_runtime_arguments(local_db_dump)
    local_db_dump.add_argument("--database", required=True)
    local_db_dump.add_argument("--reason")
    local_db_dump.add_argument(
        "--dry-run",
        action="store_true",
        help="plan the backup without running pg_dump or creating files",
    )
    local_db_dump.add_argument(
        "--json",
        action="store_true",
        help="emit dump result as JSON",
    )
    local_db_dump_all = local_db_subcommands.add_parser(
        "dump-all",
        help="dump configured RepoMap-owned runtime databases",
    )
    add_local_runtime_arguments(local_db_dump_all)
    local_db_dump_all.add_argument("--reason")
    local_db_dump_all.add_argument(
        "--dry-run",
        action="store_true",
        help="plan the backup without running pg_dump or creating files",
    )
    local_db_dump_all.add_argument(
        "--json",
        action="store_true",
        help="emit dump-all result as JSON",
    )
    local_db_restore_all = local_db_subcommands.add_parser(
        "restore-all",
        help="restore one complete coordinated graph/control backup set",
    )
    add_local_runtime_arguments(local_db_restore_all)
    local_db_restore_all.add_argument("--from-dump", required=True)
    local_db_restore_all.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and preflight without creating or restoring databases",
    )
    local_db_restore_all.add_argument(
        "--json",
        action="store_true",
        help="emit restore-all result as JSON",
    )
    local_db_backups = local_db_subcommands.add_parser(
        "backups",
        help="list local runtime backup manifests",
    )
    add_local_runtime_arguments(local_db_backups)
    local_db_backups.add_argument(
        "--json",
        action="store_true",
        help="emit backup listing as JSON",
    )
    local_db_backup_info = local_db_subcommands.add_parser(
        "backup-info",
        help="show one local runtime backup manifest",
    )
    add_local_runtime_arguments(local_db_backup_info)
    local_db_backup_info.add_argument("backup_id_or_path")
    local_db_backup_info.add_argument(
        "--json",
        action="store_true",
        help="emit backup info as JSON",
    )
    local_db_backup_inspect = local_db_subcommands.add_parser(
        "backup-inspect",
        help="inspect one local runtime backup manifest and dump TOC",
    )
    add_local_runtime_arguments(local_db_backup_inspect)
    local_db_backup_inspect.add_argument("backup_id_or_path")
    local_db_backup_inspect.add_argument(
        "--json",
        action="store_true",
        help="emit backup inspection as JSON",
    )
    local_db_init = local_db_subcommands.add_parser(
        "init",
        help="initialize a new RepoMap-owned runtime database",
    )
    add_local_runtime_arguments(local_db_init)
    local_db_init.add_argument("--database", required=True)
    init_source = local_db_init.add_mutually_exclusive_group(required=True)
    init_source.add_argument(
        "--from-source",
        action="store_true",
        help="initialize a new database from RepoMap source migrations",
    )
    init_source.add_argument(
        "--from-dump",
        help="initialize a new database from a validated backup dump",
    )
    local_db_init.add_argument(
        "--dry-run",
        action="store_true",
        help="plan the init without creating or restoring a database",
    )
    local_db_init.add_argument(
        "--json",
        action="store_true",
        help="emit init result as JSON",
    )
    local_db_upgrade = local_db_subcommands.add_parser(
        "upgrade-schema",
        help="adopt an exact pre-ledger graph schema after verified backup",
    )
    add_local_runtime_arguments(local_db_upgrade)
    local_db_upgrade.add_argument("--database", required=True)
    local_db_upgrade.add_argument(
        "--backup-first",
        action="store_true",
        help="required: create and inspect a restorable backup before adoption",
    )
    local_db_upgrade.add_argument(
        "--yes",
        action="store_true",
        help="confirm a non-dry-run schema adoption",
    )
    local_db_upgrade.add_argument("--reason")
    local_db_upgrade.add_argument(
        "--dry-run",
        action="store_true",
        help="plan schema adoption without backup or database changes",
    )
    local_db_upgrade.add_argument(
        "--json",
        action="store_true",
        help="emit graph schema upgrade result as JSON",
    )
    local_db_drop = local_db_subcommands.add_parser(
        "drop",
        help="drop one RepoMap-owned runtime database after a verified backup",
    )
    add_local_runtime_arguments(local_db_drop)
    local_db_drop.add_argument("--database", required=True)
    local_db_drop.add_argument(
        "--backup-first",
        action="store_true",
        help="required: create and verify a backup before dropping",
    )
    local_db_drop.add_argument(
        "--yes",
        action="store_true",
        help="confirm a non-dry-run backup-first drop",
    )
    local_db_drop.add_argument("--reason")
    local_db_drop.add_argument(
        "--dry-run",
        action="store_true",
        help="plan backup-first drop without creating a backup or dropping a database",
    )
    local_db_drop.add_argument(
        "--json",
        action="store_true",
        help="emit drop result as JSON",
    )
