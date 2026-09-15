"""Command dispatch for the RepoMap CLI.

This module owns command-selection control flow while command implementation
objects remain on ``repomap_kg.cli`` for compatibility with existing imports and
tests that patch those names.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from types import ModuleType
from typing import TextIO

from repomap_kg.cli._local_dispatch import dispatch_local_command
from repomap_kg.cli._observations_dispatch import dispatch_observation_commands
from repomap_kg.cli._ops_baselines_dispatch import dispatch_ops_baselines_command
from repomap_kg.cli._ops_control_dispatch import dispatch_ops_control_command
from repomap_kg.cli._ops_refresh_dispatch import dispatch_ops_refresh_command
from repomap_kg.cli.coordinator_runtime_commands import (
    dispatch_coordinator_runtime_command,
)
from repomap_kg.cli.coordinator_service_commands import (
    dispatch_coordinator_service_command,
)
from repomap_kg.cli.ops_graph_file_commands import dispatch_ops_graph_file_command
from repomap_kg.cli.release_cluster_commands import dispatch_release_cluster_command
from repomap_kg.cli.source_commands import dispatch_source_acquisition_command
from repomap_kg.cli.storage_edge_explanation_commands import (
    dispatch_storage_edge_explanation_command,
)
from repomap_kg.cli.storage_readback_edge_commands import (
    dispatch_storage_readback_edge_command,
)
from repomap_kg.cli.storage_readback_node_commands import (
    dispatch_storage_readback_node_command,
)
from repomap_kg.cli.storage_summary_commands import dispatch_storage_summary_command

_CLI_ERROR_URL_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s]+")
_CLI_ERROR_PRIVATE_PATH_RE = re.compile(
    r"(?<!\w)/(?:Users|private|tmp|var|home)/[^\s,;)]*"
)
_CLI_ERROR_SYNTHETIC_PRIVATE_VALUE_RE = re.compile(
    r"\b(?:synthetic[-_][A-Za-z0-9_.:/-]*|[A-Za-z0-9_.:/-]*secret[A-Za-z0-9_.:/-]*)\b",
    re.IGNORECASE,
)


def _sanitize_cli_error_message(message: str) -> str:
    sanitized = _CLI_ERROR_URL_RE.sub("[redacted-url]", message)
    sanitized = _CLI_ERROR_PRIVATE_PATH_RE.sub("[redacted-path]", sanitized)
    return _CLI_ERROR_SYNTHETIC_PRIVATE_VALUE_RE.sub(
        "[redacted-value]",
        sanitized,
    )


def _print_cli_error(error: Exception, *, file: TextIO) -> None:
    print(f"ERROR: {_sanitize_cli_error_message(str(error))}", file=file)


def dispatch_command(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    commands: ModuleType,
) -> int:
    coordinator_service_exit = dispatch_coordinator_service_command(
        args,
        commands,
        _print_cli_error,
    )
    if coordinator_service_exit is not None:
        return coordinator_service_exit

    if args.version:
        print(f"repomap-kg {commands.__version__}")
        return 0

    obs_result = dispatch_observation_commands(
        args,
        commands,
        _print_cli_error,
    )
    if obs_result is not None:
        return obs_result

    ops_graph_file_result = dispatch_ops_graph_file_command(
        args,
        commands,
        _print_cli_error,
    )
    if ops_graph_file_result is not None:
        return ops_graph_file_result

    source_acquisition_result = dispatch_source_acquisition_command(
        args,
        commands,
        _print_cli_error,
    )
    if source_acquisition_result is not None:
        return source_acquisition_result

    coordinator_runtime_result = dispatch_coordinator_runtime_command(
        args,
        commands,
        print_error=lambda error: _print_cli_error(error, file=sys.stderr),
    )
    if coordinator_runtime_result is not None:
        return coordinator_runtime_result

    release_cluster_result = dispatch_release_cluster_command(
        args,
        initialize=commands.initialize_release_cluster,
        status=commands.release_cluster_status,
        error_type=commands.ReleaseClusterError,
        print_error=lambda error: _print_cli_error(error, file=sys.stderr),
    )
    if release_cluster_result is not None:
        return release_cluster_result

    ops_ctrl_result = dispatch_ops_control_command(
        args,
        commands,
        _print_cli_error,
    )
    if ops_ctrl_result is not None:
        return ops_ctrl_result

    ops_refresh_result = dispatch_ops_refresh_command(
        args,
        commands,
        _print_cli_error,
    )
    if ops_refresh_result is not None:
        return ops_refresh_result

    ops_baselines_result = dispatch_ops_baselines_command(
        args,
        commands,
        _print_cli_error,
    )
    if ops_baselines_result is not None:
        return ops_baselines_result

    if args.command == "local":
        return dispatch_local_command(
            args,
            parser,
            commands,
            print_cli_error=_print_cli_error,
        )

    if args.command == "storage" and args.storage_command == "load-files":
        try:
            observations = commands.read_observations_jsonl(args.jsonl_path)
            summary = commands.publish_observation_generation(
                commands.psql_args_from_args(args),
                observations,
                repository_name=args.repository_name,
                root_path=args.root_path,
                git_commit=args.git_commit,
                psql_command=args.psql_command,
            )
        except (
            commands.MaintenanceUnavailableError,
            commands.ObservationValidationError,
            commands.StorageSchemaError,
        ) as error:
            _print_cli_error(error, file=sys.stderr)
            return 1
        payload = {
            "repository_id": summary.repository_id,
            "run_id": summary.run_id,
            "files": summary.files,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(
                f"loaded {summary.files} files into "
                f"repository {summary.repository_id} run {summary.run_id}"
            )
        return 0

    storage_canonical_result = dispatch_storage_edge_explanation_command(
        args,
        commands,
        _print_cli_error,
    )
    if storage_canonical_result is not None:
        return storage_canonical_result

    storage_readback_node_result = dispatch_storage_readback_node_command(
        args,
        commands,
        _print_cli_error,
    )
    if storage_readback_node_result is not None:
        return storage_readback_node_result

    storage_readback_edge_result = dispatch_storage_readback_edge_command(
        args,
        commands,
        _print_cli_error,
    )
    if storage_readback_edge_result is not None:
        return storage_readback_edge_result

    storage_summary_result = dispatch_storage_summary_command(
        args,
        commands,
        _print_cli_error,
    )
    if storage_summary_result is not None:
        return storage_summary_result

    parser.print_help()
    return 0
