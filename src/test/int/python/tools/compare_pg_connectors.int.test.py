import contextlib
import io
import json
import os
import compare_pg_connectors as tool

from repomap_test_support.postgres_harness import require_postgres_binaries

from repomap_kg.storage.readback_driver import READBACK_DRIVER_ENV


def _restore_environment_variable(
    name: str,
    was_present: bool,
    value: str | None,
) -> None:
    if was_present:
        if value is None:
            raise AssertionError(f"{name} was present without a string value")
        os.environ[name] = value
    else:
        os.environ.pop(name, None)


def test_psycopg21_compare_pg_connectors_cli_local_only_json_report() -> None:
    require_postgres_binaries()
    previous_driver_present = READBACK_DRIVER_ENV in os.environ
    previous_driver = os.environ.get(READBACK_DRIVER_ENV)
    previous_pgpassword_present = "PGPASSWORD" in os.environ
    previous_pgpassword = os.environ.get("PGPASSWORD")
    stdout = io.StringIO()

    try:
        with contextlib.redirect_stdout(stdout):
            exit_code = tool.main(
                [
                    "--iterations",
                    "1",
                    "--pg-container-port",
                    os.environ.get("REPOMAP_TEST_PG_CONTAINER_PORT", "55433"),
                    "--json",
                ]
            )
    finally:
        _restore_environment_variable(
            READBACK_DRIVER_ENV,
            previous_driver_present,
            previous_driver,
        )
        _restore_environment_variable(
            "PGPASSWORD",
            previous_pgpassword_present,
            previous_pgpassword,
        )

    assert exit_code == 0
    assert (READBACK_DRIVER_ENV in os.environ) == previous_driver_present
    assert os.environ.get(READBACK_DRIVER_ENV) == previous_driver
    assert ("PGPASSWORD" in os.environ) == previous_pgpassword_present
    assert os.environ.get("PGPASSWORD") == previous_pgpassword

    report = json.loads(stdout.getvalue())
    expected_operations = (
        "canonical_storage_summary",
        "canonical_node_records",
        "canonical_edge_records",
        "canonical_edge_explanation",
    )
    assert tuple((row["connector"], row["operation"]) for row in report) == tuple(
        (connector, operation)
        for connector in ("psql", "psycopg")
        for operation in expected_operations
    )
    assert len(report) == 8
    assert all(row["iterations"] == 1 for row in report)
    assert all(row["parity"] is True for row in report)
    assert all(row["elapsed_seconds_min"] >= 0 for row in report)
    assert all(row["elapsed_seconds_median"] >= 0 for row in report)
    assert all(row["elapsed_seconds_max"] >= 0 for row in report)
    assert all(row["payload_bytes"] > 0 for row in report)
    assert all(row["fixture"] == "psycopg-adapted-family-parity" for row in report)

    serialized = stdout.getvalue()
    for forbidden_text in (
        "/tmp/repomap-psycopg-parity",
        "psycopg-parity-fixture",
        "root_path",
        "repository",
        "database",
        "username",
        "psql_args",
        "--host",
        "--port",
        "--username",
        "--dbname",
        "SELECT",
        "src/app.py",
        "README.md",
        "node_stable_key",
        "edge_stable_key",
        "evidence_stable_key",
        "127.0.0.1",
        os.environ.get("REPOMAP_TEST_PG_CONTAINER_PORT", "55433"),
    ):
        assert forbidden_text not in serialized
