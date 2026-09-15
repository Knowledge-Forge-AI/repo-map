"""Bounded PERF-BASE1 refresh, spool, PostgreSQL, and query campaign."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psycopg

from perf_base1_reporting import (
    build_campaign_report,
    jsonable,
    median_stages,
    require_equivalent_results,
    require_small_equivalence,
)
from perf_base1_workload import create_representative_source
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.canonical import (
    query_canonical_edge_explanation,
    query_canonical_edge_records,
    query_canonical_neighborhood,
    query_canonical_node_records,
    query_canonical_storage_summary,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_test_support.performance_baseline import (
    QuerySummary,
    QueryWorkload,
    nearest_rank,
)
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.resource_admission import (
    collect_host_signals,
    decide_host_admission,
)
from repomap_test_support.resource_hygiene_policy import (
    GIB,
    HygieneConfig,
    HygieneProfile,
)
from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.test_scratch import (
    ENV_PROJECT,
    ENV_RUN_ROOT,
    ENV_SCRATCH_ROOT,
)

PAIR_ORDER = ((False, True), (True, False), (False, True))
QUERY_WARMUPS = 3
QUERY_ITERATIONS = 20
CAMPAIGN_LIMIT_SECONDS = 4 * 60 * 60


def run_campaign(
    *,
    scratch_root: Path,
    output: Path,
    operator_attested_exclusive: bool = False,
    operator_attested_pressure_degradation: bool = False,
) -> dict[str, object]:
    started = time.monotonic()
    source_root = scratch_root / "workload" / "representative"
    workload = create_representative_source(source_root)
    results_dir = scratch_root / "measurements" / "workers"
    results_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    admissions: list[dict[str, object]] = []
    small: list[dict[str, object]] = []
    overhead_runs: list[dict[str, object]] = []
    representative: list[dict[str, object]] = []

    def admit() -> None:
        _admit(
            admissions,
            operator_attested_exclusive=operator_attested_exclusive,
            operator_attested_pressure_degradation=operator_attested_pressure_degradation,
        )

    with temporary_postgres() as postgres:
        for index, enabled in enumerate((False, True), start=1):
            admit()
            _reset_database(postgres)
            small.append(
                _worker(
                    scratch_root, results_dir, postgres.psql_args,
                    run_id=f"small-{index}", workload="normalized",
                    size=32, instrumented=enabled,
                )
            )
        for pair_index, pair in enumerate(PAIR_ORDER, start=1):
            for arm_index, enabled in enumerate(pair, start=1):
                _deadline(started)
                admit()
                _reset_database(postgres)
                overhead_runs.append(
                    _worker(
                        scratch_root, results_dir, postgres.psql_args,
                        run_id=f"pair-{pair_index}-arm-{arm_index}",
                        workload="normalized", size=2_048, instrumented=enabled,
                        timeout_seconds=_remaining_seconds(started),
                    )
                )
        for index in range(1, 4):
            _deadline(started)
            admit()
            _reset_database(postgres)
            representative.append(
                _worker(
                    scratch_root, results_dir, postgres.psql_args,
                    run_id=f"representative-{index}", workload="source",
                    source_root=source_root,
                    source_input_digest=str(workload["source_input_digest"]),
                    instrumented=True,
                    timeout_seconds=_remaining_seconds(started),
                )
            )
        _require_small_equivalence(small)
        queries, connection = _query_campaign(
            postgres.psql_args,
            root_path=str(source_root.resolve()),
            psql_command=postgres.psql_command,
        )
    report = _report(
        workload=workload,
        admissions=admissions,
        small=small,
        overhead_runs=overhead_runs,
        representative=representative,
        queries=queries,
        connection=connection,
        elapsed_seconds=time.monotonic() - started,
    )
    output.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    output.chmod(0o600)
    return report


def _worker(
    scratch_root: Path,
    results_dir: Path,
    psql_args: Sequence[str],
    *,
    run_id: str,
    workload: str,
    instrumented: bool,
    size: int | None = None,
    source_root: Path | None = None,
    source_input_digest: str | None = None,
    timeout_seconds: int = 45 * 60,
) -> dict[str, object]:
    config_path = results_dir / f"{run_id}.config.json"
    result_path = results_dir / f"{run_id}.result.json"
    config = {
        "schema": "perf-base1-worker-config-v1",
        "psql_args": list(psql_args),
        "run_id": run_id,
        "workload": workload,
        "instrumented": instrumented,
        "size": size,
        "source_root": None if source_root is None else str(source_root),
        "source_input_digest": source_input_digest,
        "result_path": str(result_path),
    }
    config_path.write_text(json.dumps(config, sort_keys=True) + "\n", encoding="utf-8")
    config_path.chmod(0o600)
    environment = os.environ.copy()
    environment.update(
        {
            "TMPDIR": str(scratch_root / "tmp"),
            "PYTHONPYCACHEPREFIX": str(scratch_root / "pycache"),
            "REPOMAP_STORAGE_PG_CONNECTOR": "psycopg",
            "REPOMAP_STORAGE_READBACK_DRIVER": "psycopg",
        }
    )
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("perf_base1_worker.py")), str(config_path)],
        check=False, capture_output=True, text=True, timeout=timeout_seconds, env=environment,
    )
    if result.returncode != 0 or not result_path.is_file():
        raise RuntimeError("PERF-BASE1 worker failed")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    if payload.get("measurement_sink_failed") is True:
        raise RuntimeError("PERF-BASE1 measurement sink failed")
    return payload


def _reset_database(postgres) -> None:
    params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
    conninfo = psycopg.conninfo.make_conninfo(**params)
    with psycopg.connect(conninfo, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    apply_migrations(
        default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command,
    )


def _admit(
    retained: list[dict[str, object]],
    *,
    operator_attested_exclusive: bool,
    operator_attested_pressure_degradation: bool,
) -> None:
    authority_root = Path(os.environ[ENV_SCRATCH_ROOT]).resolve()
    run_root = Path(os.environ[ENV_RUN_ROOT]).resolve()
    project = os.environ[ENV_PROJECT]
    if run_root.parent.parent != authority_root or not run_root.name:
        raise RuntimeError("PERF-BASE1 scratch authority is invalid")
    index = AdvisoryIndex.open(authority_root / ".index" / project, scratch_root=authority_root)
    admitted = index.records_path / f"{run_root.name}.admitted.json"
    closed = index.records_path / f"{run_root.name}.closed.json"
    if admitted.is_symlink() or not admitted.is_file() or closed.exists():
        raise RuntimeError("PERF-BASE1 current-run admission is unproved")
    bound = index.reconcile()
    config = HygieneConfig(requested_profile=HygieneProfile.HEAVY)
    signals = collect_host_signals(
        authority_root,
        profile=HygieneProfile.HEAVY,
        live_run_count=lambda: max(0, bound.active_runs - 1),
        operator_attested_exclusive=operator_attested_exclusive,
        operator_attested_pressure_degradation=operator_attested_pressure_degradation,
        declared_complete_gates=0,
    )
    decision = decide_host_admission(HygieneProfile.HEAVY, config, signals)
    prospective = bound.allocated_bytes + 32 * GIB
    if not decision.admitted or prospective > config.hard_watermark_bytes:
        raise RuntimeError("PERF-BASE1 host admission refused")
    retained.append(
        {
            "memory_pressure": signals.memory_pressure.value,
            "memory_free_percent": signals.memory_free_percent,
            "free_disk_bytes": signals.free_disk_bytes,
            "free_disk_percent": signals.free_disk_percent,
            "docker_responsive": signals.docker_responsive,
            "live_mutating_runs": signals.live_mutating_runs,
            "declared_complete_gates": signals.declared_complete_gates,
            "prospective_scratch_bytes": prospective,
            "decision": decision.outcome,
            "degraded_signals": list(decision.degraded_signals),
        }
    )


def _query_campaign(psql_args: Sequence[str], *, root_path: str, psql_command: str):
    nodes = query_canonical_node_records(
        psql_args, root_path=root_path, limit=2, psql_command=psql_command
    )
    edges = query_canonical_edge_records(
        psql_args, root_path=root_path, limit=1, psql_command=psql_command
    )
    if not nodes or not edges:
        raise RuntimeError("PERF-BASE1 query seed is unavailable")
    node, edge = nodes[0], edges[0]
    workloads: tuple[tuple[QueryWorkload, Callable[[], object]], ...] = (
        (
            QueryWorkload.EXACT_CANONICAL_LOOKUP,
            lambda: query_canonical_node_records(
                psql_args, root_path=root_path, canonical_key=node.canonical_key, psql_command=psql_command,
            ),
        ),
        (
            QueryWorkload.PATH_PREFIX_LOOKUP,
            lambda: query_canonical_node_records(
                psql_args, root_path=root_path, path_prefix="python/", limit=50, psql_command=psql_command,
            ),
        ),
        (
            QueryWorkload.ONE_HOP_NEIGHBORHOOD,
            lambda: query_canonical_neighborhood(
                psql_args, root_path=root_path, node=node.canonical_key, depth=1, psql_command=psql_command,
            ),
        ),
        (
            QueryWorkload.DOCUMENT_EVIDENCE_LOOKUP,
            lambda: query_canonical_edge_explanation(
                psql_args, root_path=root_path, source_key=edge.source_key, kind=edge.edge_kind,
                target_key=edge.target_key, identity_metadata_hash=edge.identity_metadata_hash,
                evidence_limit=50, psql_command=psql_command,
            ),
        ),
        (
            QueryWorkload.STORAGE_SUMMARY_SERIALIZATION,
            lambda: query_canonical_storage_summary(
                psql_args, root_path=root_path, psql_command=psql_command,
            ),
        ),
    )
    summaries = [_measure_query(code, operation) for code, operation in workloads]
    connection_samples = _connection_samples(psql_args)
    return summaries, connection_samples


def _measure_query(
    code: QueryWorkload, operation: Callable[[], object]
) -> dict[str, object]:
    for _ in range(QUERY_WARMUPS):
        operation()
    samples: list[int] = []
    result = None
    cpu_started = time.process_time_ns()
    for _ in range(QUERY_ITERATIONS):
        started = time.monotonic_ns()
        result = operation()
        samples.append(time.monotonic_ns() - started)
    cpu = time.process_time_ns() - cpu_started
    rendered = json.dumps(_jsonable(result), sort_keys=True, default=str).encode("utf-8")
    cardinality = len(result) if isinstance(result, (tuple, list)) else 1
    return QuerySummary(
        code, QUERY_WARMUPS, tuple(samples), cardinality, len(rendered), cpu
    ).to_public_payload()


def _connection_samples(psql_args: Sequence[str]) -> dict[str, object]:
    params = _psycopg_connection_params_from_psql_args(psql_args)
    conninfo = psycopg.conninfo.make_conninfo(**params)
    samples: list[int] = []
    for _ in range(QUERY_WARMUPS):
        with psycopg.connect(conninfo):
            pass
    for _ in range(QUERY_ITERATIONS):
        started = time.monotonic_ns()
        with psycopg.connect(conninfo):
            pass
        samples.append(time.monotonic_ns() - started)
    return {
        "warmup_iterations": QUERY_WARMUPS,
        "measured_iterations": QUERY_ITERATIONS,
        "p50_wall_ns": nearest_rank(samples, 50),
        "p95_wall_ns": nearest_rank(samples, 95),
        "maximum_wall_ns": max(samples),
        "server_time": "unobserved",
    }


def _deadline(started: float) -> None:
    if time.monotonic() - started > CAMPAIGN_LIMIT_SECONDS:
        raise RuntimeError("PERF-BASE1 campaign time bound exceeded")


def _remaining_seconds(started: float) -> int:
    remaining = int(CAMPAIGN_LIMIT_SECONDS - (time.monotonic() - started))
    if remaining < 1:
        raise RuntimeError("PERF-BASE1 campaign time bound exceeded")
    return min(45 * 60, remaining)


_report = build_campaign_report
_jsonable = jsonable
_median_stages = median_stages
_require_small_equivalence = require_small_equivalence
_require_equivalent_results = require_equivalent_results

__all__ = (
    "CAMPAIGN_LIMIT_SECONDS",
    "PAIR_ORDER",
    "QUERY_ITERATIONS",
    "QUERY_WARMUPS",
    "_jsonable",
    "_median_stages",
    "_report",
    "_require_equivalent_results",
    "_require_small_equivalence",
    "main",
    "run_campaign",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--operator-attested-exclusive", action="store_true")
    parser.add_argument(
        "--operator-attested-pressure-degradation", action="store_true"
    )
    args = parser.parse_args(argv)
    run_campaign(
        scratch_root=args.scratch_root,
        output=args.output,
        operator_attested_exclusive=args.operator_attested_exclusive,
        operator_attested_pressure_degradation=args.operator_attested_pressure_degradation,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
