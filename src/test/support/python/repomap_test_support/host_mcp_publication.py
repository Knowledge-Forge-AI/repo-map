"""Disposable host-native MCP publication for read-store integration proofs.

Publishes a one-source graph (``host-one``) and a two-binding multi-source
graph (``host-multi``) into disposable PostgreSQL databases, provisions the
per-database roles, and then deletes the source roots so only configuration
and ``runtime/.env`` remain. The configuration also declares a hidden graph
(``host-hidden``) and a visible graph whose database was never created
(``host-absent``). Nothing here touches a live home or maintained runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import time
from typing import Any

import psycopg
import pytest

from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_kg.observations.raw import read_observations_jsonl
from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.ops.direct_publication import publish_observation_generation
from repomap_kg.runtime.database_roles import READ_STATUS_ROLE, RoleSecrets, render_database_role_sql
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.storage import apply_migrations, default_rdbms_root, run_psql
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.storage_integration import canonicalization_fixture

COUNTED_TABLES = ("repositories", "runs", "files", "canonical_nodes", "canonical_edges",
                  "canonical_evidence", "graph_publication_authority", "ingestion_stages")
RESTORE_LOGIN_SQL = (
    f"DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{READ_STATUS_ROLE}') "
    f'THEN ALTER ROLE "{READ_STATUS_ROLE}" LOGIN; END IF; END $$;'
)
ABSENT_DATABASE = "repomap_host_absent_never_created"
SHELL_LIB = "helper() {\n  echo ready\n}\n"
# Two ``source`` lines give one ``sources`` edge two evidence rows (evidence paging).
SHELL_MAIN = "#!/usr/bin/env bash\nsource ./lib.sh\nsource ./lib.sh\nmain() {\n  helper\n}\nmain \"$@\"\n"


@dataclass(frozen=True)
class HostPublication:
    home: Path
    databases: dict[str, Any]
    roots: dict[str, str]
    secrets: RoleSecrets


def publish_fixture(tmp_path: Path, postgres: Any, multi_db: Any) -> HostPublication:
    databases = {"host-one": postgres, "host-multi": multi_db}
    for database in databases.values():
        apply_migrations(default_rdbms_root(), database.psql_args, psql_command=database.psql_command)
    home, sources = tmp_path / "home", tmp_path / "sources"
    setup_local_runtime(home)
    secrets = role_secrets(home)
    for name, text in (("one/run.sh", SHELL_MAIN), ("alpha/lib.sh", SHELL_LIB),
                       ("alpha/run.sh", SHELL_MAIN), ("beta/lib.sh", SHELL_LIB)):
        (sources / name).parent.mkdir(parents=True, exist_ok=True)
        (sources / name).write_text(text, encoding="utf-8")
    write_config(home, postgres.port, postgres.database, multi_db.database, sources)
    graphs = {graph.id: graph for graph in load_ops_config_home(home).graphs}
    roots = {"host-one": str(graphs["host-one"].root_path_expanded), "host-multi": "graph:host-multi"}
    publish_observation_generation(
        postgres.psql_args,
        read_observations_jsonl(canonicalization_fixture("shell_source_static", "raw_observations.jsonl")),
        repository_name="host-one", root_path=roots["host-one"],
        repository_identity="repo1:host-one", psql_command=postgres.psql_command,
    )
    bundle = capture_multi_source_candidate(graphs["host-multi"])
    publish_observation_generation(
        multi_db.psql_args, bundle.observations, repository_name="host-multi",
        root_path=roots["host-multi"], repository_identity="repo1:host-multi",
        psql_command=multi_db.psql_command,
    )
    for database in databases.values():
        provision_roles(postgres.user, database, secrets)
    shutil.rmtree(sources)  # source-blind: only config and credential files remain
    return HostPublication(home=home, databases=databases, roots=roots, secrets=secrets)


def snapshot(publication: HostPublication) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    return home_digest(publication.home), {g: counts(d) for g, d in publication.databases.items()}


def cli(home: Path, graph_id: str, command: str, *args: str) -> Any:
    code, stdout, stderr = run_repo_map_in_process(
        "storage", command, "--repo-map-home", str(home), "--graph", graph_id, *args, "--json")
    assert code == 0, stderr
    return json.loads(stdout)


def jsonable(value: object) -> Any:
    return json.loads(json.dumps(value, sort_keys=True))


def assert_least_privilege(postgres: Any, password: str) -> None:
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(host=postgres.host, port=postgres.port, dbname=postgres.database,
                        user=READ_STATUS_ROLE, password="wrong-password", connect_timeout=10).close()
    with psycopg.connect(host=postgres.host, port=postgres.port, dbname=postgres.database,
                         user=READ_STATUS_ROLE, password=password) as connection:
        assert connection.execute("SELECT current_user").fetchone() == (READ_STATUS_ROLE,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("INSERT INTO repositories(name, root_path) VALUES ('probe', '/public/probe')")
        connection.rollback()


def await_no_read_role_backends(postgres: Any) -> None:
    deadline = time.monotonic() + 10
    sql = f"SELECT count(*) FROM pg_stat_activity WHERE usename = '{READ_STATUS_ROLE}';"
    while postgres.psql_scalar(sql) != "0":
        assert time.monotonic() < deadline, "read/status backends remained after EOF"
        time.sleep(0.2)


def counts(database: Any) -> tuple[str, ...]:
    return tuple(database.psql_scalar(f"SELECT count(*) FROM {table};") for table in COUNTED_TABLES)


def home_digest(home: Path) -> dict[str, str]:
    return {str(path.relative_to(home)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(home.rglob("*")) if path.is_file()}


def role_secrets(home: Path) -> RoleSecrets:
    values = dict(line.split("=", 1) for line in (home / "runtime" / ".env").read_text(
        encoding="utf-8").splitlines() if "=" in line and not line.startswith("#"))
    return RoleSecrets(read_status=values["REPOMAP_READ_STATUS_PASSWORD"],
                       refresh_publication=values["REPOMAP_REFRESH_PUBLICATION_PASSWORD"],
                       coordinator_control=values["REPOMAP_COORDINATOR_CONTROL_PASSWORD"])


def provision_roles(owner: str, database: Any, secrets: RoleSecrets) -> None:
    sql = render_database_role_sql(database=database.database, owner_role=owner,
                                   database_kind="graph", secrets=secrets)
    run_psql([database.psql_command, *database.psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"], input_text=sql)


def write_config(home: Path, host_port: int, one_db: str, multi_db: str, sources: Path) -> None:
    def binding(alias: str) -> str:
        return (f'[[graphs.source_bindings]]\nschema_version = 1\nsource_definition_id = "src1:{alias}"\n'
                f'alias = "{alias}"\nrevision = 1\nkind = "folder"\nroot_path = "{sources / alias}"\n'
                f'repository_name = "{alias}"\nlogical_root = "{alias}"\nprivacy = "public-dev"\n'
                'evidence_retention = "inherit"\nextractor_profile = "default"\n'
                'resolution_policy = "isolated"\nrole = "source"\nenabled = true\n')

    (home / "repomap.rpl.toml").write_text(f'''schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
[runtime]
container_runtime = "docker"
server_host_port = 18080
bind_host = "127.0.0.1"
[runtime.postgres]
direct_host_port_enabled = true
host_port = {host_port}
bind_host = "127.0.0.1"
[postgres]
host = "postgres"
port = 5432
database = "{one_db}"
user = "repomap"
password_env = "REPOMAP_PG_PASSWORD"
[[graphs]]
id = "host-one"
name = "Host One"
root_path = "{sources / 'one'}"
repository_name = "host-one"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[[graphs]]
id = "host-hidden"
name = "Host Hidden"
root_path = "{sources / 'one'}"
repository_name = "host-hidden"
database = "repomap_host_hidden_unused"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
[[graphs]]
id = "host-multi"
name = "Host Multi"
enabled = true
mcp_visible = true
refresh_policy = "manual"
database = "{multi_db}"
{binding("alpha")}{binding("beta")}[[graphs]]
id = "host-absent"
name = "Host Absent"
root_path = "{sources / 'absent'}"
repository_name = "host-absent"
database = "{ABSENT_DATABASE}"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[server_memory]
enabled = false
path = "./server-memory"
mode = "read_only"
''', encoding="utf-8")
