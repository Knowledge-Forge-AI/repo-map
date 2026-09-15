"""Unified local operations TOML config loading for RepoMap."""

from __future__ import annotations

import json as json
import os as os
import tomllib as tomllib
from pathlib import Path
from typing import Any, Mapping, Sequence

from repomap_kg.ops.config_helpers import (
    KNOWN_POSTGRES_FIELDS as KNOWN_POSTGRES_FIELDS,
    KNOWN_RUNTIME_FIELDS as KNOWN_RUNTIME_FIELDS,
    KNOWN_RUNTIME_POSTGRES_FIELDS as KNOWN_RUNTIME_POSTGRES_FIELDS,
    KNOWN_SERVER_MEMORY_FIELDS as KNOWN_SERVER_MEMORY_FIELDS,
    KNOWN_SERVICE_FIELDS as KNOWN_SERVICE_FIELDS,
    KNOWN_TOP_LEVEL_SECTIONS as KNOWN_TOP_LEVEL_SECTIONS,
    REDACTED as REDACTED,
    SECRET_KEY_PARTS as SECRET_KEY_PARTS,
    OpsConfigDiagnostic as OpsConfigDiagnostic,
    bool_text as bool_text,
    expand_user_path as expand_user_path,
    format_counts as format_counts,
    is_credentialed_url as is_credentialed_url,
    is_secret_key as is_secret_key,
    optional_bool as optional_bool,
    optional_int as optional_int,
    optional_text as optional_text,
    redact_mapping as redact_mapping,
    redact_text as redact_text,
    redact_value as redact_value,
    require_mapping as require_mapping,
    required_bool as required_bool,
    required_int as required_int,
    required_text as required_text,
    unknown_field_diagnostics as unknown_field_diagnostics,
    unknown_file_field_diagnostics as unknown_file_field_diagnostics,
    unknown_top_level_diagnostics as unknown_top_level_diagnostics,
)
from repomap_kg.ops.config_graphs import (
    GRAPH_ID_PATTERN as GRAPH_ID_PATTERN,
    SAFE_POSTGRES_DATABASE_PATTERN as SAFE_POSTGRES_DATABASE_PATTERN,
    SUPPORTED_PRIVACY as SUPPORTED_PRIVACY,
    SUPPORTED_REFRESH_POLICIES as SUPPORTED_REFRESH_POLICIES,
    parse_graph_exclude_paths as parse_graph_exclude_paths,
    parse_graphs_section as parse_graphs_section,
)
from repomap_kg.ops.config_binding_records import (
    OpsGraphSourceBindingConfig as OpsGraphSourceBindingConfig,
)
from repomap_kg.ops.config_records import (
    PRIVATE_PRIVACY as PRIVATE_PRIVACY,
    OpsConfig as OpsConfig,
    OpsConfigError as OpsConfigError,
    OpsGraphConfig as OpsGraphConfig,
    OpsGraphStorageStatus as OpsGraphStorageStatus,
    OpsPostgresConfig as OpsPostgresConfig,
    OpsPostgresStatus as OpsPostgresStatus,
    OpsRuntimeConfig as OpsRuntimeConfig,
    OpsRuntimePostgresConfig as OpsRuntimePostgresConfig,
    OpsServerMemoryConfig as OpsServerMemoryConfig,
    OpsServiceConfig as OpsServiceConfig,
    OpsSourcePlaceholder as OpsSourcePlaceholder,
    OpsSourcesConfig as OpsSourcesConfig,
)
from repomap_kg.ops.config_sections import (
    SUPPORTED_CONTAINER_RUNTIMES as SUPPORTED_CONTAINER_RUNTIMES,
    SUPPORTED_LOG_LEVELS as SUPPORTED_LOG_LEVELS,
    SUPPORTED_MCP_TRANSPORTS as SUPPORTED_MCP_TRANSPORTS,
    SUPPORTED_SERVER_MEMORY_MODES as SUPPORTED_SERVER_MEMORY_MODES,
    SUPPORTED_SERVICE_MODES as SUPPORTED_SERVICE_MODES,
    parse_postgres_section as parse_postgres_section,
    parse_runtime_section as parse_runtime_section,
    parse_server_memory_section as parse_server_memory_section,
    parse_service_section as parse_service_section,
)
from repomap_kg.ops.config_sources import (
    parse_source_placeholders as parse_source_placeholders,
    parse_sources_section as parse_sources_section,
)
from repomap_kg.ops.config_status import (
    format_ops_config_status_table as format_ops_config_status_table,
    format_ops_graph_registry_table as format_ops_graph_registry_table,
    graph_database as graph_database,
    graph_database_source as graph_database_source,
    graph_psql_args as graph_psql_args,
    graph_storage_label as graph_storage_label,
    ops_config_status_to_jsonable as ops_config_status_to_jsonable,
    ops_graph_registry_status_to_jsonable as ops_graph_registry_status_to_jsonable,
)
from repomap_kg.ops.resolved_config import resolve_ops_config
from repomap_kg.ops.config_loading_records import (
    SUPPORTED_SCHEMA_VERSION as SUPPORTED_SCHEMA_VERSION,
    merge_ops_config_payloads as merge_ops_config_payloads,
)
from repomap_kg.storage import parse_psql_json as parse_psql_json, run_psql as run_psql

