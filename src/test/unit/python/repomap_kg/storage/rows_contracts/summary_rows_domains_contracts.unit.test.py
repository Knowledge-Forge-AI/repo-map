from __future__ import annotations



def test_openapi_summary_from_storage_payload_terraform_summary_from_storage_payload_email_summary_from_storage_payload_domain_records_contracts() -> None:
    import repomap_kg.storage.summary_rows_domains as summary_rows_domains
    openapi_summary = summary_rows_domains.openapi_summary_from_storage_payload(
        {
            "root_path": "/tmp/repo's root",
            "repository_name": "repo-map",
            "openapi_observations": "34",
            "openapi_documents": "2",
            "spec_families": {"openapi3": "1", "swagger2": "2"},
            "openapi": {
                "info": "1",
                "servers": "2",
                "paths": "3",
                "operations": "4",
                "parameters": "5",
                "request_bodies": "6",
                "responses": "7",
                "schemas": "8",
                "components": "9",
                "security_schemes": "10",
                "tags": "11",
                "examples": "12",
            },
            "methods": {
                "GET": "1",
                "POST": "2",
                "PUT": "3",
                "PATCH": "4",
                "DELETE": "5",
                "OPTIONS": "6",
                "HEAD": "7",
                "TRACE": "8",
            },
            "references": {
                "internal_refs": "1",
                "local_file_refs": "2",
                "remote_refs_not_fetched": "3",
                "external_docs_not_fetched": "4",
                "refs_not_fetched": "5",
            },
            "redactions": {
                "credentialed_urls": "1",
                "openapi_ref_summaries": "2",
                "text_summaries": "3",
                "example_summaries": "4",
                "secret_prone_fields": "5",
            },
            "diagnostics": {
                "parse_errors": "1",
                "unsupported_specs": "2",
                "limit_overflows": "3",
                "local_ref_errors": "4",
                "malformed_specs": "5",
            },
            "generic_config": {
                "config_documents": "1",
                "config_paths": "2",
                "config_references": "3",
                "config_parse_errors": "4",
            },
            "safety": {
                "no_fetch": True,
                "no_api_calls": True,
                "no_tool_execution": True,
                "raw_profile_only": True,
                "no_new_canonical_namespaces": True,
            },
        }
    )
    assert openapi_summary.to_dict()["openapi_documents"] == 2
    assert openapi_summary.to_dict()["methods"] == {
        "GET": 1,
        "POST": 2,
        "PUT": 3,
        "PATCH": 4,
        "DELETE": 5,
        "OPTIONS": 6,
        "HEAD": 7,
        "TRACE": 8,
    }

    terraform_summary = summary_rows_domains.terraform_summary_from_storage_payload(
        {
            "root_path": "/tmp/repo's root",
            "repository_name": "repo-map",
            "terraform_observations": "55",
            "terraform_files": "5",
            "file_families": {
                "tf": "1",
                "tfvars": "2",
                "terraform.tfvars": "3",
                "auto.tfvars": "4",
            },
            "terraform": {
                "blocks": "1",
                "providers": "2",
                "required_providers": "3",
                "required_versions": "4",
                "backends": "5",
                "resources": "6",
                "data_sources": "7",
                "modules": "8",
                "variables": "9",
                "outputs": "10",
                "locals": "11",
                "moved": "12",
                "imports": "13",
                "checks": "14",
                "removed": "15",
            },
            "references": {
                "total": "1",
                "provider_sources": "2",
                "version_constraints": "3",
                "module_sources": "4",
                "local_module_refs": "5",
                "remote_refs_not_fetched": "6",
                "depends_on": "7",
                "provider_aliases": "8",
                "repo_escape_diagnostics": "9",
            },
            "tfvars": {
                "files": "1",
                "variables": "2",
                "literal_values_exposed": False,
            },
            "redactions": {
                "tfvars_values": "1",
                "secret_like_fields": "2",
                "credentialed_urls": "3",
                "import_ids": "4",
                "backend_values": "5",
            },
            "diagnostics": {
                "parse_errors": "1",
                "limit_overflows": "2",
                "malformed_hcl": "3",
            },
            "generic_config": {
                "config_documents": "1",
                "config_paths": "2",
                "config_references": "3",
                "file_nodes": "4",
            },
            "safety": {
                "no_execution": True,
                "no_fetch": True,
                "no_terraform_cli": True,
                "no_provider_download": True,
                "no_module_download": True,
                "no_state_access": True,
                "tfvars_redacted": True,
                "raw_profile_only": True,
                "no_new_canonical_namespaces": True,
            },
        }
    )
    assert terraform_summary.to_dict()["tfvars"] == {
        "files": 1,
        "variables": 2,
        "literal_values_exposed": False,
    }
    assert terraform_summary.to_dict()["terraform"]["resources"] == 6

    email_summary = summary_rows_domains.email_summary_from_storage_payload(
        {
            "root_path": "/tmp/repo's root",
            "repository_name": "repo-map",
            "mailboxes": "1",
            "messages": "2",
            "eml_messages": "3",
            "mbox_messages": "4",
            "addresses": "5",
            "address_observations": "6",
            "address_domains": "7",
            "mime_parts": "8",
            "text_plain_parts": "9",
            "text_html_parts": "10",
            "attachment_stubs": "11",
            "inline_attachments": "12",
            "content_id_parts": "13",
            "thread_hints": "14",
            "message_references": "15",
            "external_url_references": "16",
            "list_unsubscribe_references": "17",
            "parse_errors": "18",
            "malformed_or_oversized_diagnostics": "19",
            "message_id_present": "20",
            "message_id_missing_or_invalid": "21",
            "messages_with_attachments": "22",
            "messages_with_html": "23",
            "messages_with_plain": "24",
            "mailbox_limits": "25",
            "no_provider_api": True,
            "no_mutation": True,
            "no_body_text": True,
            "no_attachment_content": True,
        }
    )
    assert email_summary.to_dict()["messages"] == 2
    assert email_summary.to_dict()["mailbox_limits"] == 25
    assert email_summary.to_dict()["no_attachment_content"] is True
