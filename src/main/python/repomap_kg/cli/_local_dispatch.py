"""Local-runtime command dispatch for the RepoMap CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import nullcontext
from types import ModuleType


def dispatch_local_command(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    commands: ModuleType,
    *,
    print_cli_error: Callable[..., None],
) -> int:
    LocalDbBackupError = commands.LocalDbBackupError
    LocalRuntimeError = commands.LocalRuntimeError
    MaintenanceUnavailableError = commands.MaintenanceUnavailableError
    OpsConfigError = commands.OpsConfigError
    down_local_runtime = commands.down_local_runtime
    drop_database = commands.drop_database
    dump_all_databases = commands.dump_all_databases
    dump_database = commands.dump_database
    format_backup_info_table = commands.format_backup_info_table
    format_backup_inspect_table = commands.format_backup_inspect_table
    format_backup_listing_table = commands.format_backup_listing_table
    format_backup_result_table = commands.format_backup_result_table
    format_coordinated_restore_table = commands.format_coordinated_restore_table
    format_drop_result_table = commands.format_drop_result_table
    format_graph_schema_upgrade_table = commands.format_graph_schema_upgrade_table
    format_init_result_table = commands.format_init_result_table
    format_local_runtime_table = commands.format_local_runtime_table
    init_database_from_dump = commands.init_database_from_dump
    init_database_from_source = commands.init_database_from_source
    inspect_backup = commands.inspect_backup
    json = commands.json
    list_backups = commands.list_backups
    maintenance_window_for_database_drop = (
        commands.maintenance_window_for_database_drop
    )
    maintenance_window_for_coordinated_backup = (
        commands.maintenance_window_for_coordinated_backup
    )
    maintenance_window_for_graph_upgrade = (
        commands.maintenance_window_for_graph_upgrade
    )
    query_local_runtime_status = commands.query_local_runtime_status
    read_backup_info = commands.read_backup_info
    restore_coordinated_backup = commands.restore_coordinated_backup
    setup_local_runtime = commands.setup_local_runtime
    sys = commands.sys
    up_local_runtime = commands.up_local_runtime
    upgrade_graph_schema = commands.upgrade_graph_schema

    try:
        if args.local_command == "db":
            if args.local_db_command == "dump":
                backup_result = dump_database(
                    args.repo_map_home,
                    database=args.database,
                    dry_run=args.dry_run,
                    reason=args.reason,
                )
                if args.json:
                    print(json.dumps(backup_result.to_jsonable(), sort_keys=True))
                else:
                    print(format_backup_result_table(backup_result))
                return 0
            if args.local_db_command == "dump-all":
                window = (
                    nullcontext()
                    if args.dry_run
                    else maintenance_window_for_coordinated_backup(
                        args.repo_map_home,
                    )
                )
                with window:
                    backup_result = dump_all_databases(
                        args.repo_map_home,
                        dry_run=args.dry_run,
                        reason=args.reason,
                        stable_recovery_point=not args.dry_run,
                    )
                if args.json:
                    print(json.dumps(backup_result.to_jsonable(), sort_keys=True))
                else:
                    print(format_backup_result_table(backup_result))
                return 0
            if args.local_db_command == "restore-all":
                restore_result = restore_coordinated_backup(
                    args.repo_map_home,
                    backup=args.from_dump,
                    dry_run=args.dry_run,
                )
                if args.json:
                    print(json.dumps(restore_result.to_jsonable(), sort_keys=True))
                else:
                    print(format_coordinated_restore_table(restore_result))
                return 0
            if args.local_db_command == "backups":
                listing = list_backups(args.repo_map_home)
                if args.json:
                    print(json.dumps(listing.to_jsonable(), sort_keys=True))
                else:
                    print(format_backup_listing_table(listing))
                return 0
            if args.local_db_command == "backup-info":
                info = read_backup_info(
                    args.repo_map_home,
                    args.backup_id_or_path,
                )
                if args.json:
                    print(json.dumps(info.to_jsonable(), sort_keys=True))
                else:
                    print(format_backup_info_table(info))
                return 0
            if args.local_db_command == "backup-inspect":
                info = inspect_backup(
                    args.repo_map_home,
                    args.backup_id_or_path,
                )
                if args.json:
                    print(json.dumps(info.to_jsonable(), sort_keys=True))
                else:
                    print(format_backup_inspect_table(info))
                return 0
            if args.local_db_command == "init":
                if args.from_source:
                    init_result = init_database_from_source(
                        args.repo_map_home,
                        database=args.database,
                        dry_run=args.dry_run,
                    )
                else:
                    init_result = init_database_from_dump(
                        args.repo_map_home,
                        database=args.database,
                        backup=args.from_dump,
                        dry_run=args.dry_run,
                    )
                if args.json:
                    print(json.dumps(init_result.to_jsonable(), sort_keys=True))
                else:
                    print(format_init_result_table(init_result))
                return 0
            if args.local_db_command == "upgrade-schema":
                window = (
                    nullcontext()
                    if args.dry_run
                    else maintenance_window_for_graph_upgrade(
                        args.repo_map_home,
                        args.database,
                    )
                )
                with window:
                    upgrade_result = upgrade_graph_schema(
                        args.repo_map_home,
                        database=args.database,
                        backup_first=args.backup_first,
                        confirmed=args.yes,
                        dry_run=args.dry_run,
                        reason=args.reason,
                    )
                if args.json:
                    print(json.dumps(upgrade_result.to_jsonable(), sort_keys=True))
                else:
                    print(format_graph_schema_upgrade_table(upgrade_result))
                return 0
            if args.local_db_command == "drop":
                window = (
                    nullcontext()
                    if args.dry_run or not args.backup_first or not args.yes
                    else maintenance_window_for_database_drop(
                        args.repo_map_home,
                        args.database,
                    )
                )
                with window:
                    drop_result = drop_database(
                        args.repo_map_home,
                        database=args.database,
                        backup_first=args.backup_first,
                        confirmed=args.yes,
                        dry_run=args.dry_run,
                        reason=args.reason,
                    )
                if args.json:
                    print(json.dumps(drop_result.to_jsonable(), sort_keys=True))
                else:
                    print(format_drop_result_table(drop_result))
                return 0
            parser.print_help()
            return 0
        if args.local_command == "setup":
            result = setup_local_runtime(
                args.repo_map_home,
                dry_run=args.dry_run,
            )
        elif args.local_command == "up":
            result = up_local_runtime(
                args.repo_map_home,
                dry_run=args.dry_run,
            )
        elif args.local_command == "down":
            result = down_local_runtime(
                args.repo_map_home,
                dry_run=args.dry_run,
            )
        elif args.local_command == "status":
            result = query_local_runtime_status(
                args.repo_map_home,
                check_containers=args.check_containers,
            )
        else:
            parser.print_help()
            return 0
    except (
        LocalRuntimeError,
        LocalDbBackupError,
        MaintenanceUnavailableError,
        OpsConfigError,
    ) as error:
        print_cli_error(error, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.to_jsonable(), sort_keys=True))
    else:
        print(format_local_runtime_table(result))
    return 0
