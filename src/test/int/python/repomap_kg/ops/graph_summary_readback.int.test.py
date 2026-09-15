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

from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.ops.refresh import (
    OpsRefreshError,
    drift_check_to_jsonable,
    query_drift_check,
    query_graph_summary,
    save_graph_baselines,
)
from repomap_kg.storage import (
    StorageSchemaError,
    apply_migrations,
    default_rdbms_root,
    run_psql,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV

MISSING_DATABASE = "repomap_test_missing"
NO_RUN_DATABASE = "repomap_test_no_run"


def test_psycopg104_graph_summary_connector_cli_baseline_drift_and_privacy_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    names = (
        PG_CONNECTOR_ENV,
        READBACK_DRIVER_ENV,
        "PGPASSWORD",
        "PATH",
        "PUBLIC_SAFE_PASSWORD",
    )
    previous = {name: (name in os.environ, os.environ.get(name)) for name in names}
    try:
        with temporary_postgres() as postgres, tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            home = base / "repo-map-home"
            home.mkdir()
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            for database in (MISSING_DATABASE, NO_RUN_DATABASE):
                postgres.psql_scalar(f"CREATE DATABASE {database};")
                apply_migrations(
                    default_rdbms_root(),
                    _database_args(postgres.psql_args, database),
                    psql_command=postgres.psql_command,
                )
            _seed(postgres)
            run_psql(
                [
                    postgres.psql_command,
                    *_database_args(postgres.psql_args, NO_RUN_DATABASE),
                    "-qAt",
                    "-v",
                    "ON_ERROR_STOP=1",
                ],
                input_text=(
                        "INSERT INTO repositories"
                        "(name, root_path, repository_identity) "
                        "VALUES ('no-run-repository', '/public/no-run', "
                        "'repo1:no-run');"
                ),
            )
            config = load_ops_config_home(_write_config(home, postgres=postgres))

            import repomap_kg.ops.readback as readback

            def fail_topology(*args, **kwargs):
                pytest.fail("successful host graph summary inspected topology")

            monkeypatch.setattr(readback, "_runtime_plan", fail_topology)
            monkeypatch.setattr(readback, "_container_psql_execution", fail_topology)
            monkeypatch.setattr(readback, "_resolve_container_readback_plan", fail_topology)

            original_path = os.environ["PATH"]
            empty_bin = base / "empty-bin"
            empty_bin.mkdir()
            modes = (
                ("default", None, None),
                ("connector-psql", "psql", None),
                ("connector-psycopg", "psycopg", None),
                ("driver-psql", None, "psql"),
                ("driver-psycopg", None, "psycopg"),
            )
            summaries: dict[str, dict[str, object]] = {}
            for name, connector, driver in modes:
                _select(connector, driver, postgres=postgres)
                os.environ["PATH"] = (
                    str(empty_bin) if name == "default" else original_path
                )
                summaries[name] = query_graph_summary(config, "public").to_jsonable()

            expected = summaries["connector-psql"]
            assert all(summary == expected for summary in summaries.values())
            assert expected["result"] == "success"
            assert expected["repository_exists"] is True
            assert expected["latest_run_status"] == "complete"
            assert expected["files"] == 2
            assert expected["raw_observations"] == 2
            assert expected["latest_run_raw_observations"] == 2
            assert expected["canonical_nodes"] == 2
            assert expected["canonical_edges"] == 1
            assert expected["language_counts"] == {"markdown": 1, "python": 1}
            assert expected["observation_kind_counts"] == {"file": 1, "symbol": 1}

            os.environ["PATH"] = original_path
            _select("psycopg", "psycopg", postgres=postgres)
            dual = query_graph_summary(config, "public").to_jsonable()
            assert dual == expected

            os.environ[PG_CONNECTOR_ENV] = "conflict-a"
            os.environ[READBACK_DRIVER_ENV] = "unsupported-value"
            conflict = query_graph_summary(config, "public")
            assert conflict.result == "failure"
            assert conflict.diagnostics[0]["code"] == "storage-status-unavailable"
            explicit = query_graph_summary(
                config,
                "public",
                psql_command=postgres.psql_command,
            ).to_jsonable()
            assert explicit == expected

            missing = query_graph_summary(
                config,
                "missing",
                psql_command=postgres.psql_command,
            )
            no_run = query_graph_summary(
                config,
                "no-run",
                psql_command=postgres.psql_command,
            )
            assert missing.result == "success"
            assert missing.repository_exists is False
            assert missing.files == 0
            assert no_run.result == "success"
            assert no_run.repository_exists is True
            assert no_run.latest_run_id is None

            explicit_cli, explicit_raw = _run_cli(
                home,
                "graph-summary",
                psql_command=postgres.psql_command,
            )
            explicit_baseline, explicit_baseline_raw = _run_cli(
                home,
                "graph-baseline",
                psql_command=postgres.psql_command,
            )
            _select(None, None, postgres=postgres)
            os.environ["PATH"] = str(empty_bin)
            default_cli, default_raw = _run_cli(home, "graph-summary")
            default_baseline, default_baseline_raw = _run_cli(
                home,
                "graph-baseline",
            )
            assert default_cli == explicit_cli
            assert default_raw == explicit_raw == json.dumps(default_cli, sort_keys=True) + "\n"
            assert default_baseline == explicit_baseline
            assert default_baseline_raw == explicit_baseline_raw
            assert default_cli["safety"]["graph_root_read"] is False
            assert default_cli["safety"]["storage_written"] is False

            os.environ["PATH"] = original_path
            _select(None, None, postgres=postgres)
            save_graph_baselines(
                config,
                "public",
                kind="stored",
                timestamp="20260712T010101Z",
            )
            save_graph_baselines(
                config,
                "public",
                kind="stored",
                psql_command=postgres.psql_command,
                timestamp="20260712T020202Z",
            )
            stored_root = home / "status" / "baselines" / "public" / "stored"
            default_saved = json.loads(
                (stored_root / "20260712T010101Z.json").read_text(encoding="utf-8")
            )
            explicit_saved = json.loads(
                (stored_root / "20260712T020202Z.json").read_text(encoding="utf-8")
            )
            assert default_saved == explicit_saved
            assert json.loads(
                (stored_root / "latest.json").read_text(encoding="utf-8")
            ) == explicit_saved

            save_graph_baselines(
                config,
                "missing",
                kind="stored",
                timestamp="20260712T030303Z",
            )
            assert (home / "status/baselines/missing/stored/latest.json").exists()

            baseline = explicit_baseline["baseline"]
            default_drift = query_drift_check(config, "public", baseline=baseline)
            explicit_drift = query_drift_check(
                config,
                "public",
                baseline=baseline,
                psql_command=postgres.psql_command,
            )
            assert drift_check_to_jsonable(config, default_drift) == drift_check_to_jsonable(
                config,
                explicit_drift,
            )
            assert default_drift.drift_detected is False

            before_failure = sorted(stored_root.iterdir())
            with patch(
                "repomap_kg.ops.refresh.execute_ops_json_readback",
                side_effect=StorageSchemaError("public summary unavailable"),
            ):
                with pytest.raises(OpsRefreshError):
                    save_graph_baselines(
                        config,
                        "public",
                        kind="stored",
                        timestamp="20260712T040404Z",
                    )
            assert sorted(stored_root.iterdir()) == before_failure

            serialized = json.dumps(
                {
                    "summary": default_cli,
                    "baseline": default_baseline,
                    "saved": default_saved,
                    "drift": drift_check_to_jsonable(config, default_drift),
                },
                sort_keys=True,
            )
            for forbidden in (
                "PUBLIC_SAFE_PASSWORD_VALUE",
                "postgresql://",
                "raw psycopg cause",
                "PRIVATE_TOKEN",
                "private-source-content",
            ):
                assert forbidden not in serialized
    finally:
        for name, (present, value) in previous.items():
            if present and value is not None:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)


