"""Domain and language summary readback table formatter helpers."""

from __future__ import annotations

from collections.abc import Mapping

from repomap_kg.graph.readback.files import format_table_row, render_table_value
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
from repomap_kg.storage.summary_rows_nix import NixSummaryRecord

__all__ = (
    "format_count_summary",
    "format_bool_summary",
    "format_ruby_summary_table",
    "format_js_summary_table",
    "format_js_framework_summary_table",
    "format_openapi_summary_table",
    "format_terraform_summary_table",
    "format_python_summary_table",
    "format_nix_summary_table",
    "format_email_summary_table",
)


def format_count_summary(counts: Mapping[str, object]) -> str:
    rendered = []
    for key, value in counts.items():
        if isinstance(value, Mapping):
            rendered.append(f"{key}={{{format_count_summary(value)}}}")
        else:
            rendered.append(f"{key}={value}")
    return ", ".join(rendered)


def format_bool_summary(values: Mapping[str, bool | int]) -> str:
    return ", ".join(
        f"{key}={str(value).lower()}" for key, value in values.items()
    )


def format_ruby_summary_table(record: RubySummaryRecord) -> str:
    row = record.to_dict()
    row["profile_counts"] = ", ".join(
        f"{profile}={count}"
        for profile, count in sorted(record.profile_counts.items())
    )
    columns = (
        "root_path",
        "repository_name",
        "ruby_files",
        "modules",
        "classes",
        "methods",
        "singleton_methods",
        "constants",
        "routes",
        "test_cases",
        "test_methods",
        "references",
        "gem_dependencies",
        "vagrant_configs",
        "rake_tasks",
        "rake_namespaces",
        "dynamic_diagnostics",
        "parse_errors",
        "profile_counts",
        "no_execution",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {key: max(len(key), len(rendered_row[key])) for key in columns}
    return "\n".join(
        [
            format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
            format_table_row(rendered_row, columns, widths),
        ]
    )


def format_js_summary_table(record: JSSummaryRecord) -> str:
    row = record.to_dict()
    row["profile_counts"] = ", ".join(
        f"{profile}={count}"
        for profile, count in sorted(record.profile_counts.items())
    )
    columns = (
        "root_path",
        "repository_name",
        "js_files",
        "modules",
        "functions",
        "classes",
        "methods",
        "variables",
        "components",
        "routes",
        "test_suites",
        "test_cases",
        "references",
        "imports",
        "exports",
        "hooks",
        "test_expectations",
        "source_map_references",
        "frontend_asset_files",
        "saved_page_asset_files",
        "test_report_asset_files",
        "dynamic_diagnostics",
        "parse_errors",
        "profile_counts",
        "no_execution",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {key: max(len(key), len(rendered_row[key])) for key in columns}
    return "\n".join(
        [
            format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
            format_table_row(rendered_row, columns, widths),
        ]
    )


def format_js_framework_summary_table(record: JSFrameworkSummaryRecord) -> str:
    row = {
        "root_path": record.root_path,
        "repository_name": record.repository_name,
        "framework_observations": record.framework_observations,
        "framework_profiles": format_count_summary(record.framework_profiles),
        "node": format_count_summary(record.node),
        "express": format_count_summary(record.express),
        "nest": format_count_summary(record.nest),
        "next": format_count_summary(record.next),
        "jest": format_count_summary(record.jest),
        "jquery": format_count_summary(record.jquery),
        "generic_js": format_count_summary(record.generic_js),
        "diagnostics": format_count_summary(record.diagnostics),
        "safety": format_bool_summary(record.safety),
    }
    columns = (
        "root_path",
        "repository_name",
        "framework_observations",
        "framework_profiles",
        "node",
        "express",
        "nest",
        "next",
        "jest",
        "jquery",
        "generic_js",
        "diagnostics",
        "safety",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {key: max(len(key), len(rendered_row[key])) for key in columns}
    return "\n".join(
        [
            format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
            format_table_row(rendered_row, columns, widths),
        ]
    )


def format_openapi_summary_table(record: OpenAPISummaryRecord) -> str:
    row = {
        "root_path": record.root_path,
        "repository_name": record.repository_name,
        "openapi_observations": record.openapi_observations,
        "openapi_documents": record.openapi_documents,
        "spec_families": format_count_summary(record.spec_families),
        "openapi": format_count_summary(record.openapi),
        "methods": format_count_summary(record.methods),
        "references": format_count_summary(record.references),
        "redactions": format_count_summary(record.redactions),
        "diagnostics": format_count_summary(record.diagnostics),
        "generic_config": format_count_summary(record.generic_config),
        "safety": format_bool_summary(record.safety),
    }
    columns = (
        "root_path",
        "repository_name",
        "openapi_observations",
        "openapi_documents",
        "spec_families",
        "openapi",
        "methods",
        "references",
        "redactions",
        "diagnostics",
        "generic_config",
        "safety",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {key: max(len(key), len(rendered_row[key])) for key in columns}
    return "\n".join(
        [
            format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
            format_table_row(rendered_row, columns, widths),
        ]
    )


def format_terraform_summary_table(record: TerraformSummaryRecord) -> str:
    row = {
        "root_path": record.root_path,
        "repository_name": record.repository_name,
        "terraform_observations": record.terraform_observations,
        "terraform_files": record.terraform_files,
        "file_families": format_count_summary(record.file_families),
        "terraform": format_count_summary(record.terraform),
        "references": format_count_summary(record.references),
        "tfvars": format_bool_summary(record.tfvars),
        "redactions": format_count_summary(record.redactions),
        "diagnostics": format_count_summary(record.diagnostics),
        "generic_config": format_count_summary(record.generic_config),
        "safety": format_bool_summary(record.safety),
    }
    columns = (
        "root_path",
        "repository_name",
        "terraform_observations",
        "terraform_files",
        "file_families",
        "terraform",
        "references",
        "tfvars",
        "redactions",
        "diagnostics",
        "generic_config",
        "safety",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {key: max(len(key), len(rendered_row[key])) for key in columns}
    return "\n".join(
        [
            format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
            format_table_row(rendered_row, columns, widths),
        ]
    )


def format_python_summary_table(record: PythonSummaryRecord) -> str:
    row = {
        "root_path": record.root_path,
        "repository_name": record.repository_name,
        "python_observations": record.python_observations,
        "package_files": format_count_summary(record.package_files),
        "packaging": format_count_summary(record.packaging),
        "tests": format_count_summary(record.tests),
        "frameworks": format_count_summary(record.frameworks),
        "references": format_count_summary(record.references),
        "redactions": format_count_summary(record.redactions),
        "diagnostics": format_count_summary(record.diagnostics),
        "generic_python": format_count_summary(record.generic_python),
        "generic_config": format_count_summary(record.generic_config),
        "dogfooding": format_bool_summary(record.dogfooding),
        "safety": format_bool_summary(record.safety),
    }
    columns = (
        "root_path",
        "repository_name",
        "python_observations",
        "package_files",
        "packaging",
        "tests",
        "frameworks",
        "references",
        "redactions",
        "diagnostics",
        "generic_python",
        "generic_config",
        "dogfooding",
        "safety",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {key: max(len(key), len(rendered_row[key])) for key in columns}
    return "\n".join(
        [
            format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
            format_table_row(rendered_row, columns, widths),
        ]
    )


def format_nix_summary_table(record: NixSummaryRecord) -> str:
    row = {
        "root_path": record.root_path,
        "repository_name": record.repository_name,
        "nix_observations": record.nix_observations,
        "nix_files": record.nix_files,
        "flake_files": record.flake_files,
        "raw": format_count_summary(record.raw),
        "canonical": format_count_summary(record.canonical),
        "edges": format_count_summary(record.edges),
        "programs": format_count_summary(record.programs),
        "paths": format_count_summary(record.paths),
        "flake_inputs": format_count_summary(record.flake_inputs),
        "output_sections": format_count_summary(record.output_sections),
        "dynamic_output_shapes": format_count_summary(record.dynamic_output_shapes),
        "unsupported_flake_shapes": format_count_summary(
            record.unsupported_flake_shapes
        ),
        "generic_config": format_count_summary(record.generic_config),
        "diagnostics": format_count_summary(record.diagnostics),
        "limitations": format_bool_summary(record.limitations),
        "safety": format_bool_summary(record.safety),
    }
    columns = (
        "root_path",
        "repository_name",
        "nix_observations",
        "nix_files",
        "flake_files",
        "raw",
        "canonical",
        "edges",
        "programs",
        "paths",
        "flake_inputs",
        "output_sections",
        "dynamic_output_shapes",
        "unsupported_flake_shapes",
        "generic_config",
        "diagnostics",
        "limitations",
        "safety",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {key: max(len(key), len(rendered_row[key])) for key in columns}
    return "\n".join(
        [
            format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
            format_table_row(rendered_row, columns, widths),
        ]
    )


def format_email_summary_table(record: EmailSummaryRecord) -> str:
    row = record.to_dict()
    columns = (
        "root_path",
        "repository_name",
        "mailboxes",
        "messages",
        "eml_messages",
        "mbox_messages",
        "addresses",
        "address_observations",
        "address_domains",
        "mime_parts",
        "text_plain_parts",
        "text_html_parts",
        "attachment_stubs",
        "inline_attachments",
        "content_id_parts",
        "thread_hints",
        "message_references",
        "external_url_references",
        "list_unsubscribe_references",
        "parse_errors",
        "malformed_or_oversized_diagnostics",
        "message_id_present",
        "message_id_missing_or_invalid",
        "messages_with_attachments",
        "messages_with_html",
        "messages_with_plain",
        "mailbox_limits",
        "no_provider_api",
        "no_mutation",
        "no_body_text",
        "no_attachment_content",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {key: max(len(key), len(rendered_row[key])) for key in columns}
    return "\n".join(
        [
            format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
            format_table_row(rendered_row, columns, widths),
        ]
    )
