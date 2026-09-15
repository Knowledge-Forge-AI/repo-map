"""Spawn-safe resource specification and worker-owned preparation reads."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import time
from typing import Callable, Mapping, Protocol, TypeVar

import psycopg
from psycopg.conninfo import make_conninfo

from scale12_resource_sampling import (
    read_cluster_wal_bytes,
    read_container_rss_upper_bound,
    read_database_temporary_bytes,
    read_process_rss_bytes,
)
from scale14_postgres_storage import (
    read_allocated_tree_bytes,
    read_backing_free_bytes,
)
from scale28_preparation_values import (
    ResourceBaseline,
    canonical_protocol_bytes,
)


_CONTAINER_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_CONNECTION_FIELDS = frozenset(
    {
        "host",
        "hostaddr",
        "port",
        "dbname",
        "user",
        "password",
        "sslmode",
        "application_name",
        "connect_timeout",
        "options",
    }
)


class PreparationResourceError(RuntimeError):
    """One bounded resource failure with exact worker source ownership."""

    def __init__(self, category: str, boundary: str) -> None:
        self.category = category
        self.boundary = boundary
        super().__init__(f"{category} at {boundary}")


@dataclass(frozen=True, slots=True, repr=False)
class PreparationResourceSpecification:
    """Deeply immutable private inputs required by the preparation worker."""

    pgdata_root: str = field(repr=False)
    pgdata_baseline_bytes: int
    client_pid: int
    container_runtime: str
    postgres_container: str = field(repr=False)
    connection_parameters: tuple[tuple[str, str | int], ...] = field(repr=False)

    @classmethod
    def create(
        cls,
        *,
        pgdata_root: Path,
        pgdata_baseline_bytes: int,
        client_pid: int,
        container_runtime: str,
        postgres_container: str,
        connection_parameters: Mapping[str, object],
    ) -> PreparationResourceSpecification:
        if not isinstance(connection_parameters, Mapping):
            raise ValueError("preparation connection parameters are invalid")
        if not set(connection_parameters) <= _CONNECTION_FIELDS:
            raise ValueError("preparation connection parameters are invalid")
        copied: list[tuple[str, str | int]] = []
        for name in sorted(connection_parameters):
            value = connection_parameters[name]
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                raise ValueError("preparation connection parameters are invalid")
            copied.append((name, value))
        return cls(
            os.fspath(pgdata_root),
            pgdata_baseline_bytes,
            client_pid,
            container_runtime,
            postgres_container,
            tuple(copied),
        )

    def __post_init__(self) -> None:
        root = Path(self.pgdata_root)
        if not root.is_absolute():
            raise ValueError("preparation PGDATA root is invalid")
        for value in (self.pgdata_baseline_bytes, self.client_pid):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("preparation resource numeric value is invalid")
        if self.container_runtime not in {"docker", "podman"}:
            raise ValueError("preparation container runtime is invalid")
        if _CONTAINER_IDENTITY.fullmatch(self.postgres_container) is None:
            raise ValueError("preparation container identity is invalid")
        if (
            not self.connection_parameters
            or tuple(sorted(self.connection_parameters))
            != self.connection_parameters
            or len({name for name, _value in self.connection_parameters})
            != len(self.connection_parameters)
        ):
            raise ValueError("preparation connection parameters are invalid")

    def __repr__(self) -> str:
        return "PreparationResourceSpecification(<redacted>)"

    @property
    def digest(self) -> str:
        """Bind private values without projecting them into retained evidence."""

        private = canonical_protocol_bytes(
            {
                "pgdata_root": self.pgdata_root,
                "pgdata_baseline_bytes": self.pgdata_baseline_bytes,
                "client_pid": self.client_pid,
                "container_runtime": self.container_runtime,
                "postgres_container": self.postgres_container,
                "connection_parameters": [
                    [name, value] for name, value in self.connection_parameters
                ],
            }
        )
        return hashlib.sha256(private).hexdigest()

    def connection_mapping(self) -> dict[str, str | int]:
        """Return a detached worker-local connection mapping."""

        return dict(self.connection_parameters)


class PreparedResourceHandleLike(Protocol):
    """Protocol for prepared resource handles."""

    @property
    def baseline(self) -> ResourceBaseline: ...
    def close(self) -> None: ...


@dataclass(slots=True)
class PreparedResourceHandle:
    """Worker-local baseline plus its sole still-open SQL connection."""

    baseline: ResourceBaseline
    connection: object = field(repr=False)

    def close(self) -> None:
        close = getattr(self.connection, "close", None)
        if callable(close):
            close()
        self.connection = None


def prepare_resources(
    specification: PreparationResourceSpecification,
) -> PreparedResourceHandle:
    """Perform the complete slow resource preparation inside the worker."""

    started_ns = time.monotonic_ns()
    with ThreadPoolExecutor(
        max_workers=4,
        thread_name_prefix="scale28-preparation-resource",
    ) as executor:
        allocated_future = executor.submit(
            _timed_read,
            read_allocated_tree_bytes,
            Path(specification.pgdata_root),
        )
        free_future = executor.submit(
            _timed_read,
            read_backing_free_bytes,
            Path(specification.pgdata_root),
        )
        client_rss_future = executor.submit(
            _timed_read,
            read_process_rss_bytes,
            specification.client_pid,
        )
        container_rss_future = executor.submit(
            _timed_read,
            read_container_rss_upper_bound,
            specification.container_runtime,
            specification.postgres_container,
        )
        allocated, allocated_completed_ns = allocated_future.result()
        free_bytes, free_completed_ns = free_future.result()
        client_rss, client_rss_completed_ns = client_rss_future.result()
        container_rss, container_rss_completed_ns = container_rss_future.result()
    if allocated is None:
        raise PreparationResourceError(
            "resource_unavailable",
            "pgdata_allocated_read",
        )
    if free_bytes is None:
        raise PreparationResourceError("resource_unavailable", "backing_free_read")
    pgdata_completed_ns = max(allocated_completed_ns, free_completed_ns)
    if min(client_rss_completed_ns, container_rss_completed_ns) < started_ns:
        raise RuntimeError("preparation resource reader ordering is invalid")
    if client_rss is None:
        raise PreparationResourceError("resource_unavailable", "client_rss_read")
    if container_rss is None:
        raise PreparationResourceError(
            "resource_unavailable",
            "container_rss_read",
        )
    parameters = specification.connection_mapping()
    parameters["connect_timeout"] = 2
    existing_options = parameters.get("options", "")
    if not isinstance(existing_options, str):
        raise RuntimeError("preparation connection options are invalid")
    parameters["options"] = " ".join(
        part
        for part in (
            existing_options,
            "-c statement_timeout=4000ms",
        )
        if part
    )
    try:
        connection = psycopg.connect(
            conninfo=make_conninfo("", **parameters), autocommit=True,
        )
    except Exception as error:
        raise PreparationResourceError(
            "worker_connection_bootstrap_failed",
            "resource_connection",
        ) from error
    try:
        try:
            temporary_bytes = read_database_temporary_bytes(connection)
        except Exception as error:
            raise PreparationResourceError(
                "resource_reader_failed",
                "temporary_bytes_read",
            ) from error
        try:
            wal_bytes = read_cluster_wal_bytes(connection)
        except Exception as error:
            raise PreparationResourceError(
                "resource_reader_failed",
                "wal_bytes_read",
            ) from error
        baseline = ResourceBaseline(
            schema_version=1,
            client_peak_rss_bytes=int(client_rss),
            postgresql_container_rss_upper_bound=int(container_rss),
            temporary_byte_upper_bound_delta=0,
            wal_upper_bound_delta=0,
            allocated_delta_bytes=max(
                0,
                int(allocated) - specification.pgdata_baseline_bytes,
            ),
            backing_free_bytes=int(free_bytes),
            pgdata_reader_elapsed_ns=pgdata_completed_ns - started_ns,
            availability="available",
        )
        if temporary_bytes < 0 or wal_bytes < 0:
            raise RuntimeError("preparation resource counter is invalid")
        return PreparedResourceHandle(baseline, connection)
    except BaseException:
        connection.close()
        raise


_T = TypeVar("_T")


def _timed_read(reader: Callable[..., _T], *arguments: object) -> tuple[_T, int]:
    value = reader(*arguments)
    return value, time.monotonic_ns()


__all__ = [
    "PreparationResourceError",
    "PreparationResourceSpecification",
    "PreparedResourceHandle",
    "PreparedResourceHandleLike",
    "prepare_resources",
]
