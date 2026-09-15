from __future__ import annotations
import psycopg
from repomap_test_support.publication_fixtures import (
    PublicationFixture,
)



def _required_row(cursor: psycopg.Cursor[tuple[object, ...]]) -> tuple[object, ...]:
    row = cursor.fetchone()
    assert row is not None
    return row


def _seed_fixture(postgres, fixture: PublicationFixture, *, files: int = 0, state: str = "validated", merge_status: str | None = None, pub_state: str | None = None, status: str = "running", with_receipt: bool = False, file_path: str | None = None) -> None:
    sql = (
        fixture.repository_seed_sql()
        + fixture.run_seed_sql(status=status, with_receipt=with_receipt)
        + fixture.stage_seed_sql(files=files, state=state, merge_status=merge_status, publication_reconciliation_state=pub_state)
    )
    if file_path:
        sql += fixture.stage_files_seed_sql(path=file_path)
    postgres.psql_scalar(sql)
