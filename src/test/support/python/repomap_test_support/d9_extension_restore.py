"""Test support for D9-B owned disposable clusters, homes, roles and clean template references."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from typing import Any

from common_lore_index.runtime._extension_restore_template import parse_template_baseline, template_baseline_sql
from common_lore_index.runtime.local import LocalRuntimeIdentity, setup_local_runtime
from common_lore_index.runtime.release import POSTGRES_RELEASE_IMAGE
from common_lore_index.storage import apply_migrations, default_rdbms_root
from repomap_test_support.local_db_backup import connect_real_postgres
from repomap_test_support.pgvector_profile import PGVECTOR_PROFILE, current_pg_test_profile
from repomap_test_support.postgres_container import (
    TEST_POSTGRES_IMAGE, PostgresContainerConfig, PostgresContainerDatabase, PostgresContainerHarness,
    build_psql_wrapper_script,
)

_CLEAN_TEMPLATE_REFERENCES: dict[tuple[str | None, str], str] = {}
PRODUCT_INITDB_ARGS = "--encoding=UTF8 --locale=C"
# The only explicit image: the exact release server pin the outer sandbox already preloads (ADR 0091). None keeps the
# profile's default image; the reference cache is keyed by image and profile, so no image reuses another's reference.
D9_EXPLICIT_IMAGES = {POSTGRES_RELEASE_IMAGE: "release"}


def _explicit_image(image: str | None, profile: str | None) -> str | None:
    if image is None:
        return None
    if image not in D9_EXPLICIT_IMAGES:
        raise ValueError(f"unsupported D9 image {image!r}; only the exact release server pin may be selected")
    if (profile or current_pg_test_profile()) == PGVECTOR_PROFILE:
        raise ValueError("the pgvector profile keeps its own image; an explicit D9 image runs only the core profile")
    return image


def _reserve_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass(frozen=True)
class _D9ContainerConfig(PostgresContainerConfig):
    profile: str | None = None


class OwnedD9PostgresHarness(PostgresContainerHarness):
    """PostgresContainerHarness named and labeled with a LocalRuntimeIdentity."""

    def __init__(self, config: PostgresContainerConfig, runtime_identity: LocalRuntimeIdentity) -> None:
        self._runtime_identity = runtime_identity
        super().__init__(config)

    @property
    def container_name(self) -> str:
        return self._runtime_identity.postgres_container

    def labels(self) -> dict[str, str]:
        return {**super().labels(), **self._runtime_identity.labels("postgres")}

    def start_command(self) -> list[str]:
        # Mirror the product runtime cluster (runtime/compose.py): template1 is UTF8/C, the
        # locale of RepoMap graph and control databases, so the template1 route can create them.
        command = super().start_command()
        return [*command[:-1], "-e", f"POSTGRES_INITDB_ARGS={PRODUCT_INITDB_ARGS}", command[-1]]

    def wait_until_ready(self) -> None:
        super().wait_until_ready()
        self._run_checked([
            self.config.runtime, "exec", "-i", "-u", "root", self.container_name, "sh", "-euc",
            'mkdir -p /usr/lib/postgresql/16/bin && for b in psql pg_dump pg_restore; do p=$(command -v "$b"); '
            '[ -x "/usr/bin/$b" ] || ln -sf "$p" "/usr/bin/$b"; '
            '[ -x "/usr/lib/postgresql/16/bin/$b" ] || ln -sf "$p" "/usr/lib/postgresql/16/bin/$b"; done',
        ])


def setup_d9_backup_home(home: Path, postgres: Any, *, graph_db: str = "repomap") -> LocalRuntimeIdentity:
    """Configure a local backup/restore home bound to a real owned container."""
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    setup_local_runtime(home)
    home.chmod(0o700)
    (home / "runtime").chmod(0o700)
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
    (home / "repomap.rpl.toml").write_text(toml_text, encoding="utf-8")
    identity = LocalRuntimeIdentity.from_home(home)
    env_file = home / "runtime" / ".env"
    env_lines = [
        line for line in env_file.read_text(encoding="utf-8").splitlines()
        if not line.startswith(("REPOMAP_RUNTIME_HOME_HASH=", "POSTGRES_PASSWORD=", "REPOMAP_PG_PASSWORD=", "PGPASSWORD="))
    ] + [
        f"REPOMAP_RUNTIME_HOME_HASH={identity.home_hash}", f"POSTGRES_PASSWORD={postgres.password}",
        f"REPOMAP_PG_PASSWORD={postgres.password}", f"PGPASSWORD={postgres.password}",
    ]
    env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    env_file.chmod(0o600)
    return identity


@contextmanager
def owned_d9_postgres_cluster(
    home: Path, *, graph_db: str = "repomap", runtime: str = "docker",
    password: str = "repomap_d9_test_pw", profile: str | None = None, image: str | None = None,
) -> Iterator[tuple[LocalRuntimeIdentity, PostgresContainerDatabase, Any]]:
    """Start an owned PostgreSQL container whose name and labels match LocalRuntimeIdentity.from_home(home).

    ``image`` optionally selects the one exact preloaded release pin (never pulled); anything else refuses first.
    """
    selected = _explicit_image(image, profile) or TEST_POSTGRES_IMAGE  # the unchanged configuration default
    config = _D9ContainerConfig(
        runtime=runtime, host_port=_reserve_free_local_port(), password=password, profile=profile,
                                image=selected)
    stub_pg = PostgresContainerDatabase(
        host=config.bind_host, port=config.host_port, user=config.user,
        database=config.database, psql_command="psql", password=config.password,
    )
    identity = setup_d9_backup_home(home, stub_pg, graph_db=graph_db)
    harness = OwnedD9PostgresHarness(config, identity)
    tmpdir = tempfile.TemporaryDirectory(prefix="repomap-d9-owned-client-")
    prev_pw = os.environ.get("PGPASSWORD")
    try:
        harness.start()
        psql_path = Path(tmpdir.name) / "psql"
        psql_path.write_text(
            build_psql_wrapper_script(password=config.password, runtime=config.runtime, container_name=harness.container_name),
            encoding="utf-8",
        )
        psql_path.chmod(0o700)
        os.environ["PGPASSWORD"] = config.password
        yield identity, PostgresContainerDatabase(
            host=config.bind_host, port=config.host_port, user=config.user,
            database=config.database, psql_command=str(psql_path), password=config.password,
        ), subprocess.run
    finally:
        os.environ.pop("PGPASSWORD", None) if prev_pw is None else os.environ.__setitem__("PGPASSWORD", prev_pw)
        try:
            harness.teardown()
        finally:
            tmpdir.cleanup()


def seed_adr0077_roles_on_cluster(
    psql_runner: Any, *, owner: str = "repomap",
    reader_role: str = "candidate_fixture_reader", writer_role: str = "candidate_fixture_enrichment",
) -> None:
    """Create least-privilege custom roles for ADR 0077 on the target cluster."""
    del owner
    sql = (
        f"DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{reader_role}') THEN "
        f"CREATE ROLE {reader_role} LOGIN PASSWORD 'fixture_reader_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT; "
        f"END IF; "
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{writer_role}') THEN "
        f"CREATE ROLE {writer_role} LOGIN PASSWORD 'fixture_writer_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT; "
        f"END IF; END $$;"
    )
    psql_runner(sql)


def observe_template_baseline_in_container(container_name: str, *, user: str, database: str = "template1", runtime: str = "docker") -> str:
    """Compute the product's canonical logical baseline digest for one database of a running cluster."""
    res = subprocess.run(
        [runtime, "exec", "-i", container_name, "psql", "-U", user, "-d", database, "-X", "-A", "-t", "-q", "-v", "ON_ERROR_STOP=1"],
        input=template_baseline_sql(), capture_output=True, text=True, check=True,
    )
    return parse_template_baseline(res.stdout, field=database)


