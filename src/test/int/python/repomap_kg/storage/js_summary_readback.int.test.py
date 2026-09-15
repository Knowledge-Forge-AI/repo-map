from __future__ import annotations

import json
import os

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.storage_integration import canonicalization_fixture

from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    js_summary_to_jsonable,
    query_js_summary,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV


EXPECTED_FIELDS = (
    "root_path",
    "repository_name",
    "js_files",
    "modules",
    "functions",
    "classes",
    "methods",
    "variables",
    "components",
    "routes",
    "test_suites",
    "test_cases",
    "references",
    "imports",
    "exports",
    "hooks",
    "test_expectations",
    "source_map_references",
    "frontend_asset_files",
    "saved_page_asset_files",
    "test_report_asset_files",
    "dynamic_diagnostics",
    "parse_errors",
    "profile_counts",
    "no_execution",
)

COUNT_FIELDS = EXPECTED_FIELDS[2:23]


def test_psycopg68_js_summary_connector_and_cli_parity() -> None:
    require_postgres_binaries()
    root_path = "/tmp/psycopg68-js-public"
    repository_name = "psycopg68-js-public"
    missing_root = "/tmp/psycopg68-js-missing"
    invalid_psql = "/bin/psql-not-used-by-psycopg68"
    previous_environment = {
        name: (name in os.environ, os.environ.get(name))
        for name in (PG_CONNECTOR_ENV, READBACK_DRIVER_ENV, "PGPASSWORD")
    }

    try:
        with temporary_postgres() as postgres:
            _select_connector(None, None, postgres=postgres)
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            _load_fixture(
                root_path=root_path,
                repository_name=repository_name,
                postgres=postgres,
            )

            modes = (
                ("default", None, None, invalid_psql),
                ("connector-psql", PG_CONNECTOR_ENV, "psql", postgres.psql_command),
                ("connector-psycopg", PG_CONNECTOR_ENV, "psycopg", invalid_psql),
                ("driver-psql", READBACK_DRIVER_ENV, "psql", postgres.psql_command),
                ("driver-psycopg", READBACK_DRIVER_ENV, "psycopg", invalid_psql),
            )
            direct_payloads: dict[str, dict[str, object]] = {}
            jsonable_payloads: dict[str, dict[str, object]] = {}
            for mode, selector, connector, psql_command in modes:
                _select_connector(selector, connector, postgres=postgres)
                record = query_js_summary(
                    postgres.psql_args,
                    root_path=root_path,
                    psql_command=psql_command,
                )
                direct_payloads[mode] = record.to_dict()
                jsonable_payloads[mode] = js_summary_to_jsonable(record)

            expected = direct_payloads["connector-psql"]
            assert tuple(expected) == EXPECTED_FIELDS
            assert expected["root_path"] == root_path
            assert expected["repository_name"] == repository_name
            assert all(payload == expected for payload in direct_payloads.values())
            assert all(payload == expected for payload in jsonable_payloads.values())
            _assert_nonempty_contract(expected)

            missing_payloads = {}
            for mode, selector, connector, psql_command in (
                modes[0],
                modes[1],
            ):
                _select_connector(selector, connector, postgres=postgres)
                missing_payloads[mode] = query_js_summary(
                    postgres.psql_args,
                    root_path=missing_root,
                    psql_command=psql_command,
                ).to_dict()
            missing = missing_payloads["default"]
            assert missing == missing_payloads["connector-psql"]
            assert tuple(missing) == EXPECTED_FIELDS
            assert missing["root_path"] == missing_root
            assert missing["repository_name"] is None
            assert all(missing[field] == 0 for field in COUNT_FIELDS)
            assert missing["profile_counts"] == {}
            assert missing["no_execution"] is True

            cli_args = _cli_connection_args(postgres, root_path=root_path)
            _select_connector(PG_CONNECTOR_ENV, "psql", postgres=postgres)
            psql_cli = _successful_json(
                run_repo_map_in_process(
                    "storage",
                    "js-summary",
                    *cli_args,
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
            )
            _select_connector(None, None, postgres=postgres)
            default_cli = _successful_json(
                run_repo_map_in_process(
                    "storage",
                    "js-summary",
                    *cli_args,
                    "--psql-command",
                    invalid_psql,
                    "--json",
                )
            )
            assert default_cli == psql_cli == expected

            serialized = json.dumps(
                {
                    "direct": direct_payloads,
                    "jsonable": jsonable_payloads,
                    "missing": missing_payloads,
                    "cli": {"default": default_cli, "psql": psql_cli},
                },
                sort_keys=True,
            )
            assert root_path in serialized
            assert repository_name in serialized
            for forbidden in (
                "src/index.js",
                "src/util.mjs",
                "public/report.js",
                "public/report.js.map",
                "@angular/core",
                "react-router-dom",
                "18.0.0",
                "renderReport",
                "Runner",
                "start",
                "COUNT",
                "FixtureCard",
                "/home",
                "describe[1]",
                "test[1]",
                "npm run build",
                "https://example.invalid/api",
                "EXAMPLE_API_KEY",
                "<FixtureCard",
                "raw_expression",
                "dynamic-eval",
                "free-form diagnostic",
                "Bearer ${apiToken}",
                "EXAMPLE_SESSION_SECRET",
                "TOKEN",
                "SECRET",
            ):
                assert forbidden not in serialized, forbidden
    finally:
        for name, (was_present, value) in previous_environment.items():
            _restore_environment(name, was_present, value)


def _load_fixture(*, root_path: str, repository_name: str, postgres) -> None:
    result = run_repo_map_in_process(
        "storage",
        "load-files",
        str(canonicalization_fixture("js_basic", "raw_observations.jsonl")),
        "--repository-name",
        repository_name,
        *_cli_connection_args(postgres, root_path=root_path),
        "--psql-command",
        postgres.psql_command,
        "--json",
    )
    exit_code, _stdout, stderr = result
    assert exit_code == 0, stderr


def _cli_connection_args(postgres, *, root_path: str) -> tuple[str, ...]:
    return (
        "--root-path",
        root_path,
        "--pg-host",
        str(postgres.socket_dir),
        "--pg-port",
        str(postgres.port),
        "--pg-user",
        postgres.user,
        "--pg-database",
        postgres.database,
    )


def _assert_nonempty_contract(payload: dict[str, object]) -> None:
    assert all(field in payload for field in COUNT_FIELDS)
    assert all(isinstance(payload[field], int) for field in COUNT_FIELDS)
    assert _count(payload, "js_files") >= 10
    assert _count(payload, "functions") >= 5
    assert _count(payload, "components") >= 5
    assert _count(payload, "routes") >= 2
    assert _count(payload, "test_suites") >= 2
    assert _count(payload, "test_cases") >= 2
    assert _count(payload, "imports") >= 10
    assert _count(payload, "exports") >= 5
    assert _count(payload, "hooks") >= 2
    assert _count(payload, "test_expectations") >= 2
    assert _count(payload, "source_map_references") >= 1
    assert _count(payload, "frontend_asset_files") >= 1
    assert _count(payload, "test_report_asset_files") >= 1
    assert _count(payload, "dynamic_diagnostics") >= 5
    assert _count(payload, "saved_page_asset_files") == 0
    assert _count(payload, "parse_errors") == 0
    profile_counts = payload["profile_counts"]
    assert isinstance(profile_counts, dict)
    assert len(profile_counts) >= 4
    assert tuple(profile_counts) == tuple(sorted(profile_counts))
    for profile in ("angular", "jest", "react", "vue"):
        assert profile in profile_counts
    assert payload["no_execution"] is True


def _count(payload: dict[str, object], field: str) -> int:
    value = payload[field]
    assert isinstance(value, int)
    return value


def _select_connector(selector: str | None, connector: str | None, *, postgres) -> None:
    os.environ.pop(PG_CONNECTOR_ENV, None)
    os.environ.pop(READBACK_DRIVER_ENV, None)
    if selector is not None:
        assert connector is not None
        os.environ[selector] = connector
    password = getattr(postgres, "password", None)
    if password is None:
        os.environ.pop("PGPASSWORD", None)
    else:
        os.environ["PGPASSWORD"] = password


def _successful_json(result: tuple[int, str, str]) -> dict[str, object]:
    exit_code, stdout, stderr = result
    assert exit_code == 0, stderr
    payload = json.loads(stdout)
    assert isinstance(payload, dict)
    return payload


def _restore_environment(name: str, was_present: bool, value: str | None) -> None:
    if was_present:
        assert value is not None
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
