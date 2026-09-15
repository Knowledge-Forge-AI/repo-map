"""Observation and server command dispatch for the RepoMap CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import os
import sys
from types import ModuleType

__all__ = ("dispatch_observation_commands",)


def dispatch_observation_commands(
    args: argparse.Namespace,
    commands: ModuleType,
    print_cli_error: Callable[..., None],
) -> int | None:
    if args.command == "identity":
        identity = commands.PROJECT_IDENTITY.as_dict()
        if args.json:
            print(json.dumps(identity, sort_keys=True))
        else:
            for key, value in identity.items():
                print(f"{key}: {value}")
        return 0

    if args.command == "discover":
        try:
            profile = commands.load_profile(args.profile) if args.profile else None
        except commands.ProfileValidationError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        try:
            observations = commands.discover_observations(args.root, profile=profile)
        except (commands.GoHelperUnavailableError, commands.GoProtocolError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.jsonl:
            for observation in observations:
                print(observation.to_json_line(), end="")
        else:
            print(f"discovered {len(observations)} observations")
        return 0

    if args.command == "files":
        try:
            observations = commands.read_observations_argument(args.jsonl_path)
        except commands.ObservationValidationError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        filters = commands.FileFilters(
            role=args.role,
            language=args.language,
            generated=args.generated,
        )
        records = commands.filter_file_records(
            commands.file_records_from_observations(observations), filters
        )
        if args.json:
            print(json.dumps(commands.records_to_jsonable(records), sort_keys=True))
        else:
            print(commands.format_file_table(records))
        return 0

    if args.command == "entrypoints":
        try:
            observations = commands.read_observations_argument(args.jsonl_path)
        except commands.ObservationValidationError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        records = commands.entrypoint_records_from_observations(observations)
        if args.json:
            print(json.dumps(commands.entrypoints_to_jsonable(records), sort_keys=True))
        else:
            print(commands.format_entrypoint_table(records))
        return 0

    if args.command == "host-mutators":
        try:
            observations = commands.read_observations_argument(args.jsonl_path)
        except commands.ObservationValidationError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        records = commands.host_mutator_records_from_observations(observations)
        records = commands.filter_host_mutator_records(
            records,
            category=args.category,
            tool=args.tool,
        )
        if args.json:
            print(json.dumps(commands.host_mutators_to_jsonable(records), sort_keys=True))
        else:
            print(commands.format_host_mutator_table(records))
        return 0

    if args.command == "host-mutators-summary":
        try:
            observations = commands.read_observations_argument(args.jsonl_path)
        except commands.ObservationValidationError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        records = commands.host_mutator_records_from_observations(observations)
        records = commands.filter_host_mutator_records(
            records,
            category=args.category,
            tool=args.tool,
        )
        summaries = commands.summarize_host_mutator_records(records)
        if args.json:
            print(
                json.dumps(
                    commands.host_mutator_summaries_to_jsonable(summaries),
                    sort_keys=True,
                )
            )
        else:
            print(commands.format_host_mutator_summary_table(summaries))
        return 0

    if args.command == "observations" and args.observation_command == "normalize":
        try:
            observations = commands.read_observations_jsonl(args.jsonl_path)
        except commands.ObservationValidationError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        normalized = commands.normalize_observations(observations)
        payload = normalized.to_dict()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            summary = payload["summary"]
            print(
                "normalized "
                f"{summary['raw_observations']} observations into "
                f"{summary['nodes']} nodes, "
                f"{summary['edges']} edges, and "
                f"{summary['evidence']} evidence records"
            )
        return 0

    if args.command == "mcp" and args.mcp_command == "serve":
        if getattr(args, "repo_map_home", None):
            os.environ["REPOMAP_HOME"] = args.repo_map_home
        if args.config:
            os.environ["REPOMAP_OPS_CONFIG"] = args.config
        from repomap_kg.server.mcp import serve_stdio

        return serve_stdio()

    if args.command == "server" and args.server_command == "serve":
        try:
            return commands.serve_local_http(
                args.repo_map_home,
                host=args.host,
                port=args.port,
                allow_container_internal=args.container_internal_bind,
            )
        except commands.LocalServerError as error:
            print_cli_error(error, file=sys.stderr)
            return 1

    return None
