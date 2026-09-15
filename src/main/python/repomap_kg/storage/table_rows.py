"""Storage readback table formatter helpers."""

from __future__ import annotations

from collections.abc import Sequence

from repomap_kg.graph.readback.files import format_table_row, render_table_value
from repomap_kg.storage._table_rows_domains import (
    format_bool_summary,
    format_count_summary,
    format_email_summary_table as _format_email_summary_table,
    format_js_framework_summary_table as _format_js_framework_summary_table,
    format_js_summary_table as _format_js_summary_table,
    format_nix_summary_table as _format_nix_summary_table,
    format_openapi_summary_table as _format_openapi_summary_table,
    format_python_summary_table as _format_python_summary_table,
    format_ruby_summary_table as _format_ruby_summary_table,
    format_terraform_summary_table as _format_terraform_summary_table,
)
from repomap_kg.storage.canonical_readback_rows import (
    CanonicalEdgeExplanationRecord,
    CanonicalEdgeRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
)
from repomap_kg.storage.source_summary_table_rows import (
    format_api_summary_table as _format_api_summary_table,
    format_bulk_summary_table as _format_bulk_summary_table,
)
from repomap_kg.storage.summary_rows_domains import (
    EmailSummaryRecord,
    OpenAPISummaryRecord,
    TerraformSummaryRecord,
)
from repomap_kg.storage.summary_rows_languages import (
    JSFrameworkSummaryRecord,
    JSSummaryRecord,
    PythonSummaryRecord,
    RubySummaryRecord,
)
from repomap_kg.storage.summary_rows_manifest import (
    APISummaryRecord,
    BulkSummaryRecord,
)
from repomap_kg.storage.summary_rows_nix import NixSummaryRecord
from repomap_kg.storage.summary_rows_storage import CanonicalStorageSummaryRecord

__all__ = (
    "format_canonical_node_table",
    "format_canonical_edge_table",
    "format_canonical_neighborhood_table",
    "format_canonical_edge_explanation_table",
    "format_canonical_storage_summary_table",
    "format_ruby_summary_table",
    "format_count_summary",
    "format_bool_summary",
    "format_js_summary_table",
    "format_js_framework_summary_table",
    "format_openapi_summary_table",
    "format_terraform_summary_table",
    "format_python_summary_table",
    "format_nix_summary_table",
    "format_email_summary_table",
    "format_bulk_summary_table",
    "format_api_summary_table",
)


def format_canonical_node_table(records: Sequence[CanonicalNodeRecord]) -> str:
    rows = [record.to_dict() for record in records]
    columns = (
        "canonical_key",
        "kind",
        "display_name",
        "confidence",
        "conflict",
        "first_seen_run_id",
        "last_seen_run_id",
    )
    rendered_rows = [
        {key: render_table_value(row[key]) for key in columns}
        for row in rows
    ]
    widths = {
        key: max([len(key), *(len(row[key]) for row in rendered_rows)])
        for key in columns
    }
    lines = [format_table_row(dict(zip(columns, columns, strict=True)), columns, widths)]
    for row in rendered_rows:
        lines.append(format_table_row(row, columns, widths))
    return "\n".join(lines)


def format_canonical_edge_table(records: Sequence[CanonicalEdgeRecord]) -> str:
    rows = [record.to_dict() for record in records]
    columns = (
        "source_key",
        "edge_kind",
        "target_key",
        "identity_metadata_hash",
        "confidence",
        "conflict",
        "first_seen_run_id",
        "last_seen_run_id",
    )
    rendered_rows = [
        {key: render_table_value(row[key]) for key in columns}
        for row in rows
    ]
    widths = {
        key: max([len(key), *(len(row[key]) for row in rendered_rows)])
        for key in columns
    }
    lines = [format_table_row(dict(zip(columns, columns, strict=True)), columns, widths)]
    for row in rendered_rows:
        lines.append(format_table_row(row, columns, widths))
    return "\n".join(lines)


