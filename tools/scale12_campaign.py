"""Run the bounded public-safe SCALE12 supervised profiling campaign."""

from __future__ import annotations

import argparse
from collections.abc import Buffer
from dataclasses import replace
import json
from pathlib import Path
import socket
import statistics
import subprocess
import sys
from typing import Mapping, Sequence, SupportsFloat, SupportsIndex


REPO_ROOT = Path(__file__).resolve().parents[1]
for import_root in (
    REPO_ROOT / "src" / "main" / "python",
    REPO_ROOT / "src" / "test" / "support" / "python",
    REPO_ROOT / "tools",
):
    import_root_text = str(import_root)
    if import_root_text not in sys.path:
        sys.path.insert(0, import_root_text)

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.staging_operation_contracts import (
    STAGING_OPERATION_DESCRIPTORS,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from scale11_profile_workloads import PROFILES
from scale11_threshold_evaluator import IncrementalThresholdMonitor
from scale12_event_transport import Scale12EventChannel
from scale12_campaign_summary import summarize_campaign
from scale12_profile_supervisor import (
    Scale12ProfileSupervisor,
    Scale12SupervisionResult,
    start_profile_child,
)
from scale12_resource_sampling import (
    Scale12ResourceSampler,
    directory_size_bytes,
    host_free_bytes,
    read_postmaster_process_id,
    read_process_rss_bytes,
    read_process_tree_rss_bytes,
    threshold_specs,
)


_EXPECTED_PUBLICATION_SEQUENCE = tuple(
    code for code in STAGING_OPERATION_DESCRIPTORS if code != "cleanup.stage"
)
_DELAYED_OPERATIONS = (
    "statistics.canonical_node_evidence",
    "guard.canonical_proposals",
    "merge.files",
    "receipt.finalize",
)


class Scale12CampaignError(RuntimeError):
    """Raised when the bounded campaign cannot prove its accepted contract."""


def summaries_match(
    left: Mapping[str, object] | None,
    right: Mapping[str, object] | None,
) -> bool:
    """Compare semantic profile fields while excluding repetition and timing."""

    if left is None or right is None:
        return False
    ignored = {"repetition", "elapsed_seconds"}
    return {key: value for key, value in left.items() if key not in ignored} == {
        key: value for key, value in right.items() if key not in ignored
    }


def median_overhead_percent(
    instrumented_seconds: Sequence[float],
    uninstrumented_seconds: Sequence[float],
) -> float:
    """Return deterministic median elapsed overhead as a percentage."""

    instrumented = statistics.median(instrumented_seconds)
    uninstrumented = statistics.median(uninstrumented_seconds)
    if uninstrumented <= 0:
        raise Scale12CampaignError("uninstrumented median is invalid")
    return round(((instrumented / uninstrumented) - 1.0) * 100.0, 1)


def _monitor(elapsed_limit_seconds: int) -> IncrementalThresholdMonitor:
    specifications = tuple(
        replace(specification, limit=elapsed_limit_seconds)
        if specification.category == "elapsed_seconds"
        else specification
        for specification in threshold_specs()
    )
    return IncrementalThresholdMonitor(specifications)


def _sampler(process, postgres) -> Scale12ResourceSampler:
    data_root = getattr(postgres, "data", None)
    runtime_root = getattr(postgres, "root", None)
    postmaster_process_id = (
        read_postmaster_process_id(data_root) if data_root is not None else None
    )
    readers = {
        "client_peak_rss_bytes": lambda: read_process_rss_bytes(process.pid),
        "host_free_bytes": lambda: host_free_bytes(Path.cwd()),
    }
    if runtime_root is not None:
        readers["disposable_runtime_growth_bytes"] = (
            lambda: directory_size_bytes(runtime_root)
        )
    if postmaster_process_id is not None:
        readers["owned_postgresql_process_group_rss_bytes"] = (
            lambda: read_process_tree_rss_bytes(postmaster_process_id)
        )
    return Scale12ResourceSampler(readers)


def run_supervised_profile(
    postgres,
    *,
    profile: str,
    work_items: int,
    repetition: int,
    instrumented: bool,
    elapsed_limit_seconds: int = 300,
    delay_operation_code: str | None = None,
    delay_seconds: float | None = None,
) -> Scale12SupervisionResult:
    """Run one current-source child under live operation and resource authority."""

    parent_socket, child_socket = socket.socketpair()
    try:
        try:
            process = start_profile_child(
                sys.executable, postgres.psql_args, profile=profile,
                work_items=work_items, repetition=repetition,
                event_socket=child_socket, instrumented=instrumented,
                delay_operation_code=delay_operation_code,
                delay_seconds=delay_seconds,
            )
        finally:
            child_socket.close()
        supervisor = Scale12ProfileSupervisor(
            process, Scale12EventChannel(parent_socket),
            _sampler(process, postgres), monitor=_monitor(elapsed_limit_seconds),
        )
    except BaseException:
        parent_socket.close()
        raise
    primary_exc: BaseException | None = None
    try:
        return supervisor.run()
    except BaseException as error:
        primary_exc = error
        raise
    finally:
        try:
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                if primary_exc is None:
                    campaign_error = Scale12CampaignError(
                        "profile child did not reach bounded quiescence"
                    )
                    campaign_error.add_note(
                        "role=scale12_profile_child phase=terminal return=timeout wait_failure=timeout"
                    )
                    primary_exc = campaign_error
                    raise campaign_error from None
                else:
                    primary_exc.add_note("wait_failure=timeout")
        finally:
            supervisor.settle(primary_exc=primary_exc)


def _require_completion(result: Scale12SupervisionResult) -> None:
    if result.terminal_category != "completed" or result.child_exit_code != 0:
        raise Scale12CampaignError("profile did not complete")
    if result.signal_count != 0:
        raise Scale12CampaignError("completed profile received a signal")
    if result.threshold_evaluation.primary_stop_category is not None:
        raise Scale12CampaignError("completed profile crossed a resource ceiling")


def _run_payload(
    stage: str,
    result: Scale12SupervisionResult,
) -> dict[str, object]:
    return {
        "stage": stage,
        "terminal_category": result.terminal_category,
        "child_exit_code": result.child_exit_code,
        "signal_count": result.signal_count,
        "crossing_to_signal_seconds": result.crossing_to_signal_seconds,
        "signal_to_child_exit_seconds": result.signal_to_child_exit_seconds,
        "primary_stop_active_operation": result.primary_stop_active_operation,
        "operation_sequence": list(result.operation_sequence),
        "operation_max_duration_seconds": result.operation_max_duration_seconds,
        "threshold_evaluation": result.threshold_evaluation.to_payload(),
        "profile_summary": result.profile_summary,
    }


def _stage_a(postgres) -> tuple[list[dict[str, object]], int]:
    payloads: list[dict[str, object]] = []
    operation_codes: set[str] = set()
    for ordinal, profile in enumerate(PROFILES, start=1):
        instrumented = run_supervised_profile(
            postgres,
            profile=profile,
            work_items=512,
            repetition=ordinal * 10 + 1,
            instrumented=True,
        )
        uninstrumented = run_supervised_profile(
            postgres,
            profile=profile,
            work_items=512,
            repetition=ordinal * 10 + 2,
            instrumented=False,
        )
        _require_completion(instrumented)
        _require_completion(uninstrumented)
        if instrumented.operation_sequence != _EXPECTED_PUBLICATION_SEQUENCE:
            raise Scale12CampaignError("stage A operation sequence changed")
        if not summaries_match(
            instrumented.profile_summary, uninstrumented.profile_summary
        ):
            raise Scale12CampaignError("stage A instrumentation parity failed")
        operation_codes.update(instrumented.operation_sequence)
        payloads.append(_run_payload("A-instrumented", instrumented))
        payloads.append(_run_payload("A-uninstrumented", uninstrumented))
    return payloads, len(operation_codes)


def _stage_b(postgres) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for repetition, operation_code in enumerate(_DELAYED_OPERATIONS, start=101):
        result = run_supervised_profile(
            postgres,
            profile="mixed",
            work_items=32,
            repetition=repetition,
            instrumented=True,
            elapsed_limit_seconds=1,
            delay_operation_code=operation_code,
            delay_seconds=3.0,
        )
        if (
            result.terminal_category != "cancelled"
            or result.signal_count != 1
            or result.primary_stop_active_operation != operation_code
            or result.crossing_to_signal_seconds is None
            or result.crossing_to_signal_seconds > 2.0
        ):
            raise Scale12CampaignError("stage B cancellation attribution failed")
        payloads.append(_run_payload("B-delayed", result))
    return payloads


def _stage_c(postgres) -> list[dict[str, object]]:
    configurations = [(512, 301)]
    configurations.extend((2048, repetition) for repetition in range(311, 314))
    configurations.extend((8192, repetition) for repetition in range(321, 324))
    payloads: list[dict[str, object]] = []
    for work_items, repetition in configurations:
        result = run_supervised_profile(
            postgres,
            profile="mixed",
            work_items=work_items,
            repetition=repetition,
            instrumented=True,
        )
        _require_completion(result)
        if max(result.operation_max_duration_seconds.values(), default=0.0) > 90:
            raise Scale12CampaignError("stage C operation exceeded 90 seconds")
        payloads.append(_run_payload("C-targeted", result))
    return payloads


def _elapsed_seconds(summary: Mapping[str, object]) -> float:
    elapsed = summary["elapsed_seconds"]
    if isinstance(elapsed, (str, Buffer, SupportsFloat, SupportsIndex)):
        return float(elapsed)
    raise TypeError(f"float() argument must be a string or a real number, not '{type(elapsed).__name__}'")


def _stage_d_overhead(postgres) -> tuple[list[dict[str, object]], float]:
    instrumented_results = [
        run_supervised_profile(
            postgres,
            profile="mixed",
            work_items=512,
            repetition=repetition,
            instrumented=True,
        )
        for repetition in range(401, 404)
    ]
    uninstrumented_results = [
        run_supervised_profile(
            postgres,
            profile="mixed",
            work_items=512,
            repetition=repetition,
            instrumented=False,
        )
        for repetition in range(411, 414)
    ]
    for result in (*instrumented_results, *uninstrumented_results):
        _require_completion(result)
    for instrumented, uninstrumented in zip(
        instrumented_results, uninstrumented_results, strict=True
    ):
        if not summaries_match(
            instrumented.profile_summary, uninstrumented.profile_summary
        ):
            raise Scale12CampaignError("stage D semantic parity failed")
    instrumented_seconds = tuple(
        _elapsed_seconds(result.profile_summary)
        for result in instrumented_results
        if result.profile_summary is not None
    )
    uninstrumented_seconds = tuple(
        _elapsed_seconds(result.profile_summary)
        for result in uninstrumented_results
        if result.profile_summary is not None
    )
    overhead = median_overhead_percent(
        instrumented_seconds, uninstrumented_seconds
    )
    if overhead > 20.0:
        raise Scale12CampaignError("instrumentation overhead exceeded 20 percent")
    payloads = [
        _run_payload("D-instrumented", result) for result in instrumented_results
    ]
    payloads.extend(
        _run_payload("D-uninstrumented", result)
        for result in uninstrumented_results
    )
    return payloads, overhead


def run_campaign() -> dict[str, object]:
    """Execute Stages A through D against one disposable PostgreSQL runtime."""

    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        stage_a, operation_code_count = _stage_a(postgres)
        stage_b = _stage_b(postgres)
        stage_c = _stage_c(postgres)
        stage_d, overhead = _stage_d_overhead(postgres)
    return {
        "schema_version": 1,
        "result": "passed",
        "operation_code_count": operation_code_count,
        "instrumentation_median_overhead_percent": overhead,
        "runs": [*stage_a, *stage_b, *stage_c, *stage_d],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the campaign and emit one bounded deterministic JSON result."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", action="store_true")
    arguments = parser.parse_args(argv)
    payload = run_campaign()
    if arguments.summary:
        payload = summarize_campaign(payload)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 1024 * 1024:
        raise Scale12CampaignError("serialized campaign result exceeds 1 MiB")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
