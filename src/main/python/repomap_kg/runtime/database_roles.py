"""Declarative least-privilege database role and grant reconciliation."""

from __future__ import annotations

from typing import Literal

from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    planned_psql_stdin_command,
    quote_sql_identifier,
    run_container_command,
    validate_database_name,
)
from repomap_kg.runtime.local import LocalRuntimePlan
from repomap_kg.runtime.database_role_contract import (
    COORDINATOR_CONTROL_ROLE,
    READ_STATUS_ROLE,
    REFRESH_PUBLICATION_ROLE,
    RoleSecrets,
    ensure_role_secrets,
    project_database_role_config,
    project_read_status_config,
    read_role_secrets,
)


_RoleRuntimePlan = LocalRuntimePlan


DatabaseKind = Literal["graph", "control"]


def render_database_role_sql(
    *,
    database: str,
    owner_role: str,
    database_kind: DatabaseKind,
    secrets: RoleSecrets,
) -> str:
    """Render deterministic idempotent role and database grant SQL."""

    validate_database_name(database)
    if database_kind not in ("graph", "control"):
        raise ValueError("database_kind must be graph or control")
    database_sql = quote_sql_identifier(database)
    owner_sql = _quote_role_identifier(owner_role)
    read_sql = _quote_role_identifier(READ_STATUS_ROLE)
    refresh_sql = _quote_role_identifier(REFRESH_PUBLICATION_ROLE)
    control_sql = _quote_role_identifier(COORDINATOR_CONTROL_ROLE)
    role_statements = "\n".join(
        _role_sql(role, password)
        for role, password in (
            (READ_STATUS_ROLE, secrets.read_status),
            (REFRESH_PUBLICATION_ROLE, secrets.refresh_publication),
            (COORDINATOR_CONTROL_ROLE, secrets.coordinator_control),
        )
    )
    common = f"""
REVOKE ALL ON DATABASE {database_sql} FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM {read_sql}, {refresh_sql}, {control_sql};
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {read_sql}, {refresh_sql}, {control_sql};
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {read_sql}, {refresh_sql}, {control_sql};
GRANT CONNECT ON DATABASE {database_sql} TO {read_sql};
GRANT USAGE ON SCHEMA public TO {read_sql};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO {read_sql};
ALTER DEFAULT PRIVILEGES FOR ROLE {owner_sql} IN SCHEMA public
  GRANT SELECT ON TABLES TO {read_sql};
""".strip()
    capability_sql = (
        _graph_grants(database_sql, owner_sql, refresh_sql, control_sql)
        if database_kind == "graph"
        else _control_grants(database_sql, owner_sql, refresh_sql, control_sql)
    )
    return f"BEGIN;\n{role_statements}\n{common}\n{capability_sql}\nCOMMIT;\n"


def reconcile_graph_database_roles(
    plan: _RoleRuntimePlan,
    database: str,
    command_runner: CommandRunner,
) -> None:
    """Reconcile graph read and publication capabilities."""

    if database not in plan.graph_databases:
        raise ValueError("graph role target is not configured")
    _reconcile_database_roles(plan, database, "graph", command_runner)


def reconcile_control_database_roles(
    plan: _RoleRuntimePlan,
    database: str,
    command_runner: CommandRunner,
) -> None:
    """Reconcile control read and coordinator capabilities."""

    control = tuple(
        value for value in plan.owned_databases if value not in plan.graph_databases
    )
    if control != (database,):
        raise ValueError("control role target is not configured")
    _reconcile_database_roles(plan, database, "control", command_runner)


def _reconcile_database_roles(
    plan: _RoleRuntimePlan,
    database: str,
    database_kind: DatabaseKind,
    command_runner: CommandRunner,
) -> None:
    sql = render_database_role_sql(
        database=database,
        owner_role=plan.user,
        database_kind=database_kind,
        secrets=read_role_secrets(plan.env_file),
    )
    run_container_command(
        plan,
        planned_psql_stdin_command(plan, database),
        command_runner,
        label="database role reconciliation",
        input_data=sql.encode("utf-8"),
    )


def _role_sql(role: str, password: str) -> str:
    role_sql = _quote_role_identifier(role)
    role_literal = _quote_sql_literal(role)
    password_sql = _quote_sql_literal(password)
    return f"""DO $repomap$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {role_literal}) THEN
    CREATE ROLE {role_sql} LOGIN;
  END IF;
END
$repomap$;
DO $repomap$
DECLARE
  granted_role record;
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_shdepend AS dependency
    JOIN pg_roles AS owned_role ON owned_role.oid = dependency.refobjid
    WHERE dependency.refclassid = 'pg_authid'::regclass
      AND dependency.deptype = 'o'
      AND owned_role.rolname = {role_literal}
  ) THEN
    RAISE EXCEPTION 'database capability role owns objects';
  END IF;
  FOR granted_role IN
    SELECT parent.rolname
    FROM pg_auth_members AS membership
    JOIN pg_roles AS member ON member.oid = membership.member
    JOIN pg_roles AS parent ON parent.oid = membership.roleid
    WHERE member.rolname = {role_literal}
  LOOP
    EXECUTE format('REVOKE %I FROM %I', granted_role.rolname, {role_literal});
  END LOOP;
END
$repomap$;
ALTER ROLE {role_sql}
  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS
  PASSWORD {password_sql};"""


def _graph_grants(
    database_sql: str,
    owner_sql: str,
    refresh_sql: str,
    control_sql: str,
) -> str:
    return f"""REVOKE CONNECT ON DATABASE {database_sql} FROM {control_sql};
GRANT CONNECT, TEMPORARY ON DATABASE {database_sql} TO {refresh_sql};
GRANT USAGE ON SCHEMA public TO {refresh_sql};
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON ALL TABLES IN SCHEMA public TO {refresh_sql};
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {refresh_sql};
ALTER DEFAULT PRIVILEGES FOR ROLE {owner_sql} IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON TABLES TO {refresh_sql};
ALTER DEFAULT PRIVILEGES FOR ROLE {owner_sql} IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {refresh_sql};"""


def _control_grants(
    database_sql: str,
    owner_sql: str,
    refresh_sql: str,
    control_sql: str,
) -> str:
    return f"""REVOKE CONNECT ON DATABASE {database_sql} FROM {refresh_sql};
GRANT CONNECT ON DATABASE {database_sql} TO {control_sql};
GRANT USAGE ON SCHEMA public TO {control_sql};
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON ALL TABLES IN SCHEMA public TO {control_sql};
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {control_sql};
ALTER DEFAULT PRIVILEGES FOR ROLE {owner_sql} IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON TABLES TO {control_sql};
ALTER DEFAULT PRIVILEGES FOR ROLE {owner_sql} IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {control_sql};"""


def _quote_sql_literal(value: str) -> str:
    if "\x00" in value:
        raise ValueError("database role value contains NUL")
    return "'" + value.replace("'", "''") + "'"


def _quote_role_identifier(identifier: str) -> str:
    if (
        not isinstance(identifier, str)
        or not identifier
        or "\x00" in identifier
    ):
        raise ValueError("database role identifier is invalid")
    return '"' + identifier.replace('"', '""') + '"'


__all__ = [
    "COORDINATOR_CONTROL_ROLE",
    "READ_STATUS_ROLE",
    "REFRESH_PUBLICATION_ROLE",
    "RoleSecrets",
    "ensure_role_secrets",
    "project_database_role_config",
    "project_read_status_config",
    "read_role_secrets",
    "reconcile_control_database_roles",
    "reconcile_graph_database_roles",
    "render_database_role_sql",
]
