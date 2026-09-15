"""Protocol interfaces for local operations configuration records serialization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol


class OpsServiceConfigProtocol(Protocol):
    """Protocol for service configuration projection."""

    @property
    def mode(self) -> str: ...

    @property
    def mcp_transport(self) -> str: ...

    @property
    def log_level(self) -> str: ...


OpsServiceConfig = OpsServiceConfigProtocol


class OpsPostgresConfigProtocol(Protocol):
    """Protocol for postgres configuration projection."""

    @property
    def host(self) -> str: ...

    @property
    def port(self) -> int: ...

    @property
    def database(self) -> str: ...

    @property
    def user(self) -> str: ...

    @property
    def password_env(self) -> str | None: ...

    @property
    def password_file(self) -> str | None: ...

    @property
    def password(self) -> str | None: ...


OpsPostgresConfig = OpsPostgresConfigProtocol


class OpsRuntimePostgresConfigProtocol(Protocol):
    """Protocol for runtime postgres configuration projection."""

    @property
    def direct_host_port_enabled(self) -> bool: ...

    @property
    def host_port(self) -> int | None: ...

    @property
    def bind_host(self) -> str: ...

    def to_jsonable(self) -> Mapping[str, object]: ...


OpsRuntimePostgresConfig = OpsRuntimePostgresConfigProtocol


class OpsRuntimeConfigProtocol(Protocol):
    """Protocol for runtime configuration projection."""

    @property
    def container_runtime(self) -> str | None: ...

    @property
    def postgres_host_port(self) -> int | None: ...

    @property
    def server_host_port(self) -> int | None: ...

    @property
    def bind_host(self) -> str: ...

    @property
    def postgres(self) -> OpsRuntimePostgresConfigProtocol: ...


OpsRuntimeConfig = OpsRuntimeConfigProtocol


class OpsSourceBindingProtocol(Protocol):
    """Protocol for source binding projection."""

    def to_jsonable(
        self, *, graph_privacy: str | None = None
    ) -> Mapping[str, object]: ...


OpsSourceBinding = OpsSourceBindingProtocol


class OpsGraphConfigProtocol(Protocol):
    """Protocol for graph configuration projection."""

    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def root_path(self) -> str: ...

    @property
    def root_path_expanded(self) -> str: ...

    @property
    def repository_name_display(self) -> str: ...

    @property
    def database(self) -> str | None: ...

    @property
    def privacy(self) -> str: ...

    @property
    def enabled(self) -> bool: ...

    @property
    def mcp_visible(self) -> bool: ...

    @property
    def extractor_profile(self) -> str: ...

    @property
    def refresh_policy(self) -> str: ...

    @property
    def exclude_paths(self) -> Sequence[str]: ...

    @property
    def source_binding_mode(self) -> str: ...

    @property
    def effective_source_bindings(
        self,
    ) -> Sequence[OpsSourceBindingProtocol]: ...

    @property
    def refresh_unsupported_classification(self) -> str | None: ...


OpsGraphConfig = OpsGraphConfigProtocol


class OpsServerMemoryConfigProtocol(Protocol):
    """Protocol for server memory configuration projection."""

    @property
    def enabled(self) -> bool: ...

    @property
    def path(self) -> str | None: ...

    @property
    def path_expanded(self) -> str | None: ...

    @property
    def mode(self) -> str: ...


OpsServerMemoryConfig = OpsServerMemoryConfigProtocol


class OpsSourcePlaceholderProtocol(Protocol):
    """Protocol for individual source placeholder projection."""

    @property
    def source_type(self) -> str: ...

    @property
    def id(self) -> str: ...

    @property
    def graph_id(self) -> str: ...

    @property
    def enabled(self) -> bool: ...

    @property
    def metadata(self) -> Mapping[str, object]: ...

    def to_jsonable(self) -> Mapping[str, object]: ...


OpsSourcePlaceholder = OpsSourcePlaceholderProtocol


class OpsSourcesConfigProtocol(Protocol):
    """Protocol for aggregate sources configuration projection."""

    @property
    def feed(self) -> Sequence[OpsSourcePlaceholderProtocol]: ...

    @property
    def github(self) -> Sequence[OpsSourcePlaceholderProtocol]: ...

    @property
    def api(self) -> Sequence[OpsSourcePlaceholderProtocol]: ...


OpsSourcesConfig = OpsSourcesConfigProtocol


class OpsPostgresStatusProtocol(Protocol):
    """Protocol for postgres status projection."""

    @property
    def db_checked(self) -> bool: ...

    @property
    def connected(self) -> bool | None: ...

    @property
    def schema_available(self) -> bool | None: ...

    @property
    def required_tables(self) -> Mapping[str, bool] | None: ...

    @property
    def error(self) -> str | None: ...


OpsPostgresStatus = OpsPostgresStatusProtocol


class OpsGraphStorageStatusProtocol(Protocol):
    """Protocol for graph storage status projection."""

    @property
    def db_checked(self) -> bool: ...

    @property
    def repository_name(self) -> str: ...

    @property
    def database(self) -> str | None: ...

    @property
    def schema_available(self) -> bool | None: ...

    @property
    def repository_exists(self) -> bool | None: ...

    @property
    def repository_id(self) -> int | None: ...

    @property
    def raw_observations(self) -> int | None: ...

    @property
    def raw_observations_total(self) -> int | None: ...

    @property
    def latest_run_raw_observations(self) -> int | None: ...

    @property
    def canonical_nodes(self) -> int | None: ...

    @property
    def canonical_edges(self) -> int | None: ...

    @property
    def error(self) -> str | None: ...


OpsGraphStorageStatus = OpsGraphStorageStatusProtocol


__all__ = [
    "OpsGraphConfig",
    "OpsGraphConfigProtocol",
    "OpsGraphStorageStatus",
    "OpsGraphStorageStatusProtocol",
    "OpsPostgresConfig",
    "OpsPostgresConfigProtocol",
    "OpsPostgresStatus",
    "OpsPostgresStatusProtocol",
    "OpsRuntimeConfig",
    "OpsRuntimeConfigProtocol",
    "OpsRuntimePostgresConfig",
    "OpsRuntimePostgresConfigProtocol",
    "OpsServerMemoryConfig",
    "OpsServerMemoryConfigProtocol",
    "OpsServiceConfig",
    "OpsServiceConfigProtocol",
    "OpsSourceBinding",
    "OpsSourceBindingProtocol",
    "OpsSourcePlaceholder",
    "OpsSourcePlaceholderProtocol",
    "OpsSourcesConfig",
    "OpsSourcesConfigProtocol",
]
