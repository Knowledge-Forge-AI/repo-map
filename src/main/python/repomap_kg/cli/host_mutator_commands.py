"""Canonical host-mutator readback helpers for the CLI facade."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from types import ModuleType

from repomap_kg.graph.keys import (
    GRAPH_KEY_VERSION,
    GraphKeyError,
    host_category_key,
    validate_key,
)
from repomap_kg.storage import StorageSchemaError

CANONICAL_HOST_MUTATOR_EDGE_KINDS = ("mutates_host", "host_mutation_intent")
HOST_CATEGORY_KEY_PREFIX = "host.category:"
CANONICAL_HOST_MUTATOR_BOOLEAN_METADATA_KEYS = (
    "privileged_observed",
    "destructive_observed",
    "runtime_intent",
    "host_mutation_proven",
    "static_only",
    "shell_executed",
    "zsh_executed",
    "powershell_executed",
    "target_redacted_observed",
)


def canonical_host_mutator_filters_from_args(args) -> str | None:
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError("unsupported graph key version")
    for option, value in (
        ("--source-key", getattr(args, "source_key", None)),
        ("--target-key", getattr(args, "target_key", None)),
    ):
        if value is None:
            continue
        validation = validate_key(value)
        if not validation.valid:
            detail = f": {validation.error}" if validation.error else ""
            raise StorageSchemaError(f"invalid {option} canonical key{detail}")
    target_key = getattr(args, "target_key", None)
    if args.category is not None:
        try:
            category_target_key = host_category_key(args.category)
        except GraphKeyError as error:
            raise StorageSchemaError(
                f"invalid host mutation category: {error}"
            ) from error
        if target_key is not None and target_key != category_target_key:
            raise StorageSchemaError(
                "category and target-key refer to different host categories"
            )
        target_key = category_target_key
    return target_key


def canonical_host_mutator_summary_target_from_args(args) -> str | None:
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError("unsupported graph key version")
    if args.category is None:
        return None
    try:
        return host_category_key(args.category)
    except GraphKeyError as error:
        raise StorageSchemaError(
            f"invalid host mutation category: {error}"
        ) from error


def query_canonical_host_mutator_edge_records(
    args,
    target_key,
    *,
    commands: ModuleType,
):
    records = []
    for edge_kind in CANONICAL_HOST_MUTATOR_EDGE_KINDS:
        records.extend(
            commands.query_canonical_edge_records(
                psql_args_from_args(args),
                root_path=args.root_path,
                kind=edge_kind,
                source_key=getattr(args, "source_key", None),
                target_key=target_key,
                graph_key_version=args.graph_key_version,
                psql_command=args.psql_command,
            )
        )
    return tuple(
        sorted(
            records,
            key=lambda record: (
                record.source_key,
                record.edge_kind,
                record.target_key,
                record.identity_metadata_hash,
            ),
        )
    )


def filter_canonical_host_mutator_records(records, *, tool: str | None):
    if tool is None:
        return records
    return tuple(
        record
        for record in records
        if canonical_host_mutator_record_has_tool(record, tool)
    )


def canonical_host_mutator_records_to_jsonable(records):
    return [canonical_host_mutator_record_to_jsonable(record) for record in records]


def canonical_host_mutator_record_to_jsonable(record):
    payload = {
        "source_key": record.source_key,
        "edge_kind": record.edge_kind,
        "target_key": record.target_key,
        "graph_key_version": record.graph_key_version,
        "identity_metadata_hash": record.identity_metadata_hash,
        "confidence": record.confidence,
        "conflict": record.conflict,
        "first_seen_run_id": record.first_seen_run_id,
        "last_seen_run_id": record.last_seen_run_id,
    }
    category = canonical_host_mutator_category(record.target_key)
    if category is not None:
        payload["category"] = category
    tool_names = canonical_metadata_text_values(
        record.metadata,
        ("tool", "tools", "manager", "managers"),
    )
    if tool_names:
        payload["tool_names"] = list(tool_names)
    command_names = canonical_metadata_text_values(
        record.metadata,
        ("command", "commands", "command_name", "command_names"),
    )
    if command_names:
        payload["command_names"] = list(command_names)
    for key in CANONICAL_HOST_MUTATOR_BOOLEAN_METADATA_KEYS:
        value = record.metadata.get(key)
        if isinstance(value, bool):
            payload[key] = value
    return payload


def canonical_host_mutator_category(target_key: str) -> str | None:
    if target_key.startswith(HOST_CATEGORY_KEY_PREFIX):
        return target_key[len(HOST_CATEGORY_KEY_PREFIX) :]
    return None


def canonical_metadata_text_values(
    metadata: Mapping[str, object], keys: Sequence[str]
) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    candidates: tuple[str, ...]
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str):
            candidates = (value,)
        elif isinstance(value, (list, tuple)):
            candidates = tuple(item for item in value if isinstance(item, str))
        else:
            candidates = ()
        for candidate in candidates:
            if candidate and candidate not in seen:
                values.append(candidate)
                seen.add(candidate)
    return tuple(values)


def summarize_canonical_host_mutator_records(records):
    groups: dict[tuple[str, str], list] = {}
    for record in records:
        category = canonical_host_mutator_category(record.target_key)
        if category is None:
            continue
        groups.setdefault((category, record.edge_kind), []).append(record)
    summaries = []
    for (category, edge_kind), group_records in groups.items():
        edge_keys = {
            (
                record.source_key,
                record.edge_kind,
                record.target_key,
                record.identity_metadata_hash,
            )
            for record in group_records
        }
        source_keys = {record.source_key for record in group_records}
        privileged_edge_count = sum(
            1
            for record in group_records
            if record.metadata.get("privileged_observed") is True
        )
        summaries.append(
            {
                "category": category,
                "edge_kind": edge_kind,
                "source_count": len(source_keys),
                "canonical_edge_count": len(edge_keys),
                "privileged_edge_count": privileged_edge_count,
                "intent_edge_count": (
                    len(edge_keys) if edge_kind == "host_mutation_intent" else 0
                ),
                "proven_edge_count": len(edge_keys) if edge_kind == "mutates_host" else 0,
            }
        )
    return tuple(
        sorted(
            summaries,
            key=lambda summary: (summary["category"], summary["edge_kind"]),
        )
    )


def canonical_host_mutator_summaries_to_jsonable(summaries):
    return [dict(summary) for summary in summaries]


def format_canonical_host_mutator_summary_table(summaries) -> str:
    rows = canonical_host_mutator_summaries_to_jsonable(summaries)
    columns = (
        "category",
        "edge_kind",
        "source_count",
        "canonical_edge_count",
        "privileged_edge_count",
        "intent_edge_count",
        "proven_edge_count",
    )
    rendered_rows = [
        {key: render_host_mutator_table_value(row.get(key)) for key in columns}
        for row in rows
    ]
    widths = {
        key: max([len(key), *(len(row[key]) for row in rendered_rows)])
        for key in columns
    }
    lines = [
        format_cli_table_row(dict(zip(columns, columns, strict=True)), columns, widths)
    ]
    for row in rendered_rows:
        lines.append(format_cli_table_row(row, columns, widths))
    return "\n".join(lines)


def format_canonical_host_mutator_table(records) -> str:
    rows = canonical_host_mutator_records_to_jsonable(records)
    columns = (
        "source_key",
        "edge_kind",
        "category",
        "tool_names",
        "command_names",
        "confidence",
        "conflict",
        "first_seen_run_id",
        "last_seen_run_id",
    )
    rendered_rows = [
        {key: render_host_mutator_table_value(row.get(key)) for key in columns}
        for row in rows
    ]
    widths = {
        key: max([len(key), *(len(row[key]) for row in rendered_rows)])
        for key in columns
    }
    lines = [
        format_cli_table_row(dict(zip(columns, columns, strict=True)), columns, widths)
    ]
    for row in rendered_rows:
        lines.append(format_cli_table_row(row, columns, widths))
    return "\n".join(lines)


def render_host_mutator_table_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def format_cli_table_row(row, columns, widths) -> str:
    return "  ".join(row[column].ljust(widths[column]) for column in columns)


def canonical_host_mutator_record_has_tool(record, tool: str) -> bool:
    return tool in canonical_metadata_text_values(
        record.metadata,
        (
            "tool",
            "tools",
            "command",
            "commands",
            "command_name",
            "command_names",
            "manager",
            "managers",
        ),
    )


def canonical_edge_identity_metadata_from_args(args) -> dict[str, object]:
    try:
        payload = json.loads(args.identity_metadata_json)
    except json.JSONDecodeError as error:
        raise StorageSchemaError(
            "identity-metadata-json must be a JSON object"
        ) from error
    if not isinstance(payload, dict):
        raise StorageSchemaError("identity-metadata-json must be a JSON object")
    return payload


def psql_args_from_args(args) -> list[str]:
    psql_args = []
    options = (
        ("pg_host", "-h"),
        ("pg_port", "-p"),
        ("pg_user", "-U"),
        ("pg_database", "-d"),
    )
    for attribute, flag in options:
        value = getattr(args, attribute)
        if value:
            psql_args.extend([flag, value])
    return psql_args
