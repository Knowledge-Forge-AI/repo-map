"""Source-acquisition command handlers for the RepoMap CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from types import ModuleType

__all__ = ("dispatch_source_acquisition_command",)


def dispatch_source_acquisition_command(
    args: argparse.Namespace,
    commands: ModuleType,
    print_cli_error: Callable[..., None],
) -> int | None:
    ApiPolicyError = commands.ApiPolicyError
    BulkPolicyError = commands.BulkPolicyError
    GitHubApiPolicyError = commands.GitHubApiPolicyError
    SourceAcquisitionError = commands.SourceAcquisitionError
    SourcePolicyError = commands.SourcePolicyError
    acquire_api_source = commands.acquire_api_source
    acquire_github_api_source = commands.acquire_github_api_source
    build_api_plan_from_config = commands.build_api_plan_from_config
    build_bulk_plan_from_config = commands.build_bulk_plan_from_config
    build_github_api_plan_from_config = commands.build_github_api_plan_from_config
    import_archive_source = commands.import_archive_source
    import_bulk_source = commands.import_bulk_source
    import_warc_source = commands.import_warc_source
    ingest_feed_source = commands.ingest_feed_source
    json = commands.json
    sys = commands.sys

    if args.command == "sources" and args.source_command == "ingest-feed":
        try:
            summary = ingest_feed_source(
                config_path=args.config,
                root_path=args.root_path,
                artifact_dir=args.artifact_dir,
            )
        except (SourcePolicyError, SourceAcquisitionError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(summary.to_jsonable(), sort_keys=True))
        else:
            print(
                "ingested feed source "
                f"{summary.source_id} without graph publication "
                f"({summary.feed_observations} feed observations)"
            )
        return 0

    if args.command == "sources" and args.source_command == "import-archive":
        try:
            summary = import_archive_source(
                config_path=args.config,
                root_path=args.root_path,
            )
        except (SourcePolicyError, SourceAcquisitionError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(summary.to_jsonable(), sort_keys=True))
        else:
            print(
                "imported local artifact source "
                f"{summary.source_id} without graph publication "
                f"({summary.observations} observations)"
            )
        return 0

    if args.command == "sources" and args.source_command == "import-warc":
        try:
            summary = import_warc_source(
                config_path=args.config,
                root_path=args.root_path,
            )
        except (SourcePolicyError, SourceAcquisitionError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(summary.to_jsonable(), sort_keys=True))
        else:
            print(
                "imported local WARC source "
                f"{summary.source_id} without graph publication "
                f"({summary.observations} observations, "
                f"{summary.routed_payloads} routed payloads)"
            )
        return 0

    if args.command == "bulk" and args.bulk_command == "plan":
        try:
            manifest = build_bulk_plan_from_config(args.config)
        except BulkPolicyError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(manifest.to_jsonable(), sort_keys=True))
        else:
            print(
                "planned bulk source "
                f"{manifest.source_id} "
                f"({manifest.file_count_included} included, "
                f"{manifest.file_count_skipped} skipped)"
            )
        return 0

    if args.command == "bulk" and args.bulk_command == "import":
        try:
            summary = import_bulk_source(
                config_path=args.config,
                root_path=args.root_path,
            )
        except BulkPolicyError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(summary.to_jsonable(), sort_keys=True))
        else:
            print(
                "imported bulk source "
                f"{summary.source_id} without graph publication "
                f"({summary.observations} observations)"
            )
        return 0

    if args.command == "api" and args.api_command == "plan":
        try:
            manifest = build_api_plan_from_config(args.config)
        except ApiPolicyError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(manifest.to_jsonable(), sort_keys=True))
        else:
            print(
                "planned API source "
                f"{manifest.source_id} "
                f"({manifest.request_count} GET requests)"
            )
        return 0

    if args.command == "api" and args.api_command == "acquire":
        try:
            summary = acquire_api_source(
                config_path=args.config,
                root_path=args.root_path,
            )
        except ApiPolicyError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(summary.to_jsonable(), sort_keys=True))
        else:
            print(
                "acquired API source "
                f"{summary.source_id} without graph publication "
                f"({summary.observations} observations)"
            )
        return 0

    if args.command == "github" and args.github_command == "plan":
        try:
            manifest = build_github_api_plan_from_config(args.config)
        except GitHubApiPolicyError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(manifest.to_jsonable(), sort_keys=True))
        else:
            print(
                "planned GitHub API source "
                f"{manifest.source_id} "
                f"({manifest.request_count} GET requests)"
            )
        return 0

    if args.command == "github" and args.github_command == "acquire":
        try:
            summary = acquire_github_api_source(
                config_path=args.config,
                root_path=args.root_path,
            )
        except GitHubApiPolicyError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(summary.to_jsonable(), sort_keys=True))
        else:
            print(
                "acquired GitHub API source "
                f"{summary.source_id} without graph publication "
                f"({summary.observations} observations)"
            )
        return 0

    return None
