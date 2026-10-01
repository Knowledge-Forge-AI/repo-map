"""JSON readback adapter boundary for storage queries."""

from __future__ import annotations

import importlib
import json
import math
import os
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, Protocol

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.psql import parse_psql_json, run_psql
from repomap_kg.storage.readback_credentials import (
    DiagnosticOptions,
    _resolve_diagnostic_options as _resolve_diagnostic_options,
    psql_environment,
    psycopg_connection_params,
    sanitized_psycopg_error,
)

ExpectedJsonShape = Literal["object", "array"]
JsonReadbackPayload = dict[str, Any] | list[Any]
JsonReadbackDriver = Literal["psql", "psycopg"]
CatalogPresence = Literal["absent", "present", "denied", "unavailable", "malformed"]


PG_CONNECTOR_ENV = "REPOMAP_STORAGE_PG_CONNECTOR"
READBACK_DRIVER_ENV = "REPOMAP_STORAGE_READBACK_DRIVER"
JSON_READBACK_CAPABILITY = "json_readback"

__all__ = (
    "CatalogPresence",
    "DiagnosticOptions",
    "diagnose_psycopg_database_presence",
    "execute_json_readback",
)


class PgJsonReadbackConnector(Protocol):
    name: str
    capabilities: frozenset[str]

    def execute_json(
        self,
        sql: str,
        *,
        psql_args: Sequence[str],
        psql_command: str,
        label: str,
        expected_shape: ExpectedJsonShape,
        password: str | None = None,
    ) -> JsonReadbackPayload: ...


