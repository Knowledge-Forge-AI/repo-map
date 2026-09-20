from contextlib import closing, contextmanager
from pathlib import Path
import tomllib

import psycopg
import pytest

from repomap_kg.runtime.database_roles import (
    COORDINATOR_CONTROL_ROLE,
    READ_STATUS_ROLE,
    REFRESH_PUBLICATION_ROLE,
    RoleSecrets,
    render_database_role_sql,
)
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.release_cluster import (
    ReleaseClusterError,
    ReleaseGraphOperator,
    initialize_release_cluster,
    release_cluster_status,
)
from repomap_kg.storage import default_rdbms_root, discover_migrations
from repomap_kg.storage.main import _migration_script
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def test_graph_and_control_privilege_matrix_is_exact() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        secrets = RoleSecrets("read-secret", "refresh-secret", "control-secret")
        with closing(_connection(postgres, postgres.database, autocommit=True)) as admin:
            admin.execute('CREATE DATABASE "arch7e_graph"')
            admin.execute('CREATE DATABASE "arch7e_control"')
            admin.execute(
                "DO $arch7e$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'arch7e_parent') THEN "
                "CREATE ROLE arch7e_parent; END IF; "
                "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'repomap_read_status') THEN "
                "CREATE ROLE repomap_read_status LOGIN; END IF; "
                "END $arch7e$;"
            )
            admin.execute(
                f'ALTER ROLE "{READ_STATUS_ROLE}" LOGIN SUPERUSER CREATEDB CREATEROLE INHERIT REPLICATION BYPASSRLS'
            )
            admin.execute(f'GRANT "arch7e_parent" TO "{READ_STATUS_ROLE}"')

        _create_fixture_and_roles(postgres, "arch7e_graph", "graph", secrets)
        _create_fixture_and_roles(postgres, "arch7e_control", "control", secrets)

        with closing(_connection(postgres, "arch7e_graph")) as admin:
            assert _database_privilege(admin, READ_STATUS_ROLE, "arch7e_graph", "CONNECT")
            assert _table_privilege(admin, READ_STATUS_ROLE, "SELECT")
            assert not _table_privilege(admin, READ_STATUS_ROLE, "INSERT")
            assert _table_privilege(admin, REFRESH_PUBLICATION_ROLE, "SELECT")
            assert _table_privilege(admin, REFRESH_PUBLICATION_ROLE, "INSERT")
            assert not _database_privilege(admin, COORDINATOR_CONTROL_ROLE, "arch7e_graph", "CONNECT")

        with closing(_connection(postgres, "arch7e_control")) as admin:
            assert _database_privilege(admin, COORDINATOR_CONTROL_ROLE, "arch7e_control", "CONNECT")
            assert _table_privilege(admin, COORDINATOR_CONTROL_ROLE, "SELECT")
            assert _table_privilege(admin, COORDINATOR_CONTROL_ROLE, "INSERT")
            assert not _database_privilege(admin, REFRESH_PUBLICATION_ROLE, "arch7e_control", "CONNECT")

        with closing(_connection(postgres, postgres.database)) as admin:
            row = admin.execute(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolreplication, rolbypassrls "
                "FROM pg_roles WHERE rolname = %s",
                (READ_STATUS_ROLE,),
            ).fetchone()
            assert row == (False, False, False, False, False, False)
            membership_count = admin.execute(
                "SELECT count(*) FROM pg_auth_members AS m JOIN pg_roles AS r ON r.oid = m.member WHERE r.rolname = %s",
                (READ_STATUS_ROLE,),
            ).fetchone()
            assert membership_count == (0,)


def test_role_reconciliation_is_transactional_and_refuses_owned_objects() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        secrets = RoleSecrets("read-secret", "refresh-secret", "control-secret")
        sql = render_database_role_sql(
            database=postgres.database,
            owner_role=postgres.user,
            database_kind="graph",
            secrets=secrets,
        )
        failing_sql = sql.replace(
            "GRANT USAGE ON SCHEMA public TO",
            "GRANT USAGE ON SCHEMA arch7e_missing TO",
            1,
        )
        with closing(_connection(postgres, postgres.database)) as admin:
            admin.execute(f'ALTER ROLE "{READ_STATUS_ROLE}" SUPERUSER INHERIT')
            admin.commit()
            with pytest.raises(psycopg.Error):
                admin.execute(failing_sql)
            admin.rollback()
            attributes = admin.execute(
                "SELECT rolsuper, rolinherit FROM pg_roles WHERE rolname = %s",
                (READ_STATUS_ROLE,),
            ).fetchone()
            assert attributes == (True, True)

        with closing(_connection(postgres, postgres.database)) as admin:
            admin.execute("CREATE TABLE arch7e_owned(id integer)")
            admin.execute(f'ALTER TABLE arch7e_owned OWNER TO "{READ_STATUS_ROLE}"')
            admin.commit()
            with pytest.raises(psycopg.Error, match="database capability role owns objects"):
                admin.execute(sql)


