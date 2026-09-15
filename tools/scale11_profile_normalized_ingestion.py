"""Profile the accepted seven-family normalized full-refresh pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Callable, Mapping, Sequence, TypedDict


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src" / "main" / "python"
TEST_SUPPORT_ROOT = REPO_ROOT / "src" / "test" / "support" / "python"
TOOL_ROOT = REPO_ROOT / "tools"
for import_root in (SOURCE_ROOT, TEST_SUPPORT_ROOT, TOOL_ROOT):
    import_root_text = str(import_root)
    if import_root_text not in sys.path:
        sys.path.insert(0, import_root_text)

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.row_spool import RowSpool
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    run_staged_full_refresh,
)
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_kg.storage.staging_observability import (
    StagingMeasurementEvent,
    StagingMeasurements,
)
from repomap_kg.storage.staging_operation_events import StagingOperationEvent
from repomap_test_support.postgres_harness import (
    DEFAULT_TEST_POSTGRES_PORT,
    DEFAULT_TEST_POSTGRES_RUNTIME,
    require_postgres_binaries,
    temporary_postgres,
)
from scale11_profile_contracts import (
    FAMILIES,
    FamilyProfile,
    MetricValue,
    ProfileResult,
)
from scale11_profile_analysis import analyze_scaling
from scale11_profile_events import (
    aggregate_metrics,
    boundary_occurrences,
    family_duration,
)
from scale11_profile_readback import read_final_state
from scale11_profile_workloads import (
    MEASURED_SIZE_BANDS,
    PROFILES,
    Scale11Workload,
    build_workload,
)
from scale11_threshold_evaluator import (
    MetricSample,
    MetricSpec,
    evaluate_thresholds,
)


class Scale11ProfilerError(RuntimeError):
    """Raised when profiling cannot prove its bounded result contract."""


class _ExpectedRows(TypedDict):
    row_counts: dict[str, int]
    normalized_bytes: dict[str, int]
    spool_bytes: dict[str, int]
    structural_digest: str


def profile_publication(
    psql_args: Sequence[str],
    workload: Scale11Workload,
    *,
    repetition: int,
    instrumented: bool,
    operation_sink: Callable[[StagingOperationEvent], None] | None = None,
) -> ProfileResult:
    """Profile one direct receipt-bearing publication on disposable storage."""

    repository_scope = (
        f"scale11-public-fixture-{workload.profile}-{workload.work_items}"
    )
    expected = _prepare_expected(workload, repository_scope)
    events: list[StagingMeasurementEvent] = []
    observer = (
        StagingMeasurements(events.append, operation_sink=operation_sink)
        if instrumented or operation_sink is not None
        else None
    )
    operation_key = f"{workload.profile}:{workload.work_items}:{repetition}"
    stage_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"scale11:{operation_key}"))
    authority = IngestionAuthority(
        operation_id=OperationId(
            f"scale11-{workload.profile}-{workload.work_items}-{repetition}"
        ),
        attempt=AttemptNumber(1),
        execution_mode="direct",
        source_generation="sg1:scale11-public-fixture",
        config_generation="cg1:scale11-profile",
        extractor_generation="eg1:scale11-profile",
        canonicalizer_generation="kg1:scale11-profile",
    )
    started = time.perf_counter()
    summary = run_staged_full_refresh(
        psql_args,
        workload.observations,
        repository_name=repository_scope,
        root_path=f"{repository_scope}-root",
        authority=authority,
        stage_id=stage_id,
        staging_measurements=observer,
    )
    elapsed = max(0.0, time.perf_counter() - started)
    final_counts, cleanup_complete = read_final_state(
        psql_args,
        summary.repository_id,
        summary.run_id,
        stage_id,
    )
    if final_counts != expected["row_counts"]:
        mismatched = ",".join(
            family
            for family in FAMILIES
            if final_counts[family] != expected["row_counts"][family]
        )
        raise Scale11ProfilerError(
            f"final seven-family counts differ for: {mismatched}"
        )
    family_profiles = _family_profiles(expected, events, instrumented)
    aggregate_values = aggregate_metrics(events, instrumented)
    threshold_evaluation = _threshold_evaluation(elapsed, aggregate_values)
    return ProfileResult(
        profile=workload.profile,
        size_band=workload.work_items,
        repetition=repetition,
        work_items=workload.work_items,
        observation_count=len(workload.observations),
        elapsed_seconds=elapsed,
        families=family_profiles,
        aggregate_metrics=aggregate_values,
        receipt_complete=summary.publication_receipt is not None,
        generation=summary.run_id,
        structural_digest=expected["structural_digest"],
        cleanup_complete=cleanup_complete,
        threshold_evaluation=threshold_evaluation,
        boundary_occurrences=boundary_occurrences(events, instrumented),
    )


def run_campaign(
    profiles: Sequence[str],
    sizes: Sequence[int],
    repetitions: int,
    *,
    instrumented: bool,
) -> dict[str, object]:
    """Run a bounded sequential campaign in one disposable PostgreSQL runtime."""

    require_postgres_binaries()
    results: list[ProfileResult] = []
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        for profile in profiles:
            for size in sizes:
                workload = build_workload(profile, size)
                for repetition in range(1, repetitions + 1):
                    result = profile_publication(
                        postgres.psql_args,
                        workload,
                        repetition=repetition,
                        instrumented=instrumented,
                    )
                    prior = next(
                        (
                            item
                            for item in results
                            if item.profile == profile
                            and item.size_band == size
                        ),
                        None,
                    )
                    results.append(
                        replace(
                            result,
                            repeat_equal=(
                                None
                                if prior is None
                                else result.structural_digest
                                == prior.structural_digest
                                and tuple(
                                    family.row_count
                                    for family in result.families
                                )
                                == tuple(
                                    family.row_count
                                    for family in prior.families
                                )
                            ),
                        )
                    )
    aggregates = [
        analyze_scaling(
            tuple(result for result in results if result.profile == profile)
        ).to_payload()
        for profile in profiles
    ]
    return {
        "schema_version": 1,
        "instrumented": instrumented,
        "profiles": list(profiles),
        "sizes": list(sizes),
        "repetitions": repetitions,
        "aggregates": aggregates,
    }


def _prepare_expected(
    workload: Scale11Workload,
    repository_scope: str,
) -> _ExpectedRows:
    prepared = build_staged_rows(
        workload.observations,
        repository_name=repository_scope,
        stage_id="00000000-0000-0000-0000-000000000011",
    )
    try:
        row_counts = dict(prepared.row_counts)
        normalized_bytes = dict(prepared.normalized_byte_counts)
        spool_bytes = {
            family: rows.byte_count if isinstance(rows, RowSpool) else 0
            for family, rows in prepared.family_rows.items()
        }
        digest_input = [
            (
                family,
                row_counts[family],
                normalized_bytes[family],
                prepared.checksums[family].stable_key_digest,
                prepared.checksums[family].payload_digest,
            )
            for family in FAMILIES
        ]
        structural_digest = hashlib.sha256(
            json.dumps(digest_input, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "row_counts": row_counts,
            "normalized_bytes": normalized_bytes,
            "spool_bytes": spool_bytes,
            "structural_digest": structural_digest,
        }
    finally:
        prepared.close()


def _family_profiles(
    expected: _ExpectedRows,
    events: Sequence[StagingMeasurementEvent],
    instrumented: bool,
) -> tuple[FamilyProfile, ...]:
    row_counts = expected["row_counts"]
    normalized_bytes = expected["normalized_bytes"]
    spool_bytes = expected["spool_bytes"]
    unavailable_reason = "aggregate_scope" if instrumented else "instrumentation_disabled"
    return tuple(
        FamilyProfile(
            family=family,
            row_count=row_counts[family],
            normalized_bytes=normalized_bytes[family],
            spool_bytes=spool_bytes[family],
            encoded_bytes=MetricValue.unavailable("not_observed"),
            preparation_seconds=family_duration(events, family, "family_preparation", instrumented),
            checksum_seconds=family_duration(events, family, "checksum", instrumented),
            copy_seconds=family_duration(events, family, "copy", instrumented),
            statistics_seconds=MetricValue.unavailable(unavailable_reason),
            completeness_validation_seconds=MetricValue.unavailable(unavailable_reason),
            semantic_guard_seconds=MetricValue.unavailable(unavailable_reason),
            merge_seconds=MetricValue.unavailable(unavailable_reason),
            cleanup_seconds=MetricValue.unavailable(unavailable_reason),
        )
        for family in FAMILIES
    )


def _threshold_evaluation(
    elapsed: float,
    metrics: Mapping[str, MetricValue],
) -> dict[str, object]:
    values = {
        "elapsed_seconds": math.ceil(elapsed),
        "client_memory_bytes": _metric_integer(metrics["client_memory_bytes"]),
        "temporary_byte_upper_bound_bytes": _metric_integer(metrics["temporary_byte_upper_bound_bytes"]),
        "wal_upper_bound_bytes": _metric_integer(metrics["wal_upper_bound_bytes"]),
    }
    result = evaluate_thresholds(
        (
            MetricSpec("elapsed_seconds", 300, 0),
            MetricSpec("client_memory_bytes", 1_073_741_824, 1),
            MetricSpec("temporary_byte_upper_bound_bytes", 4_294_967_296, 2, counter=True),
            MetricSpec("wal_upper_bound_bytes", 8_589_934_592, 3, counter=True),
        ),
        (MetricSample(elapsed, values, ownership_exclusive=False, terminal=True),),
    )
    return result.to_payload()


def _metric_integer(metric: MetricValue) -> int | None:
    return (
        int(metric.value)
        if metric.availability == "available" and metric.value is not None
        else None
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", action="append", choices=PROFILES, dest="profiles")
    parser.add_argument("--size", action="append", type=int, dest="sizes")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--uninstrumented", action="store_true")
    parser.add_argument("--pg-container-port", type=int, default=DEFAULT_TEST_POSTGRES_PORT)
    parser.add_argument("--pg-container-runtime", default=DEFAULT_TEST_POSTGRES_RUNTIME)
    args = parser.parse_args()
    profiles = tuple(args.profiles or ("mixed",))
    sizes = tuple(args.sizes or (MEASURED_SIZE_BANDS[0],))
    if not 1 <= args.repetitions <= 3:
        parser.error("--repetitions must be between 1 and 3")
    os.environ["REPOMAP_TEST_PG_CONTAINER_PORT"] = str(args.pg_container_port)
    os.environ["REPOMAP_TEST_PG_CONTAINER_RUNTIME"] = args.pg_container_runtime
    print(json.dumps(run_campaign(profiles, sizes, args.repetitions, instrumented=not args.uninstrumented), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