def format_canonical_neighborhood_table(record: CanonicalNeighborhoodRecord) -> str:
    center_key = (
        record.center.canonical_key
        if record.center is not None
        else "<not found>"
    )
    node_columns = (
        "canonical_key",
        "kind",
        "display_name",
        "confidence",
        "conflict",
    )
    edge_columns = (
        "source_key",
        "edge_kind",
        "target_key",
        "identity_metadata_hash",
        "confidence",
        "conflict",
    )
    node_rows = [
        {key: render_table_value(row[key]) for key in node_columns}
        for row in (node.to_dict() for node in record.nodes)
    ]
    edge_rows = [
        {key: render_table_value(row[key]) for key in edge_columns}
        for row in (edge.to_dict() for edge in record.edges)
    ]
    node_widths = {
        key: max([len(key), *(len(row[key]) for row in node_rows)])
        for key in node_columns
    }
    edge_widths = {
        key: max([len(key), *(len(row[key]) for row in edge_rows)])
        for key in edge_columns
    }
    lines = [
        f"center: {center_key}",
        "",
        "Nodes:",
        format_table_row(
            dict(zip(node_columns, node_columns, strict=True)),
            node_columns,
            node_widths,
        ),
    ]
    for row in node_rows:
        lines.append(format_table_row(row, node_columns, node_widths))
    lines.extend(
        [
            "",
            "Edges:",
            format_table_row(
                dict(zip(edge_columns, edge_columns, strict=True)),
                edge_columns,
                edge_widths,
            ),
        ]
    )
    for row in edge_rows:
        lines.append(format_table_row(row, edge_columns, edge_widths))
    return "\n".join(lines)


def format_canonical_edge_explanation_table(
    record: CanonicalEdgeExplanationRecord,
) -> str:
    if record.edge is None:
        edge_lines = ["edge: <not found>"]
    else:
        edge_row = record.edge.to_dict()
        edge_columns = (
            "source_key",
            "edge_kind",
            "target_key",
            "identity_metadata_hash",
            "confidence",
            "conflict",
        )
        edge_lines = ["edge:"]
        for column in edge_columns:
            edge_lines.append(f"{column}: {render_table_value(edge_row[column])}")

    evidence_columns = (
        "raw_observation.run_id",
        "raw_observation.ordinal",
        "raw_observation.kind",
        "raw_observation.source_id",
        "path",
        "start_line",
        "end_line",
        "extractor",
        "extractor_version",
        "confidence",
    )
    evidence_rows = [
        {
            "raw_observation.run_id": evidence_record.raw_observation["run_id"],
            "raw_observation.ordinal": evidence_record.raw_observation["ordinal"],
            "raw_observation.kind": evidence_record.raw_observation["kind"],
            "raw_observation.source_id": evidence_record.raw_observation["source_id"],
            "path": evidence_record.path,
            "start_line": evidence_record.start_line,
            "end_line": evidence_record.end_line,
            "extractor": evidence_record.extractor,
            "extractor_version": evidence_record.extractor_version,
            "confidence": evidence_record.confidence,
        }
        for evidence_record in record.evidence
    ]
    rendered_evidence_rows = [
        {key: render_table_value(row[key]) for key in evidence_columns}
        for row in evidence_rows
    ]
    widths = {
        key: max([len(key), *(len(row[key]) for row in rendered_evidence_rows)])
        for key in evidence_columns
    }
    evidence_lines = [
        "evidence:",
        format_table_row(
            dict(zip(evidence_columns, evidence_columns, strict=True)),
            evidence_columns,
            widths,
        ),
    ]
    for row in rendered_evidence_rows:
        evidence_lines.append(format_table_row(row, evidence_columns, widths))
    return "\n".join([*edge_lines, "", *evidence_lines])


def format_canonical_storage_summary_table(
    record: CanonicalStorageSummaryRecord,
) -> str:
    row = record.to_dict()
    columns = (
        "root_path",
        "repository_name",
        "latest_run_id",
        "runs",
        "files",
        "raw_observations",
        "raw_observations_total",
        "latest_run_raw_observations",
        "canonical_nodes",
        "canonical_edges",
        "canonical_evidence",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {
        key: max(len(key), len(rendered_row[key]))
        for key in columns
    }
    return "\n".join(
        [
            format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
            format_table_row(rendered_row, columns, widths),
        ]
    )


def format_ruby_summary_table(record: RubySummaryRecord) -> str:
    return _format_ruby_summary_table(record)


def format_js_summary_table(record: JSSummaryRecord) -> str:
    return _format_js_summary_table(record)


def format_js_framework_summary_table(record: JSFrameworkSummaryRecord) -> str:
    return _format_js_framework_summary_table(record)


def format_openapi_summary_table(record: OpenAPISummaryRecord) -> str:
    return _format_openapi_summary_table(record)


def format_terraform_summary_table(record: TerraformSummaryRecord) -> str:
    return _format_terraform_summary_table(record)


def format_python_summary_table(record: PythonSummaryRecord) -> str:
    return _format_python_summary_table(record)


def format_nix_summary_table(record: NixSummaryRecord) -> str:
    return _format_nix_summary_table(record)


def format_email_summary_table(record: EmailSummaryRecord) -> str:
    return _format_email_summary_table(record)


def format_bulk_summary_table(record: BulkSummaryRecord) -> str:
    return _format_bulk_summary_table(record)


def format_api_summary_table(record: APISummaryRecord) -> str:
    return _format_api_summary_table(record)