def _create_fixture_and_roles(postgres, database, database_kind, secrets) -> None:
    with closing(_connection(postgres, database, autocommit=True)) as admin:
        admin.execute("CREATE TABLE role_fixture(id bigint GENERATED BY DEFAULT AS IDENTITY)")
        role_sql = render_database_role_sql(
            database=database,
            owner_role=postgres.user,
            database_kind=database_kind,
            secrets=secrets,
        )
        admin.execute(role_sql)
        admin.execute(role_sql)


def _connection(postgres, database, *, autocommit=False):
    return psycopg.connect(
        host=postgres.host,
        port=postgres.port,
        user=postgres.user,
        dbname=database,
        password=postgres.password,
        autocommit=autocommit,
    )


def _database_privilege(connection, role, database, privilege) -> bool:
    row = connection.execute(
        "SELECT has_database_privilege(%s, %s, %s)",
        (role, database, privilege),
    ).fetchone()
    return bool(row and row[0])


def _table_privilege(connection, role, privilege) -> bool:
    row = connection.execute(
        "SELECT has_table_privilege(%s, 'public.role_fixture', %s)",
        (role, privilege),
    ).fetchone()
    return bool(row and row[0])


@contextmanager
def _owned_cluster_databases():
    with temporary_postgres() as postgres:
        names = (
            "repomap_cluster_graph",
            "repomap_refusal_graph",
            "repomap_wave1_control",
            "repomap_preexisting",
        )
        with closing(_connection(postgres, postgres.database, autocommit=True)) as admin:
            assert admin.execute(
                "SELECT datname FROM pg_database WHERE datname = ANY(%s)",
                (list(names),),
            ).fetchall() == []
            try:
                yield postgres
            finally:
                for name in names:
                    admin.execute(
                        psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                            psycopg.sql.Identifier(name)
                        )
                    )


def _verify_cluster_toml(path: Path, postgres, graph_db: str) -> None:
    data = tomllib.loads((path / "repomap.rpl.toml").read_text(encoding="utf-8"))
    assert type(data["schema_version"]) is int and data["schema_version"] == 1
    assert data["service"] == {"mode": "local", "mcp_transport": "stdio", "log_level": "info"}
    assert data["runtime"]["container_runtime"] == "docker"
    assert data["runtime"]["server_host_port"] == 8080 and data["runtime"]["bind_host"] == "127.0.0.1"
    assert data["runtime"]["postgres"] == {"direct_host_port_enabled": False, "host_port": postgres.port, "bind_host": "127.0.0.1"}
    assert data["postgres"] == {
        "host": postgres.host, "port": postgres.port, "database": "repomap_wave1",
        "user": postgres.user, "password_env": "REPOMAP_PG_PASSWORD",
    }
    assert len(data["graphs"]) == 1
    assert data["graphs"][0] == {
        "id": "cluster-graph", "name": "ClusterGraph", "root_path": "./cluster-graph",
        "repository_name": "cluster-graph", "privacy": "public-dev", "database": graph_db,
        "enabled": False, "mcp_visible": False, "extractor_profile": "default",
        "refresh_policy": "manual", "exclude_paths": [],
    }