DEFAULT_REPOMAP_HOME = "~/.repo-map"


def resolve_repo_map_home(value: str | Path | None = None) -> Path:
    if value is not None:
        return Path(value).expanduser()
    env_value = os.environ.get("REPOMAP_HOME")
    if env_value:
        return Path(env_value).expanduser()
    return Path(DEFAULT_REPOMAP_HOME).expanduser()


def load_ops_config_home(config_home: str | Path | None = None) -> OpsConfig:
    home = resolve_repo_map_home(config_home)
    if not home.exists():
        raise OpsConfigError(
            (
                OpsConfigDiagnostic(
                    "error",
                    "config-home-missing",
                    str(home),
                    "REPOMAP_HOME does not exist; MCP-RUNTIME1 validates existing config homes only",
                ),
            )
        )
    if not home.is_dir():
        raise OpsConfigError(
            (
                OpsConfigDiagnostic(
                    "error",
                    "config-home-not-directory",
                    str(home),
                    "REPOMAP_HOME must be a directory",
                ),
            )
        )

    matched_files: list[Path] = []
    ignored_files: list[Path] = []
    for child in sorted(home.iterdir(), key=lambda item: item.name):
        if not child.is_file():
            continue
        if child.name.endswith(".rp.toml") or child.name.endswith(".rpl.toml"):
            matched_files.append(child)
        elif child.suffix == ".toml":
            ignored_files.append(child)

    ordered_files = sorted(
        matched_files,
        key=lambda item: (0 if item.name.endswith(".rp.toml") else 1, item.name),
    )
    diagnostics: list[OpsConfigDiagnostic] = [
        OpsConfigDiagnostic(
            "warning",
            "config-file-ignored",
            ignored_file.name,
            f"ignored non RepoMap config TOML file {ignored_file.name!r}",
        )
        for ignored_file in ignored_files
    ]
    if not ordered_files:
        raise OpsConfigError(
            tuple(diagnostics)
            + (
                OpsConfigDiagnostic(
                    "error",
                    "config-home-empty",
                    str(home),
                    "REPOMAP_HOME contains no *.rp.toml or *.rpl.toml files",
                ),
            )
        )

    file_payloads: list[tuple[str, Mapping[str, Any]]] = []
    for path in ordered_files:
        payload = read_toml_payload(path)
        validate_file_schema(payload, path.name)
        diagnostics.extend(unknown_top_level_diagnostics(payload, source=path.name))
        diagnostics.extend(unknown_file_field_diagnostics(payload, path.name))
        file_payloads.append((path.name, payload))

    merged_payload, merge_diagnostics = merge_ops_config_payloads(file_payloads)
    diagnostics.extend(merge_diagnostics)
    return build_ops_config_from_payload(
        merged_payload,
        config_path=str(home),
        config_home=str(home),
        config_files=tuple(path.name for path in ordered_files),
        diagnostics=diagnostics,
    )


