#!/usr/bin/env python3
"""Local-only comparison helper for official PostgreSQL readback connectors."""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path


from compare_pg_connector_report import (
    ConnectorComparisonError as ConnectorComparisonError,
    FIXTURE_LABEL as FIXTURE_LABEL,
    FORBIDDEN_REPORT_FIELDS as FORBIDDEN_REPORT_FIELDS,
    JsonPayload as JsonPayload,
    QueryPayload as QueryPayload,
    _payload_int as _payload_int,
    _rounded as _rounded,
    _validate_report_fields as _validate_report_fields,
    _validate_report_text as _validate_report_text,
    assert_payload_parity as assert_payload_parity,
    elapsed_summary as elapsed_summary,
    emit_report as emit_report,
    format_text_report as format_text_report,
    report_row as report_row,
    safe_context_fields as safe_context_fields,
    serialize_report as serialize_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src" / "main" / "python"
TEST_SUPPORT_ROOT = REPO_ROOT / "src" / "test" / "support" / "python"
for import_root in (SOURCE_ROOT, TEST_SUPPORT_ROOT):
    import_root_text = str(import_root)
    if import_root_text not in sys.path:
        sys.path.insert(0, import_root_text)

from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.direct_publication import (
    publish_observation_generation,
)
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_canonical_edge_explanation,
    query_canonical_edge_records,
    query_canonical_node_records,
    query_canonical_storage_summary,
)
from repomap_kg.storage.readback_driver import (
    PG_CONNECTOR_ENV,
    READBACK_DRIVER_ENV,
)
from repomap_test_support.postgres_harness import (
    DEFAULT_TEST_POSTGRES_PORT,
    DEFAULT_TEST_POSTGRES_RUNTIME,
    temporary_postgres,
)


CONNECTORS = ("psql", "psycopg")
SYNTHETIC_ROOT_PATH = "/tmp/repomap-psycopg-parity"
SYNTHETIC_REPOSITORY_NAME = "psycopg-parity-fixture"


def run_connector_comparison(
    *,
    iterations: int,
    pg_container_port: int,
    pg_container_runtime: str,
) -> tuple[list[dict[str, object]], tuple[str, ...]]:
    if iterations < 1:
        raise ConnectorComparisonError("iterations must be at least 1")

    env_updates = {
        "REPOMAP_TEST_PG_CONTAINER_PORT": str(pg_container_port),
        "REPOMAP_TEST_PG_CONTAINER_RUNTIME": pg_container_runtime,
        PG_CONNECTOR_ENV: None,
        READBACK_DRIVER_ENV: None,
        "PGPASSWORD": None,
    }
    with temporary_environment(env_updates):
        with temporary_postgres() as postgres:
            private_values = _private_values_for_postgres(postgres)
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            publish_observation_generation(
                postgres.psql_args,
                synthetic_observations(),
                repository_name=SYNTHETIC_REPOSITORY_NAME,
                root_path=SYNTHETIC_ROOT_PATH,
                git_commit="psycopg21",
                psql_command=postgres.psql_command,
            )
            operations = comparison_operations(postgres)
            rows = collect_report_rows(
                postgres,
                operations=operations,
                iterations=iterations,
            )
    return rows, private_values


def collect_report_rows(
    postgres: object,
    *,
    operations: Sequence[tuple[str, QueryPayload]],
    iterations: int,
) -> list[dict[str, object]]:
    payloads: dict[tuple[str, str], JsonPayload] = {}
    elapsed: dict[tuple[str, str], list[float]] = {}

    for connector in CONNECTORS:
        _select_connector(connector, postgres=postgres)
        for operation, query_payload in operations:
            timings: list[float] = []
            first_payload: JsonPayload | None = None
            for _iteration in range(1, iterations + 1):
                started_at = time.perf_counter()
                payload = query_payload()
                timings.append(time.perf_counter() - started_at)
                if first_payload is None:
                    first_payload = payload
                elif payload != first_payload:
                    raise ConnectorComparisonError(
                        f"{connector} {operation} payload changed across iterations"
                    )
            if first_payload is None:
                raise ConnectorComparisonError(f"{connector} {operation} did not run")
            payloads[(connector, operation)] = first_payload
            elapsed[(connector, operation)] = timings

    for operation, _query_payload in operations:
        assert_payload_parity(
            operation,
            payloads[("psql", operation)],
            payloads[("psycopg", operation)],
        )

    rows: list[dict[str, object]] = []
    for connector in CONNECTORS:
        for operation, _query_payload in operations:
            rows.append(
                report_row(
                    connector=connector,
                    operation=operation,
                    iterations=iterations,
                    elapsed_seconds=elapsed[(connector, operation)],
                    payload=payloads[(connector, operation)],
                    parity=True,
                )
            )
    return rows


