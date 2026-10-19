"""Unit tests for failure-preserving optional SQL fixture cleanup and redaction."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[6]
for extra_path in (
    REPO_ROOT,
    REPO_ROOT / "src" / "main" / "python",
    REPO_ROOT / "src" / "test" / "support" / "python",
):
    if str(extra_path) not in sys.path:
        sys.path.insert(0, str(extra_path))

from repomap_kg.storage.errors import StorageSchemaError
from repomap_test_support import semantic_candidate_cleanup as cleanup_module
from repomap_test_support.semantic_candidate_restore import (
    ENRICHMENT_CLEANUP_SQL,
    VECTOR_CLEANUP_SQL,
    cleanup_optional_sql_fixture,
    format_optional_cleanup_diagnostic,
    optional_database_cleanup,
    optional_sql_fixture_cleanup,
    teardown_optional_schema_without_cascade,
)


def test_primary_exception_preserved_when_all_cleanup_steps_fail() -> None:
    calls: list[str] = []

    def _failing_execute(_pg: object, sql: str) -> None:
        calls.append(sql)
        raise StorageSchemaError(
            f"DROP SCHEMA repomap_enrichment; failed at /Users/private_op/db.sql password=secret123 sql={sql}"
        )

    canonical_called = False

    def _canonical_nodes() -> tuple[str, ...]:
        nonlocal canonical_called
        canonical_called = True
        return ("node-1", "node-2", "node-3")

    primary = RuntimeError("initiating body assertion failure")
    with pytest.raises(RuntimeError) as exc_info:
        with optional_sql_fixture_cleanup(
            object(),
            reader="r_role",
            writer="w_role",
            extra_roles=("restorer_role",),
            execute_fn=_failing_execute,
            canonical_nodes_fn=_canonical_nodes,
            expected_canonical_count=3,
        ):
            raise primary

    assert exc_info.value is primary
    assert not canonical_called
    assert len(calls) == 3
    assert calls[0] == ENRICHMENT_CLEANUP_SQL
    assert calls[1] == VECTOR_CLEANUP_SQL
    assert "DROP OWNED BY r_role, w_role;" in calls[2]
    assert "DROP ROLE IF EXISTS restorer_role;" in calls[2]
    assert all("CASCADE" not in sql.upper() for sql in calls)

    notes = getattr(primary, "__notes__", [])
    assert len(notes) == 3
    assert "step=enrichment_schema" in notes[0]
    assert "step=vector_schema" in notes[1]
    assert "step=fixture_roles" in notes[2]
    for note in notes:
        assert "StorageSchemaError" in note
        assert "secret123" not in note
        assert "/Users/private_op" not in note
        assert "DROP SCHEMA" not in note


@pytest.mark.parametrize("control_exc_type", [KeyboardInterrupt, SystemExit])
def test_process_control_exceptions_preserve_identity_when_cleanup_fails(
    control_exc_type: type[BaseException],
) -> None:
    calls: list[str] = []

    def _failing_execute(_pg: object, sql: str) -> None:
        calls.append(sql)
        raise StorageSchemaError("cleanup failure during interrupt")

    primary = control_exc_type("operator interrupt")
    with pytest.raises(control_exc_type) as exc_info:
        with optional_sql_fixture_cleanup(
            object(),
            reader="r_role",
            writer="w_role",
            execute_fn=_failing_execute,
        ):
            raise primary

    assert exc_info.value is primary
    assert len(calls) == 3
    notes = getattr(primary, "__notes__", [])
    assert len(notes) == 3


@pytest.mark.parametrize("prior_failure", [False, True])
@pytest.mark.parametrize("control_exc_type", [KeyboardInterrupt, SystemExit])
def test_process_control_exception_raised_inside_cleanup_step_aborts_immediately(
    control_exc_type: type[BaseException],
    prior_failure: bool,
) -> None:
    calls: list[str] = []
    interrupt = control_exc_type("interrupt during cleanup")

    def _interrupting_execute(_pg: object, sql: str) -> None:
        calls.append(sql)
        if prior_failure and sql == ENRICHMENT_CLEANUP_SQL:
            raise StorageSchemaError("first step sql error")
        raise interrupt

    with pytest.raises(control_exc_type) as exc_info:
        with optional_sql_fixture_cleanup(
            object(),
            reader="r_role",
            writer="w_role",
            execute_fn=_interrupting_execute,
        ):
            pass

    assert exc_info.value is interrupt
    assert calls == ([ENRICHMENT_CLEANUP_SQL, VECTOR_CLEANUP_SQL] if prior_failure else [ENRICHMENT_CLEANUP_SQL])
    notes = getattr(interrupt, "__notes__", [])
    assert len(notes) == int(prior_failure)
    if prior_failure:
        assert "step=enrichment_schema" in notes[0]
        assert "error_type=StorageSchemaError" in notes[0]
        assert "first step sql error" not in notes[0]


@pytest.mark.parametrize("control_exc_type", [KeyboardInterrupt, SystemExit])
def test_cleanup_control_signal_preserves_active_body_error_and_stops_sql(
    control_exc_type: type[BaseException],
) -> None:
    primary = RuntimeError("initiating body failure")
    calls: list[str] = []

    def interrupting_execute(_pg: object, sql: str) -> None:
        calls.append(sql)
        raise control_exc_type("cleanup control signal")

    with pytest.raises(BaseException) as observed:
        with optional_sql_fixture_cleanup(
            object(), reader="r_role", writer="w_role", execute_fn=interrupting_execute,
        ):
            raise primary

    assert observed.value is primary
    assert calls == [ENRICHMENT_CLEANUP_SQL]
    notes = getattr(primary, "__notes__", [])
    assert len(notes) == 1
    assert "step=enrichment_schema" in notes[0]
    assert f"error_type={control_exc_type.__name__}" in notes[0]


def test_pre_teardown_canonical_readback_failure_still_executes_cleanup() -> None:
    calls: list[str] = []
    readback_error = StorageSchemaError("pre-teardown canonical readback failed")

    def _execute(_pg: object, sql: str) -> None:
        calls.append(sql)
        if sql == ENRICHMENT_CLEANUP_SQL:
            raise StorageSchemaError("enrichment cleanup also failed")

    with pytest.raises(StorageSchemaError) as exc_info:
        with optional_sql_fixture_cleanup(
            object(),
            reader="r_role",
            writer="w_role",
            execute_fn=_execute,
            canonical_nodes_fn=lambda: (_ for _ in ()).throw(readback_error),
        ):
            pass

    assert exc_info.value is readback_error
    assert len(calls) == 3
    notes = getattr(readback_error, "__notes__", [])
    assert notes == [
        "optional SQL fixture cleanup failed: step=enrichment_schema; error_type=StorageSchemaError; detail=<redacted>"
    ]


def test_cleanup_failure_without_primary_exception_fails_and_attempts_remaining_steps() -> None:
    calls: list[str] = []

    def _execute(_pg: object, sql: str) -> None:
        calls.append(sql)
        if sql == ENRICHMENT_CLEANUP_SQL:
            raise StorageSchemaError("first cleanup failure")
        if "DROP OWNED BY" in sql:
            raise StorageSchemaError("third cleanup failure")

    with pytest.raises(StorageSchemaError, match="first cleanup failure") as exc_info:
        with optional_sql_fixture_cleanup(
            object(),
            reader="r_role",
            writer="w_role",
            execute_fn=_execute,
        ):
            pass

    assert len(calls) == 3
    notes = getattr(exc_info.value, "__notes__", [])
    assert len(notes) == 1
    assert "step=fixture_roles" in notes[0]


def test_success_path_verifies_canonical_node_invariance_and_teardown_steps() -> None:
    calls: list[str] = []
    snapshots = [("n1", "n2", "n3"), ("n1", "n2", "n3")]

    with optional_sql_fixture_cleanup(
        object(),
        reader="r_role",
        writer="w_role",
        execute_fn=lambda _pg, sql: calls.append(sql),
        canonical_nodes_fn=lambda: snapshots.pop(0),
        expected_canonical_count=3,
    ):
        pass

    assert len(calls) == 3
    assert snapshots == []


def test_teardown_optional_schema_without_cascade_attempts_both_schema_steps() -> None:
    calls: list[str] = []

    def _execute(_pg: object, sql: str) -> None:
        calls.append(sql)
        if sql == ENRICHMENT_CLEANUP_SQL:
            raise StorageSchemaError("enrichment drop blocked")

    with pytest.raises(StorageSchemaError, match="enrichment drop blocked"):
        teardown_optional_schema_without_cascade(
            object(), reader="r_role", writer="w_role", execute_fn=_execute
        )

    assert calls == [ENRICHMENT_CLEANUP_SQL, VECTOR_CLEANUP_SQL]


def test_custom_schema_teardown_failure_still_attempts_role_cleanup() -> None:
    role_sql_calls: list[str] = []
    primary = RuntimeError("primary seed or profile failure")

    def _failing_schema_teardown(_pg: object, *, reader: str, writer: str) -> None:
        assert (reader, writer) == ("seed_reader", "seed_writer")
        raise StorageSchemaError("schema teardown failed")

    with pytest.raises(RuntimeError) as exc_info:
        cleanup_optional_sql_fixture(
            object(),
            reader="seed_reader",
            writer="seed_writer",
            execute_fn=lambda _pg, sql: role_sql_calls.append(sql),
            schema_teardown_fn=_failing_schema_teardown,
            primary=primary,
        )
        raise primary

    assert exc_info.value is primary
    assert len(role_sql_calls) == 1
    assert "DROP OWNED BY seed_reader, seed_writer;" in role_sql_calls[0]
    notes = getattr(primary, "__notes__", [])
    assert len(notes) == 1
    assert "step=optional_schema" in notes[0]


def test_optional_database_cleanup_preserves_primary_and_surfaces_standalone_failure() -> None:
    primary = ValueError("restored verification failure")
    with pytest.raises(ValueError) as exc_info:
        with optional_database_cleanup(
            object(),
            database_name="repomap_test_candidates_restored",
            execute_fn=lambda _pg, _sql: (_ for _ in ()).throw(StorageSchemaError("drop db failed")),
        ):
            raise primary
    assert exc_info.value is primary
    assert any("step=restored_database" in note for note in getattr(primary, "__notes__", []))

    with pytest.raises(StorageSchemaError, match="drop db failed"):
        with optional_database_cleanup(
            object(),
            database_name="repomap_test_candidates_restored",
            execute_fn=lambda _pg, _sql: (_ for _ in ()).throw(StorageSchemaError("drop db failed")),
        ):
            pass


def test_format_optional_cleanup_diagnostic_redacts_sql_paths_literals_and_secrets() -> None:
    raw = StorageSchemaError(
        "postgres://admin:topsecret@127.0.0.1:5432/db "
        "PGPASSWORD=my_pw token=tok_123 Bearer bearer_xyz "
        "path=/Users/alice/private/repo/dump.sql "
        "payload='private-node-payload' "
        "DROP SCHEMA repomap_enrichment CASCADE;"
    )
    note = format_optional_cleanup_diagnostic("enrichment_schema", raw)
    assert note == (
        "optional SQL fixture cleanup failed: "
        "step=enrichment_schema; error_type=StorageSchemaError; detail=<redacted>"
    )
    assert format_optional_cleanup_diagnostic("ad_hoc_step", raw) == (
        "optional SQL fixture cleanup failed: "
        "step=unknown_step; error_type=StorageSchemaError; detail=<redacted>"
    )
    for forbidden in (
        "topsecret",
        "my_pw",
        "tok_123",
        "bearer_xyz",
        "/Users/alice",
        "private-node-payload",
        "DROP SCHEMA",
    ):
        assert forbidden not in note


def test_default_executor_uses_the_supported_psql_command_and_input_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], str | None]] = []

    def record(command: list[str], *, input_text: str | None = None) -> None:
        calls.append((command, input_text))

    monkeypatch.setattr(cleanup_module, "run_psql", record)
    postgres = SimpleNamespace(psql_command="fixture-psql", psql_args=["--dbname", "fixture"])
    teardown_optional_schema_without_cascade(postgres, reader="r_role", writer="w_role")

    expected_command = ["fixture-psql", "--dbname", "fixture", "-qAt", "-v", "ON_ERROR_STOP=1"]
    assert calls == [(expected_command, ENRICHMENT_CLEANUP_SQL), (expected_command, VECTOR_CLEANUP_SQL)]


def test_cleanup_diagnostic_never_reads_unstructured_exception_payload() -> None:
    class UnprintableCleanupError(Exception):
        def __str__(self) -> str:
            raise AssertionError("exception payload must not be read")

    note = format_optional_cleanup_diagnostic(
        "enrichment_schema", UnprintableCleanupError("unstructured synthetic payload"),
    )
    assert "error_type=UnprintableCleanupError" in note
    assert "unstructured synthetic payload" not in note
