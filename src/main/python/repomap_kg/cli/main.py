"""Command-line entry point for RepoMap."""

from __future__ import annotations

import argparse
from collections.abc import Mapping as Mapping, Sequence as Sequence
import json
import os as os
import sys
from pathlib import Path

# Same-name aliases preserve the historical CLI facade and monkeypatch seams.
from repomap_kg import __version__ as __version__
from repomap_kg.coordinator.client import CoordinatorClientError as CoordinatorClientError
from repomap_kg.coordinator.job_control import (
    cancel_coordinator_job as cancel_coordinator_job,
    coordinator_health as coordinator_health,
    coordinator_job_status as coordinator_job_status,
    format_coordinator_health_table as format_coordinator_health_table,
    format_coordinator_job_table as format_coordinator_job_table,
    format_coordinator_jobs_table as format_coordinator_jobs_table,
    list_coordinator_jobs as list_coordinator_jobs,
    wait_for_coordinator_job as wait_for_coordinator_job,
)
from repomap_kg.coordinator.local_lifecycle import (
    CoordinatorControlError as CoordinatorControlError,
    coordinator_control_status as coordinator_control_status,
    format_coordinator_control_table as format_coordinator_control_table,
    initialize_coordinator_control as initialize_coordinator_control,
    maintenance_activity_for_home as maintenance_activity_for_home,
    maintenance_window_for_coordinated_backup as maintenance_window_for_coordinated_backup,
    maintenance_window_for_database_drop as maintenance_window_for_database_drop,
    maintenance_window_for_graph_upgrade as maintenance_window_for_graph_upgrade,
    upgrade_coordinator_control as upgrade_coordinator_control,
)
from repomap_kg.coordinator.local_mode import (
    CoordinatorModeError as CoordinatorModeError,
    format_coordinator_refresh_table as format_coordinator_refresh_table,
    run_coordinator_refresh as run_coordinator_refresh,
    serve_configured_coordinator as serve_configured_coordinator,
)
from repomap_kg.service_package.contract import apply_service_environment as apply_service_environment
from repomap_kg.service_package.api import (
    format_service_action_table as format_service_action_table,
    run_coordinator_service_action as run_coordinator_service_action,
)
from repomap_kg.service_package.operations import ServicePackageError as ServicePackageError
from repomap_kg.extractors.languages.go_helper import GoHelperUnavailableError as GoHelperUnavailableError
from repomap_kg.extractors.languages.go_protocol import GoProtocolError as GoProtocolError
from repomap_kg.ops.ingestion.api import (
    ApiPolicyError as ApiPolicyError,
    acquire_api_source as acquire_api_source,
    build_api_plan_from_config as build_api_plan_from_config,
)
from repomap_kg.ops.ingestion.bulk import (
    BulkPolicyError as BulkPolicyError,
    build_bulk_plan_from_config as build_bulk_plan_from_config,
    import_bulk_source as import_bulk_source,
)
from repomap_kg.graph.discovery import discover_observations as discover_observations
from repomap_kg.graph.edge_kinds import CANONICAL_EDGE_KINDS as CANONICAL_EDGE_KINDS
from repomap_kg.graph.readback.entrypoints import (
    entrypoint_records_from_observations as entrypoint_records_from_observations,
    entrypoints_to_jsonable as entrypoints_to_jsonable,
    format_entrypoint_table as format_entrypoint_table,
)
from repomap_kg.graph.readback.files import (
    FileFilters as FileFilters,
    file_records_from_observations as file_records_from_observations,
    filter_file_records as filter_file_records,
    format_file_table as format_file_table,
    records_to_jsonable as records_to_jsonable,
)
from repomap_kg.graph.keys import (
    GRAPH_KEY_VERSION,
    GraphKeyError,
    file_key,
    host_category_key as host_category_key,
    validate_key as validate_key,
)
from repomap_kg.ops.ingestion.github_api import (
    GitHubApiPolicyError as GitHubApiPolicyError,
    acquire_github_api_source as acquire_github_api_source,
    build_github_api_plan_from_config as build_github_api_plan_from_config,
)
from repomap_kg.graph.readback.host_mutators import (
    filter_host_mutator_records as filter_host_mutator_records,
    format_host_mutator_summary_table as format_host_mutator_summary_table,
    format_host_mutator_table as format_host_mutator_table,
    host_mutator_records_from_observations as host_mutator_records_from_observations,
    host_mutator_summaries_to_jsonable as host_mutator_summaries_to_jsonable,
    host_mutators_to_jsonable as host_mutators_to_jsonable,
    summarize_host_mutator_records as summarize_host_mutator_records,
)
from repomap_kg.runtime.backup import (
    LocalDbBackupError as LocalDbBackupError,
    drop_database as drop_database,
    dump_all_databases as dump_all_databases,
    dump_database as dump_database,
    format_backup_inspect_table as format_backup_inspect_table,
    format_backup_info_table as format_backup_info_table,
    format_backup_listing_table as format_backup_listing_table,
    format_backup_result_table as format_backup_result_table,
    format_drop_result_table as format_drop_result_table,
    format_init_result_table as format_init_result_table,
    init_database_from_dump as init_database_from_dump,
    init_database_from_source as init_database_from_source,
    inspect_backup as inspect_backup,
    list_backups as list_backups,
    read_backup_info as read_backup_info,
)
from repomap_kg.runtime.backup_restore_sets import (
    format_coordinated_restore_table as format_coordinated_restore_table,
    restore_coordinated_backup as restore_coordinated_backup,
)
from repomap_kg.runtime.local import (
    LocalRuntimeError as LocalRuntimeError,
    down_local_runtime as down_local_runtime,
    format_local_runtime_table as format_local_runtime_table,
    query_local_runtime_status as query_local_runtime_status,
    setup_local_runtime as setup_local_runtime,
    up_local_runtime as up_local_runtime,
)
from repomap_kg.runtime.schema_upgrade import (
    format_graph_schema_upgrade_table as format_graph_schema_upgrade_table,
    upgrade_graph_schema as upgrade_graph_schema,
)
from repomap_kg.runtime.maintenance import MaintenanceUnavailableError as MaintenanceUnavailableError
from repomap_kg.runtime.release_cluster import (
    ReleaseClusterError as ReleaseClusterError,
    initialize_release_cluster as initialize_release_cluster,
    release_cluster_status as release_cluster_status,
)
from repomap_kg.server.http import LocalServerError as LocalServerError, serve_local_http as serve_local_http
from repomap_kg.observations.normalization import normalize_observations as normalize_observations
from repomap_kg.observations.raw import ObservationValidationError as ObservationValidationError, read_observations_jsonl as read_observations_jsonl
from repomap_kg.ops.config import (
    OpsConfigError as OpsConfigError,
    check_ops_graph_storage_status as check_ops_graph_storage_status,
    check_ops_postgres_status as check_ops_postgres_status,
    format_ops_graph_registry_table as format_ops_graph_registry_table,
    format_ops_config_status_table as format_ops_config_status_table,
    load_ops_config,
    load_ops_config_home,
    ops_graph_registry_status_to_jsonable as ops_graph_registry_status_to_jsonable,
    ops_config_status_to_jsonable as ops_config_status_to_jsonable,
)
from repomap_kg.ops.policy_dogfood import (
    format_policy_dogfood_table as format_policy_dogfood_table,
    policy_dogfood_payload as policy_dogfood_payload,
)
from repomap_kg.ops.direct_publication import publish_observation_generation as publish_observation_generation
from repomap_kg.ops.graph_files import (
    GraphFileFilters as GraphFileFilters,
    format_graph_file_table as format_graph_file_table,
    graph_file_page_to_jsonable as graph_file_page_to_jsonable,
    query_graph_files as query_graph_files,
)
from repomap_kg.ops.refresh import (
    OpsRefreshError as OpsRefreshError,
    baseline_prune_to_jsonable as baseline_prune_to_jsonable,
    baseline_save_to_jsonable as baseline_save_to_jsonable,
    drift_check_to_jsonable as drift_check_to_jsonable,
    format_baseline_prune_table as format_baseline_prune_table,
    format_baseline_save_table as format_baseline_save_table,
    format_drift_check_table as format_drift_check_table,
    format_graph_summary_table as format_graph_summary_table,
    format_preflight_table as format_preflight_table,
    format_refresh_result_table as format_refresh_result_table,
    format_refresh_status_table as format_refresh_status_table,
    graph_baseline_to_jsonable as graph_baseline_to_jsonable,
    graph_summary_to_jsonable as graph_summary_to_jsonable,
    preflight_graph as preflight_graph,
    preflight_to_jsonable as preflight_to_jsonable,
    query_drift_check as query_drift_check,
    query_graph_summary as query_graph_summary,
    query_refresh_status as query_refresh_status,
    prune_graph_baselines as prune_graph_baselines,
    refresh_enabled_graphs as refresh_enabled_graphs,
    refresh_graph as refresh_graph,
    refresh_result_to_jsonable as refresh_result_to_jsonable,
    refresh_status_to_jsonable as refresh_status_to_jsonable,
    save_graph_baselines as save_graph_baselines,
)
from repomap_kg.storage.backend_telemetry import (
    ConnectionTelemetryError as ConnectionTelemetryError,
    telemetry_from_inherited_fds as telemetry_from_inherited_fds,
)
from repomap_kg.storage.staging_event_transport import (
    StagingEventTransportError as StagingEventTransportError,
    staging_event_channel_from_inherited_fd as staging_event_channel_from_inherited_fd,
)
from repomap_kg.storage.staging_observability import StagingMeasurements as StagingMeasurements
from repomap_kg.storage.canonical_filters import (
    canonical_edge_filters_from_args as canonical_edge_filters_from_args,
    canonical_neighborhood_filters_from_args as canonical_neighborhood_filters_from_args,
    canonical_node_kind_from_args as canonical_node_kind_from_args,
)
from repomap_kg.graph.profiles import ProfileValidationError as ProfileValidationError, load_profile as load_profile
from repomap_kg.runtime.project_identity import PROJECT_IDENTITY as PROJECT_IDENTITY
from repomap_kg.server.memory_bridge import (
    format_server_memory_search_table as format_server_memory_search_table,
    format_server_memory_summary_table as format_server_memory_summary_table,
    server_memory_search_payload as server_memory_search_payload,
    server_memory_summary_payload as server_memory_summary_payload,
)
from repomap_kg.ops.ingestion.source import (
    SourceAcquisitionError as SourceAcquisitionError,
    SourcePolicyError as SourcePolicyError,
    import_archive_source as import_archive_source,
    import_warc_source as import_warc_source,
    ingest_feed_source as ingest_feed_source,
)
from repomap_kg.storage import (
    StorageSchemaError,
    api_summary_to_jsonable as api_summary_to_jsonable,
    canonical_edge_explanation_to_jsonable as canonical_edge_explanation_to_jsonable,
    canonical_edge_records_to_jsonable as canonical_edge_records_to_jsonable,
    canonical_neighborhood_to_jsonable as canonical_neighborhood_to_jsonable,
    canonical_node_records_to_jsonable as canonical_node_records_to_jsonable,
    canonical_storage_summary_to_jsonable as canonical_storage_summary_to_jsonable,
    bulk_summary_to_jsonable as bulk_summary_to_jsonable,
    format_api_summary_table as format_api_summary_table,
    format_canonical_edge_explanation_table as format_canonical_edge_explanation_table,
    format_canonical_edge_table as format_canonical_edge_table,
    format_canonical_neighborhood_table as format_canonical_neighborhood_table,
    format_canonical_node_table as format_canonical_node_table,
    format_public_read_page_footer as format_public_read_page_footer,
    format_canonical_storage_summary_table as format_canonical_storage_summary_table,
    format_bulk_summary_table as format_bulk_summary_table,
    format_email_summary_table as format_email_summary_table,
    format_js_framework_summary_table as format_js_framework_summary_table,
    format_js_summary_table as format_js_summary_table,
    format_nix_summary_table as format_nix_summary_table,
    format_openapi_summary_table as format_openapi_summary_table,
    format_python_summary_table as format_python_summary_table,
    format_ruby_summary_table as format_ruby_summary_table,
    format_terraform_summary_table as format_terraform_summary_table,
    identity_metadata_hash as identity_metadata_hash,
    query_canonical_edge_explanation as query_canonical_edge_explanation,
    query_canonical_neighborhood as query_canonical_neighborhood,
    query_canonical_node_records as query_canonical_node_records,
    query_canonical_edge_records as query_canonical_edge_records,
    query_canonical_storage_summary as query_canonical_storage_summary,
    public_read_page as public_read_page,
    public_embedded_read_result_to_jsonable as public_embedded_read_result_to_jsonable,
    public_read_page_to_jsonable as public_read_page_to_jsonable,
    validate_public_read_window as validate_public_read_window,
    query_api_summary as query_api_summary,
    query_bulk_summary as query_bulk_summary,
    query_email_summary as query_email_summary,
    query_js_framework_summary as query_js_framework_summary,
    query_js_summary as query_js_summary,
    query_nix_summary as query_nix_summary,
    query_openapi_summary as query_openapi_summary,
    query_python_summary as query_python_summary,
    query_ruby_summary as query_ruby_summary,
    query_terraform_summary as query_terraform_summary,
    email_summary_to_jsonable as email_summary_to_jsonable,
    js_framework_summary_to_jsonable as js_framework_summary_to_jsonable,
    js_summary_to_jsonable as js_summary_to_jsonable,
    nix_summary_to_jsonable as nix_summary_to_jsonable,
    openapi_summary_to_jsonable as openapi_summary_to_jsonable,
    python_summary_to_jsonable as python_summary_to_jsonable,
    ruby_summary_to_jsonable as ruby_summary_to_jsonable,
    terraform_summary_to_jsonable as terraform_summary_to_jsonable,
)
from repomap_kg.cli.dispatch import dispatch_command
from repomap_kg.cli.host_mutator_commands import (
    CANONICAL_HOST_MUTATOR_BOOLEAN_METADATA_KEYS as CANONICAL_HOST_MUTATOR_BOOLEAN_METADATA_KEYS,
    CANONICAL_HOST_MUTATOR_EDGE_KINDS as CANONICAL_HOST_MUTATOR_EDGE_KINDS,
    HOST_CATEGORY_KEY_PREFIX as HOST_CATEGORY_KEY_PREFIX,
    query_canonical_host_mutator_edge_records as _query_canonical_host_mutator_edge_records,
    canonical_edge_identity_metadata_from_args as canonical_edge_identity_metadata_from_args,
    canonical_host_mutator_category as canonical_host_mutator_category,
    canonical_host_mutator_filters_from_args as canonical_host_mutator_filters_from_args,
    canonical_host_mutator_record_has_tool as canonical_host_mutator_record_has_tool,
    canonical_host_mutator_record_to_jsonable as canonical_host_mutator_record_to_jsonable,
    canonical_host_mutator_records_to_jsonable as canonical_host_mutator_records_to_jsonable,
    canonical_host_mutator_summaries_to_jsonable as canonical_host_mutator_summaries_to_jsonable,
    canonical_host_mutator_summary_target_from_args as canonical_host_mutator_summary_target_from_args,
    canonical_metadata_text_values as canonical_metadata_text_values,
    filter_canonical_host_mutator_records as filter_canonical_host_mutator_records,
    format_canonical_host_mutator_summary_table as format_canonical_host_mutator_summary_table,
    format_canonical_host_mutator_table as format_canonical_host_mutator_table,
    format_cli_table_row as format_cli_table_row,
    psql_args_from_args as psql_args_from_args,
    render_host_mutator_table_value as render_host_mutator_table_value,
    summarize_canonical_host_mutator_records as summarize_canonical_host_mutator_records,
)
from repomap_kg.cli.parser import (
    add_local_runtime_arguments as add_local_runtime_arguments,
    add_ops_config_arguments as add_ops_config_arguments,
    add_storage_connection_arguments as add_storage_connection_arguments,
    add_storage_root_argument as add_storage_root_argument,
    build_parser,
)


