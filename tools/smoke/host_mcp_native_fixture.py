"""Fresh, run-owned fixture for the host MCP native qualification runner.

Publishes two tiny graphs into databases the current run created in its own
disposable PostgreSQL cluster, through the incumbent publishers:

- ``host-multi``: two source-qualified folder bindings (``alpha``/``beta``)
  of the maintained shell fixture text, captured by the multi-source pipeline
  and published under its configured tuple (name ``[multi-source]``, root
  ``graph:host-multi``, identity ``repo1:host-multi``) as supported refresh
  publishes it;
- ``host-feed``: one offline RSS acquisition through the production ingestion
  path with a fake fetcher (no network).

A third graph, ``host-hidden``, is declared with ``mcp_visible = false`` and a
database that is never created. The setup-owned home comes from
``setup_local_runtime`` (its generated secrets stay in the owner-private
``runtime/.env``), roles are provisioned by the maintained role SQL owner, and
then only the source roots are deleted. No operator home, maintained graph,
QUAL12 artifact, or credential is searched for or reused.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import stat
from typing import Any

from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.ops.direct_publication import publish_observation_generation
from repomap_kg.ops.ingestion.source import FeedFetchResponse, ingest_feed_source
from repomap_kg.ops.resolved_config import configured_repository_identity
from repomap_kg.runtime.database_roles import READ_STATUS_ROLE, RoleSecrets
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.postgres_route import effective_postgres_route, readback_postgres_authority
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.sql_core import sql_literal
from repomap_test_support.host_mcp_publication import (
    COUNTED_TABLES, SHELL_LIB, SHELL_MAIN, HostPublication, provision_roles, role_secrets,
)
from repomap_test_support.storage_integration import discovery_fixture, fixed_source_clock, source_fixture

VISIBLE_GRAPHS = ("host-multi", "host-feed")
FEED_SOURCE_ID = "example-rss-feed"
FEED_URL = "https://example.invalid/rss.xml"
HIDDEN_DATABASE = "repomap_native_hidden_unused"
SECRET_FILE = "runtime/.env"
_IDENTITY_SQL = ("SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.repository_id), '[]'::jsonb)::text "
                 "FROM graph_publication_authority t;")
_RUNS_SQL = "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.id), '[]'::jsonb)::text FROM runs t;"
_SCHEMA_SQL = ("SELECT md5(coalesce(string_agg(table_name || '.' || column_name || ':' || data_type, ',' "
               "ORDER BY table_name, ordinal_position), '')) FROM information_schema.columns "
               "WHERE table_schema = 'public';")


def fixture_inputs() -> dict[str, Path]:
    """The only non-installed inputs (shipped in the operator kit at the same relative paths)."""
    return {"rss": discovery_fixture("feed_static_basic") / "rss.xml",
            "feed_source": source_fixture("allowed-rss.toml")}


@dataclass(frozen=True)
class NativeFixture:
    home: Path
    sources: Path
    host_port: int
    databases: dict[str, Any]
    roots: dict[str, str]
    secrets: RoleSecrets
    fetches: tuple[str, ...]

    def publication(self) -> HostPublication:
        return HostPublication(home=self.home, databases=self.databases, roots=self.roots, secrets=self.secrets)


def configured_publication(graph: Any) -> dict[str, str]:
    """The repository tuple supported refresh publishes for a configured graph.

    Mirrors ``ops.portable_refresh`` (``repository_name=graph.repository_name``,
    ``root_path=f"graph:{graph.id}"``, ``configured_repository_identity``). The
    name is the ``[multi-source]`` token for a multi-binding graph, and it is the
    key of the name-selected status family (refresh status, graph summary,
    storage status), so a fixture that stores another name is status-invisible.
    """
    return {"repository_name": graph.repository_name, "root_path": f"graph:{graph.id}",
            "repository_identity": str(configured_repository_identity(graph.id))}


def stage_native_config(work: Path, host_port: int, multi_db: str, feed_db: str) -> tuple[Path, Path, dict[str, Any]]:
    """Set up the home, write the tiny sources and configuration, and load the configured graphs."""
    home, sources = work / "home", work / "sources"
    setup_local_runtime(home)
    for name, text in (("alpha/lib.sh", SHELL_LIB), ("alpha/run.sh", SHELL_MAIN), ("beta/lib.sh", SHELL_LIB)):
        (sources / name).parent.mkdir(parents=True, exist_ok=True)
        (sources / name).write_text(text, encoding="utf-8")
    (sources / "feed").mkdir(parents=True)
    write_native_config(home, host_port, multi_db, feed_db, sources)
    return home, sources, {graph.id: graph for graph in load_ops_config_home(home).graphs}


def publish_native_fixture(work: Path, owner_role: str, databases: dict[str, Any], host_port: int) -> NativeFixture:
    """Publish ``host-multi`` and ``host-feed`` into the given run-created databases."""
    for database in databases.values():
        apply_migrations(default_rdbms_root(), database.psql_args, psql_command=database.psql_command)
    multi_db, feed_db = databases["host-multi"], databases["host-feed"]
    home, sources, graphs = stage_native_config(work, host_port, multi_db.database, feed_db.database)
    secrets = role_secrets(home)
    multi = configured_publication(graphs["host-multi"])
    roots = {"host-multi": multi["root_path"], "host-feed": str(graphs["host-feed"].root_path_expanded)}
    bundle = capture_multi_source_candidate(graphs["host-multi"])
    publish_observation_generation(multi_db.psql_args, bundle.observations, **multi,
                                   psql_command=multi_db.psql_command)
    fetches: list[str] = []
    feed_body = fixture_inputs()["rss"].read_bytes()

    def fetcher(config: Any) -> FeedFetchResponse:
        fetches.append(config.url)
        return FeedFetchResponse(status=200, headers={"content-type": "application/rss+xml"}, body=feed_body)

    acquisition = ingest_feed_source(fixture_inputs()["feed_source"], root_path=Path(roots["host-feed"]),
                                     fetcher=fetcher, clock=fixed_source_clock)
    publish_observation_generation(
        feed_db.psql_args, acquisition.raw_observations, repository_name="host-feed", root_path=roots["host-feed"],
        repository_identity="repo1:host-feed", psql_command=feed_db.psql_command,
    )
    for database in databases.values():
        provision_roles(owner_role, database, secrets)
    shutil.rmtree(sources)  # source-blind: only configuration and the credential file remain
    return NativeFixture(home=home, sources=sources, host_port=host_port, databases=databases, roots=roots,
                         secrets=secrets, fetches=tuple(fetches))


def write_native_config(home: Path, host_port: int, multi_db: str, feed_db: str, sources: Path) -> None:
    def binding(alias: str) -> str:
        return (f'[[graphs.source_bindings]]\nschema_version = 1\nsource_definition_id = "src1:{alias}"\n'
                f'alias = "{alias}"\nrevision = 1\nkind = "folder"\nroot_path = "{sources / alias}"\n'
                f'repository_name = "{alias}"\nlogical_root = "{alias}"\nprivacy = "public-dev"\n'
                'evidence_retention = "inherit"\nextractor_profile = "default"\n'
                'resolution_policy = "isolated"\nrole = "source"\nenabled = true\n')

    def graph(graph_id: str, root: Path, database: str, visible: bool) -> str:
        return (f'[[graphs]]\nid = "{graph_id}"\nname = "{graph_id}"\nroot_path = "{root}"\n'
                f'repository_name = "{graph_id}"\ndatabase = "{database}"\nprivacy = "public-dev"\n'
                f'enabled = true\nmcp_visible = {"true" if visible else "false"}\n'
                'extractor_profile = "default"\nrefresh_policy = "manual"\n')

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
database = "{multi_db}"
user = "repomap"
password_env = "REPOMAP_PG_PASSWORD"
[[graphs]]
id = "host-multi"
name = "host-multi"
enabled = true
mcp_visible = true
refresh_policy = "manual"
database = "{multi_db}"
{binding("alpha")}{binding("beta")}{graph("host-feed", sources / "feed", feed_db, True)}\
{graph("host-hidden", sources / "feed", HIDDEN_DATABASE, False)}[server_memory]
enabled = false
path = "./server-memory"
mode = "read_only"
''', encoding="utf-8")


def route_record(home: Path, host_port: int) -> dict[str, Any]:
    """The native route must agree with ``direct_host_port_enabled`` and the bound port."""
    config = load_ops_config_home(home)
    route = effective_postgres_route(config)
    authority = readback_postgres_authority(config)  # password stays in memory, never recorded
    record = {"route_kind": route.kind, "route_host": route.host, "route_port": route.port,
              "bound_port": host_port, "direct_host_port_enabled": config.runtime.postgres.direct_host_port_enabled,
              "projected_read_status": authority.projected_read_status, "read_user": authority.postgres.user}
    record["agrees"] = (route.kind == "local-native" and route.host == "127.0.0.1" and route.port == host_port
                        and record["direct_host_port_enabled"] is True and authority.projected_read_status
                        and authority.postgres.user == READ_STATUS_ROLE)
    return record


def database_state(database: Any) -> dict[str, Any]:
    return {"counts": dict(zip(COUNTED_TABLES, (database.psql_scalar(f"SELECT count(*) FROM {table};")
                                                for table in COUNTED_TABLES))),
            "publication_authority": database.psql_scalar(_IDENTITY_SQL), "runs": database.psql_scalar(_RUNS_SQL),
            "schema_md5": database.psql_scalar(_SCHEMA_SQL)}


def stored_repository_facts(database: Any, graph_id: str) -> dict[str, Any]:
    """Fixture-admin oracle: the stored row for ``repo1:<graph_id>`` and its repository-scoped totals.

    Selects by the configured identity (never by name or root) and records no
    physical path; it is independent of every status query under test.
    """
    identity = sql_literal(str(configured_repository_identity(graph_id)))

    def scoped(table: str) -> str:
        return f"'{table}', (SELECT count(*) FROM {table} WHERE repository_id IN (SELECT id FROM repo))"

    return json.loads(database.psql_scalar(
        f"WITH repo AS (SELECT id, name FROM repositories WHERE repository_identity = {identity}), "
        "latest AS (SELECT id, status FROM runs WHERE repository_id IN (SELECT id FROM repo) "
        "ORDER BY id DESC LIMIT 1) "
        "SELECT json_build_object('repository_rows', (SELECT count(*) FROM repo), "
        "'name', (SELECT min(name) FROM repo), 'latest_run_id', (SELECT id FROM latest), "
        f"'latest_run_status', (SELECT status FROM latest), {scoped('raw_observations')}, "
        f"{scoped('canonical_nodes')}, {scoped('canonical_edges')})::text;"))


def fixture_state(fixture: NativeFixture) -> dict[str, Any]:
    """Graph counts, publication identity, schema digest, home bytes/modes and source absence."""
    return {"databases": {graph_id: database_state(database) for graph_id, database in fixture.databases.items()},
            "home": home_state(fixture.home), "sources_absent": not fixture.sources.exists()}


def home_state(home: Path) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for path in (home, *sorted(home.rglob("*"))):
        info = path.lstat()
        entry: dict[str, Any] = {"mode": oct(stat.S_IMODE(info.st_mode))}
        if stat.S_ISREG(info.st_mode):
            entry.update(size=info.st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        else:
            entry["type"] = "dir" if stat.S_ISDIR(info.st_mode) else "other"
        state[path.relative_to(home).as_posix()] = entry
    return state


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    """Evidence form: the secret file keeps mode and size; its digest is compared in memory only."""
    home = {name: ({**entry, "sha256": "withheld (compared in memory)"} if name == SECRET_FILE else entry)
            for name, entry in state["home"].items()}
    return {**state, "home": home}
