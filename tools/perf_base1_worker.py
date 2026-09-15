"""Fresh-process refresh worker for the PERF-BASE1 campaign."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
import json
from pathlib import Path
import resource
import sys
import time
from typing import overload

import psutil
import psycopg

from repomap_kg.observations.raw import RawObservation
from repomap_kg.observations.spool import ObservationSpool
from repomap_kg.ops.config_records import (
    OpsConfig,
    OpsGraphConfig,
    OpsPostgresConfig,
    OpsRuntimeConfig,
    OpsServerMemoryConfig,
    OpsServiceConfig,
    OpsSourcesConfig,
)
from repomap_kg.ops.refresh import refresh_graph
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    run_staged_full_refresh,
)
from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurementEvent,
    StagingMeasurements,
    StagingOperationEvent,
    StagingPhaseEvent,
)
from repomap_test_support.performance_baseline import (
    close_phase_spans,
    measurement_index,
    reconcile_families,
    reconcile_replays,
    validate_operation_terminals,
)
from perf_base1_reporting import coerce_int
from scale11_profile_workloads import build_workload
from semantic_digest_readback import read_semantic_digest


class _SpoolSequence(Sequence[RawObservation]):
    """Sequence adapter for ObservationSpool disk replay."""

    def __init__(self, spool: ObservationSpool) -> None:
        self._spool = spool

    def __len__(self) -> int:
        return len(self._spool)

    def __iter__(self) -> Iterator[RawObservation]:
        return iter(self._spool)

    @overload
    def __getitem__(self, index: int) -> RawObservation: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[RawObservation]: ...

    def __getitem__(
        self, index: int | slice
    ) -> RawObservation | Sequence[RawObservation]:
        length = len(self._spool)
        if isinstance(index, slice):
            target_indices = range(*index.indices(length))
            if not target_indices:
                return ()
            wanted = set(target_indices)
            max_index = max(target_indices)
            collected: dict[int, RawObservation] = {}
            for i, item in enumerate(self._spool):
                if i in wanted:
                    collected[i] = item
                if i >= max_index:
                    break
            return tuple(collected[i] for i in target_indices)
        if isinstance(index, int):
            target = index + length if index < 0 else index
            if target < 0 or target >= length:
                raise IndexError("spool sequence index out of range")
            for i, item in enumerate(self._spool):
                if i == target:
                    return item
            raise IndexError("spool sequence index out of range")
        raise TypeError(
            f"spool sequence indices must be integers or slices, not {type(index).__name__}"
        )


def run_worker(config_path: Path) -> dict[str, object]:
    config = _read_config(config_path)
    raw_args = config.get("psql_args")
    if not isinstance(raw_args, (list, tuple)):
        raise ValueError("worker config psql_args is invalid")
    if not all(isinstance(arg, str) for arg in raw_args):
        raise ValueError("worker config psql_args must contain strings")
    psql_args: tuple[str, ...] = tuple(raw_args)
    run_id = str(config["run_id"])
    instrumented = bool(config["instrumented"])
    measurement_events: list[StagingMeasurementEvent] = []
    phase_events: list[StagingPhaseEvent] = []
    operation_events: list[StagingOperationEvent] = []
    recorder = (
        StagingMeasurements(
            measurement_events.append, phase_sink=phase_events.append,
            operation_sink=operation_events.append, event_limit=256,
        ) if instrumented else None
    )
    starting_rss = psutil.Process().memory_info().rss
    started_wall = time.monotonic_ns()
    started_cpu = time.process_time_ns()
    if config["workload"] == "source":
        result, observation_count = _run_ops_refresh(
            config, psql_args, run_id, recorder
        )
        source_digest = str(config["source_input_digest"])
    else:
        observations, source_digest = _normalized_observations(config)
        observation_count = len(observations)
        if recorder is None:
            result = _run_refresh(psql_args, observations, run_id, None)
        else:
            with recorder.phase("refresh.total"):
                result = _run_refresh(psql_args, observations, run_id, recorder)
    total_wall = time.monotonic_ns() - started_wall
    total_cpu = time.process_time_ns() - started_cpu
    final_rss = psutil.Process().memory_info().rss
    peak_rss = _peak_rss_bytes()
    params = _psycopg_connection_params_from_psql_args(psql_args)
    conninfo = psycopg.conninfo.make_conninfo(**params)
    with psycopg.connect(conninfo) as connection:
        family_counts, structural_digest = read_semantic_digest(
            connection, result["repository_id"], result["run_id"]
        )
    payload: dict[str, object] = {
        "schema": "repomap-performance-worker-v1",
        "run_id": run_id,
        "instrumented": instrumented,
        "source_input_digest": source_digest,
        "configuration_digest": "perf-base1-fixed-config-v1",
        "extractor_digest": "current-tree-extractors",
        "structural_digest": structural_digest,
        "family_counts": family_counts,
        "publication_state": "published",
        "repository_id": result["repository_id"],
        "publication_run_id": result["run_id"],
        "raw_observations": observation_count,
        "total_wall_ns": total_wall,
        "total_process_cpu_ns": total_cpu,
        "starting_client_rss_bytes": starting_rss,
        "final_client_rss_bytes": final_rss,
        "peak_client_rss_bytes": peak_rss,
        "server_time": "unobserved",
        "subprocess_cpu": "unobserved",
    }
    if recorder is not None:
        payload.update(
            _instrumented_payload(
                measurement_events, phase_events, operation_events
            )
        )
        payload["measurement_sink_failed"] = recorder.failed
        payload["operation_event_count"] = len(operation_events)
        payload["stage_reconciliation"] = "passed"
    _write_json(Path(str(config["result_path"])), payload)
    return payload


def _normalized_observations(
    config: Mapping[str, object],
) -> tuple[tuple[RawObservation, ...], str]:
    workload = build_workload("mixed", coerce_int(config["size"]))
    return workload.observations, f"scale11-mixed-{workload.work_items}"


def _run_ops_refresh(
    config: Mapping[str, object],
    psql_args: tuple[str, ...],
    run_id: str,
    recorder: StagingMeasurements | None,
) -> tuple[dict[str, int], int]:
    root = Path(str(config["source_root"])).resolve()
    params = _psycopg_connection_params_from_psql_args(psql_args)
    graph_id = "perf-base1"
    postgres = OpsPostgresConfig(
        host=str(params["host"]), port=int(params["port"]),
        database=str(params["dbname"]), user=str(params["user"]),
    )
    graph = OpsGraphConfig(
        id=graph_id, name="PERF-BASE1", root_path=str(root),
        root_path_expanded=str(root), repository_name=f"perf-base1-{run_id}",
        privacy="private-ops", enabled=True, mcp_visible=False,
        extractor_profile="default", refresh_policy="manual",
    )
    ops_config = OpsConfig(
        config_path=str(root / ".perf-base1-config"), config_home=None,
        config_files=(), schema_version=1,
        service=OpsServiceConfig("local", "stdio", "warning"),
        postgres=postgres, runtime=OpsRuntimeConfig(), graphs=(graph,),
        server_memory=OpsServerMemoryConfig(False, "", "", "read_only"),
        sources=OpsSourcesConfig(),
    )
    result = refresh_graph(ops_config, graph_id, staging_measurements=recorder)
    if (
        result.result != "success"
        or result.repository_id is None
        or result.run_id is None
        or result.observations is None
    ):
        raise RuntimeError("PERF-BASE1 operations refresh failed")
    return {
        "repository_id": result.repository_id,
        "run_id": result.run_id,
    }, result.observations


def _run_refresh(
    psql_args: tuple[str, ...],
    observations: Sequence[RawObservation],
    run_id: str,
    recorder: StagingMeasurements | None,
) -> dict[str, int]:
    if recorder is None:
        spool = ObservationSpool.from_observations(observations)
    else:
        with recorder.phase("refresh.observation_spool_encode"):
            spool = ObservationSpool.from_observations(observations)
        recorder.record_rows(
            StagingMeasurementCategory.OBSERVATION_SPOOL_ROW_COUNT, len(spool)
        )
        recorder.record_bytes(
            StagingMeasurementCategory.OBSERVATION_SPOOL_LOGICAL_BYTES,
            spool.byte_count,
        )
        recorder.record_bytes(
            StagingMeasurementCategory.OBSERVATION_SPOOL_ALLOCATED_BYTES,
            spool.allocated_byte_count,
        )
    try:
        authority = IngestionAuthority(
            operation_id=OperationId(f"perf-base1-{run_id}"),
            attempt=AttemptNumber(1), execution_mode="direct",
            source_generation="sg1:perf-base1-current",
            config_generation="cg1:perf-base1-current",
            extractor_generation="eg1:perf-base1-current",
            canonicalizer_generation="kg1:perf-base1-current",
        )
        summary = run_staged_full_refresh(
            psql_args, _SpoolSequence(spool),
            repository_name=f"perf-base1-{run_id}",
            root_path=f"perf-base1-root-{run_id}",
            authority=authority, staging_measurements=recorder,
        )
        return {"repository_id": summary.repository_id, "run_id": summary.run_id}
    finally:
        if recorder is None:
            spool.close()
        else:
            with recorder.phase("refresh.observation_spool_cleanup"):
                spool.close()


def _instrumented_payload(
    measurements: Sequence[StagingMeasurementEvent],
    phases: Sequence[StagingPhaseEvent],
    operations: Sequence[StagingOperationEvent],
) -> dict[str, object]:
    spans = close_phase_spans(phases)
    validate_operation_terminals(operations)
    observation_count = next(
        event.value
        for event in measurements
        if event.category is StagingMeasurementCategory.OBSERVATION_SPOOL_ROW_COUNT
    )
    assert isinstance(observation_count, int)
    index = measurement_index(measurements)
    reconcile_replays(index, observation_count)
    families = reconcile_families(index)
    phase_ns = {span.code: span.wall_ns for span in spans}
    phase_cpu_ns = {span.code: span.process_cpu_ns for span in spans}
    family_timings: dict[str, dict[str, object]] = {}
    spool_ns = phase_ns["refresh.observation_spool_encode"] + sum(
        _global_measurement_ns(index, category)
        for category in (
            StagingMeasurementCategory.OBSERVATION_FILE_REPLAY,
            StagingMeasurementCategory.OBSERVATION_CANONICALIZATION_REPLAY,
            StagingMeasurementCategory.OBSERVATION_RAW_REPLAY,
        )
    )
    for family, evidence in families.items():
        preparation = _measurement_ns(
            index, StagingMeasurementCategory.FAMILY_PREPARATION, family
        )
        checksum = _measurement_ns(
            index, StagingMeasurementCategory.CHECKSUM, family
        )
        copy = _measurement_ns(index, StagingMeasurementCategory.COPY, family)
        spool_write = _optional_family_measurement_ns(
            index, StagingMeasurementCategory.FAMILY_SPOOL_WRITE, family
        )
        spool_ns += checksum + (spool_write or 0)
        family_timings[family] = {
            **evidence,
            "materialize_inclusive_ns": preparation,
            "checksum_ns": checksum,
            "private_spool_write_ns": spool_write,
            "copy_fused_client_and_server_ns": copy,
        }
    refresh_span = next(span for span in spans if span.code == "refresh.total")
    pre_final = next(
        span for span in spans if span.code == "staging.pre_final_commit"
    ).finish_ns - refresh_span.start_ns
    return {
        "phase_wall_ns": phase_ns,
        "phase_process_cpu_ns": phase_cpu_ns,
        "families": family_timings,
        "spool_elapsed_ns": spool_ns,
        "pre_final_elapsed_ns": pre_final,
        "measurement_event_count": len(measurements),
        "phase_event_count": len(phases),
    }


def _measurement_ns(
    index: Mapping[tuple[str, str | None], StagingMeasurementEvent],
    category: StagingMeasurementCategory,
    family: str,
) -> int:
    event = index[(category.value, family)]
    if not isinstance(event.value, int):
        raise ValueError("family timing is unavailable")
    return event.value


def _global_measurement_ns(
    index: Mapping[tuple[str, str | None], StagingMeasurementEvent],
    category: StagingMeasurementCategory,
) -> int:
    event = index[(category.value, None)]
    if not isinstance(event.value, int):
        raise ValueError("global timing is unavailable")
    return event.value


def _optional_family_measurement_ns(
    index: Mapping[tuple[str, str | None], StagingMeasurementEvent],
    category: StagingMeasurementCategory,
    family: str,
) -> int | None:
    event = index[(category.value, family)]
    return event.value if isinstance(event.value, int) else None


def _peak_rss_bytes() -> int:
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


def _read_config(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "perf-base1-worker-config-v1":
        raise ValueError("worker config is invalid")
    return payload


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        raise SystemExit("usage: perf_base1_worker.py CONFIG")
    run_worker(Path(arguments[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
