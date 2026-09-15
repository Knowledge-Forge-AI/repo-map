"""Storage migration discovery and local schema loading."""

from __future__ import annotations

import hashlib as hashlib
import subprocess as subprocess
import sysconfig as sysconfig
from collections.abc import Sequence
from dataclasses import dataclass as dataclass
from enum import Enum as Enum
from pathlib import Path

from repomap_kg.canonicalization.records import CanonicalizationResult as CanonicalizationResult
from repomap_kg.canonicalization.main import canonicalize_observations as canonicalize_observations
from repomap_kg.observations.raw import RawObservation as RawObservation
from repomap_kg.storage.canonical_rows import (
    prepare_canonical_load as prepare_canonical_load,
    canonicalization_error_message as canonicalization_error_message,
)
from repomap_kg.storage.canonical import (
    query_canonical_edge_explanation as query_canonical_edge_explanation,
    query_canonical_edge_records as query_canonical_edge_records,
    query_canonical_neighborhood as query_canonical_neighborhood,
    query_canonical_node_records as query_canonical_node_records,
    query_canonical_storage_summary as query_canonical_storage_summary,
)
from repomap_kg.storage.source_readback import (
    query_ingested_source_records as query_ingested_source_records,
    query_source_feed_item_explanation as query_source_feed_item_explanation,
    query_source_feed_item_records as query_source_feed_item_records,
    query_source_reference_records as query_source_reference_records,
    query_source_run_records as query_source_run_records,
    query_source_summary as query_source_summary,
)
from repomap_kg.storage.psql import (
    last_output_line as last_output_line, parse_psql_json as parse_psql_json,
    psql_failure_message as psql_failure_message, run_psql as run_psql,
)
from repomap_kg.storage.publication_readback import (
    RunPublicationRecord as RunPublicationRecord,
    read_latest_publication as read_latest_publication,
    read_latest_receipt_bearing_publication as read_latest_receipt_bearing_publication,
    read_run_publication as read_run_publication,
)
from repomap_kg.storage.read_pages import (
    DEFAULT_PUBLIC_READ_LIMIT as DEFAULT_PUBLIC_READ_LIMIT,
    MAX_PUBLIC_READ_LIMIT as MAX_PUBLIC_READ_LIMIT,
    PUBLIC_READ_SCHEMA_VERSION as PUBLIC_READ_SCHEMA_VERSION,
    PublicReadPage as PublicReadPage,
    format_public_read_page_footer as format_public_read_page_footer,
    public_embedded_read_result_to_jsonable as public_embedded_read_result_to_jsonable,
    public_read_page as public_read_page,
    public_read_page_to_jsonable as public_read_page_to_jsonable,
    validate_public_read_window as validate_public_read_window,
)
from repomap_kg.storage.repository_identity import (
    StorageSchemaError as StorageSchemaError, annotations as annotations,
    re as re,
    repository_identity_reconciliation_sql as repository_identity_reconciliation_sql,
    repository_identity_state_sql as repository_identity_state_sql,
    repository_upsert_sql as repository_upsert_sql,
    validate_repository_identity as validate_repository_identity,
)
from repomap_kg.storage.rows import (
    APISummaryRecord as APISummaryRecord, BulkSummaryRecord as BulkSummaryRecord,
    CanonicalEdgeEvidenceLinkRow as CanonicalEdgeEvidenceLinkRow,
    CanonicalEdgeEvidenceRecord as CanonicalEdgeEvidenceRecord,
    CanonicalEdgeExplanationRecord as CanonicalEdgeExplanationRecord,
    CanonicalEdgeRecord as CanonicalEdgeRecord, CanonicalEdgeRow as CanonicalEdgeRow,
    CanonicalEvidenceRow as CanonicalEvidenceRow,
    CanonicalLoadRows as CanonicalLoadRows,
    CanonicalLoadSummary as CanonicalLoadSummary,
    CanonicalNeighborhoodRecord as CanonicalNeighborhoodRecord,
    CanonicalNodeEvidenceLinkRow as CanonicalNodeEvidenceLinkRow,
    CanonicalNodeRecord as CanonicalNodeRecord, CanonicalNodeRow as CanonicalNodeRow,
    CanonicalStorageSummaryRecord as CanonicalStorageSummaryRecord,
    EmailSummaryRecord as EmailSummaryRecord, FileRow as FileRow,
    IngestedSourceRecord as IngestedSourceRecord,
    JSFrameworkSummaryRecord as JSFrameworkSummaryRecord,
    JSSummaryRecord as JSSummaryRecord, LoadSummary as LoadSummary,
    NixSummaryRecord as NixSummaryRecord, OpenAPISummaryRecord as OpenAPISummaryRecord,
    PreparedCanonicalLoad as PreparedCanonicalLoad,
    PythonSummaryRecord as PythonSummaryRecord, RawObservationRow as RawObservationRow,
    RubySummaryRecord as RubySummaryRecord,
    SourceFeedItemRecord as SourceFeedItemRecord,
    SourceReferenceRecord as SourceReferenceRecord, SourceRunRecord as SourceRunRecord,
    SourceSummaryRecord as SourceSummaryRecord,
    TerraformSummaryRecord as TerraformSummaryRecord,
    api_manifest_summary_payload as api_manifest_summary_payload,
    api_summary_from_storage_payload as api_summary_from_storage_payload,
    api_summary_to_jsonable as api_summary_to_jsonable,
    bulk_manifest_summary_payload as bulk_manifest_summary_payload,
    bulk_summary_from_storage_payload as bulk_summary_from_storage_payload,
    bulk_summary_to_jsonable as bulk_summary_to_jsonable,
    canonical_edge_evidence_record_from_storage_payload as canonical_edge_evidence_record_from_storage_payload,
    canonical_edge_explanation_from_storage_payload as canonical_edge_explanation_from_storage_payload,
    canonical_edge_explanation_to_jsonable as canonical_edge_explanation_to_jsonable,
    canonical_edge_link_row as canonical_edge_link_row,
    canonical_edge_record_from_storage_payload as canonical_edge_record_from_storage_payload,
    canonical_edge_records_to_jsonable as canonical_edge_records_to_jsonable,
    canonical_json_text as canonical_json_text,
    canonical_json_value as canonical_json_value,
    canonical_load_summary_from_payload as canonical_load_summary_from_payload,
    canonical_neighborhood_from_storage_payload as canonical_neighborhood_from_storage_payload,
    canonical_neighborhood_to_jsonable as canonical_neighborhood_to_jsonable,
    canonical_node_record_from_storage_payload as canonical_node_record_from_storage_payload,
    canonical_node_records_to_jsonable as canonical_node_records_to_jsonable,
    canonical_rows_from_result as canonical_rows_from_result,
    canonical_storage_summary_from_payload as canonical_storage_summary_from_payload,
    canonical_storage_summary_to_jsonable as canonical_storage_summary_to_jsonable,
    clean_yaml_value as clean_yaml_value,
    email_summary_from_storage_payload as email_summary_from_storage_payload,
    email_summary_to_jsonable as email_summary_to_jsonable,
    file_rows_from_observations as file_rows_from_observations,
    format_api_summary_table as format_api_summary_table,
    format_bool_summary as format_bool_summary,
    format_bulk_summary_table as format_bulk_summary_table,
    format_canonical_edge_explanation_table as format_canonical_edge_explanation_table,
    format_canonical_edge_table as format_canonical_edge_table,
    format_canonical_neighborhood_table as format_canonical_neighborhood_table,
    format_canonical_node_table as format_canonical_node_table,
    format_canonical_storage_summary_table as format_canonical_storage_summary_table,
    format_count_summary as format_count_summary,
    format_email_summary_table as format_email_summary_table,
    format_js_framework_summary_table as format_js_framework_summary_table,
    format_js_summary_table as format_js_summary_table,
    format_nix_summary_table as format_nix_summary_table,
    format_openapi_summary_table as format_openapi_summary_table,
    format_python_summary_table as format_python_summary_table,
    format_ruby_summary_table as format_ruby_summary_table,
    format_terraform_summary_table as format_terraform_summary_table,
    identity_metadata_hash as identity_metadata_hash,
    ingested_source_record_from_storage_payload as ingested_source_record_from_storage_payload,
    ingested_source_records_to_jsonable as ingested_source_records_to_jsonable,
    js_framework_summary_from_storage_payload as js_framework_summary_from_storage_payload,
    js_framework_summary_to_jsonable as js_framework_summary_to_jsonable,
    js_summary_from_storage_payload as js_summary_from_storage_payload,
    js_summary_to_jsonable as js_summary_to_jsonable,
    load_summary_from_payload as load_summary_from_payload,
    manifest_counter as manifest_counter, manifest_int as manifest_int,
    manifest_list as manifest_list, metadata_bool as metadata_bool,
    metadata_text as metadata_text,
    nix_summary_from_storage_payload as nix_summary_from_storage_payload,
    nix_summary_to_jsonable as nix_summary_to_jsonable,
    openapi_summary_from_storage_payload as openapi_summary_from_storage_payload,
    openapi_summary_to_jsonable as openapi_summary_to_jsonable,
    optional_manifest_text as optional_manifest_text, optional_text as optional_text,
    payload_bool as payload_bool, payload_count_map as payload_count_map,
    payload_int as payload_int, payload_json_object as payload_json_object,
    payload_optional_bool as payload_optional_bool,
    payload_optional_int as payload_optional_int,
    payload_optional_text as payload_optional_text,
    payload_required_bool_map as payload_required_bool_map,
    payload_required_count_map as payload_required_count_map,
    payload_string as payload_string, payload_string_tuple as payload_string_tuple,
    payload_text as payload_text,
    python_summary_from_storage_payload as python_summary_from_storage_payload,
    python_summary_to_jsonable as python_summary_to_jsonable,
    raw_observation_payload_hash as raw_observation_payload_hash,
    raw_observation_reference_from_storage_payload as raw_observation_reference_from_storage_payload,
    raw_observation_rows_from_observations as raw_observation_rows_from_observations,
    read_api_manifest_payloads as read_api_manifest_payloads,
    read_bulk_manifest_payloads as read_bulk_manifest_payloads,
    ruby_summary_from_storage_payload as ruby_summary_from_storage_payload,
    ruby_summary_to_jsonable as ruby_summary_to_jsonable, sha256_text as sha256_text,
    source_feed_item_record_from_storage_payload as source_feed_item_record_from_storage_payload,
    source_feed_item_records_to_jsonable as source_feed_item_records_to_jsonable,
    source_reference_record_from_storage_payload as source_reference_record_from_storage_payload,
    source_reference_records_to_jsonable as source_reference_records_to_jsonable,
    source_run_record_from_storage_payload as source_run_record_from_storage_payload,
    source_run_records_to_jsonable as source_run_records_to_jsonable,
    source_summary_from_storage_payload as source_summary_from_storage_payload,
    source_summary_to_jsonable as source_summary_to_jsonable,
    terraform_summary_from_storage_payload as terraform_summary_from_storage_payload,
    terraform_summary_to_jsonable as terraform_summary_to_jsonable,
)
from repomap_kg.storage.sql import (
    build_api_summary_query_sql as build_api_summary_query_sql,
    build_bulk_summary_query_sql as build_bulk_summary_query_sql,
    build_canonical_edge_query_sql as build_canonical_edge_query_sql,
    build_canonical_ingest_sql as build_canonical_ingest_sql,
    build_canonical_neighborhood_query_sql as build_canonical_neighborhood_query_sql,
    build_canonical_node_query_sql as build_canonical_node_query_sql,
    build_canonical_storage_summary_query_sql as build_canonical_storage_summary_query_sql,
    build_email_summary_query_sql as build_email_summary_query_sql,
    build_explain_canonical_edge_query_sql as build_explain_canonical_edge_query_sql,
    build_ingested_source_query_sql as build_ingested_source_query_sql,
    build_js_framework_summary_query_sql as build_js_framework_summary_query_sql,
    build_js_summary_query_sql as build_js_summary_query_sql,
    build_nix_summary_query_sql as build_nix_summary_query_sql,
    build_openapi_summary_query_sql as build_openapi_summary_query_sql,
    build_python_summary_query_sql as build_python_summary_query_sql,
    build_ruby_summary_query_sql as build_ruby_summary_query_sql,
    build_source_feed_item_explanation_query_sql as build_source_feed_item_explanation_query_sql,
    build_source_feed_item_query_sql as build_source_feed_item_query_sql,
    build_source_reference_query_sql as build_source_reference_query_sql,
    build_source_run_query_sql as build_source_run_query_sql,
    build_source_summary_query_sql as build_source_summary_query_sql,
    build_terraform_summary_query_sql as build_terraform_summary_query_sql,
    canonical_edge_evidence_upsert_sql as canonical_edge_evidence_upsert_sql,
    canonical_edge_upsert_sql as canonical_edge_upsert_sql,
    canonical_evidence_upsert_sql as canonical_evidence_upsert_sql,
    canonical_file_path_prefix as canonical_file_path_prefix,
    canonical_ingest_statements as canonical_ingest_statements,
    canonical_load_summary_select_sql as canonical_load_summary_select_sql,
    canonical_node_evidence_upsert_sql as canonical_node_evidence_upsert_sql,
    canonical_node_upsert_sql as canonical_node_upsert_sql,
    file_load_summary_select_sql as file_load_summary_select_sql,
    file_upsert_sql as file_upsert_sql, positive_limit as positive_limit,
    raw_observation_upsert_sql as raw_observation_upsert_sql,
    repository_run_prefix_sql as repository_run_prefix_sql,
    require_supported_graph_key_version as require_supported_graph_key_version,
    source_observations_cte as source_observations_cte, sql_bool as sql_bool,
    sql_int_or_null as sql_int_or_null,
    sql_like_prefix_literal as sql_like_prefix_literal, sql_literal as sql_literal,
)
from repomap_kg.storage.summaries import (
    query_api_summary as query_api_summary, query_bulk_summary as query_bulk_summary,
    query_email_summary as query_email_summary,
    query_js_framework_summary as query_js_framework_summary,
    query_js_summary as query_js_summary, query_nix_summary as query_nix_summary,
    query_openapi_summary as query_openapi_summary,
    query_python_summary as query_python_summary,
    query_ruby_summary as query_ruby_summary,
    query_terraform_summary as query_terraform_summary,
)