def load_ops_config_from_args(args: argparse.Namespace):
    repo_map_home = getattr(args, "repo_map_home", None)
    config_path = getattr(args, "config", None)
    if repo_map_home:
        return load_ops_config_home(repo_map_home)
    if config_path:
        return load_ops_config(config_path)
    return load_ops_config_home()


def _read_json_file(path_text: str, label: str) -> dict[str, object]:
    path = Path(path_text)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} file is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} file must contain a JSON object")
    return payload


def _commands_module():
    return sys.modules.get("repomap_kg.cli", sys.modules[__name__])


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return dispatch_command(args, parser, _commands_module())


def read_observations_argument(jsonl_path: str):
    if jsonl_path == "-":
        return read_observations_jsonl(sys.stdin)
    return read_observations_jsonl(jsonl_path)


def canonical_file_neighborhood_node_from_args(args) -> str:
    if args.graph_key_version != GRAPH_KEY_VERSION:
        raise StorageSchemaError("unsupported graph key version")
    if args.depth != 1:
        raise StorageSchemaError(
            "storage file-neighborhood only supports depth 1"
        )
    try:
        return file_key(args.path)
    except GraphKeyError as error:
        raise StorageSchemaError(f"invalid file path: {error}") from error


def query_canonical_host_mutator_edge_records(args, target_key):
    return _query_canonical_host_mutator_edge_records(
        args,
        target_key,
        commands=_commands_module(),
    )
