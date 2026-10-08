"""Disposable host-native MCP publication for the READSTORE3 domain read proof.

Publishes two graphs into disposable PostgreSQL databases:

- ``host-mixed``: a tiny tree copied from maintained discovery fixtures
  (Python package, Terraform HCL, OpenAPI, JavaScript frameworks, Nix flake),
  captured once in process and published as ``repo1:host-mixed``;
- ``host-feed``: one RSS acquisition through the production ingestion path
  with a fake fetcher (no network), published as ``repo1:host-feed``.

It then provisions the per-database roles and deletes both source roots, so
only configuration and ``runtime/.env`` remain. The configuration also
declares a hidden graph (``host-hidden``) and a visible graph whose database
was never created (``host-absent``). Nothing here touches a live home.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any

from repomap_kg.graph.discovery import discover_observations
from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.ops.direct_publication import publish_observation_generation
from repomap_kg.ops.ingestion.source import FeedFetchResponse, ingest_feed_source
from repomap_kg.runtime.database_roles import RoleSecrets
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.host_mcp_publication import (
    counts,
    home_digest,
    provision_roles,
    role_secrets,
)
from repomap_test_support.storage_integration import (
    discovery_fixture,
    fixed_source_clock,
    source_fixture,
)

FIXTURES = Path(__file__).parents[3] / "fixtures"
MIXED_TREE = (
    ("python", FIXTURES / "discovery" / "python_package"),
    ("terraform", FIXTURES / "terraform_hcl"),
    ("openapi", FIXTURES / "openapi"),
    ("web", FIXTURES / "discovery" / "js5_frameworks"),
    ("nix", FIXTURES / "discovery" / "nix_flake_basic"),
)
FEED_SOURCE_ID = "example-rss-feed"
FEED_URL = "https://example.invalid/rss.xml"
ABSENT_DATABASE = "repomap_host_domain_absent_never_created"


@dataclass(frozen=True)
class HostDomainPublication:
    home: Path
    databases: dict[str, Any]
    roots: dict[str, str]
    secrets: RoleSecrets
    fetches: tuple[str, ...]


def publish_domain_fixture(tmp_path: Path, mixed_db: Any, feed_db: Any) -> HostDomainPublication:
    databases = {"host-mixed": mixed_db, "host-feed": feed_db}
    for database in databases.values():
        apply_migrations(default_rdbms_root(), database.psql_args, psql_command=database.psql_command)
    home, sources = tmp_path / "home", tmp_path / "sources"
    setup_local_runtime(home)
    secrets = role_secrets(home)
    for name, fixture in MIXED_TREE:
        shutil.copytree(fixture, sources / "mixed" / name)
    (sources / "feed").mkdir(parents=True)
    write_domain_config(home, mixed_db.port, mixed_db.database, feed_db.database, sources)
    graphs = {graph.id: graph for graph in load_ops_config_home(home).graphs}
    roots = {graph_id: str(graphs[graph_id].root_path_expanded) for graph_id in databases}
    publish_observation_generation(
        mixed_db.psql_args, discover_observations(roots["host-mixed"]), repository_name="host-mixed",
        root_path=roots["host-mixed"], repository_identity="repo1:host-mixed", psql_command=mixed_db.psql_command,
    )
    fetches: list[str] = []
    feed_body = (discovery_fixture("feed_static_basic") / "rss.xml").read_bytes()

    def fetcher(config: Any) -> FeedFetchResponse:
        fetches.append(config.url)
        return FeedFetchResponse(status=200, headers={"content-type": "application/rss+xml"}, body=feed_body)

    acquisition = ingest_feed_source(source_fixture("allowed-rss.toml"), root_path=Path(roots["host-feed"]),
                                     fetcher=fetcher, clock=fixed_source_clock)
    publish_observation_generation(
        feed_db.psql_args, acquisition.raw_observations, repository_name="host-feed",
        root_path=roots["host-feed"], repository_identity="repo1:host-feed", psql_command=feed_db.psql_command,
    )
    for database in databases.values():
        provision_roles(mixed_db.user, database, secrets)
    shutil.rmtree(sources)  # source-blind: only config and credential files remain
    return HostDomainPublication(home=home, databases=databases, roots=roots, secrets=secrets,
                                 fetches=tuple(fetches))


def domain_snapshot(publication: HostDomainPublication) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    return home_digest(publication.home), {g: counts(d) for g, d in publication.databases.items()}


def write_domain_config(home: Path, host_port: int, mixed_db: str, feed_db: str, sources: Path) -> None:
    def graph(graph_id: str, root: Path, database: str, *, visible: bool = True) -> str:
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
database = "{mixed_db}"
user = "repomap"
password_env = "REPOMAP_PG_PASSWORD"
{graph("host-mixed", sources / "mixed", mixed_db)}{graph("host-feed", sources / "feed", feed_db)}\
{graph("host-hidden", sources / "mixed", "repomap_host_domain_hidden_unused", visible=False)}\
{graph("host-absent", sources / "absent", ABSENT_DATABASE)}[server_memory]
enabled = false
path = "./server-memory"
mode = "read_only"
''', encoding="utf-8")