from repomap_kg.storage._schema_migrations import (
    CHANGESET_PATTERN as CHANGESET_PATTERN,
    GraphSchemaReadiness as GraphSchemaReadiness,
    GraphSchemaStatus as GraphSchemaStatus, Migration as Migration,
    _ledger_create_statements as _ledger_create_statements,
    _ledger_insert_statement as _ledger_insert_statement,
    _migration_script as _migration_script, _sql_literal as _sql_literal,
    default_rdbms_root as default_rdbms_root,
    discover_migrations as discover_migrations,
    graph_schema_forward_sql as graph_schema_forward_sql,
    graph_schema_initialization_sql as graph_schema_initialization_sql,
    graph_schema_ledger_bootstrap_sql as graph_schema_ledger_bootstrap_sql,
    include_all_paths as include_all_paths, migration_from_path as migration_from_path,
)


def graph_schema_readiness(
    rdbms_root: Path | str | None,
    psql_args: Sequence[str],
    *,
    psql_command: str = "psql",
) -> GraphSchemaReadiness:
    migrations = discover_migrations(rdbms_root)
    expected_version = migrations[-1].changeset_id
    tables = frozenset(
        _psql_query(
            psql_args,
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name",
            psql_command=psql_command,
        )
    )
    if not tables:
        return GraphSchemaReadiness(
            GraphSchemaStatus.UNINITIALIZED,
            expected_version,
            None,
            len(migrations),
            0,
        )
    if "repomap_schema_migrations" not in tables:
        return GraphSchemaReadiness(
            GraphSchemaStatus.UNMANAGED,
            expected_version,
            None,
            len(migrations),
            0,
        )

    applied = _applied_migrations(psql_args, psql_command=psql_command)
    applied_version = applied[-1][1] if applied else None
    expected_rows = tuple(
        (
            migration.ordinal,
            migration.changeset_id,
            migration.relative_path,
            migration.checksum,
        )
        for migration in migrations
    )
    if applied == expected_rows:
        status = GraphSchemaStatus.CURRENT
    elif len(applied) < len(expected_rows) and applied == expected_rows[: len(applied)]:
        status = GraphSchemaStatus.BEHIND
    else:
        status = GraphSchemaStatus.DIVERGED
    return GraphSchemaReadiness(
        status,
        expected_version,
        applied_version,
        len(migrations),
        len(applied),
    )


