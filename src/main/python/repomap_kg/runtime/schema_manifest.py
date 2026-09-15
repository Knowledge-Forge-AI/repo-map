"""Deterministic PostgreSQL catalog manifest for graph-schema recognition."""

from __future__ import annotations

import re

from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    decode_process_output,
    planned_psql_command,
    run_container_command,
)
from repomap_kg.runtime.local import LocalRuntimePlan


_SAFE_RELATION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_SCHEMA_MANIFEST_TEMPLATE = r"""
WITH manifest(kind, object_key, definition) AS (
    SELECT
        'relation',
        c.relname,
        concat_ws('|', c.relkind, c.relpersistence, obj_description(c.oid, 'pg_class'))
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p', 'S', 'v', 'm')
      AND c.relname NOT IN (__EXCLUDED_RELATIONS__)
    UNION ALL
    SELECT
        'column',
        c.relname || '.' || a.attnum::text || '.' || a.attname,
        concat_ws(
            '|', format_type(a.atttypid, a.atttypmod), a.attnotnull::text,
            a.attidentity, a.attgenerated, pg_get_expr(d.adbin, d.adrelid)
        )
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    JOIN pg_attribute AS a ON a.attrelid = c.oid
    LEFT JOIN pg_attrdef AS d ON d.adrelid = c.oid AND d.adnum = a.attnum
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p', 'v', 'm')
      AND c.relname NOT IN (__EXCLUDED_RELATIONS__)
      AND a.attnum > 0
      AND NOT a.attisdropped
    UNION ALL
    SELECT
        'constraint',
        c.relname || '.' || con.conname,
        concat_ws('|', con.contype, pg_get_constraintdef(con.oid, true))
    FROM pg_constraint AS con
    JOIN pg_class AS c ON c.oid = con.conrelid
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname NOT IN (__EXCLUDED_RELATIONS__)
    UNION ALL
    SELECT
        'index',
        c.relname || '.' || i.relname,
        pg_get_indexdef(i.oid)
    FROM pg_index AS x
    JOIN pg_class AS c ON c.oid = x.indrelid
    JOIN pg_class AS i ON i.oid = x.indexrelid
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname NOT IN (__EXCLUDED_RELATIONS__)
    UNION ALL
    SELECT
        'sequence',
        c.relname,
        concat_ws(
            '|', s.seqtypid::regtype::text, s.seqstart::text, s.seqincrement::text,
            s.seqmax::text, s.seqmin::text, s.seqcache::text, s.seqcycle::text
        )
    FROM pg_sequence AS s
    JOIN pg_class AS c ON c.oid = s.seqrelid
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname NOT IN (__EXCLUDED_RELATIONS__)
    UNION ALL
    SELECT
        'trigger',
        c.relname || '.' || t.tgname,
        pg_get_triggerdef(t.oid, true)
    FROM pg_trigger AS t
    JOIN pg_class AS c ON c.oid = t.tgrelid
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname NOT IN (__EXCLUDED_RELATIONS__)
      AND NOT t.tgisinternal
    UNION ALL
    SELECT
        'function',
        p.oid::regprocedure::text,
        pg_get_functiondef(p.oid)
    FROM pg_proc AS p
    JOIN pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
)
SELECT kind || E'\t'
    || encode(convert_to(object_key, 'UTF8'), 'hex') || E'\t'
    || encode(convert_to(coalesce(definition, ''), 'UTF8'), 'hex')
FROM manifest
ORDER BY kind, object_key, definition
""".strip()


def schema_manifest_sql(*, excluded_relations: tuple[str, ...]) -> str:
    if not excluded_relations or any(
        not _SAFE_RELATION.fullmatch(relation) for relation in excluded_relations
    ):
        raise ValueError("schema manifest exclusions must be safe relation names")
    sql_literals = ", ".join(
        "'" + relation.replace("'", "''") + "'" for relation in excluded_relations
    )
    return _SCHEMA_MANIFEST_TEMPLATE.replace("__EXCLUDED_RELATIONS__", sql_literals)


SCHEMA_MANIFEST_SQL = schema_manifest_sql(
    excluded_relations=("repomap_schema_migrations",)
)


def query_schema_manifest(
    plan: LocalRuntimePlan,
    database: str,
    command_runner: CommandRunner,
) -> tuple[str, ...]:
    result = run_container_command(
        plan,
        planned_psql_command(
            plan,
            database,
            "-X",
            "-A",
            "-t",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            SCHEMA_MANIFEST_SQL,
        ),
        command_runner,
        label="schema manifest",
    )
    return tuple(
        line for line in decode_process_output(result.stdout).splitlines() if line
    )
