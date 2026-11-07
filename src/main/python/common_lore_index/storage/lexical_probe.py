"""PostgreSQL 16 native full-text search and cloe_lexical schema readiness probe."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common_lore_index.storage.lexical_driver import (
    LexicalStorageError,
    execute_fetchone,
)

MINIMUM_POSTGRES_VERSION_NUM = 160000
EXPECTED_SCHEMA_COMMENT = "cloe-lexical-schema:1"
EXPECTED_TEXT_CONFIG = "pg_catalog.simple"
REQUIRED_LEXICAL_TABLES = (
    "generations",
    "authority",
    "documents",
    "chunks",
    "omissions",
)
REQUIRED_GIN_INDEXES = (
    "idx_cloe_lexical_chunks_ranked_gin",
    "idx_cloe_lexical_chunks_phrase_gin",
)

_PROBE_SQL = """
SELECT
    current_setting('server_version_num')::integer AS server_version_num,
    to_regnamespace('cloe_lexical') IS NOT NULL AS schema_exists,
    COALESCE(obj_description(to_regnamespace('cloe_lexical'), 'pg_namespace'), '') AS schema_comment,
    EXISTS (
        SELECT 1
        FROM pg_ts_config cfg
        JOIN pg_namespace n ON n.oid = cfg.cfgnamespace
        WHERE n.nspname = 'pg_catalog' AND cfg.cfgname = 'simple'
    ) AS has_simple_config,
    (
        SELECT count(*)::integer
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'cloe_lexical'
          AND c.relkind = 'r'
          AND c.relname = ANY(%(tables)s)
    ) AS table_count,
    (
        SELECT count(*)::integer
        FROM pg_index x
        JOIN pg_class i ON i.oid = x.indexrelid
        JOIN pg_namespace n ON n.oid = i.relnamespace
        JOIN pg_am am ON am.oid = i.relam
        WHERE n.nspname = 'cloe_lexical'
          AND am.amname = 'gin'
          AND i.relname = ANY(%(gin_indexes)s)
          AND x.indisvalid
    ) AS gin_index_count,
    ts_rank_cd(
        '{0.1, 0.2, 0.4, 1.0}'::real[],
        setweight(to_tsvector('pg_catalog.simple', 'alpha beta'), 'A'),
        websearch_to_tsquery('pg_catalog.simple', 'alpha')
            && phraseto_tsquery('pg_catalog.simple', 'alpha beta'),
        32
    ) > 0.0 AS fts_smoke_ok
"""


@dataclass(frozen=True)
class LexicalRuntimeProbe:
    """Result of probing PostgreSQL 16 core FTS and cloe_lexical schema readiness."""

    ready: bool
    server_version_num: int
    schema_exists: bool
    schema_comment: str
    has_simple_config: bool
    table_count: int
    gin_index_count: int
    fts_smoke_ok: bool
    failure_reason: str | None = None

    def require_ready(self) -> LexicalRuntimeProbe:
        if not self.ready:
            raise LexicalStorageError(
                self.failure_reason or "lexical_schema_unavailable",
                f"cloe_lexical runtime probe failed: {self.failure_reason}",
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "server_version_num": self.server_version_num,
            "schema_exists": self.schema_exists,
            "schema_comment": self.schema_comment,
            "has_simple_config": self.has_simple_config,
            "table_count": self.table_count,
            "gin_index_count": self.gin_index_count,
            "fts_smoke_ok": self.fts_smoke_ok,
            "failure_reason": self.failure_reason,
        }


def probe_lexical_runtime(connection: Any) -> LexicalRuntimeProbe:
    """Probe PostgreSQL 16 FTS primitives and cloe_lexical schema objects."""
    row = execute_fetchone(
        connection,
        _PROBE_SQL,
        {
            "tables": list(REQUIRED_LEXICAL_TABLES),
            "gin_indexes": list(REQUIRED_GIN_INDEXES),
        },
        operation="probe",
    )
    if row is None or len(row) != 7:
        return LexicalRuntimeProbe(
            ready=False,
            server_version_num=0,
            schema_exists=False,
            schema_comment="",
            has_simple_config=False,
            table_count=0,
            gin_index_count=0,
            fts_smoke_ok=False,
            failure_reason="lexical_probe_empty",
        )
    (
        server_version_num,
        schema_exists,
        schema_comment,
        has_simple_config,
        table_count,
        gin_index_count,
        fts_smoke_ok,
    ) = (
        int(row[0]),
        bool(row[1]),
        str(row[2]),
        bool(row[3]),
        int(row[4]),
        int(row[5]),
        bool(row[6]),
    )
    failure: str | None = None
    if server_version_num < MINIMUM_POSTGRES_VERSION_NUM:
        failure = "postgres_version_unsupported"
    elif not has_simple_config or not fts_smoke_ok:
        failure = "postgres_fts_primitives_unavailable"
    elif not schema_exists or schema_comment != EXPECTED_SCHEMA_COMMENT:
        failure = "lexical_schema_missing_or_unrecognized"
    elif table_count != len(REQUIRED_LEXICAL_TABLES):
        failure = "lexical_tables_incomplete"
    elif gin_index_count != len(REQUIRED_GIN_INDEXES):
        failure = "lexical_gin_indexes_incomplete"
    return LexicalRuntimeProbe(
        ready=failure is None,
        server_version_num=server_version_num,
        schema_exists=schema_exists,
        schema_comment=schema_comment,
        has_simple_config=has_simple_config,
        table_count=table_count,
        gin_index_count=gin_index_count,
        fts_smoke_ok=fts_smoke_ok,
        failure_reason=failure,
    )


LexicalCapabilityReport = LexicalRuntimeProbe
probe_lexical_capabilities = probe_lexical_runtime

__all__ = [
    "EXPECTED_SCHEMA_COMMENT",
    "EXPECTED_TEXT_CONFIG",
    "LexicalCapabilityReport",
    "LexicalRuntimeProbe",
    "MINIMUM_POSTGRES_VERSION_NUM",
    "REQUIRED_GIN_INDEXES",
    "REQUIRED_LEXICAL_TABLES",
    "probe_lexical_capabilities",
    "probe_lexical_runtime",
]
