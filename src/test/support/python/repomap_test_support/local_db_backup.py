"""Shared support for local database backup unit and integration tests."""

from __future__ import annotations

import contextlib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any
import unittest
from unittest.mock import MagicMock, patch

import psycopg

from repomap_kg.runtime.local import LocalRuntimeIdentity, setup_local_runtime
from repomap_test_support.public_branch_contracts import owned_container_result


def default_baseline_server_provenance() -> dict[str, object]:
    return {
        "catalog_version_no": 202307071,
        "client_identities": {
            "pg_dump_version": "unavailable",
            "pg_restore_version": "unavailable",
            "psql_version": "unavailable",
        },
        "compile_abi": {
            "data_page_checksum_version": 0,
            "database_block_size": 8192,
            "float8_pass_by_value": True,
            "max_data_alignment": 8,
        },
        "os_arch_abi": "x86_64-pc-linux-musl",
        "server_version": "16.4",
        "server_version_num": 160004,
        "shared_preload_libraries": [],
        "version_string": "PostgreSQL 16.4 on x86_64-pc-linux-musl",
    }


def default_baseline_database_catalog(
    owner: str = "repomap",
    *,
    database_role: str = "graph",
) -> dict[str, object]:
    return {
        "creation_semantics": {
            "template": "unknown",
            "encoding": "UTF8",
            "datcollate": "C",
            "datctype": "C",
            "datlocprovider": "c",
            "daticulocale": None,
            "datcollversion": None,
        },
        "database_role": database_role,
        "non_system_schemas": [{"name": "public", "owner": owner}],
        "installed_extensions": [
            {
                "name": "plpgsql",
                "version": "1.0",
                "schema": "pg_catalog",
                "owner": owner,
                "relocatable": False,
                "trusted": True,
                "is_baseline": True,
                "baseline_origin": "unavailable",
                "ownership_classification": "unclassified",
                "declaration_identity": "unavailable",
                "experimental_context": "unavailable",
                "prerequisite_extensions": [],
                "extconfig_tables": [],
                "extcondition": [],
            }
        ],
        "extension_config_tables": [],
        "extension_dependency_summary": {
            "by_class": {},
            "edge_count": 0,
            "edges": [],
        },
    }


def baseline_observation_json_bytes(
    database: str = "repomap",
    *,
    owner: str = "repomap",
    database_role: str | None = None,
) -> bytes:
    role = (
        database_role
        if database_role is not None
        else ("control" if database == "repomap_control" else "graph")
    )
    payload = {
        "server_provenance": default_baseline_server_provenance(),
        "database_catalog": default_baseline_database_catalog(owner=owner, database_role=role),
    }
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def baseline_toc_bytes() -> bytes:
    return (
        b"; Archive created\n"
        b"1; 3079 13500 EXTENSION - plpgsql\n"
    )


def maybe_provenance_runner_result(
    command: Any,
    *,
    owner: str = "repomap",
) -> subprocess.CompletedProcess[Any] | None:
    cmd_str = " ".join(str(x) for x in command)
    if "repomap_d9_catalog_observation" in cmd_str:
        role = "control" if "'database_role', 'control'" in cmd_str else "graph"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=baseline_observation_json_bytes(owner=owner, database_role=role),
            stderr=b"",
        )
    if "/usr/bin/pg_restore" in command and "-l" in command:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=baseline_toc_bytes(),
            stderr=b"",
        )
    return None


def connect_real_postgres(
    postgres: Any, dbname: str | None = None, *, autocommit: bool = False
) -> Any:
    return psycopg.connect(
        host=postgres.host, port=postgres.port, user=postgres.user,
        dbname=dbname or postgres.database, password=postgres.password, autocommit=autocommit,
    )