def _seed(postgres) -> None:
    run_psql(
        [
            postgres.psql_command,
            *postgres.psql_args,
            "-qAt",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input_text="""
INSERT INTO repositories(name, root_path, repository_identity)
VALUES ('public-repository', '/public/repository', 'repo1:public');
INSERT INTO runs(repository_id, status, finished_at)
SELECT id, 'complete', CURRENT_TIMESTAMP FROM repositories
WHERE name = 'public-repository';
INSERT INTO files(repository_id, path, language, role)
SELECT id, 'README.md', 'markdown', 'documentation' FROM repositories
WHERE name = 'public-repository';
INSERT INTO files(repository_id, path, language, role)
SELECT id, 'src/main.py', 'python', 'source' FROM repositories
WHERE name = 'public-repository';
INSERT INTO raw_observations(repository_id, run_id, ordinal, schema_version,
kind, source_id, path, payload_json, payload_hash)
SELECT r.id, ru.id, ordinal, 1, kind, source_id, path, '{}'::jsonb, hash
FROM repositories r JOIN runs ru ON ru.repository_id = r.id
CROSS JOIN (VALUES
  (0, 'file', 'README.md', 'README.md', repeat('1', 64)),
  (1, 'symbol', 'main', 'src/main.py', repeat('2', 64))
) AS rows(ordinal, kind, source_id, path, hash)
WHERE r.name = 'public-repository';
INSERT INTO canonical_nodes(repository_id, graph_key_version, canonical_key,
kind, display_name, metadata_json, confidence)
SELECT r.id, 1, key, 'file', key, '{}'::jsonb, 'extracted'
FROM repositories r CROSS JOIN (VALUES ('public:a'), ('public:b')) AS keys(key)
WHERE r.name = 'public-repository';
INSERT INTO canonical_edges(repository_id, graph_key_version,
source_canonical_key, edge_kind, target_canonical_key,
identity_metadata_hash, confidence)
SELECT id, 1, 'public:a', 'references', 'public:b', repeat('0', 64), 'extracted'
FROM repositories WHERE name = 'public-repository';
""",
    )


def _write_config(home: Path, *, postgres) -> Path:
    (home / "repomap.rpl.toml").write_text(
        f'''schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"
password_env = "PUBLIC_SAFE_PASSWORD"
[[graphs]]
id = "public"
name = "Public"
root_path = "/public/repository"
repository_name = "public-repository"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[[graphs]]
id = "missing"
name = "Missing"
root_path = "/public/missing"
repository_name = "missing-repository"
database = "{MISSING_DATABASE}"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[[graphs]]
id = "no-run"
name = "No Run"
root_path = "/public/no-run"
repository_name = "no-run-repository"
database = "{NO_RUN_DATABASE}"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[server_memory]
enabled = false
path = "./public-server-memory"
mode = "read_only"
''',
        encoding="utf-8",
    )
    return home


def _database_args(args: list[str], database: str) -> list[str]:
    updated = list(args)
    updated[updated.index("-d") + 1] = database
    return updated


def _select(connector: str | None, driver: str | None, *, postgres) -> None:
    for name, value in ((PG_CONNECTOR_ENV, connector), (READBACK_DRIVER_ENV, driver)):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    if postgres.password:
        os.environ["PGPASSWORD"] = postgres.password
    os.environ["PUBLIC_SAFE_PASSWORD"] = "PUBLIC_SAFE_PASSWORD_VALUE"


def _run_cli(
    home: Path,
    command: str,
    *,
    psql_command: str | None = None,
):
    args = ["ops", command, "--repo-map-home", str(home), "--graph", "public", "--json"]
    if psql_command is not None:
        args.extend(("--psql-command", psql_command))
    exit_code, stdout, stderr = run_repo_map_in_process(*args)
    assert exit_code == 0, stderr
    return json.loads(stdout), stdout
