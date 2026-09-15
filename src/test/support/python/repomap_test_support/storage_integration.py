import os
import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from repomap_test_support.source_ingestion_integration import (
    publish_acquisition_summary as publish_acquisition_summary,
)
from repomap_kg.observations.raw import RawObservation

from repomap_kg.storage import (
    query_canonical_edge_explanation,
    query_canonical_edge_records,
    query_canonical_node_records,
)
from repomap_kg.storage.canonical import query_canonical_storage_summary
from repomap_kg.storage.readback_driver import (
    PG_CONNECTOR_ENV,
    READBACK_DRIVER_ENV,
)

_PSYCOPG19_TIMING_FIXTURE_LABEL = "psycopg-adapted-family-parity"

_PSYCOPG19_TIMING_ITERATIONS = 1

_PSYCOPG19_TIMING_RECORD_FIELDS = frozenset(
    {
        "connector",
        "operation",
        "method",
        "elapsed_seconds",
        "iteration",
        "iterations",
        "payload_bytes",
        "runs",
        "files",
        "raw_observations",
        "canonical_nodes",
        "canonical_edges",
        "record_count",
        "file_node_count",
        "edge_kind_count",
        "has_edge",
        "evidence_count",
        "fixture",
    }
)

def _psycopg5_summary_parity_observations() -> list[RawObservation]:
    return [
        RawObservation(
            kind="file",
            source_id="src/app.py",
            path="src/app.py",
            confidence="manual",
            extractor="psycopg5-fixture-discovery",
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
            extractor="psycopg5-fixture-discovery",
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
            extractor="psycopg5-fixture-shell",
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
            extractor="psycopg5-fixture-python",
            extractor_version="0.1.0",
            metadata={"module": "json"},
        ),
    ]

def _psycopg19_collect_connector_timing_records(
    psql_args: list[str],
    *,
    root_path: str,
    psql_command: str,
    postgres,
    iterations: int = _PSYCOPG19_TIMING_ITERATIONS,
) -> tuple[list[dict[str, object]], dict[tuple[str, str], object]]:
    records: list[dict[str, object]] = []
    payloads: dict[tuple[str, str], object] = {}
    _select_psycopg19_timing_connector("psql", postgres=postgres)
    selected_edges = query_canonical_edge_records(
        psql_args,
        root_path=root_path,
        graph_key_version=1,
        psql_command=psql_command,
    )
    if not selected_edges:
        raise AssertionError("expected timing fixture to include canonical edges")
    selected_edge = selected_edges[0]
    operations = (
        (
            "canonical_storage_summary",
            lambda: query_canonical_storage_summary(
                psql_args,
                root_path=root_path,
                psql_command=psql_command,
            ).to_dict(),
        ),
        (
            "canonical_node_records",
            lambda: [
                record.to_dict()
                for record in query_canonical_node_records(
                    psql_args,
                    root_path=root_path,
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
                    root_path=root_path,
                    graph_key_version=1,
                    psql_command=psql_command,
                )
            ],
        ),
        (
            "canonical_edge_explanation",
            lambda: query_canonical_edge_explanation(
                psql_args,
                root_path=root_path,
                source_key=selected_edge.source_key,
                kind=selected_edge.edge_kind,
                target_key=selected_edge.target_key,
                identity_metadata_hash=selected_edge.identity_metadata_hash,
                graph_key_version=selected_edge.graph_key_version,
                psql_command=psql_command,
            ).to_dict(),
        ),
    )

    for iteration in range(1, iterations + 1):
        for connector in ("psql", "psycopg"):
            _select_psycopg19_timing_connector(connector, postgres=postgres)
            for operation, query_payload in operations:
                started_at = time.perf_counter()
                payload = query_payload()
                elapsed_seconds = time.perf_counter() - started_at
                existing_payload = payloads.setdefault((connector, operation), payload)
                if payload != existing_payload:
                    raise AssertionError(
                        f"{connector} {operation} payload changed across iterations"
                    )
                records.append(
                    _psycopg19_timing_record(
                        connector=connector,
                        operation=operation,
                        payload=payload,
                        elapsed_seconds=elapsed_seconds,
                        iteration=iteration,
                        iterations=iterations,
                    )
                )

    return records, payloads

def _select_psycopg19_timing_connector(connector: str, *, postgres) -> None:
    _select_readback_driver_for_postgres(connector, postgres=postgres)

def _select_readback_driver_for_postgres(driver: str, *, postgres) -> None:
    os.environ[READBACK_DRIVER_ENV] = driver
    password = getattr(postgres, "password", None)
    if password is None:
        os.environ.pop("PGPASSWORD", None)
    else:
        os.environ["PGPASSWORD"] = password