def comparison_operations(postgres: object) -> tuple[tuple[str, QueryPayload], ...]:
    psql_args = list(getattr(postgres, "psql_args"))
    psql_command = str(getattr(postgres, "psql_command"))
    _select_connector("psql", postgres=postgres)
    selected_edges = query_canonical_edge_records(
        psql_args,
        root_path=SYNTHETIC_ROOT_PATH,
        graph_key_version=1,
        psql_command=psql_command,
    )
    if not selected_edges:
        raise ConnectorComparisonError("expected synthetic fixture to include edges")
    selected_edge = selected_edges[0]
    return (
        (
            "canonical_storage_summary",
            lambda: query_canonical_storage_summary(
                psql_args,
                root_path=SYNTHETIC_ROOT_PATH,
                psql_command=psql_command,
            ).to_dict(),
        ),
        (
            "canonical_node_records",
            lambda: [
                record.to_dict()
                for record in query_canonical_node_records(
                    psql_args,
                    root_path=SYNTHETIC_ROOT_PATH,
                    graph_key_version=1,
                    psql_command=psql_command,
                )
            ],
        ),
        (
            "canonical_edge_records",
            lambda: [
                record.to_dict()
                for record in query_canonical_edge_records(
                    psql_args,
                    root_path=SYNTHETIC_ROOT_PATH,
                    graph_key_version=1,
                    psql_command=psql_command,
                )
            ],
        ),
        (
            "canonical_edge_explanation",
            lambda: query_canonical_edge_explanation(
                psql_args,
                root_path=SYNTHETIC_ROOT_PATH,
                source_key=selected_edge.source_key,
                kind=selected_edge.edge_kind,
                target_key=selected_edge.target_key,
                identity_metadata_hash=selected_edge.identity_metadata_hash,
                graph_key_version=selected_edge.graph_key_version,
                psql_command=psql_command,
            ).to_dict(),
        ),
    )


def synthetic_observations() -> tuple[RawObservation, ...]:
    return (
        RawObservation(
            kind="file",
            source_id="src/app.py",
            path="src/app.py",
            confidence="manual",
            extractor="psycopg21-fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "python",
                "role": "source",
                "content_hash": "a" * 64,
                "generated": False,
                "executable": False,
            },
        ),
        RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="manual",
            extractor="psycopg21-fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "markdown",
                "role": "documentation",
                "content_hash": "b" * 64,
                "generated": False,
                "executable": False,
            },
        ),
        RawObservation(
            kind="shell.command",
            source_id="src/app.py#call:python-module",
            path="src/app.py",
            start_line=3,
            end_line=3,
            name="python -m repomap_kg",
            target="tool:python",
            confidence="heuristic",
            extractor="psycopg21-fixture-shell",
            extractor_version="0.1.0",
            metadata={"argv": ["python", "-m", "repomap_kg"]},
        ),
        RawObservation(
            kind="python.import",
            source_id="src/app.py#import:json",
            path="src/app.py",
            start_line=5,
            end_line=5,
            name="json",
            target="module:json",
            confidence="heuristic",
            extractor="psycopg21-fixture-python",
            extractor_version="0.1.0",
            metadata={"module": "json"},
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare official psql and psycopg PostgreSQL JSON readback "
            "connectors using disposable synthetic fixtures."
        )
    )
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument(
        "--pg-container-port",
        type=int,
        default=int(
            os.environ.get(
                "REPOMAP_TEST_PG_CONTAINER_PORT",
                str(DEFAULT_TEST_POSTGRES_PORT),
            )
        ),
    )
    parser.add_argument(
        "--pg-container-runtime",
        default=os.environ.get(
            "REPOMAP_TEST_PG_CONTAINER_RUNTIME",
            DEFAULT_TEST_POSTGRES_RUNTIME,
        ),
        choices=("docker", "podman"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        rows, private_values = run_connector_comparison(
            iterations=args.iterations,
            pg_container_port=args.pg_container_port,
            pg_container_runtime=args.pg_container_runtime,
        )
        report_text = (
            serialize_report(rows, private_values=private_values)
            if args.json
            else format_text_report(rows, private_values=private_values)
        )
        emit_report(report_text, output_path=args.output)
    except ConnectorComparisonError as error:
        print(f"compare_pg_connectors: {error}", file=sys.stderr)
        return 1
    return 0


def _select_connector(connector: str, *, postgres: object) -> None:
    os.environ[READBACK_DRIVER_ENV] = connector
    password = getattr(postgres, "password", None)
    if password is None:
        os.environ.pop("PGPASSWORD", None)
    else:
        os.environ["PGPASSWORD"] = str(password)


@contextmanager
def temporary_environment(updates: Mapping[str, str | None]):
    previous_values = {name: os.environ.get(name) for name in updates}
    previous_presence = {name: name in os.environ for name in updates}
    try:
        for name, value in updates.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, was_present in previous_presence.items():
            if was_present:
                previous_value = previous_values[name]
                if previous_value is None:
                    raise AssertionError(
                        f"{name} was present without a string value"
                    )
                os.environ[name] = previous_value
            else:
                os.environ.pop(name, None)


def _private_values_for_postgres(postgres: object) -> tuple[str, ...]:
    raw_values = [
        SYNTHETIC_ROOT_PATH,
        SYNTHETIC_REPOSITORY_NAME,
        str(getattr(postgres, "socket_dir", "")),
        str(getattr(postgres, "port", "")),
        str(getattr(postgres, "user", "")),
        str(getattr(postgres, "database", "")),
        str(getattr(postgres, "password", "")),
        *[
            str(item)
            for item in getattr(postgres, "psql_args", ())
            if not str(item).startswith("-")
        ],
    ]
    return tuple(value for value in raw_values if value)


if __name__ == "__main__":
    raise SystemExit(main())
