"""Internal configured-graph composition for the asynchronous refresh pilot."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import stat
from threading import Event
from typing import Mapping

from repomap_kg.coordinator.contracts import JobRequest, normalize_request
from repomap_kg.coordinator._refresh_contracts import RefreshSourceError
from repomap_kg.coordinator.core import CoordinatorStore, SyntheticCoordinator
from repomap_kg.coordinator.limits import DEFAULT_LIMITS, CoordinatorLimits
from repomap_kg.coordinator.refresh_adapter import (
    ResolvedRefreshAuthority,
    build_refresh_worker_runner,
)
from repomap_kg.coordinator.startup_recovery import PublicationRouteChangedError
from repomap_kg.ops.config import graph_database, load_ops_config
from repomap_kg.ops.generations import (
    canonicalizer_generation,
    config_generation,
    configured_graph,
    extractor_generation,
)
from repomap_kg.ops.source_generation import (
    DEFAULT_SOURCE_GENERATION_LIMITS,
    SourceGenerationResult,
    scan_source_generation,
)
from repomap_kg.graph.multi_source_pipeline import (
    MultiSourceCaptureError,
    multi_source_config_generation,
    scan_multi_source_generations,
)
from repomap_kg.runtime.database_role_contract import project_database_role_config
from repomap_kg.storage import (
    read_latest_receipt_bearing_publication,
    read_run_publication,
)
from repomap_kg.coordinator.windows_security import (
    WindowsSecurityError,
    reject_reparse_path,
    validate_owner_private_acl,
)


class ConfiguredRefreshResolver:
    """Resolve private execution authority and stable generations from one config."""

    def __init__(
        self,
        config_path: Path,
        psql_path: Path,
        *,
        limits: CoordinatorLimits = DEFAULT_LIMITS,
        postgres_user: str | None = None,
        postgres_password: str | None = None,
    ) -> None:
        if (postgres_user is None) != (postgres_password is None):
            raise ValueError("configured refresh authority is incomplete")
        self._config_path = Path(config_path).resolve()
        self._psql_path = Path(psql_path)
        self._limits = limits
        self._postgres_user = postgres_user
        self._postgres_password = postgres_password

    def resolve_request(self, payload: object) -> JobRequest:
        if not isinstance(payload, Mapping):
            raise ValueError("configured refresh request is invalid")
        preflight = normalize_request(
            payload,
            source_generation="sg1:preflight",
            config_generation="cg1:preflight",
            require_synthetic_graph=False,
            limits=self._limits,
        )
        snapshot = self._snapshot(preflight.graph_id)
        return normalize_request(
            payload,
            source_generation=snapshot.source_generation,
            config_generation=snapshot.config_generation,
            extractor_generation=snapshot.extractor_generation,
            canonicalizer_generation=snapshot.canonicalizer_generation,
            require_synthetic_graph=False,
            limits=self._limits,
        )

    def resolve_authority(self, graph_id: str) -> ResolvedRefreshAuthority:
        snapshot = self._snapshot(graph_id)
        return ResolvedRefreshAuthority(
            graph_id=snapshot.graph_id,
            config_path=self._config_path,
            psql_path=self._psql_path,
            postgres_user=snapshot.postgres_user,
            postgres_password=snapshot.password,
            executable_search_path=_executable_search_path(self._psql_path),
            source_generation=snapshot.source_generation,
            config_generation=snapshot.config_generation,
            extractor_generation=snapshot.extractor_generation,
            canonicalizer_generation=snapshot.canonicalizer_generation,
        )

    def polling_graphs(self) -> tuple[tuple[str, str], ...]:
        """Return enabled polling policies without exposing configured paths."""

        config = load_ops_config(self._config_path)
        return tuple(
            (graph.id, graph.refresh_policy)
            for graph in config.graphs
            if graph.enabled
            and graph.refresh_policy in {"polling", "continuous"}
            and not graph.explicit_source_bindings
        )

    def polling_snapshot(
        self,
        graph_id: str,
        *,
        cancel_event: Event | None = None,
    ) -> "ConfiguredPollingSnapshot":
        """Resolve one bounded desired-state snapshot for reconciliation."""

        if not isinstance(graph_id, str):
            raise ValueError("configured graph is invalid")
        config = load_ops_config(self._config_path)
        authority_config = self._authority_config(config)
        graph = configured_graph(config, graph_id, require_enabled=True)
        if graph.refresh_unsupported_classification is not None:
            raise ValueError(graph.refresh_unsupported_classification)
        if graph.explicit_source_bindings:
            raise ValueError("multi-source graph polling refresh is unsupported")
        root = Path(graph.root_path_expanded).resolve()
        source = scan_source_generation(
            root,
            exclude_paths=graph.exclude_paths,
            limits=DEFAULT_SOURCE_GENERATION_LIMITS,
            cancel_event=cancel_event,
        )
        database = graph_database(config, graph)
        return ConfiguredPollingSnapshot(
            graph_id=graph.id,
            refresh_policy=graph.refresh_policy,
            source=source,
            config_generation=config_generation(authority_config, graph, root),
            extractor_generation=extractor_generation(graph),
            canonicalizer_generation=canonicalizer_generation(),
            password=_postgres_password(authority_config, self._config_path),
            psql_args=tuple(
                authority_config.postgres.psql_args_for_database(database)
            ),
        )

    def latest_publication(self, graph_id: str) -> Mapping[str, object] | None:
        """Read the latest committed generation receipt for one graph."""

        snapshot = self._snapshot(graph_id, discover_source=False)
        record = read_latest_receipt_bearing_publication(
            snapshot.psql_args,
            psql_command=str(self._psql_path),
            env=_psql_environment(
                snapshot.password, _executable_search_path(self._psql_path)
            ),
        )
        return None if record is None else record.marker()

    def read_publication(self, claim: object) -> Mapping[str, object] | None:
        graph_id = getattr(claim, "graph_id", None)
        snapshot = self._snapshot(graph_id, discover_source=False)
        if snapshot.config_generation != getattr(claim, "config_generation", None):
            raise PublicationRouteChangedError("configured storage route changed")
        record = read_run_publication(
            snapshot.psql_args,
            job_id=getattr(claim, "job_id"),
            attempt=getattr(claim, "attempt"),
            psql_command=str(self._psql_path),
            env=_psql_environment(
                snapshot.password, _executable_search_path(self._psql_path)
            ),
        )
        return None if record is None else record.marker()

    def _snapshot(
        self, graph_id: object, *, discover_source: bool = True
    ) -> "_ConfiguredSnapshot":
        if not isinstance(graph_id, str):
            raise ValueError("configured graph is invalid")
        config = load_ops_config(self._config_path)
        authority_config = self._authority_config(config)
        graph = configured_graph(
            config, graph_id, require_enabled=discover_source
        )
        if graph.refresh_unsupported_classification is not None:
            raise ValueError(graph.refresh_unsupported_classification)
        multi_source = graph.explicit_source_bindings
        root = Path(graph.root_path_expanded).resolve() if not multi_source else None
        if discover_source and not multi_source:
            assert root is not None
            if not root.is_dir():
                raise ValueError("configured graph root is unavailable")
        database = graph_database(config, graph)
        try:
            if discover_source:
                scan = scan_multi_source_generations(graph)
                source_token = scan.source_generation
                graph_config_generation = scan.config_generation
            elif multi_source:
                source_token = "sg1:readback"
                graph_config_generation = multi_source_config_generation(graph)
            else:
                source_token = "sg1:readback"
                graph_config_generation = multi_source_config_generation(graph)
        except MultiSourceCaptureError as error:
            category = (
                "source_unavailable"
                if error.category == "source_unavailable"
                else "source_capture"
            )
            raise RefreshSourceError(category) from None
        except (OSError, UnicodeError, ValueError):
            raise ValueError("configured graph source is unavailable") from None
        return _ConfiguredSnapshot(
            graph_id=graph.id,
            source_generation=source_token,
            config_generation=graph_config_generation,
            extractor_generation=extractor_generation(graph),
            canonicalizer_generation=canonicalizer_generation(),
            postgres_user=authority_config.postgres.user,
            password=_postgres_password(authority_config, self._config_path),
            psql_args=tuple(
                authority_config.postgres.psql_args_for_database(database)
            ),
        )

    def _authority_config(self, config):
        if self._postgres_user is None or self._postgres_password is None:
            return config
        return project_database_role_config(
            config,
            role=self._postgres_user,
            password=self._postgres_password,
        )


@dataclass(frozen=True)
class _ConfiguredSnapshot:
    graph_id: str
    source_generation: str
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str
    postgres_user: str
    password: str
    psql_args: tuple[str, ...]


@dataclass(frozen=True)
class ConfiguredPollingSnapshot:
    """Private polling evidence and publication-routing authority."""

    graph_id: str
    refresh_policy: str
    source: SourceGenerationResult
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str
    password: str
    psql_args: tuple[str, ...]


def _source_token(root: Path, exclude_paths: tuple[str, ...]) -> str:
    result = scan_source_generation(
        root,
        exclude_paths=exclude_paths,
        limits=DEFAULT_SOURCE_GENERATION_LIMITS,
    )
    if result.generation is None:
        raise ValueError("configured graph source is unavailable")
    return result.generation


def build_configured_refresh_coordinator(
    store: CoordinatorStore,
    instance_id: str,
    resolver: ConfiguredRefreshResolver,
    capability_directory: Path,
    *,
    limits: CoordinatorLimits = DEFAULT_LIMITS,
) -> SyntheticCoordinator:
    """Compose the proven coordinator core with configured refresh adapters."""

    return SyntheticCoordinator(
        store,
        instance_id,
        build_refresh_worker_runner(
            resolver.resolve_authority, capability_directory, limits
        ),
        publication_reader=resolver.read_publication,
        max_workers=limits.max_running_workers,
    )


def _postgres_password(config, config_path: Path) -> str:
    postgres = config.postgres
    if postgres.password is not None:
        value = postgres.password
    elif postgres.password_env is not None:
        value = os.environ.get(postgres.password_env, "")
    elif postgres.password_file is not None:
        path = Path(postgres.password_file).expanduser()
        if not path.is_absolute():
            base = config_path if config_path.is_dir() else config_path.parent
            path = base / path
        value = _read_private_password(path)
    else:
        value = ""
    if not value or len(value) > 256:
        raise ValueError("postgres credential is unavailable")
    return value


def _read_private_password(path: Path) -> str:
    try:
        if os.name == "nt":  # pragma: no cover - native Windows runner
            reject_reparse_path(path)
        details = path.lstat()
    except (OSError, WindowsSecurityError):
        raise ValueError("postgres credential is unavailable") from None
    if os.name == "nt":  # pragma: no cover - native Windows runner
        try:
            validate_owner_private_acl(path)
        except WindowsSecurityError:
            raise ValueError("postgres credential is unavailable") from None
        unsafe = not stat.S_ISREG(details.st_mode) or details.st_size > 4096
    else:
        unsafe = (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.getuid()
            or (stat.S_IMODE(details.st_mode) & 0o077) != 0
            or details.st_size > 4096
        )
    if unsafe:
        raise ValueError("postgres credential is unavailable")
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise ValueError("postgres credential is unavailable") from None


def _executable_search_path(psql_path: Path) -> tuple[Path, ...]:
    candidates = [psql_path.parent]
    candidates.extend(Path(value) for value in os.environ.get("PATH", "").split(os.pathsep))
    paths = []
    for path in candidates:
        if path in paths:
            continue
        try:
            details = path.stat()
        except OSError:
            continue
        if not stat.S_ISDIR(details.st_mode):
            continue
        if os.name == "nt":  # pragma: no cover - native Windows runner
            try:
                reject_reparse_path(path)
            except WindowsSecurityError:
                continue
            if os.access(path, os.W_OK):
                continue
        elif details.st_uid not in {0, os.getuid()} or (stat.S_IMODE(details.st_mode) & 0o022):
            continue
        if stat.S_ISDIR(details.st_mode):
            paths.append(path)
    if not paths or len(paths) > 32:
        raise ValueError("executable search path is unavailable")
    return tuple(paths)


def _psql_environment(password: str, paths: tuple[Path, ...]) -> dict[str, str]:
    environment = {
        "PATH": os.pathsep.join(str(path) for path in paths),
        "PGPASSWORD": password,
        "PSQLRC": os.devnull,
        "LANG": "C",
        "LC_ALL": "C",
    }
    if os.name == "nt":  # pragma: no cover - native Windows runner
        system_root = os.environ.get("SystemRoot")
        if not system_root:
            raise ValueError("windows_runtime_environment_unavailable")
        environment["SystemRoot"] = system_root
    return environment


__all__ = [
    "ConfiguredPollingSnapshot", "ConfiguredRefreshResolver", "build_configured_refresh_coordinator"
]
