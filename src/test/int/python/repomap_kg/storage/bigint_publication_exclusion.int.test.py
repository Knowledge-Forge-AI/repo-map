"""Real final publication and admission over the PostgreSQL BIGINT boundary."""

from __future__ import annotations

from dataclasses import replace

import psycopg
from psycopg.conninfo import make_conninfo
import pytest

from common_lore_index.runtime.database_roles import (
    READ_STATUS_ROLE,
    REFRESH_PUBLICATION_ROLE,
    RoleSecrets,
    render_database_role_sql,
)
from common_lore_index.storage import apply_migrations, default_rdbms_root
from common_lore_index.storage._staged_ingestion_stages import _ensure_repository
from common_lore_index.storage._repository_publication_lock import acquire_publication_lock
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.publication_readback import read_run_publication
from common_lore_index.storage.readback_driver import _psycopg_connection_params_from_psql_args
from common_lore_index.storage.sql_load import repository_run_prefix_sql
from common_lore_index.storage.staged_publication import execute_final_transaction
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.publication_fixtures import PublicationFixture


@pytest.fixture
def database():
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        yield postgres


def _connection(postgres):
    return psycopg.connect(make_conninfo(**_psycopg_connection_params_from_psql_args(postgres.psql_args)))


def _seed(postgres, repository_id, run_id):
    fix = PublicationFixture(
        stage_id=f"stage-bigint-{run_id}", job_id=f"job-bigint-{run_id}",
        repository_id=repository_id, run_id=run_id,
    )
    postgres.psql_scalar(
        fix.repository_seed_sql(root_path=f"root-{repository_id}")
        + fix.run_seed_sql() + fix.stage_seed_sql(files=1)
        + fix.stage_files_seed_sql(path=f"source-{run_id}.py")
    )
    return fix


def _handoff(postgres, fix, mode):
    handoff = fix.handoff
    if mode == "direct":
        postgres.psql_scalar(
            "UPDATE ingestion_stages SET execution_mode='direct', job_id=NULL, "
            "coordinator_instance_id=NULL, singleton_fencing_epoch=0, graph_lease_fencing_epoch=0 "
            f"WHERE stage_id='stage-bigint-{fix.run_id}';"
        )
        owner = replace(
            handoff.merge.owner, execution_mode="direct", job_id=None,
            coordinator_instance_id=None, singleton_fencing_epoch=0, graph_lease_fencing_epoch=0,
        )
        handoff = replace(handoff, merge=replace(handoff.merge, owner=owner))
    return handoff.validate()


def _receipt(postgres, fix):
    return read_run_publication(
        postgres.psql_args, job_id=fix.job_id, attempt=fix.attempt,
        psql_command=postgres.psql_command,
    )


@pytest.mark.parametrize("repository_id", [1, 2**31])
@pytest.mark.parametrize("first_mode", ["direct", "coordinator"])
def test_cross_mode_exclusion_distinct_identity_and_rollback_release(database, repository_id, first_mode):
    first = _seed(database, repository_id, 1)
    second = _seed(database, repository_id, 2)
    distinct = _seed(database, 2**63 - 1, 3)
    first_handoff = _handoff(database, first, first_mode)
    second_handoff = _handoff(database, second, "coordinator" if first_mode == "direct" else "direct")
    with _connection(database) as holder, _connection(database) as contender:
        execute_final_transaction(holder, first_handoff)
        with pytest.raises(StorageSchemaError, match="^graph publication already active$"):
            execute_final_transaction(contender, second_handoff)
        contender.rollback()
        assert contender.execute("SELECT status FROM runs WHERE id=2").fetchone() == ("running",)
        assert contender.execute("SELECT state FROM ingestion_stages WHERE stage_id=%s", (second.stage_id,)).fetchone() == ("validated",)
        contender.rollback()
        execute_final_transaction(contender, distinct.handoff)
        contender.commit()
        assert _receipt(database, distinct) is not None
        holder.rollback()
        assert _receipt(database, first) is None
        execute_final_transaction(contender, second_handoff)
        contender.commit()
        assert _receipt(database, second) is not None
        assert contender.execute("SELECT path FROM files WHERE repository_id=%s", (repository_id,)).fetchall() == [("source-2.py",)]
        assert contender.execute("SELECT status FROM runs WHERE id=1").fetchone() == ("running",)


