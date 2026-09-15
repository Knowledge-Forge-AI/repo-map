"""JSON readback adapter boundary for storage queries."""

from __future__ import annotations

import importlib
import json
import math
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, NamedTuple, Protocol

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.psql import parse_psql_json, run_psql

ExpectedJsonShape = Literal["object", "array"]
JsonReadbackPayload = dict[str, Any] | list[Any]
JsonReadbackDriver = Literal["psql", "psycopg"]
CatalogPresence = Literal["absent", "present", "denied", "unavailable", "malformed"]


class DiagnosticOptions(NamedTuple):
    options: str
    effective_timeout_ms: int


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
    ) -> JsonReadbackPayload:
        result = run_psql([psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"], input_text=sql)
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
    ) -> JsonReadbackPayload:
        psycopg = _import_psycopg()
        connection_params = _psycopg_connection_params_from_psql_args(psql_args)
        phase = "connect"
        try:
            with psycopg.connect(**connection_params) as connection:
                phase = "query"
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                    row = cursor.fetchone()
        except StorageSchemaError:
            raise
        except Exception as error:
            schema_error = StorageSchemaError(f"psycopg readback failed for {label}")
            setattr(schema_error, "_readback_phase", phase)
            raise schema_error from error

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
            params = _psycopg_connection_params_from_psql_args(psql_args)
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


def _resolve_diagnostic_options(existing: str | None, target_ms: int) -> DiagnosticOptions | None:
    if not existing or not existing.strip():
        return DiagnosticOptions(f"-c default_transaction_read_only=on -c statement_timeout={target_ms}", target_ms)
    if any(ch in existing for ch in ('"', "'", "\\")):
        return None
    mults = {"ms": 1, "s": 1000, "min": 60_000, "h": 3_600_000, "d": 86_400_000}
    tokens, new_toks, seen = existing.strip().split(), [], set()
    has_to, has_ro, eff_to, i = False, False, target_ms, 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "-c" and i + 1 < len(tokens):
            is_att, pair, i = False, tokens[i + 1], i + 2
        elif tok.startswith("-c") and len(tok) > 2:
            is_att, pair, i = True, tok[2:], i + 1
        else:
            return None
        if "=" not in pair:
            return None
        k, v = (x.strip() for x in pair.split("=", 1))
        k = k.lower()
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", k) or k in seen:
            return None
        seen.add(k)
        if k == "statement_timeout":
            if not (m := re.match(r"^(\d+)(ms|s|min|h|d)?$", v.lower())):
                return None
            has_to, parsed = True, int(m.group(1)) * mults[m.group(2) or "ms"]
            eff_to = target_ms if parsed == 0 else min(target_ms, parsed)
            val = f"statement_timeout={eff_to}"
        elif k == "default_transaction_read_only":
            if v.lower() not in {"on", "off", "true", "false", "yes", "no", "1", "0"}:
                return None
            has_ro, val = True, "default_transaction_read_only=on"
        elif re.match(r"^[a-zA-Z0-9_.,:-]+$", v):
            val = f"{k}={v}"
        else:
            return None
        new_toks.append(f"-c{val}" if is_att else f"-c {val}")
    if not has_ro:
        new_toks.append("-c default_transaction_read_only=on")
    if not has_to:
        new_toks.append(f"-c statement_timeout={target_ms}")
    return DiagnosticOptions(" ".join(new_toks), eff_to)


CONNECTORS: dict[str, PgJsonReadbackConnector] = {
    "psql": PsqlJsonReadbackConnector(),
    "psycopg": PsycopgJsonReadbackConnector(),
}


def diagnose_psycopg_database_presence(
    *,
    psql_args: Sequence[str],
    target_database: str,
    timeout_seconds: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> CatalogPresence:
    connector = CONNECTORS.get("psycopg")
    if isinstance(connector, PsycopgJsonReadbackConnector):
        return connector.diagnose_database_presence(
            psql_args=psql_args,
            target_database=target_database,
            timeout_seconds=timeout_seconds,
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
) -> JsonReadbackPayload:
    return execute_json_readback_with_driver(
        sql,
        driver=selected_json_readback_driver(),
        psql_args=psql_args,
        psql_command=psql_command,
        label=label,
        expected_shape=expected_shape,
    )


def execute_json_readback_with_driver(
    sql: str,
    *,
    driver: JsonReadbackDriver,
    psql_args: Sequence[str],
    psql_command: str,
    label: str,
    expected_shape: ExpectedJsonShape,
) -> JsonReadbackPayload:
    if (connector := CONNECTORS.get(driver)) is None:
        raise StorageSchemaError("unsupported storage readback driver")
    return connector.execute_json(
        sql, psql_args=psql_args, psql_command=psql_command, label=label, expected_shape=expected_shape
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
        sql, psql_args=psql_args, psql_command=psql_command, label=label, expected_shape=expected_shape
    )


def _execute_json_readback_with_psycopg(
    sql: str,
    *,
    psql_args: Sequence[str],
    label: str,
    expected_shape: ExpectedJsonShape,
) -> JsonReadbackPayload:
    return PsycopgJsonReadbackConnector().execute_json(
        sql, psql_args=psql_args, psql_command="psql", label=label, expected_shape=expected_shape
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
