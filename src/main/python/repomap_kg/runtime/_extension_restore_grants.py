"""Canonical optional-capability grant projection, reconciliation and privilege verification for D9-B.

Grants reuse the exact GRANT/REVOKE statements of canonical
``semantic_candidate_import.candidate_schema_sql``; no grant list is duplicated here.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from repomap_kg.runtime._extension_restore_native import run_bounded_ext_command
from repomap_kg.runtime._extension_restore_policy import (
    TrustedOptionalCapabilityContract,
)
from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    decode_process_output,
    planned_psql_command,
    planned_psql_stdin_command,
    quote_sql_identifier,
)
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.database_role_contract import (
    COORDINATOR_CONTROL_ROLE,
    READ_STATUS_ROLE,
    REFRESH_PUBLICATION_ROLE,
)
from repomap_kg.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan
from repomap_kg.storage.semantic_candidate_import import candidate_schema_sql


def _err(code: str, field: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError((LocalRuntimeDiagnostic("error", code, field, message),))


def _lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


CANONICAL_EXTENSION_SCHEMA = "repomap_vector"


ENRICHMENT_SCHEMA = "repomap_enrichment"


_BASELINE_ROLES = (READ_STATUS_ROLE, REFRESH_PUBLICATION_ROLE, COORDINATOR_CONTROL_ROLE)


_PROBE_READER, _PROBE_WRITER = "repomap_projection_reader", "repomap_projection_writer"


def canonical_grant_statements(reader: str, writer: str) -> tuple[str, ...]:
    """Extract the canonical top-level GRANT/REVOKE statements for the configured principals."""
    statements = tuple(
        " ".join(part.split()) + ";"
        for part in candidate_schema_sql(read_principal=reader, enrichment_principal=writer).split(
            ";\n"
        )
        if part.strip().startswith(("GRANT ", "REVOKE "))
    )
    if not any(s.startswith("GRANT INSERT (") for s in statements) or not any(
        " ON public." in s for s in statements
    ):
        raise _err(
            "restore-grant-contract-unavailable",
            ENRICHMENT_SCHEMA,
            "canonical optional grant statements could not be projected",
        )
    return statements


@lru_cache(maxsize=1)
def canonical_grant_projection() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (writer INSERT columns on rebuilds, canonical public read tables) from canonical SQL."""
    joined = " ".join(canonical_grant_statements(_PROBE_READER, _PROBE_WRITER))
    cols = re.search(
        rf"GRANT INSERT \(([^)]*)\) ON {ENRICHMENT_SCHEMA}\.rebuilds TO \"{_PROBE_WRITER}\";",
        joined,
    )
    tables = re.search(
        rf"GRANT SELECT ON ((?:public\.[a-z_]+, )*public\.[a-z_]+) TO \"{_PROBE_READER}\", \"{_PROBE_WRITER}\";",
        joined,
    )
    if cols is None or tables is None:
        raise _err(
            "restore-grant-contract-unavailable",
            ENRICHMENT_SCHEMA,
            "canonical optional grant projection is malformed",
        )
    return tuple(c.strip() for c in cols.group(1).split(",")), tuple(
        t.strip() for t in tables.group(1).split(",")
    )


def _quoted(*roles: str) -> str:
    return ", ".join(quote_sql_identifier(r) for r in roles)


def reconcile_optional_grants(
    plan: LocalRuntimePlan,
    database: str,
    opt: TrustedOptionalCapabilityContract,
    command_runner: CommandRunner,
    *,
    has_enrichment: bool,
) -> None:
    reader, writer = opt.enrichment_reader_role, opt.enrichment_writer_role
    if not reader or not writer:
        raise _err(
            "restore-principal-privilege-invalid",
            database,
            "optional capability requires configured reader and writer principals",
        )
    ext = quote_sql_identifier(opt.extension_schema)
    stmts = [
        "BEGIN;",
        f"REVOKE ALL ON SCHEMA {ext} FROM PUBLIC, {_quoted(*_BASELINE_ROLES)};",
        f"REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA {ext} FROM PUBLIC, {_quoted(*_BASELINE_ROLES)};",
    ]
    if has_enrichment:
        if opt.extension_schema != CANONICAL_EXTENSION_SCHEMA:
            raise _err(
                "restore-grant-contract-unavailable",
                database,
                "canonical optional grants require the repomap_vector extension schema",
            )
        everyone = _quoted(reader, writer, *_BASELINE_ROLES)
        stmts += [
            f"REVOKE ALL ON SCHEMA {ENRICHMENT_SCHEMA} FROM PUBLIC, {_quoted(*_BASELINE_ROLES)};",
            f"REVOKE ALL ON ALL TABLES IN SCHEMA {ENRICHMENT_SCHEMA} FROM PUBLIC, {everyone};",
            f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {ENRICHMENT_SCHEMA} FROM PUBLIC, {everyone};",
            *canonical_grant_statements(reader, writer),
        ]
    else:
        stmts += [
            f"GRANT USAGE ON SCHEMA {ext} TO {_quoted(reader, writer)};",
            f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {ext} TO {_quoted(reader, writer)};",
        ]
    stmts.append("COMMIT;")
    run_bounded_ext_command(
        plan,
        planned_psql_stdin_command(plan, database),
        command_runner,
        field="optional capability grant reconciliation",
        input_bytes="\n".join(stmts).encode("utf-8"),
    )


