"""Operations configuration section parsing."""

from __future__ import annotations

from typing import Any

from repomap_kg.ops.config_helpers import (
    KNOWN_POSTGRES_FIELDS,
    KNOWN_RUNTIME_FIELDS,
    KNOWN_RUNTIME_POSTGRES_FIELDS,
    KNOWN_SERVER_MEMORY_FIELDS,
    KNOWN_SERVICE_FIELDS,
    OpsConfigDiagnostic,
    expand_user_path,
    optional_bool,
    optional_int,
    optional_text,
    require_mapping,
    required_bool,
    required_int,
    required_text,
    unknown_field_diagnostics,
)
from repomap_kg.ops.config_records import (
    OpsPostgresConfig,
    OpsRuntimeConfig,
    OpsRuntimePostgresConfig,
    OpsServerMemoryConfig,
    OpsServiceConfig,
)

SUPPORTED_SERVICE_MODES = frozenset(("local",))
SUPPORTED_MCP_TRANSPORTS = frozenset(("stdio", "localhost"))
SUPPORTED_LOG_LEVELS = frozenset(("debug", "info", "warning", "error"))
SUPPORTED_SERVER_MEMORY_MODES = frozenset(("read_only",))
SUPPORTED_CONTAINER_RUNTIMES = frozenset(("docker", "podman"))


def parse_service_section(
    payload: Any,
) -> tuple[OpsServiceConfig, list[OpsConfigDiagnostic]]:
    diagnostics: list[OpsConfigDiagnostic] = []
    section = require_mapping(payload, "service", diagnostics)
    diagnostics.extend(unknown_field_diagnostics(section, KNOWN_SERVICE_FIELDS, "service"))
    mode = required_text(section, "mode", "service.mode", diagnostics)
    mcp_transport = required_text(
        section, "mcp_transport", "service.mcp_transport", diagnostics
    )
    log_level = required_text(section, "log_level", "service.log_level", diagnostics)
    if mode and mode not in SUPPORTED_SERVICE_MODES:
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "unsupported-service-mode",
                "service.mode",
                "service.mode must be local",
            )
        )
    if mcp_transport and mcp_transport not in SUPPORTED_MCP_TRANSPORTS:
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "unsupported-mcp-transport",
                "service.mcp_transport",
                "service.mcp_transport must be stdio or localhost",
            )
        )
    if log_level and log_level not in SUPPORTED_LOG_LEVELS:
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "unsupported-log-level",
                "service.log_level",
                "service.log_level must be debug, info, warning, or error",
            )
        )
    return (
        OpsServiceConfig(
            mode=mode or "local",
            mcp_transport=mcp_transport or "stdio",
            log_level=log_level or "info",
        ),
        diagnostics,
    )


def parse_postgres_section(
    payload: Any,
) -> tuple[OpsPostgresConfig, list[OpsConfigDiagnostic]]:
    diagnostics: list[OpsConfigDiagnostic] = []
    section = require_mapping(payload, "postgres", diagnostics)
    diagnostics.extend(
        unknown_field_diagnostics(section, KNOWN_POSTGRES_FIELDS, "postgres")
    )
    host = required_text(section, "host", "postgres.host", diagnostics)
    port = required_int(section, "port", "postgres.port", diagnostics)
    database = required_text(section, "database", "postgres.database", diagnostics)
    user = required_text(section, "user", "postgres.user", diagnostics)
    password_env = optional_text(section.get("password_env"))
    password_file = optional_text(section.get("password_file"))
    password = optional_text(section.get("password"))
    if password is not None:
        diagnostics.append(
            OpsConfigDiagnostic(
                "warning",
                "literal-postgres-password",
                "postgres.password",
                "literal postgres password is local-dev only and is redacted",
            )
        )
    if not (password_env or password_file or password):
        diagnostics.append(
            OpsConfigDiagnostic(
                "warning",
                "missing-postgres-password-reference",
                "postgres",
                "postgres password reference is absent; local peer auth may still work",
            )
        )
    return (
        OpsPostgresConfig(
            host=host or "",
            port=port or 5432,
            database=database or "",
            user=user or "",
            password_env=password_env,
            password_file=password_file,
            password=password,
        ),
        diagnostics,
    )


