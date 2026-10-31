"""Failure-preserving, non-cascading cleanup helpers for optional SQL test fixtures."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from common_lore_index.storage.psql import run_psql

ENRICHMENT_CLEANUP_SQL = (
    "DROP TABLE IF EXISTS repomap_enrichment.embeddings; "
    "DROP TABLE IF EXISTS repomap_enrichment.rebuilds; "
    "DROP SCHEMA IF EXISTS repomap_enrichment;"
)
VECTOR_CLEANUP_SQL = "DROP EXTENSION IF EXISTS vector; DROP SCHEMA IF EXISTS repomap_vector;"
KNOWN_CLEANUP_STEPS = frozenset(
    {
        "enrichment_schema",
        "vector_schema",
        "optional_schema",
        "fixture_roles",
        "restored_database",
    }
)


def _execute_cleanup_sql(postgres: Any, sql: str) -> None:
    """Execute SQL against a disposable test Postgres handle with ON_ERROR_STOP=1."""
    run_psql(
        [postgres.psql_command, *postgres.psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=sql,
    )


def format_optional_cleanup_diagnostic(step: str, error: BaseException) -> str:
    """Return a bounded cleanup note naming only the allowlisted step and exception type."""
    safe_step = step if step in KNOWN_CLEANUP_STEPS else "unknown_step"
    error_type = type(error).__name__[:80]
    return (
        f"optional SQL fixture cleanup failed: "
        f"step={safe_step}; error_type={error_type}; detail=<redacted>"
    )


def _run_cleanup_steps(
    steps: Sequence[tuple[str, Callable[[], None]]],
    *,
    primary: BaseException | None = None,
) -> None:
    active_primary = primary
    first_failure_step: str | None = None
    for step_name, action in steps:
        try:
            action()
        except BaseException as cleanup_error:
            if isinstance(cleanup_error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                if primary is not None:
                    primary.add_note(format_optional_cleanup_diagnostic(step_name, cleanup_error))
                    return
                if active_primary is not None:
                    cleanup_error.add_note(format_optional_cleanup_diagnostic(
                        first_failure_step or "unknown_step", active_primary,
                    ))
                raise
            if active_primary is None:
                active_primary = cleanup_error
                first_failure_step = step_name
            else:
                active_primary.add_note(
                    format_optional_cleanup_diagnostic(step_name, cleanup_error)
                )
    if primary is None and active_primary is not None:
        raise active_primary


def teardown_optional_schema_without_cascade(
    postgres: Any,
    *,
    reader: str,
    writer: str,
    execute_fn: Callable[[Any, str], None] = _execute_cleanup_sql,
    primary: BaseException | None = None,
) -> None:
    """Drop exact known optional objects without CASCADE across separate schema steps."""
    del reader, writer
    _run_cleanup_steps(
        (
            ("enrichment_schema", lambda: execute_fn(postgres, ENRICHMENT_CLEANUP_SQL)),
            ("vector_schema", lambda: execute_fn(postgres, VECTOR_CLEANUP_SQL)),
        ),
        primary=primary,
    )


def cleanup_optional_sql_fixture(
    postgres: Any,
    *,
    reader: str,
    writer: str,
    extra_roles: Sequence[str] = (),
    execute_fn: Callable[[Any, str], None] = _execute_cleanup_sql,
    schema_teardown_fn: Callable[..., None] | None = None,
    primary: BaseException | None = None,
) -> None:
    """Attempt optional schema and role cleanup best-effort without CASCADE."""
    role_drops = " ".join(
        f"DROP ROLE IF EXISTS {role};" for role in (reader, writer, *extra_roles)
    )
    roles_sql = f"DROP OWNED BY {reader}, {writer}; {role_drops}"
    steps: list[tuple[str, Callable[[], None]]] = []
    if schema_teardown_fn is not None:
        steps.append(
            (
                "optional_schema",
                lambda: schema_teardown_fn(postgres, reader=reader, writer=writer),
            )
        )
    else:
        steps.extend(
            (
                ("enrichment_schema", lambda: execute_fn(postgres, ENRICHMENT_CLEANUP_SQL)),
                ("vector_schema", lambda: execute_fn(postgres, VECTOR_CLEANUP_SQL)),
            )
        )
    steps.append(("fixture_roles", lambda: execute_fn(postgres, roles_sql)))
    _run_cleanup_steps(steps, primary=primary)


@contextmanager
def optional_sql_fixture_cleanup(
    postgres: Any,
    *,
    reader: str,
    writer: str,
    extra_roles: Sequence[str] = (),
    execute_fn: Callable[[Any, str], None] = _execute_cleanup_sql,
    schema_teardown_fn: Callable[..., None] | None = None,
    canonical_nodes_fn: Callable[[], Sequence[Any]] | None = None,
    expected_canonical_count: int | None = None,
) -> Iterator[None]:
    """Preserve primary body exceptions across optional SQL fixture cleanup."""
    primary: BaseException | None = None
    body_failed = False
    try:
        yield
    except BaseException as exc:
        primary = exc
        body_failed = True
        raise
    finally:
        before_nodes: tuple[Any, ...] = ()
        if primary is None and canonical_nodes_fn is not None:
            try:
                before_nodes = tuple(canonical_nodes_fn())
            except BaseException as exc:
                primary = exc
        cleanup_optional_sql_fixture(
            postgres,
            reader=reader,
            writer=writer,
            extra_roles=extra_roles,
            execute_fn=execute_fn,
            schema_teardown_fn=schema_teardown_fn,
            primary=primary,
        )
        if primary is not None:
            if not body_failed:
                raise primary
        elif canonical_nodes_fn is not None:
            after_nodes = tuple(canonical_nodes_fn())
            assert after_nodes == before_nodes
            if expected_canonical_count is not None:
                assert len(after_nodes) == expected_canonical_count


@contextmanager
def optional_database_cleanup(
    postgres: Any,
    *,
    database_name: str,
    execute_fn: Callable[[Any, str], None] = _execute_cleanup_sql,
) -> Iterator[None]:
    """Drop a second disposable database while preserving any primary body failure."""
    primary: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        primary = exc
        raise
    finally:
        _run_cleanup_steps(
            (
                (
                    "restored_database",
                    lambda: execute_fn(postgres, f"DROP DATABASE IF EXISTS {database_name};"),
                ),
            ),
            primary=primary,
        )
