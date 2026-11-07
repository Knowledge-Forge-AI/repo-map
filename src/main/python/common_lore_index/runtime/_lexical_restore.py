"""PostgreSQL cloe_lexical custody verification, role denial, and restore purge SQL."""

from __future__ import annotations

from collections.abc import Sequence
import os
import subprocess

from common_lore_index.runtime.backup_commands import CommandRunner
from common_lore_index.runtime.database_role_contract import (
    COORDINATOR_CONTROL_ROLE,
    READ_STATUS_ROLE,
    REFRESH_PUBLICATION_ROLE,
)
from common_lore_index.runtime.local import LocalRuntimePlan
from common_lore_index.storage.errors import StorageSchemaError

LEXICAL_SCHEMA = "cloe_lexical"
LEXICAL_SCHEMA_MARKER = "cloe-lexical-schema:1"
LEXICAL_ALLOWED_RELATIONS = (
    "generations",
    "authority",
    "documents",
    "chunks",
    "omissions",
)
LEXICAL_TABLES_DELETE_ORDER = (
    "authority",
    "omissions",
    "chunks",
    "documents",
)
RESTORED_INVALIDATION_REASON = "restored_snapshot_unverified_lexical_index_invalidated"


def _quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_lexical_custody_and_restore_plpgsql(
    *,
    owner_role: str | None = None,
    purge_restored_rows: bool = True,
) -> list[str]:
    """Render PL/pgSQL statements for cloe_lexical custody, role denial, and restore purge."""
    owner_expr = (
        f"{_quote_literal(owner_role)}::regrole"
        if owner_role is not None
        else "(SELECT datdba FROM pg_database WHERE datname = current_database())"
    )
    owner_name_expr = (
        _quote_literal(owner_role)
        if owner_role is not None
        else "(SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database())"
    )
    allowed_rels = ", ".join(_quote_literal(r) for r in LEXICAL_ALLOWED_RELATIONS)
    lines = [
        f"IF to_regnamespace('{LEXICAL_SCHEMA}') IS NOT NULL THEN",
        "    IF EXISTS (",
        "        SELECT 1 FROM pg_namespace",
        f"        WHERE nspname = '{LEXICAL_SCHEMA}'",
        f"          AND (nspowner <> {owner_expr} OR COALESCE(obj_description(oid, 'pg_namespace'), '') <> '{LEXICAL_SCHEMA_MARKER}')",
        "    ) OR EXISTS (",
        "        SELECT 1 FROM pg_class c",
        "        JOIN pg_namespace n ON n.oid = c.relnamespace",
        f"        WHERE n.nspname = '{LEXICAL_SCHEMA}'",
        f"          AND (c.relowner <> {owner_expr} OR (c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') AND c.relname NOT IN ({allowed_rels})))",
        "    ) OR EXISTS (",
        "        SELECT 1 FROM pg_proc p",
        "        JOIN pg_namespace n ON n.oid = p.pronamespace",
        f"        WHERE n.nspname = '{LEXICAL_SCHEMA}'",
        "    ) THEN",
        "        RAISE EXCEPTION 'cloe_lexical schema or object custody is not owned by the database owner';",
        "    END IF;",
        f"    EXECUTE 'REVOKE ALL ON SCHEMA {LEXICAL_SCHEMA} FROM PUBLIC';",
        f"    EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA {LEXICAL_SCHEMA} FROM PUBLIC';",
        f"    EXECUTE 'REVOKE ALL ON ALL SEQUENCES IN SCHEMA {LEXICAL_SCHEMA} FROM PUBLIC';",
        f"    EXECUTE 'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {LEXICAL_SCHEMA} FROM PUBLIC';",
        f"    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA {LEXICAL_SCHEMA} REVOKE ALL ON TABLES FROM PUBLIC', {owner_name_expr});",
        f"    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA {LEXICAL_SCHEMA} REVOKE ALL ON SEQUENCES FROM PUBLIC', {owner_name_expr});",
        f"    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA {LEXICAL_SCHEMA} REVOKE ALL ON FUNCTIONS FROM PUBLIC', {owner_name_expr});",
    ]
    for role in (READ_STATUS_ROLE, REFRESH_PUBLICATION_ROLE, COORDINATOR_CONTROL_ROLE):
        r_ident = _quote_ident(role)
        r_lit = _quote_literal(role)
        lines.extend(
            [
                f"    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {r_lit}) THEN",
                "        EXECUTE " + _quote_literal(f"REVOKE ALL ON SCHEMA {LEXICAL_SCHEMA} FROM {r_ident}") + ";",
                "        EXECUTE " + _quote_literal(f"REVOKE ALL ON ALL TABLES IN SCHEMA {LEXICAL_SCHEMA} FROM {r_ident}") + ";",
                "        EXECUTE " + _quote_literal(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {LEXICAL_SCHEMA} FROM {r_ident}") + ";",
                "        EXECUTE " + _quote_literal(f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {LEXICAL_SCHEMA} FROM {r_ident}") + ";",
                f"        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA {LEXICAL_SCHEMA} REVOKE ALL ON TABLES FROM %I', {owner_name_expr}, {r_lit});",
                f"        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA {LEXICAL_SCHEMA} REVOKE ALL ON SEQUENCES FROM %I', {owner_name_expr}, {r_lit});",
                f"        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA {LEXICAL_SCHEMA} REVOKE ALL ON FUNCTIONS FROM %I', {owner_name_expr}, {r_lit});",
                "    END IF;",
            ]
        )
    if purge_restored_rows:
        for table in LEXICAL_TABLES_DELETE_ORDER:
            qualified = f"{LEXICAL_SCHEMA}.{table}"
            lines.extend(
                [
                    f"    IF to_regclass('{qualified}') IS NOT NULL THEN",
                    f"        EXECUTE 'DELETE FROM {qualified}';",
                    "    END IF;",
                ]
            )
        lines.extend(
            [
                f"    IF to_regclass('{LEXICAL_SCHEMA}.generations') IS NOT NULL THEN",
                "        EXECUTE "
                + _quote_literal(
                    f"UPDATE {LEXICAL_SCHEMA}.generations "
                    f"SET state = 'revoked', revocation_reason = '{RESTORED_INVALIDATION_REASON}', "
                    f"revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP), "
                    f"builder_owner_id = NULL, lease_expires_at = NULL "
                    f"WHERE state IN ('building', 'published', 'invalidated')"
                )
                + ";",
                "    END IF;",
            ]
        )
    lines.append("END IF;")
    return lines


def render_lexical_role_enforcement_sql(*, owner_role: str | None = None) -> str:
    """Render standalone transactional SQL enforcing cloe_lexical custody and role denial."""
    body = "\n    ".join(
        render_lexical_custody_and_restore_plpgsql(
            owner_role=owner_role,
            purge_restored_rows=False,
        )
    )
    return f"BEGIN;\nDO $repomap_lexical$\nBEGIN\n    {body}\nEND\n$repomap_lexical$;\nCOMMIT;\n"


def render_lexical_restore_reconciliation_sql(*, owner_role: str | None = None) -> str:
    """Render standalone transactional SQL enforcing custody, role denial, and restore row purge."""
    body = "\n    ".join(
        render_lexical_custody_and_restore_plpgsql(
            owner_role=owner_role,
            purge_restored_rows=True,
        )
    )
    return f"BEGIN;\nDO $repomap_lexical$\nBEGIN\n    {body}\nEND\n$repomap_lexical$;\nCOMMIT;\n"


def reconcile_restored_graph_lexical_roles(
    plan_or_psql_args: LocalRuntimePlan | Sequence[str],
    database: str | None = None,
    command_runner: CommandRunner | None = None,
    reconciler: object = None,
    *,
    psql_command: str = "psql",
    password: str | None = None,
    purge_restored_rows: bool = True,
) -> None:
    """Invoke the graph database role reconciler or execute direct psql restore reconciliation."""
    if isinstance(plan_or_psql_args, LocalRuntimePlan):
        if database is None or command_runner is None or not callable(reconciler):
            raise TypeError(
                "LocalRuntimePlan reconciliation requires database, command_runner, and callable reconciler"
            )
        reconciler(
            plan_or_psql_args,
            database,
            command_runner,
            purge_restored_lexical=purge_restored_rows,
        )
        return

    sql = (
        render_lexical_restore_reconciliation_sql()
        if purge_restored_rows
        else render_lexical_role_enforcement_sql()
    )
    env = dict(os.environ)
    if password is not None:
        env["PGPASSWORD"] = password
    try:
        subprocess.run(
            [psql_command, "-X", "-v", "ON_ERROR_STOP=1", *plan_or_psql_args],
            input=sql,
            text=True,
            capture_output=True,
            check=True,
            env=env,
        )
    except subprocess.CalledProcessError as error:
        raw_err = (error.stderr or error.stdout or "").strip()
        if "cloe_lexical schema or object custody is not owned by the database owner" in raw_err:
            detail = "cloe_lexical schema or object custody is not owned by the database owner"
        else:
            detail = "psql restore role reconciliation failed"
        raise StorageSchemaError(
            f"failed to reconcile restored cloe_lexical roles: {detail}"
        ) from error


__all__ = [
    "LEXICAL_ALLOWED_RELATIONS",
    "LEXICAL_SCHEMA",
    "LEXICAL_SCHEMA_MARKER",
    "LEXICAL_TABLES_DELETE_ORDER",
    "RESTORED_INVALIDATION_REASON",
    "reconcile_restored_graph_lexical_roles",
    "render_lexical_custody_and_restore_plpgsql",
    "render_lexical_restore_reconciliation_sql",
    "render_lexical_role_enforcement_sql",
]