class PsqlJsonReadbackConnector:
    name = "psql"
    capabilities = frozenset({JSON_READBACK_CAPABILITY})

    def execute_json(
        self,
        sql: str,
        *,
        psql_args: Sequence[str],
        psql_command: str,
        label: str,
        expected_shape: ExpectedJsonShape,
        password: str | None = None,
    ) -> JsonReadbackPayload:
        sanitized_error: StorageSchemaError | None = None
        try:
            result = run_psql(
                [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
                input_text=sql,
                env=psql_environment(password),
            )
        except StorageSchemaError:
            if password is None:
                raise
            sanitized_error = StorageSchemaError(f"psql readback failed for {label}")
        if sanitized_error is not None:
            raise sanitized_error
        payload = parse_psql_json(result.stdout, label)
        return _validate_json_readback_payload(payload, label=label, expected_shape=expected_shape)


class PsycopgJsonReadbackConnector:
    name = "psycopg"
    capabilities = frozenset({JSON_READBACK_CAPABILITY})

    def execute_json(
        self,
        sql: str,
        *,
        psql_args: Sequence[str],
        psql_command: str,
        label: str,
        expected_shape: ExpectedJsonShape,
        password: str | None = None,
    ) -> JsonReadbackPayload:
        psycopg = _import_psycopg()
        connection_params = psycopg_connection_params(
            _psycopg_connection_params_from_psql_args(psql_args), password
        )
        phase = "connect"
        sanitized_error: StorageSchemaError | None = None
        try:
            with psycopg.connect(**connection_params) as connection:
                phase = "query"
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                    row = cursor.fetchone()
        except StorageSchemaError:
            raise
        except Exception as error:
            sanitized_error = sanitized_psycopg_error(label, phase, error)
        if sanitized_error is not None:
            raise sanitized_error

        payload = _json_payload_from_psycopg_row(row, label=label)
        return _validate_json_readback_payload(
            payload, label=label, expected_shape=expected_shape, driver_label="psycopg"
        )

    def diagnose_database_presence(
        self,
        *,
        psql_args: Sequence[str],
        target_database: str,
        timeout_seconds: float | None = None,
        password: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> CatalogPresence:
        """Execute a single bounded catalog query to verify target database presence.

        When timeout_seconds is None, applies independent 3.0s connect-stage and
        3000ms query-stage caps. When timeout_seconds is supplied, treats it as a
        shared remaining operation budget, accounting for elapsed connection time.
        """
        if timeout_seconds is not None and (
            type(timeout_seconds) is bool
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds < 2.0
        ):
            return "unavailable"
        try:
            psycopg = _import_psycopg()
            params = psycopg_connection_params(
                _psycopg_connection_params_from_psql_args(psql_args), password
            )
        except Exception:
            return "unavailable"
        if not (host := params.get("host")) or "," in host:
            return "unavailable"
        connect_cap = min(3.0, float(timeout_seconds)) if timeout_seconds is not None else 3.0
        if env_to := os.environ.get("PGCONNECT_TIMEOUT"):
            try:
                env_val = float(env_to)
                if env_val < 2.0 or not math.isfinite(env_val):
                    return "unavailable"
                connect_cap = min(connect_cap, env_val)
            except ValueError:
                return "unavailable"
        params["connect_timeout"] = str(int(connect_cap))
        init_query_ms = min(3000, int(timeout_seconds * 1000)) if timeout_seconds is not None else 3000
        opts = params.get("options") or os.environ.get("PGOPTIONS", "").strip()
        if (diag_opts := _resolve_diagnostic_options(opts, init_query_ms)) is None:
            return "unavailable"
        params["options"], effective_query_ms = diag_opts.options, diag_opts.effective_timeout_ms
        start_time = clock()
        try:
            with psycopg.connect(**params) as connection:
                connection.read_only = True
                if timeout_seconds is not None:
                    rem_ms = int((timeout_seconds - (clock() - start_time)) * 1000)
                    if rem_ms <= 0:
                        return "unavailable"
                    if rem_ms < effective_query_ms:
                        with connection.cursor() as cur:
                            cur.execute(f"SET statement_timeout = {rem_ms}")
                        effective_query_ms = rem_ms
                    if int((timeout_seconds - (clock() - start_time)) * 1000) < effective_query_ms:
                        return "unavailable"
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s)",
                        (target_database,),
                    )
                    row = cursor.fetchone()
        except Exception as error:
            sqlstate = getattr(error, "sqlstate", None)
            if (isinstance(sqlstate, str) and sqlstate.startswith("28")) or (
                error.__class__.__name__ == "OperationalError"
                and "password authentication failed" in str(error).lower()
            ):
                return "denied"
            return "unavailable"
        if (
            not isinstance(row, (tuple, list))
            or isinstance(row, Mapping)
            or len(row) != 1
            or type(row[0]) is not bool
        ):
            return "malformed"
        return "present" if row[0] is True else "absent"


CONNECTORS: dict[str, PgJsonReadbackConnector] = {
    "psql": PsqlJsonReadbackConnector(),
    "psycopg": PsycopgJsonReadbackConnector(),
}


