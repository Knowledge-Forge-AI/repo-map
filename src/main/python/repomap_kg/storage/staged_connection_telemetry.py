"""Open source-controlled staged-ingestion connections with optional telemetry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from repomap_kg.storage.backend_ownership import ConnectionRole
from repomap_kg.storage.backend_telemetry import (
    BackendTelemetry,
    ConnectionTelemetryError,
)
from repomap_kg.storage.errors import StorageSchemaError

__all__ = ["close_owned_connection", "open_owned_connection"]


def open_owned_connection(
    connection_factory: Callable[..., Any],
    params: Mapping[str, object],
    *,
    role: ConnectionRole,
    telemetry: BackendTelemetry | None,
) -> Any:
    """Open one source-controlled connection and register it before SQL."""

    try:
        connection = connection_factory(**params)
    except BaseException as error:
        if isinstance(error, Exception):
            _record_connection_failure(telemetry, role)
        raise
    if telemetry is None:
        return connection
    try:
        return telemetry.track(connection, role)
    except ConnectionTelemetryError as error:
        raise StorageSchemaError("backend ownership telemetry failed") from error


def close_owned_connection(connection: Any) -> None:
    """Close one staged connection without exposing telemetry transport errors."""

    try:
        connection.close()
    except ConnectionTelemetryError as error:
        raise StorageSchemaError("backend ownership telemetry failed") from error


def _record_connection_failure(
    telemetry: BackendTelemetry | None,
    role: ConnectionRole,
) -> None:
    if telemetry is None:
        return
    try:
        telemetry.connection_failed(role)
    except ConnectionTelemetryError as error:
        raise StorageSchemaError("backend ownership telemetry failed") from error
