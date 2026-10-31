"""Ops control, coordinator, service, and jobs parser construction for RepoMap CLI."""

from __future__ import annotations

import argparse

__all__ = ("add_ops_control_commands",)


def add_ops_control_commands(
    ops_subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    coordinator_serve = ops_subcommands.add_parser(
        "coordinator-serve",
        help="run the configured machine-local coordinator in the foreground",
    )
    coordinator_serve.add_argument(
        "--repo-map-home",
        required=True,
        help="REPOMAP_HOME that owns configuration and the private endpoint",
    )
    coordinator_serve.add_argument(
        "--json",
        action="store_true",
        help="emit bounded coordinator readiness as JSON",
    )
    coordinator_serve.add_argument(
        "--service-package-environment",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    coordinator_serve.add_argument(
        "--service-package-psql",
        help=argparse.SUPPRESS,
    )
    coordinator_serve.add_argument(
        "--startup-wait-seconds",
        type=int,
        default=0,
        help=argparse.SUPPRESS,
    )
    for command_name, command_help in (
        (
            "release-cluster-init",
            "initialize or backup-first upgrade the release cluster",
        ),
        (
            "release-cluster-status",
            "inspect bounded release-cluster schema readiness",
        ),
    ):
        release_cluster = ops_subcommands.add_parser(
            command_name,
            help=command_help,
        )
        release_cluster.add_argument(
            "--repo-map-home",
            required=True,
            help="container-mounted RepoMap configuration authority",
        )
        release_cluster.add_argument(
            "--json",
            action="store_true",
            help="emit bounded release-cluster state as JSON",
        )
    coordinator_service = ops_subcommands.add_parser(
        "coordinator-service",
        help="manage portable native user-service packaging",
    )
    coordinator_service_subcommands = coordinator_service.add_subparsers(
        dest="coordinator_service_action",
        required=True,
    )
    for action_name, action_help in (
        ("install", "install a validated owner-private native definition"),
        ("status", "inspect bounded native and coordinator readiness state"),
        ("start", "explicitly enable or load and start the user service"),
        ("stop", "explicitly stop and disable or unload the user service"),
        ("restart", "explicitly restart the installed user service"),
        ("upgrade", "replace an owned definition with rollback"),
        ("uninstall", "stop and remove only an owned definition"),
        ("render", "render the native definition without manager mutation"),
        ("validate", "validate generated and installed definitions"),
    ):
        service_action = coordinator_service_subcommands.add_parser(
            action_name,
            help=action_help,
        )
        service_action.add_argument(
            "--repo-map-home",
            required=True,
            help="absolute owner-private REPOMAP_HOME selected by the service",
        )
        if action_name != "render":
            service_action.add_argument(
                "--json",
                action="store_true",
                help="emit bounded service-package state as JSON",
            )
    for command_name, command_help in (
        (
            "coordinator-health",
            "inspect the existing coordinator health projection",
        ),
        (
            "coordinator-control-status",
            "inspect derived coordinator control database compatibility",
        ),
        (
            "coordinator-control-init",
            "explicitly create and initialize derived coordinator control state",
        ),
    ):
        control_command = ops_subcommands.add_parser(
            command_name,
            help=command_help,
        )
        control_command.add_argument(
            "--repo-map-home",
            required=True,
            help="owner-private REPOMAP_HOME that determines control authority",
        )
        control_command.add_argument(
            "--json",
            action="store_true",
            help="emit bounded coordinator control state as JSON",
        )
    control_upgrade = ops_subcommands.add_parser(
        "coordinator-control-upgrade",
        help="adopt an exact pre-ledger control database after verified backup",
    )
    control_upgrade.add_argument(
        "--repo-map-home",
        required=True,
        help="owner-private REPOMAP_HOME that determines control authority",
    )
    control_upgrade.add_argument(
        "--backup-first",
        action="store_true",
        help="required: create and inspect a restorable backup before adoption",
    )
    control_upgrade.add_argument(
        "--yes",
        action="store_true",
        help="confirm a non-dry-run control schema adoption",
    )
    control_upgrade.add_argument("--reason")
    control_upgrade.add_argument("--dry-run", action="store_true")
    control_upgrade.add_argument("--json", action="store_true")
    for command_name, command_help in (
        ("coordinator-job-status", "inspect one existing durable coordinator job"),
        ("coordinator-job-wait", "wait within a bound for one existing coordinator job"),
        ("coordinator-job-cancel", "request cancellation of one existing coordinator job"),
    ):
        job_command = ops_subcommands.add_parser(command_name, help=command_help)
        job_command.add_argument(
            "--repo-map-home",
            required=True,
            help="owner-private REPOMAP_HOME that determines coordinator authority",
        )
        job_command.add_argument("--job-id", required=True, help="existing durable job ID")
        if command_name == "coordinator-job-wait":
            job_command.add_argument(
                "--wait-timeout-seconds",
                type=int,
                default=3600,
                help="overall wait bound from 1 through 86400 seconds",
            )
        job_command.add_argument(
            "--json", action="store_true", help="emit bounded coordinator job state as JSON"
        )
    jobs_command = ops_subcommands.add_parser(
        "coordinator-jobs", help="list one bounded page of active and recent jobs"
    )
    jobs_command.add_argument("--repo-map-home", required=True)
    jobs_command.add_argument("--limit", type=int, default=20)
    jobs_command.add_argument("--graph-id")
    jobs_command.add_argument("--cursor")
    jobs_command.add_argument("--json", action="store_true")