def diagnose_psycopg_database_presence(
    *,
    psql_args: Sequence[str],
    target_database: str,
    timeout_seconds: float | None = None,
    password: str | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> CatalogPresence:
    connector = CONNECTORS.get("psycopg")
    if isinstance(connector, PsycopgJsonReadbackConnector):
        return connector.diagnose_database_presence(
            psql_args=psql_args,
            target_database=target_database,
            timeout_seconds=timeout_seconds,
            password=password,
            clock=clock,
        )
    return "unavailable"


def execute_json_readback(
    sql: str,
    *,
    psql_args: Sequence[str],
    psql_command: str = "psql",
    label: str,
    expected_shape: ExpectedJsonShape,
    password: str | None = None,
) -> JsonReadbackPayload:
    return execute_json_readback_with_driver(
        sql,
        driver=selected_json_readback_driver(),
        psql_args=psql_args,
        psql_command=psql_command,
        label=label,
        expected_shape=expected_shape,
        password=password,
    )


def execute_json_readback_with_driver(
    sql: str,
    *,
    driver: JsonReadbackDriver,
    psql_args: Sequence[str],
    psql_command: str,
    label: str,
    expected_shape: ExpectedJsonShape,
    password: str | None = None,
) -> JsonReadbackPayload:
    if (connector := CONNECTORS.get(driver)) is None:
        raise StorageSchemaError("unsupported storage readback driver")
    kwargs = {"password": password} if password is not None else {}
    return connector.execute_json(
        sql,
        psql_args=psql_args,
        psql_command=psql_command,
        label=label,
        expected_shape=expected_shape,
        **kwargs,
    )


def selected_json_readback_driver() -> JsonReadbackDriver:
    pg_connector = _connector_env_value(PG_CONNECTOR_ENV)
    readback_driver = _connector_env_value(READBACK_DRIVER_ENV)
    if (
        pg_connector is not None
        and readback_driver is not None
        and pg_connector != readback_driver
    ):
        raise StorageSchemaError(
            "conflicting PostgreSQL connector selectors; "
            "set only one selector or use matching values "
            f"({PG_CONNECTOR_ENV}, {READBACK_DRIVER_ENV})"
        )
    driver = pg_connector or readback_driver or "psycopg"
    if driver == "psql":
        return "psql"
    if driver == "psycopg":
        return "psycopg"
    raise StorageSchemaError(
        "unsupported storage readback driver; expected psql or psycopg"
    )


_selected_json_readback_driver = selected_json_readback_driver


def _connector_env_value(name: str) -> str | None:
    value = os.environ.get(name)
    return None if value is None else value.strip().lower()


def _execute_json_readback_with_psql(
    sql: str,
    *,
    psql_args: Sequence[str],
    psql_command: str,
    label: str,
    expected_shape: ExpectedJsonShape,
) -> JsonReadbackPayload:
    return PsqlJsonReadbackConnector().execute_json(
        sql,
        psql_args=psql_args,
        psql_command=psql_command,
        label=label,
        expected_shape=expected_shape,
    )


def _execute_json_readback_with_psycopg(
    sql: str,
    *,
    psql_args: Sequence[str],
    label: str,
    expected_shape: ExpectedJsonShape,
) -> JsonReadbackPayload:
    return PsycopgJsonReadbackConnector().execute_json(
        sql,
        psql_args=psql_args,
        psql_command="psql",
        label=label,
        expected_shape=expected_shape,
    )


def _import_psycopg():
    try:
        return importlib.import_module("psycopg")
    except ImportError as error:
        raise StorageSchemaError("Psycopg readback driver is unavailable; install psycopg") from error


def _psycopg_connection_params_from_psql_args(psql_args: Sequence[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    flag_to_param = {
        "-h": "host", "--host": "host", "-p": "port", "--port": "port",
        "-U": "user", "--username": "user", "-d": "dbname", "--dbname": "dbname",
    }
    index, args = 0, list(psql_args)
    while index < len(args):
        flag = args[index]
        if (param_name := flag_to_param.get(flag)) is None:
            raise StorageSchemaError("unsupported psql connection argument for Psycopg readback")
        value_index = index + 1
        if value_index >= len(args) or args[value_index].startswith("-"):
            raise StorageSchemaError("Psycopg readback requires a value after each psql connection flag")
        params[param_name] = args[value_index]
        index += 2
    return params


def _json_payload_from_psycopg_row(row: Any, *, label: str) -> Any:
    if row is None or len(row) != 1:
        raise StorageSchemaError(f"psycopg did not return {label} as JSON")
    value = row[0]
    if isinstance(value, str | bytes | bytearray):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise StorageSchemaError(f"psycopg did not return {label} as JSON") from error
    return value


def _validate_json_readback_payload(
    payload: Any,
    *,
    label: str,
    expected_shape: ExpectedJsonShape,
    driver_label: str = "psql",
) -> JsonReadbackPayload:
    if expected_shape == "object":
        if isinstance(payload, dict):
            return payload
        raise StorageSchemaError(f"{driver_label} did not return {label} as a JSON object")
    if expected_shape == "array":
        if isinstance(payload, list):
            return payload
        raise StorageSchemaError(f"{driver_label} did not return {label} as a JSON array")
    raise StorageSchemaError(f"unsupported JSON readback shape: {expected_shape}")
