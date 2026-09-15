from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.storage import (
    apply_migrations,
    bulk_summary_to_jsonable,
    default_rdbms_root,
    query_bulk_summary,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV
from repomap_kg.storage.sql_core import sql_literal


EXPECTED_FIELDS = tuple(
    "root_path_summary repository_name bulk_runs sources source_ids "
    "corpus_kinds policy_statuses file_count_included file_count_skipped "
    "total_bytes_included extractor_counts skip_reasons diagnostic_counts "
    "redaction_counts limit_hit_count max_files_hit_count "
    "max_total_bytes_hit_count max_file_bytes_hit_count max_depth_hit_count "
    "archive_deferred warc_deferred email_export_runs mixed_corpus_runs "
    "observations_with_bulk_provenance no_provider_api no_external_fetch "
    "no_source_mutation no_archive_decompression".split()
)
COUNT_MAP_FIELDS = (
    "corpus_kinds",
    "policy_statuses",
    "extractor_counts",
    "skip_reasons",
    "diagnostic_counts",
    "redaction_counts",
)
BOOLEAN_FIELDS = EXPECTED_FIELDS[24:]


def test_psycopg87_bulk_full_function_connector_cli_and_privacy_parity() -> None:
    require_postgres_binaries()
    invalid_psql = "/bin/psql-not-used-by-psycopg87"
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
                    record = query_bulk_summary(
                        postgres.psql_args,
                        root_path=str(root.resolve()),
                        psql_command=psql_command,
                    )
                    direct = record.to_dict()
                    assert bulk_summary_to_jsonable(record) == direct
                    _assert_order(direct)
                    payloads[mode][scenario] = direct

            for scenario in roots:
                expected = payloads["connector-psql"][scenario]
                assert all(mode_payload[scenario] == expected for mode_payload in payloads.values())

            expected = payloads["connector-psql"]["main"]
            _assert_meaningful_main(expected)
            _assert_scenario_contracts(payloads["connector-psql"])

            _select_connectors("psycopg", "psycopg", postgres=postgres)
            dual = query_bulk_summary(
                postgres.psql_args,
                root_path=str(roots["main"].resolve()),
                psql_command=invalid_psql,
            ).to_dict()
            assert dual == expected

            cli_args = _cli_connection_args(postgres, root=roots["main"])
            _select_connectors("psql", None, postgres=postgres)
            psql_cli, psql_stdout = _successful_json(
                run_repo_map_in_process(
                    "storage", "bulk-summary", *cli_args,
                    "--psql-command", postgres.psql_command, "--json",
                )
            )
            _select_connectors(None, None, postgres=postgres)
            default_cli, default_stdout = _successful_json(
                run_repo_map_in_process(
                    "storage", "bulk-summary", *cli_args,
                    "--psql-command", invalid_psql, "--json",
                )
            )
            json_normalized_direct = json.loads(json.dumps(expected, sort_keys=True))
            assert default_cli == psql_cli == json_normalized_direct
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


def _create_scenarios(base: Path) -> dict[str, Path]:
    roots = {name: base / name for name in (
        "main", "absent", "empty", "unknown", "manifest-greater", "equal",
        "missing-zero", "defects", "all-invalid", "run-escape",
    )}
    for root in roots.values():
        root.mkdir()
    (roots["empty"] / ".repomap" / "bulk-runs").mkdir(parents=True)

    _write_manifest(
        roots["main"], "public-source-b", "private-run-mixed",
        corpus_kind="mixed_corpus", policy_status="allowed_with_limits",
        file_count_included=4, file_count_skipped=2, total_bytes_included=400,
        extractor_counts={"python": 2}, diagnostic_counts={"public_diagnostic": 1},
        redaction_counts={"raw_observations": 1, "content_redacted": 1},
        skipped_files=[
            {"relative_path": "private-archive.zip", "reason": "archive_deferred"},
            {"relative_path": "private-archive.warc", "reason": "warc_deferred"},
        ],
        limit_hit=True,
        limit_reason=("max_files_exceeded,max_total_bytes_exceeded,"
                      "max_file_bytes_exceeded,max_depth_exceeded"),
        resolved_root=str(roots["main"].resolve()),
        raw_manifest="private-raw-manifest-content",
        credential="PRIVATE_BULK_CREDENTIAL", secret="PRIVATE_BULK_SECRET",
        token="PRIVATE_BULK_TOKEN", url="https://private.example.invalid/data",
        source_content="private-source-snippet",
    )
    _write_manifest(
        roots["main"], "public-source-a", "private-run-email",
        corpus_kind="email_export", policy_status="allowed",
        file_count_included=1, file_count_skipped=1, total_bytes_included=100,
        extractor_counts={"eml": 1},
    )
    _write_manifest(roots["unknown"], "public-unknown", "private-run-unknown")
    _write_manifest(
        roots["manifest-greater"], "public-source", "private-run-manifest-greater",
        redaction_counts={"raw_observations": 5},
    )
    _write_manifest(
        roots["equal"], "public-source", "private-run-equal",
        redaction_counts={"raw_observations": 2},
    )
    _write_manifest(roots["missing-zero"], "public-source", "private-run-zero")
    _write_manifest(roots["defects"], "public-valid", "private-run-valid")
    _raw_manifest(roots["defects"], "bad-json", "run").write_text("{bad", encoding="utf-8")
    _raw_manifest(roots["defects"], "not-object", "run").write_text("[]\n", encoding="utf-8")
    outside = base / "private-outside-manifest.json"
    outside.write_text('{"bulk_run_id":"private-outside-run"}\n', encoding="utf-8")
    _raw_manifest(roots["defects"], "escape", "run").symlink_to(outside)
    _raw_manifest(roots["all-invalid"], "bad-json", "run").write_text("{bad", encoding="utf-8")
    _raw_manifest(roots["all-invalid"], "not-object", "run").write_text("[]\n", encoding="utf-8")
    escaped = base / "private-escaped-bulk-runs"
    _write_manifest_at(escaped, "source", "run", {"bulk_run_id": "private-escaped-run"})
    (roots["run-escape"] / ".repomap").mkdir()
    (roots["run-escape"] / ".repomap" / "bulk-runs").symlink_to(escaped, target_is_directory=True)
    return roots


def _seed_storage(postgres, roots: dict[str, Path]) -> None:
    _insert_repository(
        postgres, roots["main"], "public-bulk-main",
        (
            {"bulk_run_id": "db-private-run-1", "redacted": True},
            {"bulk_run_id": "db-private-run-2", "redaction_reason": "private-redaction-reason"},
            {"bulk_run_id": "db-private-run-3"},
        ),
    )
    _insert_repository(
        postgres, roots["absent"], "public-bulk-absent",
        ({"bulk_run_id": "db-private-absent", "redacted": True},),
    )
    _insert_repository(postgres, roots["empty"], "public-bulk-empty", ())
    _insert_repository(
        postgres, roots["manifest-greater"], "public-bulk-manifest-greater",
        ({"bulk_run_id": "db-private-manifest-greater", "redacted": True},),
    )
    _insert_repository(
        postgres, roots["equal"], "public-bulk-equal",
        (
            {"bulk_run_id": "db-private-equal-1", "redacted": True},
            {"bulk_run_id": "db-private-equal-2", "redacted": True},
        ),
    )
    for name in ("missing-zero", "defects", "all-invalid", "run-escape"):
        _insert_repository(postgres, roots[name], f"public-bulk-{name}", ())


def _insert_repository(postgres, root: Path, name: str, rows: tuple[dict[str, object], ...]) -> None:
    root_sql = sql_literal(str(root.resolve()))
    statement = (
        "INSERT INTO repositories(name, root_path) VALUES "
        f"({sql_literal(name)}, {root_sql}); "
        "INSERT INTO runs(repository_id, status) SELECT id, 'complete' "
        f"FROM repositories WHERE root_path = {root_sql}; "
    )
    if rows:
        values = ", ".join(
            f"((SELECT id FROM repositories WHERE root_path = {root_sql}), "
            f"(SELECT MAX(id) FROM runs WHERE repository_id = "
            f"(SELECT id FROM repositories WHERE root_path = {root_sql})), "
            f"{ordinal}, 1, 'bulk.synthetic', 'private-source-id', 'private-path', "
            f"{sql_literal(json.dumps({'metadata': metadata, 'raw_payload': 'private-db-payload'}, sort_keys=True))}::jsonb, "
            f"{sql_literal(format(ordinal + 1, '064x'))})"
            for ordinal, metadata in enumerate(rows)
        )
        statement += (
            "INSERT INTO raw_observations(repository_id, run_id, ordinal, "
            "schema_version, kind, source_id, path, payload_json, payload_hash) VALUES "
            f"{values}; "
        )
    postgres.psql_scalar(statement + "SELECT COUNT(*)::text FROM repositories;")


def _assert_meaningful_main(payload: dict[str, object]) -> None:
    assert tuple(payload) == EXPECTED_FIELDS
    assert payload["root_path_summary"] == "."
    assert payload["repository_name"] == "public-bulk-main"
    assert payload["source_ids"] == ("public-source-a", "public-source-b")
    for field in (
        "bulk_runs", "sources", "file_count_included", "file_count_skipped",
        "total_bytes_included", "limit_hit_count", "max_files_hit_count",
        "max_total_bytes_hit_count", "max_file_bytes_hit_count",
        "max_depth_hit_count", "archive_deferred", "warc_deferred",
        "email_export_runs", "mixed_corpus_runs", "observations_with_bulk_provenance",
    ):
        value = payload[field]
        assert isinstance(value, int)
        assert value > 0
    assert all(payload[field] for field in COUNT_MAP_FIELDS)
    redaction_counts = payload["redaction_counts"]
    assert isinstance(redaction_counts, dict)
    assert redaction_counts["raw_observations"] == 2
    assert all(payload[field] is True for field in BOOLEAN_FIELDS)


def _assert_scenario_contracts(payloads: dict[str, dict[str, object]]) -> None:
    assert payloads["unknown"]["repository_name"] is None
    assert payloads["unknown"]["bulk_runs"] == 1
    assert payloads["absent"]["repository_name"] == "public-bulk-absent"
    assert payloads["absent"]["bulk_runs"] == 0
    assert payloads["absent"]["redaction_counts"] == {"raw_observations": 1}
    assert payloads["empty"]["bulk_runs"] == 0
    assert payloads["empty"]["redaction_counts"] == {}
    assert payloads["manifest-greater"]["redaction_counts"] == {"raw_observations": 5}
    assert payloads["equal"]["redaction_counts"] == {"raw_observations": 2}
    assert payloads["missing-zero"]["redaction_counts"] == {}
    assert payloads["defects"]["bulk_runs"] == 1
    assert payloads["defects"]["diagnostic_counts"] == {"manifest_parse_error": 3}
    assert payloads["all-invalid"]["diagnostic_counts"] == {"manifest_parse_error": 2}
    assert payloads["run-escape"]["diagnostic_counts"] == {"manifest_parse_error": 1}


def _assert_order(payload: dict[str, object]) -> None:
    assert tuple(payload) == EXPECTED_FIELDS
    source_ids = payload["source_ids"]
    assert isinstance(source_ids, tuple)
    assert all(isinstance(source_id, str) for source_id in source_ids)
    assert source_ids == tuple(sorted(source_ids))
    for field in COUNT_MAP_FIELDS:
        values = payload[field]
        assert isinstance(values, dict)
        keys = tuple(values)
        assert all(isinstance(key, str) for key in keys)
        assert keys == tuple(sorted(keys))


def _write_manifest(root: Path, source: str, run: str, **values: object) -> None:
    payload: dict[str, object] = {
        "source_id": source, "bulk_run_id": run,
        "corpus_kind": "mixed_corpus", "policy_status": "allowed",
    }
    payload.update(values)
    _write_manifest_at(root / ".repomap" / "bulk-runs", source, run, payload)


def _write_manifest_at(run_root: Path, source: str, run: str, payload: dict[str, object]) -> None:
    _raw_manifest_at(run_root, source, run).write_text(
        json.dumps(payload, sort_keys=True), encoding="utf-8",
    )


def _raw_manifest(root: Path, source: str, run: str) -> Path:
    return _raw_manifest_at(root / ".repomap" / "bulk-runs", source, run)


def _raw_manifest_at(run_root: Path, source: str, run: str) -> Path:
    path = run_root / source / run / "manifest.json"
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
        "private-run-mixed", "private-run-email", "private-archive.zip",
        "private-archive.warc", "private-raw-manifest-content",
        "PRIVATE_BULK_CREDENTIAL", "PRIVATE_BULK_SECRET", "PRIVATE_BULK_TOKEN",
        "https://private.example.invalid/data", "private-source-snippet",
        "private-redaction-reason", "private-db-payload", "private-source-id",
        "private-path", "private-outside-run", "private-escaped-run",
    )


def _restore_environment(name: str, was_present: bool, value: str | None) -> None:
    if was_present:
        assert value is not None
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