def clean_template_reference(
    root: Path, *, profile: str | None = None, runtime: str = "docker", image: str | None = None,
) -> str:
    """Establish the clean template1 reference on a separate fresh cluster of the same admitted image.

    The reference never comes from a restore target; it is cached per image and profile for the session.
    """
    profile = profile or current_pg_test_profile()
    key = (_explicit_image(image, profile), profile)
    suffix = profile + (f"-{D9_EXPLICIT_IMAGES[image]}" if image else "")
    if key not in _CLEAN_TEMPLATE_REFERENCES:
        with owned_d9_postgres_cluster(
            root / f"reference-home-{suffix}", runtime=runtime, profile=profile, image=image,
        ) as (identity, postgres, _runner):
            _CLEAN_TEMPLATE_REFERENCES[key] = observe_template_baseline_in_container(
                identity.postgres_container, user=str(postgres.user), runtime=runtime)
    return _CLEAN_TEMPLATE_REFERENCES[key]


SYNTHETIC_GRAPH_SQL = (
    "CREATE SCHEMA ext_alpha_s; CREATE SCHEMA ext_beta_s; CREATE SCHEMA ext_gamma_s; CREATE SCHEMA app_ext; "
    "CREATE EXTENSION ext_alpha WITH SCHEMA ext_alpha_s VERSION '1.0'; "
    "CREATE EXTENSION ext_beta WITH SCHEMA ext_beta_s VERSION '1.0'; "
    "CREATE EXTENSION ext_gamma WITH SCHEMA ext_gamma_s VERSION '1.0'; "
    "COMMENT ON EXTENSION ext_gamma IS 'custom gamma comment'; COMMENT ON EXTENSION ext_beta IS NULL; "
    "CREATE SEQUENCE app_ext.item_seq START WITH 50; SELECT nextval('app_ext.item_seq'); "
    "CREATE TABLE app_ext.items (id int PRIMARY KEY DEFAULT nextval('app_ext.item_seq'), tag ext_gamma_s.gamma_tag NOT NULL); "
    "INSERT INTO app_ext.items (id, tag) VALUES (1, 'alpha-beta-gamma');"
)


