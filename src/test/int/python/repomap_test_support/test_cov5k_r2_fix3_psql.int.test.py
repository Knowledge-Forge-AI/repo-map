from __future__ import annotations

import socket

from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.test_cov5k_r2_fix4_psycopg import public_expected_authority
from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog
from repomap_test_support.test_cov5k_r2_fix2_evidence import verify_executor_evidence
from repomap_test_support.test_cov5k_r2_fix2_runtime import execute_runtime_driver_read


def _entry(category: str):
    return next(
        entry
        for entry in build_closed_catalog()
        if entry.semantic_group == "D"
        and entry.operation_kind == "runtime_driver_read"
        and dict(entry.parameter_values)["driver"] == "psql"
        and dict(entry.parameter_values)["failure_category"] == category
    )


def _closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _replace_port(arguments: list[str], port: int) -> tuple[str, ...]:
    result = list(arguments)
    result[result.index("-h") + 1] = "127.0.0.1"
    result[result.index("-p") + 1] = str(port)
    return tuple(result)


def test_fix3_actual_psql_success_and_transport_refusal_are_process_derived() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        success_entry = _entry("success")
        success = execute_runtime_driver_read(
            success_entry,
            psql_args=tuple(postgres.psql_args),
            psql_executable="psql",
            expected_authority=public_expected_authority(),
        )
        verify_executor_evidence(success_entry, success)
        assert dict(success.observed_fields)["failure_category"] == "success"

        refusal_entry = _entry("transport_refusal")
        refusal = execute_runtime_driver_read(
            refusal_entry,
            psql_args=_replace_port(postgres.psql_args, _closed_port()),
            psql_executable="psql",
            expected_authority=public_expected_authority(),
        )
        verify_executor_evidence(refusal_entry, refusal)
        assert dict(refusal.observed_fields)["failure_category"] == "transport_refusal"
