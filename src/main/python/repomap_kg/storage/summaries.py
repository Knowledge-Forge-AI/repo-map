"""Storage summary query orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.psql import run_psql as run_psql
from repomap_kg.storage.readback_driver import execute_json_readback
from repomap_kg.storage.rows import (
    APISummaryRecord,
    BulkSummaryRecord,
    EmailSummaryRecord,
    JSFrameworkSummaryRecord,
    JSSummaryRecord,
    NixSummaryRecord,
    OpenAPISummaryRecord,
    PythonSummaryRecord,
    RubySummaryRecord,
    TerraformSummaryRecord,
    api_manifest_summary_payload,
    api_summary_from_storage_payload,
    bulk_manifest_summary_payload,
    bulk_summary_from_storage_payload,
    email_summary_from_storage_payload,
    js_framework_summary_from_storage_payload,
    js_summary_from_storage_payload,
    nix_summary_from_storage_payload,
    openapi_summary_from_storage_payload,
    payload_int,
    payload_optional_text,
    python_summary_from_storage_payload,
    ruby_summary_from_storage_payload,
    terraform_summary_from_storage_payload,
)
from repomap_kg.storage.sql import (
    build_api_summary_query_sql,
    build_bulk_summary_query_sql,
    build_email_summary_query_sql,
    build_js_framework_summary_query_sql,
    build_js_summary_query_sql,
    build_nix_summary_query_sql,
    build_openapi_summary_query_sql,
    build_python_summary_query_sql,
    build_ruby_summary_query_sql,
    build_terraform_summary_query_sql,
)

__all__ = (
    "query_ruby_summary",
    "query_js_summary",
    "query_js_framework_summary",
    "query_openapi_summary",
    "query_terraform_summary",
    "query_python_summary",
    "query_nix_summary",
    "query_email_summary",
    "query_bulk_summary",
    "query_api_summary",
)


def query_ruby_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    psql_command: str = "psql",
) -> RubySummaryRecord:
    return ruby_summary_from_storage_payload(
        execute_json_readback(
            build_ruby_summary_query_sql(root_path),
            psql_args=psql_args,
            psql_command=psql_command,
            label="ruby summary",
            expected_shape="object",
        )
    )


def query_js_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    psql_command: str = "psql",
) -> JSSummaryRecord:
    return js_summary_from_storage_payload(
        execute_json_readback(
            build_js_summary_query_sql(root_path),
            psql_args=psql_args,
            psql_command=psql_command,
            label="js summary",
            expected_shape="object",
        )
    )


def query_js_framework_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> JSFrameworkSummaryRecord:
    return js_framework_summary_from_storage_payload(
        execute_json_readback(
            build_js_framework_summary_query_sql(
                root_path,
                repository_identity=repository_identity,
            ),
            psql_args=psql_args,
            psql_command=psql_command,
            label="js framework summary",
            expected_shape="object",
        )
    )


def query_openapi_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> OpenAPISummaryRecord:
    return openapi_summary_from_storage_payload(
        execute_json_readback(
            build_openapi_summary_query_sql(
                root_path,
                repository_identity=repository_identity,
            ),
            psql_args=psql_args,
            psql_command=psql_command,
            label="openapi summary",
            expected_shape="object",
        )
    )


def query_terraform_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> TerraformSummaryRecord:
    return terraform_summary_from_storage_payload(
        execute_json_readback(
            build_terraform_summary_query_sql(
                root_path,
                repository_identity=repository_identity,
            ),
            psql_args=psql_args,
            psql_command=psql_command,
            label="terraform summary",
            expected_shape="object",
        )
    )


def query_python_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> PythonSummaryRecord:
    return python_summary_from_storage_payload(
        execute_json_readback(
            build_python_summary_query_sql(
                root_path,
                repository_identity=repository_identity,
            ),
            psql_args=psql_args,
            psql_command=psql_command,
            label="python summary",
            expected_shape="object",
        )
    )


def query_nix_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    repository_identity: str | None = None,
    psql_command: str = "psql",
) -> NixSummaryRecord:
    return nix_summary_from_storage_payload(
        execute_json_readback(
            build_nix_summary_query_sql(
                root_path,
                repository_identity=repository_identity,
            ),
            psql_args=psql_args,
            psql_command=psql_command,
            label="nix summary",
            expected_shape="object",
        )
    )


def query_email_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    psql_command: str = "psql",
) -> EmailSummaryRecord:
    return email_summary_from_storage_payload(
        execute_json_readback(
            build_email_summary_query_sql(root_path),
            psql_args=psql_args,
            psql_command=psql_command,
            label="email summary",
            expected_shape="object",
        )
    )


def query_bulk_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    psql_command: str = "psql",
) -> BulkSummaryRecord:
    storage_payload = execute_json_readback(
        build_bulk_summary_query_sql(root_path),
        psql_args=psql_args,
        psql_command=psql_command,
        label="bulk summary",
        expected_shape="object",
    )
    if not isinstance(storage_payload, dict):
        raise StorageSchemaError("psql returned a malformed bulk summary")
    manifest_payload = bulk_manifest_summary_payload(Path(root_path))
    redaction_counts = dict(manifest_payload["redaction_counts"])
    redacted_observations = payload_int(
        storage_payload,
        "redacted_observations",
        label="bulk summary",
    )
    if redacted_observations:
        redaction_counts["raw_observations"] = max(
            redaction_counts.get("raw_observations", 0),
            redacted_observations,
        )
    return bulk_summary_from_storage_payload(
        {
            **manifest_payload,
            "repository_name": payload_optional_text(
                storage_payload,
                "repository_name",
                label="bulk summary",
            ),
            "observations_with_bulk_provenance": payload_int(
                storage_payload,
                "observations_with_bulk_provenance",
                label="bulk summary",
            ),
            "redaction_counts": redaction_counts,
        }
    )


def query_api_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    psql_command: str = "psql",
) -> APISummaryRecord:
    storage_payload = execute_json_readback(
        build_api_summary_query_sql(root_path),
        psql_args=psql_args,
        psql_command=psql_command,
        label="api summary",
        expected_shape="object",
    )
    if not isinstance(storage_payload, dict):
        raise StorageSchemaError("psql returned a malformed api summary")
    manifest_payload = api_manifest_summary_payload(Path(root_path))
    return api_summary_from_storage_payload(
        {
            **manifest_payload,
            "repository_name": payload_optional_text(
                storage_payload,
                "repository_name",
                label="api summary",
            ),
            "observations_with_api_provenance": payload_int(
                storage_payload,
                "observations_with_api_provenance",
                label="api summary",
            ),
            "config_documents_from_api": payload_int(
                storage_payload,
                "config_documents_from_api",
                label="api summary",
            ),
        }
    )
