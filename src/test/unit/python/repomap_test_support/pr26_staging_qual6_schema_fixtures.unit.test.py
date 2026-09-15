"""Pure regressions for current schema and publication seed SQL."""

from __future__ import annotations

import re
from pathlib import Path

from repomap_test_support.mcp_domain_rows import DOMAIN_ROWS_SQL
from repomap_test_support.publication_fixtures import PublicationFixture
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)


_DDL_ROOT = Path(__file__).resolve().parents[5] / "src/main/resources/rdbms/2026"


def test_domain_rows_seed_uses_current_canonical_edge_identity_columns() -> None:
    """The public MCP seed follows the canonical edge table, not legacy names."""

    match = re.search(
        r"INSERT INTO canonical_edges\((.*?)\)\s*SELECT",
        DOMAIN_ROWS_SQL,
        re.DOTALL,
    )
    assert match is not None
    columns = tuple(part.strip() for part in match.group(1).split(","))
    ddl = (_DDL_ROOT / "06/29-002-core-create_canonical_graph_tables.sql").read_text()
    table = ddl.split("CREATE TABLE canonical_edges (", 1)[1].split("\n);", 1)[0]
    declarations = dict(re.findall(r"^    (\w+) (\w+[^\n]*)", table, re.MULTILINE))
    assert declarations
    assert len(columns) == len(set(columns))
    assert set(columns) <= declarations.keys()
    required = {
        name for name, declaration in declarations.items()
        if "NOT NULL" in declaration and "DEFAULT" not in declaration
    }
    assert required <= set(columns)
    assert "edge_key" not in columns
    assert "source_key" not in columns
    assert "target_key" not in columns


def test_commit_unknown_fixture_seed_satisfies_stage_state_checks() -> None:
    """A manually seeded unknown commit carries all required companion states."""

    sql = PublicationFixture(
        stage_id="stage-schema-fixture",
        job_id="job-schema-fixture",
    ).stage_seed_sql(
        state="commit_unknown",
        merge_status="unknown",
        publication_reconciliation_state="required",
    )

    # This is the seed generator's bounded INSERT grammar, not a SQL parser.
    insert = re.fullmatch(
        r"INSERT INTO ingestion_stages \((.*?)\)\s*VALUES \((.*)\);\s*",
        sql, re.DOTALL,
    )
    assert insert is not None
    columns = [column.strip() for column in insert.group(1).split(",")]
    # JSON literals contain commas; split only outside SQL single quotes.
    values = re.split(r",(?=(?:[^']*'[^']*')*[^']*$)", insert.group(2))
    assert len(columns) == len(values)
    row = dict(zip(columns, (value.strip() for value in values), strict=True))
    ddl = (_DDL_ROOT / "07/14-001-scale1-create_staging_contract.sql").read_text()
    constraint = re.search(
        r"CHECK\s*\(\s*state <> 'commit_unknown'\s*OR\s*\(\s*"
        r"merge_status = '([^']+)'\s*AND\s*"
        r"publication_reconciliation_state IN \(([^)]+)\)\s*\)\s*\)",
        ddl,
    )
    assert constraint is not None, "companion-state DDL changed; re-evaluate the seed contract"
    assert row["state"] == "'commit_unknown'"
    assert row["merge_status"] == repr(constraint.group(1))
    assert row["publication_reconciliation_state"] in {
        value.strip() for value in constraint.group(2).split(",")
    }
    assert "'sg1:job-schema-fixture'" in sql
    assert "'cg1:job-schema-fixture'" in sql
    assert "'eg1:job-schema-fixture'" in sql
    assert "'kg1:job-schema-fixture'" in sql


def test_psql_argument_fixture_contract_excludes_password() -> None:
    """The psql argument adapter leaves credentials to the fixture environment."""

    params = _psycopg_connection_params_from_psql_args(
        ["-h", "fixture-host", "-p", "55433", "-U", "fixture-user", "-d", "fixture-db"]
    )

    assert params == {
        "host": "fixture-host",
        "port": "55433",
        "user": "fixture-user",
        "dbname": "fixture-db",
    }
    assert "password" not in params
