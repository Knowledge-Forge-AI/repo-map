"""Domain summary records and payload decoders."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.row_helpers import (
    payload_bool,
    payload_int,
    payload_json_object,
    payload_optional_text,
    payload_required_bool_map,
    payload_required_count_map,
    payload_text,
)

__all__ = (
    "OpenAPISummaryRecord",
    "TerraformSummaryRecord",
    "EmailSummaryRecord",
    "openapi_summary_from_storage_payload",
    "terraform_summary_from_storage_payload",
    "email_summary_from_storage_payload",
)


@dataclass(frozen=True)
class OpenAPISummaryRecord:
    root_path: str
    repository_name: str | None
    openapi_observations: int
    openapi_documents: int
    spec_families: dict[str, int]
    openapi: dict[str, int]
    methods: dict[str, int]
    references: dict[str, int]
    redactions: dict[str, int]
    diagnostics: dict[str, int]
    generic_config: dict[str, int]
    safety: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TerraformSummaryRecord:
    root_path: str
    repository_name: str | None
    terraform_observations: int
    terraform_files: int
    file_families: dict[str, int]
    terraform: dict[str, int]
    references: dict[str, int]
    tfvars: dict[str, int | bool]
    redactions: dict[str, int]
    diagnostics: dict[str, int]
    generic_config: dict[str, int]
    safety: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EmailSummaryRecord:
    root_path: str
    repository_name: str | None
    mailboxes: int
    messages: int
    eml_messages: int
    mbox_messages: int
    addresses: int
    address_observations: int
    address_domains: int
    mime_parts: int
    text_plain_parts: int
    text_html_parts: int
    attachment_stubs: int
    inline_attachments: int
    content_id_parts: int
    thread_hints: int
    message_references: int
    external_url_references: int
    list_unsubscribe_references: int
    parse_errors: int
    malformed_or_oversized_diagnostics: int
    message_id_present: int
    message_id_missing_or_invalid: int
    messages_with_attachments: int
    messages_with_html: int
    messages_with_plain: int
    mailbox_limits: int
    no_provider_api: bool
    no_mutation: bool
    no_body_text: bool
    no_attachment_content: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def openapi_summary_from_storage_payload(payload: Any) -> OpenAPISummaryRecord:
    label = "openapi summary"
    if not isinstance(payload, dict):
        raise StorageSchemaError(f"psql returned a malformed {label}")
    return OpenAPISummaryRecord(
        root_path=payload_text(payload, "root_path", label=label),
        repository_name=payload_optional_text(payload, "repository_name", label=label),
        openapi_observations=payload_int(payload, "openapi_observations", label=label),
        openapi_documents=payload_int(payload, "openapi_documents", label=label),
        spec_families=payload_required_count_map(
            payload, "spec_families", ("openapi3", "swagger2"), label=label
        ),
        openapi=payload_required_count_map(
            payload,
            "openapi",
            (
                "info",
                "servers",
                "paths",
                "operations",
                "parameters",
                "request_bodies",
                "responses",
                "schemas",
                "components",
                "security_schemes",
                "tags",
                "examples",
            ),
            label=label,
        ),
        methods=payload_required_count_map(
            payload,
            "methods",
            (
                "GET",
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
                "OPTIONS",
                "HEAD",
                "TRACE",
            ),
            label=label,
        ),
        references=payload_required_count_map(
            payload,
            "references",
            (
                "internal_refs",
                "local_file_refs",
                "remote_refs_not_fetched",
                "external_docs_not_fetched",
                "refs_not_fetched",
            ),
            label=label,
        ),
        redactions=payload_required_count_map(
            payload,
            "redactions",
            (
                "credentialed_urls",
                "openapi_ref_summaries",
                "text_summaries",
                "example_summaries",
                "secret_prone_fields",
            ),
            label=label,
        ),
        diagnostics=payload_required_count_map(
            payload,
            "diagnostics",
            (
                "parse_errors",
                "unsupported_specs",
                "limit_overflows",
                "local_ref_errors",
                "malformed_specs",
            ),
            label=label,
        ),
        generic_config=payload_required_count_map(
            payload,
            "generic_config",
            (
                "config_documents",
                "config_paths",
                "config_references",
                "config_parse_errors",
            ),
            label=label,
        ),
        safety=payload_required_bool_map(
            payload,
            "safety",
            (
                "no_fetch",
                "no_api_calls",
                "no_tool_execution",
                "raw_profile_only",
                "no_new_canonical_namespaces",
            ),
            label=label,
        ),
    )


def terraform_summary_from_storage_payload(payload: Any) -> TerraformSummaryRecord:
    label = "terraform summary"
    if not isinstance(payload, dict):
        raise StorageSchemaError(f"psql returned a malformed {label}")
    tfvars_payload = payload_json_object(payload, "tfvars", label=label)
    tfvars = {
        "files": payload_int(tfvars_payload, "files", label=label),
        "variables": payload_int(tfvars_payload, "variables", label=label),
        "literal_values_exposed": payload_bool(
            tfvars_payload,
            "literal_values_exposed",
            label=label,
        ),
    }
    return TerraformSummaryRecord(
        root_path=payload_text(payload, "root_path", label=label),
        repository_name=payload_optional_text(payload, "repository_name", label=label),
        terraform_observations=payload_int(payload, "terraform_observations", label=label),
        terraform_files=payload_int(payload, "terraform_files", label=label),
        file_families=payload_required_count_map(
            payload, "file_families", ("tf", "tfvars", "terraform.tfvars", "auto.tfvars"), label=label
        ),
        terraform=payload_required_count_map(
            payload,
            "terraform",
            (
                "blocks",
                "providers",
                "required_providers",
                "required_versions",
                "backends",
                "resources",
                "data_sources",
                "modules",
                "variables",
                "outputs",
                "locals",
                "moved",
                "imports",
                "checks",
                "removed",
            ),
            label=label,
        ),
        references=payload_required_count_map(
            payload,
            "references",
            (
                "total",
                "provider_sources",
                "version_constraints",
                "module_sources",
                "local_module_refs",
                "remote_refs_not_fetched",
                "depends_on",
                "provider_aliases",
                "repo_escape_diagnostics",
            ),
            label=label,
        ),
        tfvars=tfvars,
        redactions=payload_required_count_map(
            payload,
            "redactions",
            (
                "tfvars_values",
                "secret_like_fields",
                "credentialed_urls",
                "import_ids",
                "backend_values",
            ),
            label=label,
        ),
        diagnostics=payload_required_count_map(
            payload,
            "diagnostics",
            ("parse_errors", "limit_overflows", "malformed_hcl"),
            label=label,
        ),
        generic_config=payload_required_count_map(
            payload,
            "generic_config",
            ("config_documents", "config_paths", "config_references", "file_nodes"),
            label=label,
        ),
        safety=payload_required_bool_map(
            payload,
            "safety",
            (
                "no_execution",
                "no_fetch",
                "no_terraform_cli",
                "no_provider_download",
                "no_module_download",
                "no_state_access",
                "tfvars_redacted",
                "raw_profile_only",
                "no_new_canonical_namespaces",
            ),
            label=label,
        ),
    )


def email_summary_from_storage_payload(payload: Any) -> EmailSummaryRecord:
    label = "email summary"
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed email summary")
    return EmailSummaryRecord(
        root_path=payload_text(payload, "root_path", label=label),
        repository_name=payload_optional_text(payload, "repository_name", label=label),
        mailboxes=payload_int(payload, "mailboxes", label=label),
        messages=payload_int(payload, "messages", label=label),
        eml_messages=payload_int(payload, "eml_messages", label=label),
        mbox_messages=payload_int(payload, "mbox_messages", label=label),
        addresses=payload_int(payload, "addresses", label=label),
        address_observations=payload_int(payload, "address_observations", label=label),
        address_domains=payload_int(payload, "address_domains", label=label),
        mime_parts=payload_int(payload, "mime_parts", label=label),
        text_plain_parts=payload_int(payload, "text_plain_parts", label=label),
        text_html_parts=payload_int(payload, "text_html_parts", label=label),
        attachment_stubs=payload_int(payload, "attachment_stubs", label=label),
        inline_attachments=payload_int(payload, "inline_attachments", label=label),
        content_id_parts=payload_int(payload, "content_id_parts", label=label),
        thread_hints=payload_int(payload, "thread_hints", label=label),
        message_references=payload_int(payload, "message_references", label=label),
        external_url_references=payload_int(payload, "external_url_references", label=label),
        list_unsubscribe_references=payload_int(payload, "list_unsubscribe_references", label=label),
        parse_errors=payload_int(payload, "parse_errors", label=label),
        malformed_or_oversized_diagnostics=payload_int(
            payload, "malformed_or_oversized_diagnostics", label=label
        ),
        message_id_present=payload_int(payload, "message_id_present", label=label),
        message_id_missing_or_invalid=payload_int(payload, "message_id_missing_or_invalid", label=label),
        messages_with_attachments=payload_int(payload, "messages_with_attachments", label=label),
        messages_with_html=payload_int(payload, "messages_with_html", label=label),
        messages_with_plain=payload_int(payload, "messages_with_plain", label=label),
        mailbox_limits=payload_int(payload, "mailbox_limits", label=label),
        no_provider_api=payload_bool(payload, "no_provider_api", label=label),
        no_mutation=payload_bool(payload, "no_mutation", label=label),
        no_body_text=payload_bool(payload, "no_body_text", label=label),
        no_attachment_content=payload_bool(payload, "no_attachment_content", label=label),
    )