def load_ops_config(config_path: str | Path) -> OpsConfig:
    path = Path(config_path)
    if path.is_dir():
        return load_ops_config_home(path)
    if path.suffix == ".json":
        raise OpsConfigError(
            (
                OpsConfigDiagnostic(
                    "error",
                    "ops-json-config-removed",
                    str(path),
                    (
                        "JSON ops/MCP registry config is removed from the local "
                        "operations target; use REPOMAP_HOME with *.rp.toml "
                        "and *.rpl.toml files"
                    ),
                ),
            )
        )
    payload = read_toml_payload(path)
    diagnostics = unknown_top_level_diagnostics(payload)
    return build_ops_config_from_payload(
        payload,
        config_path=str(path),
        config_home=None,
        config_files=(path.name,),
        diagnostics=diagnostics,
    )


def read_toml_payload(path: Path) -> Mapping[str, Any]:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise OpsConfigError(
            (
                OpsConfigDiagnostic(
                    "error",
                    "invalid-toml",
                    str(path),
                    f"invalid TOML: {error}",
                ),
            )
        ) from error
    except OSError as error:
        raise OpsConfigError(
            (
                OpsConfigDiagnostic(
                    "error",
                    "config-read-error",
                    str(path),
                    f"could not read config: {error}",
                ),
            )
        ) from error

    if not isinstance(payload, dict):
        raise OpsConfigError(
            (
                OpsConfigDiagnostic(
                    "error",
                    "invalid-config-root",
                    str(path),
                    "operations config must be a TOML table",
                ),
            )
        )
    return payload


def validate_file_schema(payload: Mapping[str, Any], source: str) -> None:
    schema_version = payload.get("schema_version")
    if schema_version is None:
        raise OpsConfigError(
            (
                OpsConfigDiagnostic(
                    "error",
                    "missing-schema-version",
                    f"{source}:schema_version",
                    f"{source} schema_version is required",
                ),
            )
        )
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise OpsConfigError(
            (
                OpsConfigDiagnostic(
                    "error",
                    "unsupported-schema-version",
                    f"{source}:schema_version",
                    f"{source} has unsupported schema_version {schema_version!r}; supported: 1",
                ),
            )
        )


def build_ops_config_from_payload(
    payload: Mapping[str, Any],
    *,
    config_path: str,
    config_home: str | None,
    config_files: tuple[str, ...],
    diagnostics: Sequence[OpsConfigDiagnostic] = (),
) -> OpsConfig:
    collected_diagnostics = list(diagnostics)
    schema_version = payload.get("schema_version")
    if schema_version is None:
        raise OpsConfigError(
            collected_diagnostics
            + [
                OpsConfigDiagnostic(
                    "error",
                    "missing-schema-version",
                    "schema_version",
                    "schema_version is required",
                )
            ]
        )
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise OpsConfigError(
            collected_diagnostics
            + [
                OpsConfigDiagnostic(
                    "error",
                    "unsupported-schema-version",
                    "schema_version",
                    f"unsupported schema_version {schema_version!r}; supported: 1",
                )
            ]
        )

    service, service_diagnostics = parse_service_section(payload.get("service"))
    postgres, postgres_diagnostics = parse_postgres_section(payload.get("postgres"))
    runtime, runtime_diagnostics = parse_runtime_section(payload.get("runtime"))
    graphs, graph_diagnostics = parse_graphs_section(payload.get("graphs"))
    server_memory, server_memory_diagnostics = parse_server_memory_section(
        payload.get("server_memory")
    )
    sources, source_diagnostics = parse_sources_section(payload.get("sources", {}))

    collected_diagnostics.extend(service_diagnostics)
    collected_diagnostics.extend(postgres_diagnostics)
    collected_diagnostics.extend(runtime_diagnostics)
    collected_diagnostics.extend(graph_diagnostics)
    collected_diagnostics.extend(server_memory_diagnostics)
    collected_diagnostics.extend(source_diagnostics)

    errors = [
        diagnostic for diagnostic in collected_diagnostics if diagnostic.severity == "error"
    ]
    if errors:
        raise OpsConfigError(errors)

    config = OpsConfig(
        config_path=config_path,
        config_home=config_home,
        config_files=config_files,
        schema_version=schema_version,
        service=service,
        postgres=postgres,
        runtime=runtime,
        graphs=tuple(graphs),
        server_memory=server_memory,
        sources=sources,
        diagnostics=tuple(collected_diagnostics),
    )
    resolve_ops_config(config)
    return config