def setup_real_backup_home(
    home: Path, postgres: Any, *, graph_db: str = "repomap"
) -> tuple[LocalRuntimeIdentity, Any]:
    import repomap_test_support.postgres_harness as pg_harness

    pg_restore = shutil.which("pg_restore")
    assert pg_restore is not None
    session = pg_harness._ACTIVE_POSTGRES_SESSION
    assert session is not None
    real_container = session.harness.container_name
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    setup_local_runtime(home)
    home.chmod(0o700)
    (home / "runtime").chmod(0o700)
    toml_path = home / "repomap.rpl.toml"
    toml_text = (
        f'schema_version = 1\n[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n'
        f'[runtime]\ncontainer_runtime = "docker"\nserver_host_port = 8080\nbind_host = "127.0.0.1"\n'
        f'[runtime.postgres]\ndirect_host_port_enabled = false\nhost_port = {postgres.port}\nbind_host = "127.0.0.1"\n'
        f'[postgres]\nhost = "{postgres.host}"\nport = {postgres.port}\ndatabase = "{graph_db}"\n'
        f'user = "{postgres.user}"\npassword_env = "REPOMAP_PG_PASSWORD"\n'
        f'[[graphs]]\nid = "repo-map"\nname = "RepoMap"\nroot_path = "./repo-map"\n'
        f'repository_name = "repo-map"\nprivacy = "public-dev"\ndatabase = "{graph_db}"\n'
        f'enabled = false\nmcp_visible = false\nextractor_profile = "default"\nrefresh_policy = "manual"\nexclude_paths = []\n'
        f'[server_memory]\nenabled = false\npath = "./server-memory"\nmode = "read_only"\n'
    )
    toml_path.write_text(toml_text, encoding="utf-8")
    identity = LocalRuntimeIdentity.from_home(home)
    env_file = home / "runtime" / ".env"
    env_lines = [
        line for line in env_file.read_text(encoding="utf-8").splitlines()
        if not line.startswith(("REPOMAP_RUNTIME_HOME_HASH=", "POSTGRES_PASSWORD=", "REPOMAP_PG_PASSWORD=", "PGPASSWORD="))
    ] + [
        f"REPOMAP_RUNTIME_HOME_HASH={identity.home_hash}",
        f"POSTGRES_PASSWORD={postgres.password}",
        f"REPOMAP_PG_PASSWORD={postgres.password}",
        f"PGPASSWORD={postgres.password}",
    ]
    env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    env_file.chmod(0o600)

    def db_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        if "env" in kwargs and kwargs["env"] is not None:
            kwargs["env"] = dict(kwargs["env"], PGPASSWORD=postgres.password)
        if len(cmd) >= 2 and cmd[:2] == ["docker", "inspect"]:
            return owned_container_result(identity, cmd)
        if len(cmd) >= 2 and cmd[:2] == ["docker", "exec"]:
            if "pg_restore" in cmd and "-l" in cmd:
                kwargs["check"] = False
                restore_args = [pg_restore, "-l"] if cmd[-1] == "-l" else [pg_restore, "-l", cmd[-1]]
                return subprocess.run(restore_args, **kwargs)
            real_cmd = [
                real_container
                if token == identity.postgres_container
                else (Path(token).name if Path(token).name in ("psql", "pg_dump", "pg_restore") else token)
                for token in cmd
            ]
            kwargs["check"] = False
            return subprocess.run(real_cmd, **kwargs)
        kwargs["check"] = False
        return subprocess.run(cmd, **kwargs)

    return identity, db_runner


@contextlib.contextmanager
def unit_maintenance_window_patch(
    databases: tuple[str, ...] = (
        "repomap_control",
        "repomap",
        "repomap_live_harden1_control",
        "repomap_live_harden1",
        "graph_alpha",
        "graph_beta",
        "graph_gamma",
        "graph_a",
        "graph_b",
        "custom_db",
    ),
) -> Any:
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn

    def _exec(_sql: Any, params: Any = None) -> Any:
        requested = set(params[0]) if params else set(databases)
        res = MagicMock()
        res.fetchall.return_value = [(db,) for db in databases if db in requested]
        return res

    mock_conn.execute.side_effect = _exec
    with (
        patch(
            "repomap_kg.runtime._backup_operations.psycopg.connect",
            return_value=mock_conn,
        ),
        patch(
            "repomap_kg.runtime._backup_operations.maintenance_window",
            side_effect=lambda *args, **kwargs: contextlib.nullcontext(),
        ),
    ):
        yield


class LocalDbBackupUnitTestCase(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._mw_cm = unit_maintenance_window_patch()
        self._mw_cm.__enter__()

    def tearDown(self) -> None:
        self._mw_cm.__exit__(None, None, None)
        super().tearDown()

    @staticmethod
    def owned_container_result(identity: LocalRuntimeIdentity, command: Any) -> subprocess.CompletedProcess[Any]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                [
                    {
                        "Id": "container-123",
                        "Config": {
                            "Image": "postgres:16-alpine",
                            "Labels": identity.labels("postgres"),
                        },
                    }
                ]
            ),
            stderr="",
        )

    @staticmethod
    def unexpected_runner(command: Any, **kwargs: Any) -> Any:
        del kwargs
        raise AssertionError(command)

    @staticmethod
    def write_backup_fixture(
        home: Path,
        runtime_id: str,
        database: str,
        *,
        all_databases: bool = False,
        restore_supported: bool = True,
        format_version: int = 1,
    ) -> Path:
        if all_databases:
            backup_dir = home / "backups" / runtime_id / "all-databases" / "20260702T010203Z"
            dump_name = f"{database}.pgcustom"
            backup_kind = "manual-dump-all"
            database_value = None
            databases = [database]
            backup_id = f"{runtime_id}--all-databases--20260702T010203Z"
        else:
            backup_dir = home / "backups" / runtime_id / database / "20260702T010203Z"
            dump_name = "dump.pgcustom"
            backup_kind = "manual-dump"
            database_value = database
            databases = [database]
            backup_id = f"{runtime_id}--{database}--20260702T010203Z"
        backup_dir.mkdir(parents=True)
        content = f"{database}-dump".encode("utf-8")
        (backup_dir / dump_name).write_bytes(content)
        manifest = {
            "backup_format_version": format_version,
            "backup_id": backup_id,
            "backup_kind": backup_kind,
            "runtime_id": runtime_id,
            "database": database_value,
            "databases": databases,
            "timestamp": "20260702T010203Z",
            "dump_files": [
                {
                    "name": dump_name,
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            ],
            "dump_format": "pgcustom",
            "restore_supported": restore_supported,
        }
        (backup_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return backup_dir