def apply_migrations(
    rdbms_root: Path | str | None,
    psql_args: Sequence[str],
    *,
    psql_command: str = "psql",
) -> tuple[Migration, ...]:
    migrations = discover_migrations(rdbms_root)
    readiness = graph_schema_readiness(
        rdbms_root,
        psql_args,
        psql_command=psql_command,
    )
    if readiness.status is GraphSchemaStatus.CURRENT:
        return migrations
    if readiness.status is GraphSchemaStatus.UNMANAGED:
        raise StorageSchemaError("unmanaged graph schema")
    if readiness.status is GraphSchemaStatus.DIVERGED:
        raise StorageSchemaError("diverged graph schema")

    pending = migrations[readiness.applied_count :]
    run_psql(
        [
            psql_command,
            *psql_args,
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input_text=_migration_script(
            pending,
            initialize_ledger=(
                readiness.status is GraphSchemaStatus.UNINITIALIZED
            ),
        ),
    )
    current = graph_schema_readiness(
        rdbms_root,
        psql_args,
        psql_command=psql_command,
    )
    if not current.ready:
        raise StorageSchemaError("graph schema is not exact-current")
    return migrations


def _psql_query(
    psql_args: Sequence[str],
    sql: str,
    *,
    psql_command: str,
    field_separator: str | None = None,
) -> tuple[str, ...]:
    command = [
        psql_command,
        *psql_args,
        "-X",
        "-A",
        "-t",
        "-v",
        "ON_ERROR_STOP=1",
    ]
    if field_separator is not None:
        command.extend(("-F", field_separator))
    command.extend(("-c", sql))
    result = run_psql(command)
    return tuple(line for line in result.stdout.splitlines() if line)


def _applied_migrations(
    psql_args: Sequence[str], *, psql_command: str
) -> tuple[tuple[int, str, str, str], ...]:
    rows = _psql_query(
        psql_args,
        "SELECT ordinal, changeset_id, migration_path, checksum "
        "FROM repomap_schema_migrations ORDER BY ordinal",
        psql_command=psql_command,
        field_separator="\t",
    )
    applied = []
    for row in rows:
        fields = row.split("\t")
        if len(fields) != 4 or not fields[0].isdigit():
            raise StorageSchemaError("invalid graph schema ledger")
        applied.append((int(fields[0]), fields[1], fields[2], fields[3]))
    return tuple(applied)