def _setup_cluster_home(path: Path, postgres, graph_db: str = "repomap_cluster_graph") -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    setup_local_runtime(path)
    toml = (
        f'schema_version = 1\n[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n'
        f'[runtime]\ncontainer_runtime = "docker"\nserver_host_port = 8080\nbind_host = "127.0.0.1"\n'
        f'[runtime.postgres]\ndirect_host_port_enabled = false\nhost_port = {postgres.port}\nbind_host = "127.0.0.1"\n'
        f'[postgres]\nhost = "{postgres.host}"\nport = {postgres.port}\ndatabase = "repomap_wave1"\n'
        f'user = "{postgres.user}"\npassword_env = "REPOMAP_PG_PASSWORD"\n'
        f'[[graphs]]\nid = "cluster-graph"\nname = "ClusterGraph"\nroot_path = "./cluster-graph"\n'
        f'repository_name = "cluster-graph"\nprivacy = "public-dev"\ndatabase = "{graph_db}"\n'
        f'enabled = false\nmcp_visible = false\nextractor_profile = "default"\nrefresh_policy = "manual"\nexclude_paths = []\n'
        f'[server_memory]\nenabled = false\npath = "./server-memory"\nmode = "read_only"\n'
    )
    (path / "repomap.rpl.toml").write_text(toml, encoding="utf-8")
    _verify_cluster_toml(path, postgres, graph_db)
    env_file = path / "runtime" / ".env"
    env_lines = [
        line for line in env_file.read_text(encoding="utf-8").splitlines()
        if not line.startswith(("REPOMAP_PG_PASSWORD=", "POSTGRES_PASSWORD=", "PGPASSWORD="))
    ] + [f"REPOMAP_PG_PASSWORD={postgres.password}", f"POSTGRES_PASSWORD={postgres.password}", f"PGPASSWORD={postgres.password}"]
    env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    env_file.chmod(0o600)
    return path


def test_release_cluster_topology_initialization_roles_and_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    require_postgres_binaries()
    with _owned_cluster_databases() as postgres:
        monkeypatch.setenv("REPOMAP_PG_PASSWORD", postgres.password)
        monkeypatch.setenv("POSTGRES_PASSWORD", postgres.password)
        home = _setup_cluster_home(tmp_path / "cluster_home", postgres)
        _verify_cluster_toml(home, postgres, "repomap_cluster_graph")

        operator = ReleaseGraphOperator(home)
        assert operator.databases == ("repomap_cluster_graph",)
        assert operator.maintenance_database == "postgres"
        assert operator.password == postgres.password
        assert (operator.config.postgres.host, operator.config.postgres.port,
                operator.config.postgres.user) == (postgres.host, postgres.port, postgres.user)
        assert not operator.database_exists("repomap_cluster_graph")

        res = initialize_release_cluster(home)
        assert res["command"] == "release-cluster-init" and res["result"] == "ready"
        assert res["control_created"] is True
        assert res["graph_database_created_count"] == 1 and res["graph_schema_initialized_count"] == 1

        with closing(_connection(postgres, "repomap_cluster_graph")) as admin:
            assert _database_privilege(admin, READ_STATUS_ROLE, "repomap_cluster_graph", "CONNECT")
            assert not _database_privilege(admin, COORDINATOR_CONTROL_ROLE, "repomap_cluster_graph", "CONNECT")

        with closing(_connection(postgres, "repomap_wave1_control")) as admin:
            assert _database_privilege(admin, COORDINATOR_CONTROL_ROLE, "repomap_wave1_control", "CONNECT")

        status = release_cluster_status(home)
        assert status["command"] == "release-cluster-status" and status["result"] == "ready"
        assert status["control_schema_ready"] is True
        assert status["graph_database_count"] == 1 and status["graph_schema_ready_count"] == 1
        assert status["graph_schema_unavailable_count"] == 0

        res2 = initialize_release_cluster(home)
        assert res2["result"] == "ready" and res2["control_created"] is False
        assert res2["graph_schema_current_count"] == 1 and res2["graph_database_created_count"] == 0


