"""Offline ``cloe ops resource-report check|show`` dispatch.

These commands run before product dispatch and open no configuration,
database, source or worker. Refusals print one closed, path-free category.
"""

from __future__ import annotations

import argparse
import sys

from common_lore_index.ops.resource_reports._codec import (
    ResourceReportError, decode_report, encode_report,
)
from common_lore_index.ops.resource_reports._files import read_report_file
from common_lore_index.ops.resource_reports._render import render_check_text, render_report_text


def dispatch_ops_resource_report_command(args: argparse.Namespace) -> int | None:
    if getattr(args, "command", None) != "ops" or getattr(args, "ops_command", None) != "resource-report":
        return None
    try:
        report = decode_report(read_report_file(args.input))
    except ResourceReportError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.resource_report_command == "check":
        print(render_check_text(report))
    elif getattr(args, "json", False):
        print(encode_report(report).decode("utf-8"), end="")
    else:
        print(render_report_text(report))
    return 0


__all__ = ("dispatch_ops_resource_report_command",)
