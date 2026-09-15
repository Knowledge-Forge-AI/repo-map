"""Table formatting for bulk and API source summaries."""

from __future__ import annotations

from collections.abc import Mapping

from repomap_kg.graph.readback.files import format_table_row, render_table_value
from repomap_kg.storage.summary_rows_manifest import APISummaryRecord, BulkSummaryRecord


def format_bulk_summary_table(record: BulkSummaryRecord) -> str:
    row = record.to_dict()
    row["source_ids"] = ", ".join(record.source_ids)
    for key in (
        "corpus_kinds",
        "policy_statuses",
        "extractor_counts",
        "skip_reasons",
        "diagnostic_counts",
        "redaction_counts",
    ):
        value = row[key]
        if isinstance(value, Mapping):
            row[key] = ", ".join(
                f"{item_key}={item_value}"
                for item_key, item_value in sorted(value.items())
            )
    columns = (
        "root_path_summary",
        "repository_name",
        "bulk_runs",
        "sources",
        "source_ids",
        "corpus_kinds",
        "policy_statuses",
        "file_count_included",
        "file_count_skipped",
        "total_bytes_included",
        "extractor_counts",
        "skip_reasons",
        "diagnostic_counts",
        "redaction_counts",
        "limit_hit_count",
        "max_files_hit_count",
        "max_total_bytes_hit_count",
        "max_file_bytes_hit_count",
        "max_depth_hit_count",
        "archive_deferred",
        "warc_deferred",
        "email_export_runs",
        "mixed_corpus_runs",
        "observations_with_bulk_provenance",
        "no_provider_api",
        "no_external_fetch",
        "no_source_mutation",
        "no_archive_decompression",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {key: max(len(key), len(rendered_row[key])) for key in columns}
    return "\n".join(
        [
            format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
            format_table_row(rendered_row, columns, widths),
        ]
    )


def format_api_summary_table(record: APISummaryRecord) -> str:
    row = record.to_dict()
    row["source_ids"] = ", ".join(record.source_ids)
    row["endpoint_names"] = ", ".join(record.endpoint_names)
    for key in (
        "source_types",
        "api_source_classes",
        "provider_names",
        "provider_products",
        "policy_statuses",
        "methods",
        "downstream_routes",
        "response_types",
        "diagnostic_counts",
    ):
        value = row[key]
        if isinstance(value, Mapping):
            row[key] = ", ".join(
                f"{item_key}={item_value}"
                for item_key, item_value in sorted(value.items())
            )
    columns = (
        "root_path_summary",
        "repository_name",
        "api_runs",
        "sources",
        "source_ids",
        "source_types",
        "api_source_classes",
        "provider_names",
        "provider_products",
        "policy_statuses",
        "requests",
        "responses",
        "endpoints",
        "endpoint_names",
        "methods",
        "downstream_routes",
        "response_types",
        "response_byte_count",
        "redacted_responses",
        "diagnostic_counts",
        "routed_artifacts",
        "observations_with_api_provenance",
        "config_documents_from_api",
        "no_network",
        "no_mutation",
        "no_credentials_resolved",
        "no_scheduler",
        "no_provider_specific_behavior",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {key: max(len(key), len(rendered_row[key])) for key in columns}
    return "\n".join(
        [
            format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
            format_table_row(rendered_row, columns, widths),
        ]
    )