def test_maximum_bigint_full_publication_under_generated_refresh_role(database):
    fix = _seed(database, 2**63 - 1, 1)
    secrets = RoleSecrets("fixture-read", "fixture-refresh", "fixture-control")
    with _connection(database) as admin:
        admin.execute(render_database_role_sql(
            database=database.database, owner_role=database.user,
            database_kind="graph", secrets=secrets,
        ))
        admin.commit()
    params = _psycopg_connection_params_from_psql_args(database.psql_args)
    with psycopg.connect(make_conninfo(**{
        **params, "user": REFRESH_PUBLICATION_ROLE, "password": secrets.refresh_publication,
    })) as publisher:
        execute_final_transaction(publisher, fix.handoff)
        publisher.commit()
        assert publisher.execute("SELECT status, publication_job_id FROM runs WHERE id=1").fetchone() == ("complete", fix.job_id)
        assert publisher.execute("SELECT state, merge_status FROM ingestion_stages WHERE stage_id=%s", (fix.stage_id,)).fetchone() == ("published", "committed")
        assert publisher.execute("SELECT last_run_id FROM graph_publication_authority WHERE repository_id=%s", (fix.repository_id,)).fetchone() == (1,)
        assert publisher.execute("SELECT path FROM files WHERE repository_id=%s", (fix.repository_id,)).fetchall() == [("source-1.py",)]
    record = _receipt(database, fix)
    assert record is not None and record.run_id == 1 and record.receipt == fix.receipt
    with psycopg.connect(make_conninfo(**{
        **params, "user": READ_STATUS_ROLE, "password": secrets.read_status,
    })) as reader:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as denied:
            execute_final_transaction(reader, fix.handoff)
        assert denied.value.sqlstate == "42501"
        reader.rollback()
        assert reader.execute("SELECT status FROM runs WHERE id=1").fetchone() == ("complete",)
    with _connection(database) as next_owner:
        assert next_owner.execute("SELECT TRUE FROM repositories WHERE id=%s FOR NO KEY UPDATE NOWAIT", (fix.repository_id,)).fetchone() == (True,)


def test_final_publication_coexists_with_foreign_key_key_share(database):
    fix = _seed(database, 2**31, 1)
    with _connection(database) as foreign_key, _connection(database) as publisher:
        assert foreign_key.execute("SELECT id FROM repositories WHERE id=%s FOR KEY SHARE", (fix.repository_id,)).fetchone() == (fix.repository_id,)
        execute_final_transaction(publisher, fix.handoff)
        publisher.commit()
        assert _receipt(database, fix) is not None


def test_missing_repository_is_not_success_or_contention(database):
    with _connection(database) as connection:
        with pytest.raises(StorageSchemaError, match="staged repository identity was not returned"):
            acquire_publication_lock(connection, 2**63 - 1, legacy_class=19042)
        assert connection.execute("SELECT count(*) FROM repositories").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM runs").fetchone() == (0,)


def test_repeatable_read_serialization_failure_preserves_driver_error(database):
    fix = _seed(database, 2**31, 1)
    with _connection(database) as publisher, _connection(database) as updater:
        publisher.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        assert publisher.execute("SELECT name FROM repositories WHERE id=%s", (fix.repository_id,)).fetchone() == ("fixture",)
        updater.execute("UPDATE repositories SET name='updated-fixture' WHERE id=%s", (fix.repository_id,))
        updater.commit()
        with pytest.raises(psycopg.errors.SerializationFailure) as caught:
            execute_final_transaction(publisher, fix.handoff)
        assert caught.value.sqlstate == "40001"
        publisher.rollback()
        assert publisher.execute("SELECT state FROM ingestion_stages WHERE stage_id=%s", (fix.stage_id,)).fetchone() == ("validated",)
        assert _receipt(database, fix) is None


