from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.storage import (
    StorageSchemaError,
    api_manifest_summary_payload,
    api_summary_to_jsonable,
    apply_migrations,
    default_rdbms_root,
    query_api_summary,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV
from repomap_kg.storage.sql_core import sql_literal


EXPECTED_FIELDS = tuple(
    "root_path_summary repository_name api_runs sources source_ids source_types "
    "api_source_classes provider_names provider_products policy_statuses requests "
    "responses endpoints endpoint_names methods downstream_routes response_types "
    "response_byte_count redacted_responses diagnostic_counts routed_artifacts "
    "observations_with_api_provenance config_documents_from_api no_network "
    "no_mutation no_credentials_resolved no_scheduler "
    "no_provider_specific_behavior".split()
)
COUNT_MAP_FIELDS = (
    "source_types",
    "api_source_classes",
    "provider_names",
    "provider_products",
    "policy_statuses",
    "methods",
    "downstream_routes",
    "response_types",
    "diagnostic_counts",
)
BOOLEAN_FIELDS = EXPECTED_FIELDS[23:]


def test_psycopg90_api_full_function_connector_cli_and_privacy_parity() -> None:
    require_postgres_binaries()
    invalid_psql = "/bin/psql-not-used-by-psycopg90"
    previous_environment = {
        name: (name in os.environ, os.environ.get(name))
        for name in (PG_CONNECTOR_ENV, READBACK_DRIVER_ENV, "PGPASSWORD")
    }

    try:
        with tempfile.TemporaryDirectory() as tmpdir, temporary_postgres() as postgres:
            roots = _create_scenarios(Path(tmpdir))
            _select_connectors(None, None, postgres=postgres)
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            _seed_storage(postgres, roots)
            modes = (
                ("default", None, None, invalid_psql),
                ("connector-psql", "psql", None, postgres.psql_command),
                ("connector-psycopg", "psycopg", None, invalid_psql),
                ("driver-psql", None, "psql", postgres.psql_command),
                ("driver-psycopg", None, "psycopg", invalid_psql),
            )
            payloads: dict[str, dict[str, dict[str, object]]] = {}
            for mode, connector, driver, psql_command in modes:
                _select_connectors(connector, driver, postgres=postgres)
                payloads[mode] = {}
                for scenario, root in roots.items():
                    record = query_api_summary(
                        postgres.psql_args,
                        root_path=str(root.resolve()),
                        psql_command=psql_command,
                    )
                    direct = record.to_dict()
                    assert api_summary_to_jsonable(record) == direct
                    _assert_order(direct)
                    payloads[mode][scenario] = direct

            for scenario in roots:
                expected = payloads["connector-psql"][scenario]
                assert all(values[scenario] == expected for values in payloads.values())

            expected = payloads["connector-psql"]["main"]
            _assert_meaningful_main(expected)
            _assert_scenario_contracts(payloads["connector-psql"])

            _select_connectors("psycopg", "psycopg", postgres=postgres)
            dual = query_api_summary(
                postgres.psql_args,
                root_path=str(roots["main"].resolve()),
                psql_command=invalid_psql,
            ).to_dict()
            assert dual == expected

            cli_args = _cli_connection_args(postgres, root=roots["main"])
            _select_connectors("psql", None, postgres=postgres)
            psql_cli, psql_stdout = _successful_json(
                run_repo_map_in_process(
                    "storage", "api-summary", *cli_args,
                    "--psql-command", postgres.psql_command, "--json",
                )
            )
            _select_connectors(None, None, postgres=postgres)
            default_cli, default_stdout = _successful_json(
                run_repo_map_in_process(
                    "storage", "api-summary", *cli_args,
                    "--psql-command", invalid_psql, "--json",
                )
            )
            normalized = json.loads(json.dumps(expected, sort_keys=True))
            assert default_cli == psql_cli == normalized
            assert tuple(default_cli) == tuple(sorted(EXPECTED_FIELDS))
            assert default_stdout == psql_stdout == json.dumps(expected, sort_keys=True) + "\n"

            serialized = json.dumps(
                {"direct": payloads, "dual": dual, "cli": default_cli},
                sort_keys=True,
            )
            for root in roots.values():
                assert str(root.resolve()) not in serialized
            for forbidden in _private_markers():
                assert forbidden not in serialized, forbidden
    finally:
        for name, (was_present, value) in previous_environment.items():
            _restore_environment(name, was_present, value)


def test_psycopg90_database_failures_surround_manifest_work(tmp_path: Path) -> None:
    adapter_error = StorageSchemaError("api adapter failure")
    with (
        patch("repomap_kg.storage.summaries.execute_json_readback", side_effect=adapter_error),
        patch("repomap_kg.storage.summaries.api_manifest_summary_payload") as manifests,
    ):
        with pytest.raises(StorageSchemaError) as raised:
            query_api_summary(["-d", "postgres"], root_path=str(tmp_path))
    assert raised.value is adapter_error
    manifests.assert_not_called()

    malformed = {
        "repository_name": "public-api",
        "observations_with_api_provenance": None,
        "config_documents_from_api": 0,
    }
    with (
        patch("repomap_kg.storage.summaries.execute_json_readback", return_value=malformed),
        patch(
            "repomap_kg.storage.summaries.api_manifest_summary_payload",
            wraps=api_manifest_summary_payload,
        ) as manifests,
    ):
        with pytest.raises(StorageSchemaError, match="observations_with_api_provenance"):
            query_api_summary(["-d", "postgres"], root_path=str(tmp_path))
    manifests.assert_called_once_with(tmp_path)


def _create_scenarios(base: Path) -> dict[str, Path]:
    names = (
        "main", "absent", "empty", "unknown", "all-true", "false-folds",
        "defects", "all-invalid", "run-escape", "database-only",
    )
    roots = {name: base / name for name in names}
    for root in roots.values():
        root.mkdir()
    (roots["empty"] / ".repomap" / "api-runs").mkdir(parents=True)

    _write_manifest(
        roots["main"], "public-source-b", "private-run-b",
        source_type="api.rest", api_source_class="api.custom_documented_api",
        provider_name="Public Provider B", provider_product="Public Product B",
        policy_status="blocked_missing_consent",
        requests=[
            {"endpoint_name": "public-items", "method": "GET", "downstream_route": "config",
             "response_type": "application/json", "url": "https://private.example.invalid/items",
             "headers": {"Authorization": "PRIVATE_AUTH"}, "body": "PRIVATE_REQUEST"},
            {"endpoint_name": "public-status", "method": "HEAD", "downstream_route": "graph", "response_type": "text/plain"},
            "ignored-request",
        ],
        responses=[
            {"endpoint_name": "public-items", "response_byte_count": 512, "redacted": True,
             "artifact_path": "private/items.json", "headers": {"Private": "PRIVATE_RESPONSE_HEADER"},
             "body": "PRIVATE_RESPONSE", "payload": "PRIVATE_PAYLOAD"},
            {"endpoint_name": "public-extra", "response_byte_count": "128", "redacted": False, "artifact_path": None},
        ],
        root_path=str(roots["main"].resolve()), manifest_path="PRIVATE_MANIFEST_PATH",
        credential="PRIVATE_CREDENTIAL", token="PRIVATE_TOKEN", secret="PRIVATE_SECRET",
        diagnostic="PRIVATE_DIAGNOSTIC", provider_config="PRIVATE_PROVIDER_CONFIG",
    )
    _write_manifest(
        roots["main"], "public-source-a", "private-run-a",
        source_type="api.graphql", api_source_class="api.github.repository",
        provider_name="Public Provider A", provider_product="Public Product A",
        policy_status="blocked_missing_credentials",
        requests=[{"endpoint_name": "public-items", "method": "GET"}],
        responses=[{"endpoint_name": "public-items", "response_byte_count": 64, "redacted": True, "artifact_path": "private/second.json"}],
    )
    for index, policy in enumerate(("blocked_mutation", "blocked_not_allowlisted", "redacted_response"), start=1):
        _write_manifest(roots["main"], f"public-policy-{index}", f"private-policy-run-{index}", policy_status=policy)
    _write_manifest(roots["unknown"], "public-unknown", "private-run-unknown")
    _write_manifest(roots["all-true"], "public-safe", "private-run-safe")
    _write_manifest(
        roots["false-folds"], "public-false", "private-run-false",
        no_network=False, no_mutation=False, no_credentials_resolved=False, no_scheduler=False,
    )
    _write_manifest(
        roots["false-folds"], "public-ignored", "private-run-ignored",
        no_network=True, no_mutation=0, no_credentials_resolved="false",
        no_scheduler=None, no_provider_specific_behavior=False,
    )
    _write_manifest(roots["defects"], "public-valid", "private-run-valid")
    _raw_manifest(roots["defects"], "bad-json", "run").write_text("{bad", encoding="utf-8")
    _raw_manifest(roots["defects"], "not-object", "run").write_text("[]\n", encoding="utf-8")
    outside = base / "private-outside-manifest.json"
    outside.write_text('{"api_run_id":"private-outside-run"}\n', encoding="utf-8")
    _raw_manifest(roots["defects"], "escape", "run").symlink_to(outside)
    _raw_manifest(roots["all-invalid"], "bad-json", "run").write_text("{bad", encoding="utf-8")
    _raw_manifest(roots["all-invalid"], "not-object", "run").write_text("[]\n", encoding="utf-8")
    escaped = base / "private-escaped-api-runs"
    _write_manifest_at(escaped, "source", "run", {"api_run_id": "private-escaped-run"})
    (roots["run-escape"] / ".repomap").mkdir()
    (roots["run-escape"] / ".repomap" / "api-runs").symlink_to(escaped, target_is_directory=True)
    return roots


def _seed_storage(postgres, roots: dict[str, Path]) -> None:
    _insert_repository(postgres, roots["main"], "public-api-main", raw_count=2, config=True)
    _insert_repository(postgres, roots["absent"], "public-api-absent", raw_count=1, config=True)
    for name in ("empty", "all-true", "false-folds", "defects", "all-invalid", "run-escape"):
        _insert_repository(postgres, roots[name], f"public-api-{name}")
    _insert_repository(
        postgres, roots["database-only"], "public-api-database-only",
        raw_count=1, config=True,
    )


def _insert_repository(
    postgres, root: Path, name: str, *, raw_count: int = 0, config: bool = False,
) -> None:
    root_sql = sql_literal(str(root.resolve()))
    statement = (
        f"INSERT INTO repositories(name, root_path) VALUES ({sql_literal(name)}, {root_sql}); "
        f"INSERT INTO runs(repository_id, status) SELECT id, 'complete' FROM repositories WHERE root_path = {root_sql}; "
    )
    if raw_count:
        values = ", ".join(
            f"((SELECT id FROM repositories WHERE root_path = {root_sql}), "
            f"(SELECT MAX(id) FROM runs WHERE repository_id = (SELECT id FROM repositories WHERE root_path = {root_sql})), "
            f"{o}, 1, 'api.synthetic', 'private-db-source', 'private-db-path', "
            f"{sql_literal(json.dumps({'metadata': {'api_run_id': f'private-db-run-{o}'}, 'raw': 'PRIVATE_DB_PAYLOAD'}, sort_keys=True))}::jsonb, "
            f"{sql_literal(format(o + 1, '064x'))})"
            for o in range(raw_count)
        )
        statement += f"INSERT INTO raw_observations(repository_id, run_id, ordinal, schema_version, kind, source_id, path, payload_json, payload_hash) VALUES {values}; "
    if config:
        statement += _config_evidence_sql(root_sql)
    postgres.psql_scalar(statement + "SELECT COUNT(*)::text FROM repositories;")


def _config_evidence_sql(root_sql: str) -> str:
    repo = f"(SELECT id FROM repositories WHERE root_path = {root_sql})"
    run = f"(SELECT MAX(id) FROM runs WHERE repository_id = {repo})"
    raw = f"(SELECT MIN(id) FROM raw_observations WHERE repository_id = {repo})"
    return (
        f"INSERT INTO canonical_nodes(repository_id, graph_key_version, canonical_key, kind, display_name, confidence, first_seen_run_id, last_seen_run_id) VALUES "
        f"({repo}, 1, 'config.document:public-api', 'config.document', 'public-api-config', 'extracted', {run}, {run}); "
        f"INSERT INTO canonical_evidence(repository_id, run_id, graph_key_version, raw_observation_id, evidence_key, raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id, path, extractor, extractor_version, confidence) VALUES "
        f"({repo}, {run}, 1, {raw}, 'public-api-evidence', 0, 1, 'api.synthetic', 'private-db-source', 'private-db-path', 'api.synthetic', '1', 'extracted'); "
        f"INSERT INTO canonical_node_evidence(canonical_node_id, canonical_evidence_id, link_kind) SELECT canonical_nodes.id, canonical_evidence.id, 'supports' FROM canonical_nodes JOIN canonical_evidence ON canonical_evidence.repository_id = canonical_nodes.repository_id "
        f"WHERE canonical_nodes.repository_id = {repo} AND canonical_nodes.canonical_key = 'config.document:public-api'; "
    )


def _assert_meaningful_main(payload: dict[str, object]) -> None:
    assert tuple(payload) == EXPECTED_FIELDS
    assert payload["root_path_summary"] == "."
    assert payload["repository_name"] == "public-api-main"
    source_ids = payload["source_ids"]
    assert isinstance(source_ids, tuple) and source_ids == tuple(sorted(source_ids))
    assert payload["endpoint_names"] == ("public-extra", "public-items", "public-status")
    for field in ("api_runs", "sources", "requests", "responses", "endpoints",
                  "response_byte_count", "redacted_responses", "routed_artifacts",
                  "observations_with_api_provenance", "config_documents_from_api"):
        val = payload[field]
        assert isinstance(val, int) and val > 0
    assert all(payload[field] for field in COUNT_MAP_FIELDS[:-1])
    assert payload["observations_with_api_provenance"] == 2
    assert payload["config_documents_from_api"] == 1
    assert all(payload[field] is True for field in BOOLEAN_FIELDS)


def _assert_scenario_contracts(payloads: dict[str, dict[str, object]]) -> None:
    assert payloads["unknown"]["repository_name"] is None
    assert payloads["unknown"]["api_runs"] == 1
    assert payloads["absent"]["repository_name"] == "public-api-absent"
    assert payloads["absent"]["api_runs"] == 0
    assert payloads["absent"]["observations_with_api_provenance"] == 1
    assert payloads["empty"]["api_runs"] == 0
    assert payloads["database-only"]["config_documents_from_api"] == 1
    assert all(payloads["all-true"][field] is True for field in BOOLEAN_FIELDS)
    assert all(payloads["false-folds"][field] is False for field in BOOLEAN_FIELDS[:4])
    assert payloads["false-folds"]["no_provider_specific_behavior"] is True
    assert payloads["defects"]["diagnostic_counts"] == {"manifest_parse_error": 3}
    assert payloads["all-invalid"]["diagnostic_counts"] == {"manifest_parse_error": 2}
    assert payloads["run-escape"]["diagnostic_counts"] == {"manifest_parse_error": 1}


def _assert_order(payload: dict[str, object]) -> None:
    assert tuple(payload) == EXPECTED_FIELDS
    source_ids = payload["source_ids"]
    assert isinstance(source_ids, tuple) and source_ids == tuple(sorted(source_ids))
    endpoint_names = payload["endpoint_names"]
    assert isinstance(endpoint_names, tuple) and endpoint_names == tuple(sorted(endpoint_names))
    for field in COUNT_MAP_FIELDS:
        cnt = payload[field]
        assert isinstance(cnt, dict) and tuple(cnt) == tuple(sorted(cnt))


def _write_manifest(root: Path, source: str, run: str, **values: object) -> None:
    payload: dict[str, object] = {
        "source_id": source, "api_run_id": run, "source_type": "api.rest",
        "api_source_class": "api.custom_documented_api",
        "provider_name": "Public Provider", "provider_product": "Public Product",
        "policy_status": "allowed",
    }
    payload.update(values)
    _write_manifest_at(root / ".repomap" / "api-runs", source, run, payload)


def _write_manifest_at(run_root: Path, source: str, run: str, payload: dict[str, object]) -> None:
    path = run_root / source / run / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _raw_manifest(root: Path, source: str, run: str) -> Path:
    path = root / ".repomap" / "api-runs" / source / run / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _cli_connection_args(postgres, *, root: Path) -> tuple[str, ...]:
    return (
        "--root-path", str(root.resolve()), "--pg-host", str(postgres.socket_dir),
        "--pg-port", str(postgres.port), "--pg-user", postgres.user,
        "--pg-database", postgres.database,
    )


def _select_connectors(connector: str | None, driver: str | None, *, postgres) -> None:
    os.environ.pop(PG_CONNECTOR_ENV, None)
    os.environ.pop(READBACK_DRIVER_ENV, None)
    if connector is not None:
        os.environ[PG_CONNECTOR_ENV] = connector
    if driver is not None:
        os.environ[READBACK_DRIVER_ENV] = driver
    password = getattr(postgres, "password", None)
    if password is None:
        os.environ.pop("PGPASSWORD", None)
    else:
        os.environ["PGPASSWORD"] = password


def _successful_json(result: tuple[int, str, str]) -> tuple[dict[str, object], str]:
    exit_code, stdout, stderr = result
    assert exit_code == 0, stderr
    payload = json.loads(stdout)
    assert isinstance(payload, dict)
    return payload, stdout


def _private_markers() -> tuple[str, ...]:
    return (
        "private-run-b", "private-run-a", "PRIVATE_MANIFEST_PATH",
        "https://private.example.invalid/items", "PRIVATE_AUTH", "PRIVATE_REQUEST",
        "PRIVATE_RESPONSE_HEADER", "PRIVATE_RESPONSE", "PRIVATE_PAYLOAD",
        "private/items.json", "private/second.json", "PRIVATE_CREDENTIAL",
        "PRIVATE_TOKEN", "PRIVATE_SECRET", "PRIVATE_DIAGNOSTIC",
        "PRIVATE_PROVIDER_CONFIG", "private-db-source", "private-db-path",
        "PRIVATE_DB_PAYLOAD", "private-outside-run", "private-escaped-run",
    )


def _restore_environment(name: str, was_present: bool, value: str | None) -> None:
    if was_present:
        assert value is not None
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