def _select_pg_connector_for_postgres(connector: str | None, *, postgres) -> None:
    os.environ.pop(READBACK_DRIVER_ENV, None)
    if connector is None:
        os.environ.pop(PG_CONNECTOR_ENV, None)
    else:
        os.environ[PG_CONNECTOR_ENV] = connector
    password = getattr(postgres, "password", None)
    if password is None:
        os.environ.pop("PGPASSWORD", None)
    else:
        os.environ["PGPASSWORD"] = password

def _psycopg19_timing_record(
    *,
    connector: str,
    operation: str,
    payload: object,
    elapsed_seconds: float,
    iteration: int,
    iterations: int,
) -> dict[str, object]:
    encoded_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    object_payload = payload if isinstance(payload, dict) else {}
    record_payloads = payload if isinstance(payload, list) else []
    edge_kinds = {
        str(record.get("edge_kind"))
        for record in record_payloads
        if isinstance(record, dict) and record.get("edge_kind") is not None
    }
    evidence = object_payload.get("evidence", [])
    return {
        "connector": connector,
        "operation": operation,
        "method": "query_function",
        "elapsed_seconds": elapsed_seconds,
        "iteration": iteration,
        "iterations": iterations,
        "payload_bytes": len(encoded_payload),
        "runs": int(object_payload.get("runs", 0) or 0),
        "files": int(object_payload.get("files", 0) or 0),
        "raw_observations": int(object_payload.get("raw_observations", 0) or 0),
        "canonical_nodes": int(object_payload.get("canonical_nodes", 0) or 0),
        "canonical_edges": int(object_payload.get("canonical_edges", 0) or 0),
        "record_count": len(record_payloads),
        "file_node_count": sum(
            1
            for record in record_payloads
            if isinstance(record, dict) and record.get("kind") == "file"
        ),
        "edge_kind_count": len(edge_kinds),
        "has_edge": object_payload.get("edge") is not None,
        "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
        "fixture": _PSYCOPG19_TIMING_FIXTURE_LABEL,
    }

def _restore_environment_variable(
    name: str,
    was_present: bool,
    value: str | None,
) -> None:
    if was_present:
        if value is None:
            raise AssertionError(f"{name} was present without a string value")
        os.environ[name] = value
    else:
        os.environ.pop(name, None)

def canonicalization_fixture(name: str, filename: str) -> Path:
    return (
        Path(__file__).parents[3]
        / "fixtures"
        / "canonicalization"
        / name
        / filename
    )

def discovery_fixture(name: str) -> Path:
    return Path(__file__).parents[3] / "fixtures" / "discovery" / name

def openapi_fixture(name: str) -> Path:
    return Path(__file__).parents[3] / "fixtures" / "openapi" / name

def terraform_hcl_fixture(name: str) -> Path:
    return Path(__file__).parents[3] / "fixtures" / "terraform_hcl" / name

def python_ecosystem_fixture(name: str) -> Path:
    return Path(__file__).parents[3] / "fixtures" / "python_ecosystem" / name

def python_web_fixture() -> Path:
    return Path(__file__).parents[3] / "fixtures" / "python_web"

def source_fixture(filename: str) -> Path:
    return (
        Path(__file__).parents[3]
        / "fixtures"
        / "source_ingestion"
        / "feed_sources"
        / filename
    )

def archive_source_fixture(filename: str) -> Path:
    return source_ingestion_fixture_root() / "archive_sources" / filename

def warc_source_fixture(filename: str) -> Path:
    return source_ingestion_fixture_root() / "warc_sources" / filename

def copy_warc_fixture_root(parent: Path) -> Path:
    root = parent / "source_ingestion"
    root.mkdir()
    shutil.copytree(
        source_ingestion_fixture_root() / "warc_artifacts",
        root / "warc_artifacts",
    )
    shutil.copytree(
        source_ingestion_fixture_root() / "warc_sources",
        root / "warc_sources",
    )
    return root

def source_ingestion_fixture_root() -> Path:
    return Path(__file__).parents[3] / "fixtures" / "source_ingestion"

def bulk_fixture_root() -> Path:
    return Path(__file__).parents[3] / "fixtures" / "bulk"

def api_fixture_root() -> Path:
    return Path(__file__).parents[3] / "fixtures" / "api"

def github_api_fixture_root() -> Path:
    return Path(__file__).parents[3] / "fixtures" / "github_api"

def fixed_source_clock() -> datetime:
    return datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)

class MockedGitHubRestTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def fetch(self, config, request):
        self.requests.append((config, request))
        return self.responses.pop(0)