def test_existing_table_lock_timeout_keeps_conservative_busy_category(database):
    fix = _seed(database, 2**31, 1)
    with _connection(database) as maintenance, _connection(database) as publisher:
        maintenance.execute("LOCK TABLE repositories IN EXCLUSIVE MODE")
        publisher.execute("SET LOCAL lock_timeout='50ms'")
        with pytest.raises(StorageSchemaError, match="^graph publication already active$"):
            execute_final_transaction(publisher, fix.handoff)
        publisher.rollback()
        maintenance.rollback()
        execute_final_transaction(publisher, fix.handoff)
        publisher.commit()
        assert _receipt(database, fix) is not None


@pytest.mark.parametrize("identity", [None, "repo1:bigint-fixture"])
def test_actual_admission_writers_refuse_busy_high_row_and_preserve_upsert(database, identity):
    fix = _seed(database, 2**31, 1)
    root = f"root-{fix.repository_id}"
    with _connection(database) as setup:
        setup.execute("UPDATE repositories SET repository_identity=%s WHERE id=%s", (identity, fix.repository_id))
    prefix = repository_run_prefix_sql(
        repository_name="renamed-fixture", root_path=root, git_commit=None,
        run_status="running", repository_identity=identity,
    )
    guard = next(sql for sql in prefix if sql.startswith("DO "))
    upsert = next(sql for sql in prefix if sql.startswith("INSERT INTO repositories"))
    with _connection(database) as holder, _connection(database) as contender:
        execute_final_transaction(holder, fix.handoff)
        with pytest.raises(StorageSchemaError, match="^graph publication already active$"):
            _ensure_repository(contender, "renamed-fixture", root, identity)
        contender.rollback()
        with pytest.raises(psycopg.errors.LockNotAvailable, match="graph publication already active"):
            contender.execute(guard)
        contender.rollback()
        assert contender.execute("SELECT name FROM repositories WHERE id=%s", (fix.repository_id,)).fetchone() == ("fixture",)
        contender.rollback()
        holder.commit()
        assert _ensure_repository(contender, "staged-fixture", root, identity) == fix.repository_id
        contender.commit()
        contender.execute(guard)
        assert contender.execute(upsert).fetchone() == (fix.repository_id,)
        contender.commit()
        assert contender.execute("SELECT name FROM repositories WHERE id=%s", (fix.repository_id,)).fetchone() == ("renamed-fixture",)
        assert _receipt(database, fix) is not None


def test_literal_guard_keeps_quote_and_dollar_delimiters_as_root_data(database):
    root = "fixture'$publication_admission$; SELECT 1; --"
    with _connection(database) as connection:
        connection.execute(
            "INSERT INTO repositories(id,name,root_path) VALUES (%s,%s,%s)",
            (2**31, "fixture", root),
        )
        connection.commit()
        prefix = repository_run_prefix_sql(
            repository_name="fixture", root_path=root, git_commit=None, run_status="running",
        )
        connection.execute(next(sql for sql in prefix if sql.startswith("DO ")))
        assert connection.execute(next(sql for sql in prefix if sql.startswith("INSERT INTO repositories"))).fetchone() == (2**31,)
        assert connection.execute("SELECT root_path FROM repositories WHERE id=%s", (2**31,)).fetchone() == (root,)
        connection.commit()
    # Run the complete real psql prefix as well: the DO guard must not consume
    # or overwrite either of the incumbent repository/run \gset bindings.
    result = database.psql_scalar("\n".join([
        *prefix, "COMMIT;", "SELECT :repo_id::bigint, :run_id::bigint;",
    ]))
    assert result == f"{2**31}|1"
    with _connection(database) as connection:
        assert connection.execute("SELECT repository_id, status FROM runs WHERE id=1").fetchone() == (2**31, "running")