def _privilege_sql(
    opt: TrustedOptionalCapabilityContract, *, has_enrichment: bool
) -> tuple[str, dict[str, bool]]:
    reader, writer = str(opt.enrichment_reader_role), str(opt.enrichment_writer_role)
    expect: dict[str, bool] = {}
    exprs: list[str] = []

    def add(key: str, expr: str, expected: bool) -> None:
        expect[key] = expected
        exprs.append(f"({_lit(key)}, ({expr})::boolean)")

    for role in (reader, writer):
        add(
            f"{role}:usage:ext",
            f"has_schema_privilege({_lit(role)}, {_lit(opt.extension_schema)}, 'USAGE')",
            True,
        )
        add(
            f"{role}:create:ext",
            f"has_schema_privilege({_lit(role)}, {_lit(opt.extension_schema)}, 'CREATE')",
            False,
        )
        add(
            f"{role}:escalation",
            f"(SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls OR rolinherit FROM pg_roles WHERE rolname = {_lit(role)})",
            False,
        )
        add(
            f"{role}:membership",
            f"EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid IN (m.member, m.roleid) WHERE r.rolname = {_lit(role)})",
            False,
        )
    for role in _BASELINE_ROLES:
        add(
            f"{role}:usage:ext",
            f"coalesce((SELECT has_schema_privilege(r.oid, {_lit(opt.extension_schema)}, 'USAGE') FROM pg_roles r WHERE r.rolname = {_lit(role)}), false)",
            False,
        )
    if has_enrichment:
        insert_cols, read_tables = canonical_grant_projection()
        for role in (reader, writer):
            add(
                f"{role}:create:enrichment",
                f"has_schema_privilege({_lit(role)}, '{ENRICHMENT_SCHEMA}', 'CREATE')",
                False,
            )
            for table in ("rebuilds", "embeddings"):
                qualified = f"{ENRICHMENT_SCHEMA}.{table}"
                add(
                    f"{role}:select:{table}",
                    f"has_table_privilege({_lit(role)}, {_lit(qualified)}, 'SELECT')",
                    True,
                )
                for priv in ("UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    add(
                        f"{role}:{priv.lower()}:{table}",
                        f"has_table_privilege({_lit(role)}, {_lit(qualified)}, '{priv}')",
                        False,
                    )
            for table in read_tables:
                add(
                    f"{role}:select:{table}",
                    f"has_table_privilege({_lit(role)}, {_lit(table)}, 'SELECT')",
                    True,
                )
        add(
            f"{reader}:insert:embeddings",
            f"has_table_privilege({_lit(reader)}, '{ENRICHMENT_SCHEMA}.embeddings', 'INSERT')",
            False,
        )
        add(
            f"{reader}:insert:rebuilds",
            f"has_any_column_privilege({_lit(reader)}, '{ENRICHMENT_SCHEMA}.rebuilds', 'INSERT')",
            False,
        )
        add(
            f"{writer}:insert:embeddings",
            f"has_table_privilege({_lit(writer)}, '{ENRICHMENT_SCHEMA}.embeddings', 'INSERT')",
            True,
        )
        add(
            f"{writer}:insert-table:rebuilds",
            f"has_table_privilege({_lit(writer)}, '{ENRICHMENT_SCHEMA}.rebuilds', 'INSERT')",
            False,
        )
        for col in (*insert_cols, "enrichment_principal"):
            add(
                f"{writer}:insert:rebuilds.{col}",
                f"has_column_privilege({_lit(writer)}, '{ENRICHMENT_SCHEMA}.rebuilds', {_lit(col)}, 'INSERT')",
                col in insert_cols,
            )
        for role in _BASELINE_ROLES:
            add(
                f"{role}:usage:enrichment",
                f"coalesce((SELECT has_schema_privilege(r.oid, '{ENRICHMENT_SCHEMA}', 'USAGE') FROM pg_roles r WHERE r.rolname = {_lit(role)}), false)",
                False,
            )
    return "SELECT json_object_agg(k, v)::text FROM (VALUES " + ", ".join(
        exprs
    ) + ") AS p(k, v);", expect


def verify_optional_privileges(
    plan: LocalRuntimePlan,
    database: str,
    opt: TrustedOptionalCapabilityContract,
    command_runner: CommandRunner,
    *,
    has_enrichment: bool,
) -> None:
    """Require every positive reader/writer privilege and every negative spoof/escalation refusal."""
    sql, expect = _privilege_sql(opt, has_enrichment=has_enrichment)
    raw = run_bounded_ext_command(
        plan,
        planned_psql_command(plan, database, "-X", "-tAc", sql),
        command_runner,
        field="optional capability privilege verification",
    )
    try:
        observed = json.loads(decode_process_output(raw).strip())
    except json.JSONDecodeError as exc:
        raise _err(
            "restore-principal-privilege-invalid",
            database,
            "optional capability privilege verification returned invalid JSON",
        ) from exc
    wrong = sorted(
        k for k, v in expect.items() if not isinstance(observed, dict) or observed.get(k) is not v
    )
    if wrong:
        raise _err(
            "restore-principal-privilege-invalid",
            database,
            f"optional capability privileges differ from the canonical contract: {', '.join(wrong[:8])}",
        )
