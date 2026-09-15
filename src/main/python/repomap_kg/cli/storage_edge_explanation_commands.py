"""Canonical edge explanation command handler."""

from __future__ import annotations

import argparse
from dataclasses import replace
from collections.abc import Callable
from types import ModuleType

__all__ = ("dispatch_storage_edge_explanation_command",)


def dispatch_storage_edge_explanation_command(
    args: argparse.Namespace,
    commands: ModuleType,
    print_cli_error: Callable[..., None],
) -> int | None:
    if not (
        args.command == "storage"
        and args.storage_command == "explain-canonical-edge"
    ):
        return None
    try:
        commands.canonical_edge_filters_from_args(args)
        identity_hash = commands.identity_metadata_hash(
            commands.canonical_edge_identity_metadata_from_args(args)
        )
        evidence_limit, evidence_offset = commands.validate_public_read_window(
            args.evidence_limit,
            args.evidence_offset,
        )
        record = commands.query_canonical_edge_explanation(
            commands.psql_args_from_args(args),
            root_path=args.root_path,
            source_key=args.source_key,
            kind=args.kind,
            target_key=args.target_key,
            identity_metadata_hash=identity_hash,
            graph_key_version=args.graph_key_version,
            evidence_limit=evidence_limit + 1,
            evidence_offset=evidence_offset,
            psql_command=args.psql_command,
        )
        evidence_page = commands.public_read_page(
            record.evidence,
            limit=evidence_limit,
            offset=evidence_offset,
        )
        record = replace(record, evidence=evidence_page.items)
    except commands.StorageSchemaError as error:
        print_cli_error(error, file=commands.sys.stderr)
        return 1
    if args.json:
        result = commands.canonical_edge_explanation_to_jsonable(record)
        payload = commands.public_embedded_read_result_to_jsonable(
            result,
            result_kind="canonical_edge_explanation",
            collection_pages={"evidence": evidence_page},
        )
        if args.legacy_json_object:
            payload = result
        print(
            commands.json.dumps(
                payload,
                sort_keys=True,
            )
        )
    else:
        print(
            "\n".join(
                (
                    commands.format_canonical_edge_explanation_table(record),
                    commands.format_public_read_page_footer(
                        evidence_page,
                        collection="evidence",
                    ),
                )
            )
        )
    return 0