def parse_runtime_section(
    payload: Any,
) -> tuple[OpsRuntimeConfig, list[OpsConfigDiagnostic]]:
    diagnostics: list[OpsConfigDiagnostic] = []
    if payload is None:
        return OpsRuntimeConfig(), diagnostics
    section = require_mapping(payload, "runtime", diagnostics)
    diagnostics.extend(unknown_field_diagnostics(section, KNOWN_RUNTIME_FIELDS, "runtime"))
    container_runtime = optional_text(section.get("container_runtime"))
    postgres_host_port = optional_int(section.get("postgres_host_port"))
    server_host_port = optional_int(section.get("server_host_port"))
    bind_host = optional_text(section.get("bind_host")) or "127.0.0.1"
    postgres_section = section.get("postgres")
    postgres_mapping = require_mapping(
        postgres_section,
        "runtime.postgres",
        diagnostics,
    ) if postgres_section is not None else {}
    if postgres_section is not None:
        diagnostics.extend(
            unknown_field_diagnostics(
                postgres_mapping,
                KNOWN_RUNTIME_POSTGRES_FIELDS,
                "runtime.postgres",
            )
        )
    direct_host_port_enabled = optional_bool(
        postgres_mapping.get("direct_host_port_enabled")
    )
    direct_host_port_explicit = direct_host_port_enabled is not None
    direct_host_port_enabled = bool(direct_host_port_enabled)
    runtime_postgres_host_port = optional_int(postgres_mapping.get("host_port"))
    runtime_postgres_bind_host = (
        optional_text(postgres_mapping.get("bind_host")) or bind_host
    )
    if postgres_host_port is not None and not direct_host_port_explicit:
        diagnostics.append(
            OpsConfigDiagnostic(
                "warning",
                "runtime-postgres-host-port-deprecated",
                "runtime.postgres_host_port",
                (
                    "runtime.postgres_host_port is deprecated and no longer enables "
                    "direct DB host-port mapping; set runtime.postgres.direct_host_port_enabled "
                    "for local dev/debug access"
                ),
            )
        )
    if runtime_postgres_host_port is None:
        runtime_postgres_host_port = postgres_host_port
    if container_runtime and container_runtime not in SUPPORTED_CONTAINER_RUNTIMES:
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "unsupported-container-runtime",
                "runtime.container_runtime",
                "container_runtime must be docker or podman",
            )
        )
    for key, value, path in (
        ("postgres_host_port", postgres_host_port, "runtime.postgres_host_port"),
        ("server_host_port", server_host_port, "runtime.server_host_port"),
        ("host_port", runtime_postgres_host_port, "runtime.postgres.host_port"),
    ):
        if value is not None and (value <= 1024 or value > 65535):
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error",
                    "unsupported-runtime-port",
                    path,
                    f"{path} must be a high localhost port",
                )
            )
        if key in ("postgres_host_port", "host_port") and value == 5432:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    "standard-postgres-port",
                    path,
                    "postgres host port 5432 is not the default target for RepoMap local runtime",
                )
            )
    if bind_host not in ("127.0.0.1", "localhost", "::1"):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "unsupported-runtime-bind-host",
                "runtime.bind_host",
                "runtime bind_host must be localhost-only",
            )
        )
    if runtime_postgres_bind_host not in ("127.0.0.1", "localhost", "::1"):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "unsupported-runtime-bind-host",
                "runtime.postgres.bind_host",
                "runtime.postgres.bind_host must be localhost-only",
            )
        )
    return (
        OpsRuntimeConfig(
            container_runtime=container_runtime,
            postgres_host_port=postgres_host_port,
            server_host_port=server_host_port,
            bind_host=bind_host,
            postgres=OpsRuntimePostgresConfig(
                direct_host_port_enabled=direct_host_port_enabled,
                host_port=runtime_postgres_host_port,
                bind_host=runtime_postgres_bind_host,
            ),
        ),
        diagnostics,
    )


def parse_server_memory_section(
    payload: Any,
) -> tuple[OpsServerMemoryConfig, list[OpsConfigDiagnostic]]:
    diagnostics: list[OpsConfigDiagnostic] = []
    section = require_mapping(payload, "server_memory", diagnostics)
    diagnostics.extend(
        unknown_field_diagnostics(section, KNOWN_SERVER_MEMORY_FIELDS, "server_memory")
    )
    enabled = required_bool(section, "enabled", "server_memory.enabled", diagnostics)
    path = required_text(section, "path", "server_memory.path", diagnostics)
    mode = required_text(section, "mode", "server_memory.mode", diagnostics)
    if mode and mode not in SUPPORTED_SERVER_MEMORY_MODES:
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "unsupported-server-memory-mode",
                "server_memory.mode",
                "server_memory.mode must be read_only",
            )
        )
    return (
        OpsServerMemoryConfig(
            enabled=bool(enabled),
            path=path or "",
            path_expanded=expand_user_path(path or ""),
            mode=mode or "read_only",
        ),
        diagnostics,
    )
