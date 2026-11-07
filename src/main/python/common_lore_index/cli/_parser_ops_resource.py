"""Parser construction for offline resource-report commands and the opt-in flag."""

from __future__ import annotations

import argparse

RESOURCE_REPORT_HELP = (
    "after this single operation, write a new bounded identity-free cloe-resource-view-v1 "
    "report to FILE; the parent directory must already exist and be owner-only, FILE must "
    "not exist, and it may not lie under a configured source root or managed home"
)


def add_resource_report_option(command: argparse.ArgumentParser) -> None:
    """Attach ``--resource-report`` to one eligible single-operation command."""
    command.add_argument(
        "--resource-report", dest="resource_report", metavar="FILE", default=None,
        help=RESOURCE_REPORT_HELP,
    )


def add_ops_resource_commands(
    ops_subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register offline ``ops resource-report check|show``; no home or config options."""
    report = ops_subcommands.add_parser(
        "resource-report",
        help="validate or display an offline cloe-resource-view-v1 report file",
        description=(
            "Offline inspection opens no configuration, database, source or worker. "
            "Validation proves format and domain validity only, not authenticity, "
            "measurement truth or publication success."
        ),
    )
    actions = report.add_subparsers(dest="resource_report_command", required=True)
    check = actions.add_parser("check", help="strictly validate one private report file")
    check.add_argument("--input", required=True, metavar="FILE", help="report file to validate")
    show = actions.add_parser("show", help="validate, then display one private report file")
    show.add_argument("--input", required=True, metavar="FILE", help="report file to display")
    show.add_argument("--json", action="store_true", help="emit the validated canonical JSON")


__all__ = ("RESOURCE_REPORT_HELP", "add_ops_resource_commands", "add_resource_report_option")
