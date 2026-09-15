from contextlib import closing

import psycopg
import pytest

from repomap_kg.runtime.database_roles import (
    COORDINATOR_CONTROL_ROLE,
    READ_STATUS_ROLE,
    REFRESH_PUBLICATION_ROLE,
    RoleSecrets,
    render_database_role_sql,
)
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
                """DO $arch7e$
                   BEGIN
                     IF NOT EXISTS (
                       SELECT 1 FROM pg_roles WHERE rolname = 'arch7e_parent'
                     ) THEN
                       CREATE ROLE arch7e_parent;
                     END IF;
                     IF NOT EXISTS (
                       SELECT 1 FROM pg_roles
                       WHERE rolname = 'repomap_read_status'
                     ) THEN
                       CREATE ROLE repomap_read_status LOGIN;
                     END IF;
                   END
                   $arch7e$;"""
            )
            admin.execute(
                f'ALTER ROLE "{READ_STATUS_ROLE}" LOGIN SUPERUSER CREATEDB '
                "CREATEROLE INHERIT REPLICATION BYPASSRLS"
            )
            admin.execute(
                f'GRANT "arch7e_parent" TO "{READ_STATUS_ROLE}"'
            )

        _create_fixture_and_roles(postgres, "arch7e_graph", "graph", secrets)
        _create_fixture_and_roles(postgres, "arch7e_control", "control", secrets)

        with closing(_connection(postgres, "arch7e_graph")) as admin:
            assert _database_privilege(admin, READ_STATUS_ROLE, "arch7e_graph", "CONNECT")
            assert _table_privilege(admin, READ_STATUS_ROLE, "SELECT")
            assert not _table_privilege(admin, READ_STATUS_ROLE, "INSERT")
            assert _table_privilege(admin, REFRESH_PUBLICATION_ROLE, "SELECT")
            assert _table_privilege(admin, REFRESH_PUBLICATION_ROLE, "INSERT")
            assert not _database_privilege(
                admin,
                COORDINATOR_CONTROL_ROLE,
                "arch7e_graph",
                "CONNECT",
            )

        with closing(_connection(postgres, "arch7e_control")) as admin:
            assert _database_privilege(
                admin,
                COORDINATOR_CONTROL_ROLE,
                "arch7e_control",
                "CONNECT",
            )
            assert _table_privilege(admin, COORDINATOR_CONTROL_ROLE, "SELECT")
            assert _table_privilege(admin, COORDINATOR_CONTROL_ROLE, "INSERT")
            assert not _database_privilege(
                admin,
                REFRESH_PUBLICATION_ROLE,
                "arch7e_control",
                "CONNECT",
            )

        with closing(_connection(postgres, postgres.database)) as admin:
            row = admin.execute(
                """SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit,
                          rolreplication, rolbypassrls
                   FROM pg_roles
                   WHERE rolname = %s""",
                (READ_STATUS_ROLE,),
            ).fetchone()
            assert row == (False, False, False, False, False, False)
            membership_count = admin.execute(
                """SELECT count(*)
                   FROM pg_auth_members AS membership
                   JOIN pg_roles AS member ON member.oid = membership.member
                   WHERE member.rolname = %s""",
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
            admin.execute(
                f'ALTER ROLE "{READ_STATUS_ROLE}" SUPERUSER INHERIT'
            )
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
            admin.execute(
                f'ALTER TABLE arch7e_owned OWNER TO "{READ_STATUS_ROLE}"'
            )
            admin.commit()
            with pytest.raises(
                psycopg.Error,
                match="database capability role owns objects",
            ):
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
