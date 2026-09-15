"""Record types for RepoMap local operations configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from repomap_kg.graph.multi_source import (
    MultiSourceIdentityError,
    SourceKind,
    compatibility_extractor_profile,
    compatibility_source_definition_id,
    compatibility_source_selection_policy_id,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_kg.ops.config_helpers import (
    PRIVATE_DATABASE_DISPLAY as PRIVATE_DATABASE_DISPLAY,
    PRIVATE_PATH_DISPLAY as PRIVATE_PATH_DISPLAY,
    PRIVATE_PRIVACY as PRIVATE_PRIVACY,
    PRIVATE_ROOT_DISPLAY as PRIVATE_ROOT_DISPLAY,
    PRIVATE_SOURCE_DISPLAY as PRIVATE_SOURCE_DISPLAY,
    REDACTED as REDACTED,
    OpsConfigDiagnostic as OpsConfigDiagnostic,
    redact_mapping as redact_mapping,
    redact_text as redact_text,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_serialization import (
    graph_config_to_jsonable as _graph_config_to_jsonable,
    graph_storage_status_to_jsonable as _graph_storage_status_to_jsonable,
    postgres_config_to_jsonable as _postgres_config_to_jsonable,
    postgres_status_to_jsonable as _postgres_status_to_jsonable,
    runtime_config_to_jsonable as _runtime_config_to_jsonable,
    runtime_postgres_config_to_jsonable as _runtime_postgres_config_to_jsonable,
    server_memory_config_to_jsonable as _server_memory_config_to_jsonable,
    service_config_to_jsonable as _service_config_to_jsonable,
    source_placeholder_to_jsonable as _source_placeholder_to_jsonable,
    sources_config_to_jsonable as _sources_config_to_jsonable,
)


MULTI_SOURCE_REFRESH_UNSUPPORTED = "multi-source-refresh-unsupported"
MULTI_SOURCE_READBACK_UNSUPPORTED = "multi-source-readback-unsupported"
MULTI_SOURCE_REPOSITORY_DISPLAY = "[multi-source]"
SOURCE_BINDING_REFRESH_UNSUPPORTED = "source-binding-refresh-unsupported"


class OpsConfigError(ValueError):
    """Raised when the unified local operations config is invalid."""

    def __init__(self, diagnostics: Sequence["OpsConfigDiagnostic"]):
        self.diagnostics = tuple(diagnostics)
        message = "; ".join(diagnostic.message for diagnostic in self.diagnostics)
        super().__init__(message or "invalid RepoMap operations config")


@dataclass(frozen=True)
class OpsServiceConfig:
    mode: str
    mcp_transport: str
    log_level: str

    def to_jsonable(self) -> dict[str, Any]:
        return _service_config_to_jsonable(self)


@dataclass(frozen=True)
class OpsPostgresConfig:
    host: str
    port: int
    database: str
    user: str
    password_env: str | None = None
    password_file: str | None = None
    password: str | None = None

    def psql_args(self) -> list[str]:
        return self.psql_args_for_database(self.database)

    def psql_args_for_database(self, database: str | None) -> list[str]:
        return [
            "-h",
            self.host,
            "-p",
            str(self.port),
            "-U",
            self.user,
            "-d",
            database or self.database,
        ]

    def to_jsonable(self) -> dict[str, Any]:
        return _postgres_config_to_jsonable(self)


@dataclass(frozen=True)
class OpsRuntimePostgresConfig:
    direct_host_port_enabled: bool = False
    host_port: int | None = None
    bind_host: str = "127.0.0.1"

    def to_jsonable(self) -> dict[str, Any]:
        return _runtime_postgres_config_to_jsonable(self)


@dataclass(frozen=True)
class OpsRuntimeConfig:
    container_runtime: str | None = None
    postgres_host_port: int | None = None
    server_host_port: int | None = None
    bind_host: str = "127.0.0.1"
    postgres: OpsRuntimePostgresConfig = field(default_factory=OpsRuntimePostgresConfig)

    def to_jsonable(self) -> dict[str, Any]:
        return _runtime_config_to_jsonable(self)


@dataclass(frozen=True)
class OpsGraphConfig:
    id: str
    name: str
    root_path: str
    root_path_expanded: str
    repository_name: str
    privacy: str
    enabled: bool
    mcp_visible: bool
    extractor_profile: str
    refresh_policy: str
    database: str | None = None
    exclude_paths: tuple[str, ...] = ()
    source_bindings: tuple[OpsGraphSourceBindingConfig, ...] = ()
    explicit_source_bindings: bool = False

    @property
    def effective_source_bindings(self) -> tuple[OpsGraphSourceBindingConfig, ...]:
        if self.source_bindings:
            return self.source_bindings
        alias = "root"
        try:
            binding_id = graph_source_binding_id(self.id, alias)
        except MultiSourceIdentityError:
            binding_id = ""
        try:
            source_definition_id = compatibility_source_definition_id(self.id)
        except MultiSourceIdentityError:
            source_definition_id = ""
        try:
            selection_policy_id = source_selection_policy_id(
                (), self.exclude_paths
            )
        except MultiSourceIdentityError:
            try:
                selection_policy_id = compatibility_source_selection_policy_id(
                    self.exclude_paths
                )
            except MultiSourceIdentityError:
                selection_policy_id = ""
        try:
            profile = compatibility_extractor_profile(self.extractor_profile)
        except MultiSourceIdentityError:
            profile = ""
        return (
            OpsGraphSourceBindingConfig(
                schema_version=1,
                binding_id=binding_id,
                source_definition_id=source_definition_id,
                alias=alias,
                revision=1,
                source_kind=SourceKind.FOLDER,
                root_path=self.root_path,
                root_path_expanded=self.root_path_expanded,
                repository_name=self.repository_name,
                logical_root=".",
                privacy=self.privacy,
                evidence_retention="inherit",
                extractor_profile=profile,
                include_paths=(),
                exclude_paths=self.exclude_paths,
                selection_policy_id=selection_policy_id,
                resolution_policy="isolated",
                enabled=self.enabled,
            ),
        )

    @property
    def source_binding_mode(self) -> str:
        return "explicit" if self.explicit_source_bindings else "legacy-projection"

    @property
    def has_multiple_source_bindings(self) -> bool:
        return len(self.effective_source_bindings) > 1

    @property
    def repository_name_display(self) -> str:
        if self.has_multiple_source_bindings:
            return MULTI_SOURCE_REPOSITORY_DISPLAY
        if self.privacy in PRIVATE_PRIVACY and self.explicit_source_bindings:
            return PRIVATE_SOURCE_DISPLAY
        return self.repository_name

    @property
    def readback_unsupported_classification(self) -> str | None:
        if self.explicit_source_bindings and any(
            not binding.enabled
            or binding.source_kind not in {SourceKind.FOLDER, SourceKind.GIT_WORKING_TREE}
            for binding in self.effective_source_bindings
        ):
            return MULTI_SOURCE_READBACK_UNSUPPORTED
        return None

    @property
    def refresh_unsupported_classification(self) -> str | None:
        bindings = self.effective_source_bindings
        if self.explicit_source_bindings and any(
            not binding.enabled
            or binding.source_kind not in {SourceKind.FOLDER, SourceKind.GIT_WORKING_TREE}
            for binding in bindings
        ):
            return SOURCE_BINDING_REFRESH_UNSUPPORTED
        return None

    def to_jsonable(self) -> dict[str, Any]:
        return _graph_config_to_jsonable(self)


@dataclass(frozen=True)
class OpsServerMemoryConfig:
    enabled: bool
    path: str
    path_expanded: str
    mode: str

    def to_jsonable(self) -> dict[str, Any]:
        return _server_memory_config_to_jsonable(self)


@dataclass(frozen=True)
class OpsSourcePlaceholder:
    source_type: str
    id: str
    graph_id: str
    enabled: bool
    metadata: Mapping[str, Any]

    def to_jsonable(self) -> dict[str, Any]:
        return _source_placeholder_to_jsonable(self)


@dataclass(frozen=True)
class OpsSourcesConfig:
    feed: tuple[OpsSourcePlaceholder, ...] = ()
    github: tuple[OpsSourcePlaceholder, ...] = ()
    api: tuple[OpsSourcePlaceholder, ...] = ()

    def to_jsonable(self) -> dict[str, Any]:
        return _sources_config_to_jsonable(self)


@dataclass(frozen=True)
class OpsConfig:
    config_path: str
    config_home: str | None
    config_files: tuple[str, ...]
    schema_version: int
    service: OpsServiceConfig
    postgres: OpsPostgresConfig
    runtime: OpsRuntimeConfig
    graphs: tuple[OpsGraphConfig, ...]
    server_memory: OpsServerMemoryConfig
    sources: OpsSourcesConfig
    diagnostics: tuple[OpsConfigDiagnostic, ...] = ()


@dataclass(frozen=True)
class OpsPostgresStatus:
    db_checked: bool
    connected: bool | None = None
    schema_available: bool | None = None
    required_tables: Mapping[str, bool] | None = None
    error: str | None = None

    @classmethod
    def unchecked(cls) -> "OpsPostgresStatus":
        return cls(
            db_checked=False,
            connected=None,
            schema_available=None,
            required_tables=None,
            error=None,
        )

    def to_jsonable(self) -> dict[str, Any]:
        return _postgres_status_to_jsonable(self)


@dataclass(frozen=True)
class OpsGraphStorageStatus:
    db_checked: bool
    repository_name: str
    database: str | None = None
    schema_available: bool | None = None
    repository_exists: bool | None = None
    repository_id: int | None = None
    raw_observations: int | None = None
    raw_observations_total: int | None = None
    latest_run_raw_observations: int | None = None
    canonical_nodes: int | None = None
    canonical_edges: int | None = None
    error: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return _graph_storage_status_to_jsonable(self)