def seed_synthetic_graph(postgres: Any, graph_db: str) -> None:
    """Create a migrated graph with a three-level synthetic extension chain, comments and data."""
    handle = postgres.create_database(graph_db)
    apply_migrations(default_rdbms_root(), handle.psql_args, psql_command=handle.psql_command)
    with closing(connect_real_postgres(postgres, graph_db, autocommit=True)) as conn:
        conn.execute(SYNTHETIC_GRAPH_SQL)


def engine_container_id(container_name: str, *, runtime: str = "docker") -> str:
    """Return the immutable container ID that extension_v2 container custody binds."""
    res = subprocess.run([runtime, "inspect", "--format", "{{.Id}}", container_name], capture_output=True, text=True, check=True)
    return res.stdout.strip()


def database_names(postgres: Any) -> list[str]:
    with closing(connect_real_postgres(postgres, autocommit=True)) as conn:
        return sorted(str(r[0]) for r in conn.execute("SELECT datname FROM pg_database WHERE NOT datistemplate").fetchall())


# The PID 1 postmaster reaps reparented orphans; any exit other than 0 or 1 is a backend crash to it,
# logged as "server process (PID n) ..." before every other session is terminated and reinitialized.
POSTMASTER_CRASH_MARKERS = ("server process (PID", "terminated by signal", "terminating any other active server processes",
                            "all server processes terminated")


def postmaster_crash_lines(container: str, *, runtime: str = "docker") -> list[str]:
    """Return server log lines that record a reaped crashed child or a resulting crash-restart."""
    logs = subprocess.run([runtime, "logs", container], capture_output=True, text=True, check=False)
    return [line for line in (logs.stdout + logs.stderr).splitlines() if any(m in line for m in POSTMASTER_CRASH_MARKERS)]


def container_ppid(container: str, pid: str, *, runtime: str = "docker") -> str:
    stat = subprocess.run([runtime, "exec", "-u", "root", container, "cat", f"/proc/{pid}/stat"], capture_output=True, text=True, check=True)
    return stat.stdout.split(") ", 1)[1].split()[1]
