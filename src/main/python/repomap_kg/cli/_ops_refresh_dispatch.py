"""Ops config, graph, and refresh command dispatch for the RepoMap CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import nullcontext
import json
import sys
from types import ModuleType

from repomap_kg.cli.staging_event_instrumentation import (
    staging_event_instrumentation,
)

__all__ = ("dispatch_ops_refresh_command",)


def dispatch_ops_refresh_command(
    args: argparse.Namespace,
    commands: ModuleType,
    print_cli_error: Callable[..., None],
) -> int | None:
    if args.command != "ops":
        return None

    if args.ops_command == "config-check":
        try:
            config = commands.load_ops_config_from_args(args)
            postgres_status = (
                commands.check_ops_postgres_status(config, psql_command=args.psql_command)
                if args.check_db
                else None
            )
        except commands.OpsConfigError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    commands.ops_config_status_to_jsonable(
                        config,
                        postgres_status=postgres_status,
                    ),
                    sort_keys=True,
                )
            )
        else:
            print(
                commands.format_ops_config_status_table(
                    config,
                    postgres_status=postgres_status,
                )
            )
        return 0

    if args.ops_command == "graphs":
        try:
            config = commands.load_ops_config_from_args(args)
            graph_storage_status = (
                commands.check_ops_graph_storage_status(
                    config,
                    psql_command=args.psql_command,
                )
                if args.check_db
                else None
            )
        except commands.OpsConfigError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    commands.ops_graph_registry_status_to_jsonable(
                        config,
                        graph_storage_status=graph_storage_status,
                    ),
                    sort_keys=True,
                )
            )
        else:
            print(
                commands.format_ops_graph_registry_table(
                    config,
                    graph_storage_status=graph_storage_status,
                )
            )
        return 0

    if args.ops_command == "refresh-graph":
        if args.mode == "coordinator":
            if (
                getattr(args, "backend_telemetry_fd", None) is not None
                or getattr(args, "backend_telemetry_ack_fd", None) is not None
                or getattr(args, "staging_event_fd", None) is not None
            ):
                print_cli_error(
                    commands.CoordinatorModeError("coordinator_rejects_backend_telemetry"),
                    file=sys.stderr,
                )
                return 1
            if not args.repo_map_home or args.config:
                print_cli_error(
                    commands.CoordinatorModeError("coordinator_requires_repo_map_home"),
                    file=sys.stderr,
                )
                return 1
            if not args.idempotency_key:
                print_cli_error(
                    commands.CoordinatorModeError("coordinator_requires_idempotency_key"),
                    file=sys.stderr,
                )
                return 1
            if args.psql_command:
                print_cli_error(
                    commands.CoordinatorModeError("coordinator_rejects_psql_command"),
                    file=sys.stderr,
                )
                return 1
            try:
                payload = commands.run_coordinator_refresh(
                    args.repo_map_home,
                    args.graph,
                    args.idempotency_key,
                    wait_timeout_seconds=args.coordinator_wait_seconds,
                )
            except (commands.CoordinatorClientError, commands.CoordinatorModeError) as error:
                print_cli_error(error, file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print(commands.format_coordinator_refresh_table(payload))
            return 0 if payload["result"] == "success" else 1
        try:
            backend_telemetry = None
            backend_telemetry_fd = getattr(args, "backend_telemetry_fd", None)
            backend_telemetry_ack_fd = getattr(
                args, "backend_telemetry_ack_fd", None
            )
            if (backend_telemetry_fd is None) != (
                backend_telemetry_ack_fd is None
            ):
                raise commands.ConnectionTelemetryError(
                    "backend telemetry channel is unavailable"
                )
            if backend_telemetry_fd is not None:
                backend_telemetry = commands.telemetry_from_inherited_fds(
                    backend_telemetry_fd,
                    backend_telemetry_ack_fd,
                )
            with staging_event_instrumentation(
                getattr(args, "staging_event_fd", None),
                channel_factory=commands.staging_event_channel_from_inherited_fd,
                measurements_factory=commands.StagingMeasurements,
            ) as staging_measurements:
                config = commands.load_ops_config_from_args(args)
                admission = (
                    commands.maintenance_activity_for_home(args.repo_map_home)
                    if args.repo_map_home
                    else nullcontext()
                )
                with admission:
                    result = commands.refresh_graph(
                        config,
                        args.graph,
                        psql_command=args.psql_command,
                        ingestion_mode="staged",
                        backend_telemetry=backend_telemetry,
                        staging_measurements=staging_measurements,
                    )
        except (
            commands.ConnectionTelemetryError,
            commands.MaintenanceUnavailableError,
            commands.OpsConfigError,
            commands.OpsRefreshError,
            commands.StagingEventTransportError,
        ) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        payload = commands.refresh_result_to_jsonable(
            config,
            [result],
            command="refresh-graph",
        )
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(commands.format_refresh_result_table(config, [result], command="refresh-graph"))
        return 0 if payload["result"] == "success" else 1

    if args.ops_command == "refresh-preflight":
        try:
            config = commands.load_ops_config_from_args(args)
            result = commands.preflight_graph(config, args.graph)
        except (commands.OpsConfigError, commands.OpsRefreshError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        payload = commands.preflight_to_jsonable(config, result)
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(commands.format_preflight_table(config, result))
        return 0 if payload["result"] == "success" else 1

    if args.ops_command == "refresh-enabled":
        try:
            config = commands.load_ops_config_from_args(args)
            admission = (
                commands.maintenance_activity_for_home(args.repo_map_home)
                if args.repo_map_home
                else nullcontext()
            )
            with admission:
                results = commands.refresh_enabled_graphs(
                    config,
                    psql_command=args.psql_command,
                )
        except (commands.MaintenanceUnavailableError, commands.OpsConfigError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        payload = commands.refresh_result_to_jsonable(
            config,
            results,
            command="refresh-enabled",
        )
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(
                commands.format_refresh_result_table(
                    config,
                    results,
                    command="refresh-enabled",
                )
            )
        return 0 if payload["result"] == "success" else 1

    if args.ops_command == "refresh-status":
        try:
            config = commands.load_ops_config_from_args(args)
            statuses = commands.query_refresh_status(
                config,
                graph_ids=args.graph,
                psql_command=args.psql_command,
            )
        except (commands.OpsConfigError, commands.OpsRefreshError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    commands.refresh_status_to_jsonable(config, statuses, graph_ids=args.graph),
                    sort_keys=True,
                )
            )
        else:
            print(commands.format_refresh_status_table(config, statuses, graph_ids=args.graph))
        return 0

    if args.ops_command == "graph-summary":
        try:
            config = commands.load_ops_config_from_args(args)
            summary = commands.query_graph_summary(
                config,
                args.graph,
                psql_command=args.psql_command,
            )
        except (commands.OpsConfigError, commands.OpsRefreshError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    commands.graph_summary_to_jsonable(config, summary),
                    sort_keys=True,
                )
            )
        else:
            print(commands.format_graph_summary_table(config, summary))
        return 0 if summary.result == "success" else 1

    return None