def test_release_cluster_refusals_and_bounded_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    require_postgres_binaries()
    with _owned_cluster_databases() as postgres:
        monkeypatch.setenv("REPOMAP_PG_PASSWORD", postgres.password)
        monkeypatch.setenv("POSTGRES_PASSWORD", postgres.password)
        home = _setup_cluster_home(tmp_path / "refusal_home", postgres, "repomap_refusal_graph")
        _verify_cluster_toml(home, postgres, "repomap_refusal_graph")

        operator = ReleaseGraphOperator(home)
        with pytest.raises(ReleaseClusterError, match="release_cluster_cleanup_refused"):
            operator.drop_created_database("unmanaged_database")

        with closing(_connection(postgres, postgres.database, autocommit=True)) as admin:
            admin.execute('CREATE DATABASE "repomap_refusal_graph"')

        with pytest.raises(ReleaseClusterError, match="release_cluster_graph_adoption_refused"):
            initialize_release_cluster(home)

        with closing(_connection(postgres, "repomap_refusal_graph", autocommit=True)) as admin:
            admin.execute("CREATE TABLE unmanaged_table (id integer)")

        with pytest.raises(ReleaseClusterError, match="release_cluster_graph_schema_refused"):
            initialize_release_cluster(home)
        with closing(_connection(postgres, "repomap_refusal_graph")) as admin:
            assert admin.execute("SELECT to_regclass('public.unmanaged_table')::text").fetchone() == ("unmanaged_table",)
        assert not operator.database_exists("repomap_wave1_control")

        def failing_control_init(_h):
            raise RuntimeError("simulated control failure")

        with closing(_connection(postgres, postgres.database, autocommit=True)) as admin:
            admin.execute('DROP DATABASE "repomap_refusal_graph"')
            admin.execute('CREATE DATABASE "repomap_preexisting"')

        # Early control failure alone does not prove cleanup because graph DB creation is not reached.
        with pytest.raises(ReleaseClusterError, match="release_cluster_initialization_failed"):
            initialize_release_cluster(home, control_initializer=failing_control_init)
        assert not operator.database_exists("repomap_refusal_graph")

        initialized: list[str] = []

        class FailingSchemaOperator(ReleaseGraphOperator):
            def initialize_schema(self, database: str) -> None:
                assert self.database_exists(database)
                initialized.append(database)
                raise RuntimeError("simulated schema initialization failure")

        # Supported operator seam: real owned DB is created, then schema initialization fails.
        # Proves cleanup drops the created DB, preserves preexisting DB, then proves recovery.
        with pytest.raises(ReleaseClusterError, match="release_cluster_initialization_failed"):
            initialize_release_cluster(
                home,
                operator_factory=FailingSchemaOperator,
                control_initializer=lambda _h: {"command": "coordinator-control-init", "result": "ready"},
            )
        assert initialized == ["repomap_refusal_graph"]
        assert not operator.database_exists("repomap_refusal_graph")
        with closing(_connection(postgres, postgres.database)) as admin:
            assert admin.execute("SELECT 1 FROM pg_database WHERE datname = 'repomap_preexisting'").fetchone() is not None

        # Recovery state: re-verify TOML, initialize successfully, verify status and preserved preexisting DB.
        _verify_cluster_toml(home, postgres, "repomap_refusal_graph")
        recovery_res = initialize_release_cluster(
            home,
            control_initializer=lambda _h: {"command": "coordinator-control-init", "result": "ready"},
        )
        assert recovery_res["result"] == "ready" and recovery_res["graph_database_created_count"] == 1
        assert operator.database_exists("repomap_refusal_graph")
        assert operator.schema_state("repomap_refusal_graph") == ("current", operator.expected_count)

        status = release_cluster_status(
            home,
            control_status=lambda _h: {"command": "coordinator-control-status", "result": "ready"},
        )
        assert status["result"] == "ready" and status["graph_schema_ready_count"] == 1
        with closing(_connection(postgres, postgres.database)) as admin:
            assert admin.execute("SELECT 1 FROM pg_database WHERE datname = 'repomap_preexisting'").fetchone() is not None


def test_release_cluster_backup_first_upgrades_when_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    require_postgres_binaries()
    with _owned_cluster_databases() as postgres:
        monkeypatch.setenv("REPOMAP_PG_PASSWORD", postgres.password)
        monkeypatch.setenv("POSTGRES_PASSWORD", postgres.password)
        home = _setup_cluster_home(tmp_path / "upgrade_home", postgres, "repomap_cluster_graph")
        migrations = discover_migrations(default_rdbms_root())
        with closing(_connection(postgres, postgres.database, autocommit=True)) as admin:
            admin.execute('CREATE DATABASE "repomap_cluster_graph"')
        with closing(_connection(postgres, "repomap_cluster_graph", autocommit=True)) as g_admin:
            g_admin.execute(_migration_script(migrations[:1], initialize_ledger=True))

        operator = ReleaseGraphOperator(home)
        assert operator.schema_state("repomap_cluster_graph")[0] == "behind"

        backups_called: list[str] = []

        def track_backup(_home, op, db):
            state, applied = op.schema_state(db)
            assert state == "behind"
            assert applied == 1
            backups_called.append(db)

        res = initialize_release_cluster(home, backup_function=track_backup)
        assert res["result"] == "ready" and res["graph_schema_upgraded_count"] == 1
        assert res["backup_first_upgrade_count"] == 1
        assert backups_called == ["repomap_cluster_graph"]
        assert operator.schema_state("repomap_cluster_graph") == ("current", operator.expected_count)
