"""Bounded CLI dispatch for release-cluster lifecycle commands."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any


def dispatch_release_cluster_command(
    args: Any,
    *,
    initialize: Callable[[str], dict[str, object]],
    status: Callable[[str], dict[str, object]],
    error_type: type[Exception],
    print_error: Callable[[Exception], None],
) -> int | None:
    """Dispatch one release-cluster command or decline unrelated input."""

    if args.command != "ops" or args.ops_command not in {
        "release-cluster-init",
        "release-cluster-status",
    }:
        return None
    try:
        payload = (
            initialize(args.repo_map_home)
            if args.ops_command == "release-cluster-init"
            else status(args.repo_map_home)
        )
    except error_type as error:
        print_error(error)
        return 1
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            "RepoMap release cluster: "
            f"result={payload['result']} "
            f"graphs={payload['graph_database_count']}",
            file=sys.stdout,
        )
    return 0 if payload["result"] == "ready" else 1


__all__ = ["dispatch_release_cluster_command"]
