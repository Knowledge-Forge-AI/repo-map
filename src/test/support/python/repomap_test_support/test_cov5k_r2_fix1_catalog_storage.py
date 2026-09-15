"""Storage qualification catalog definitions for FIX1 (Groups D and E)."""

from __future__ import annotations

from repomap_test_support.test_cov5k_r2_fix1_catalog_values import (
    CatalogEntry,
    _BASE_OBSERVATION,
    _TOOL_ROOT,
    _entry,
)


def _group_d() -> tuple[CatalogEntry, ...]:
    entries: list[CatalogEntry] = []
    failures = (
        "success",
        "class_08",
        "unavailable",
        "authentication",
        "semantic_schema",
        "transport_refusal",
    )
    for driver in ("psycopg", "psql"):
        for failure in failures:
            mode = "host_only" if driver == "psycopg" else "host_then_container"
            entries.append(
                _entry(
                    "D",
                    f"D-driver-{driver}",
                    f"D-driver-{driver}-{failure}",
                    f"{_TOOL_ROOT}/scale15_actual_path_readback.py:read_scale15_terminal_state",
                    "runtime_driver_read",
                    (
                        ("driver", driver),
                        ("mode", mode),
                        ("failure_category", failure),
                        ("automatic_fallback", False),
                    ),
                    failure,
                    executor=f"fix1.executor.d.driver.{driver}",
                    observation=_BASE_OBSERVATION
                    + (
                        "driver",
                        "mode",
                        "failure_category",
                        "automatic_fallback",
                    ),
                    process="psycopg_no_fallback_or_explicit_psql",
                )
            )
    process_cases = (
        "current_process",
        "allocated_child",
        "second_allocation",
        "near_exit_process",
        "controlled_process_tree",
        "invalid_pid",
        "no_such_process",
        "access_denied",
        "zombie_process",
        "invalid_rss_value",
        "root_disappearance",
        "child_disappearance",
        "child_denial_or_zombie",
        "pid_reuse_proxy",
    )
    for process_case in process_cases:
        entries.append(
            _entry(
                "D",
                "D-process-rss",
                f"D-process-{process_case}",
                f"{_TOOL_ROOT}/process_rss_monitor.py:ProcessRssMonitor",
                "process_rss",
                (("process_case", process_case),),
                "sampled",
                executor="fix1.executor.d.process",
                observation=_BASE_OBSERVATION
                + ("pid", "rss_bytes", "process_case"),
                process="psutil_process_tree",
            )
        )
    for category in ("success", "unavailable", "transport", "semantic_schema"):
        entries.append(
            _entry(
                "D",
                "D-container-rss",
                f"D-container-{category}",
                f"{_TOOL_ROOT}/scale28_runtime_identity.py:capture_runtime_identity",
                "container_rss",
                (
                    ("category", category),
                    ("stream", False),
                    ("one_shot", True),
                ),
                category,
                executor="fix1.executor.d.container",
                observation=_BASE_OBSERVATION
                + (
                    "container_id",
                    "stream",
                    "one_shot",
                    "field_formula",
                    "sampling_order",
                    "automatic_fallback",
                ),
                process="engine_api_no_cli_fallback",
            )
        )
    for workload in ("quiet", "database_activity", "unrelated_activity"):
        for pair in range(1, 11):
            entries.append(
                _entry(
                    "D",
                    f"D-container-pair-{workload}",
                    f"D-container-pair-{workload}-{pair:02d}",
                    f"{_TOOL_ROOT}/scale28_runtime_identity.py:capture_runtime_identity",
                    "container_rss_equivalence",
                    (
                        ("workload", workload),
                        ("pair", pair),
                        ("stream", False),
                        ("one_shot", True),
                        ("value_tolerance_bytes", 33_554_432),
                        ("sampling_skew_ms", 250),
                    ),
                    "equivalent",
                    executor="fix1.executor.d.container_pair",
                    observation=_BASE_OBSERVATION
                    + (
                        "container_id",
                        "api_rss_bytes",
                        "diagnostic_rss_bytes",
                        "sampling_skew_ms",
                        "stream",
                        "one_shot",
                    ),
                    process="engine_api_plus_explicit_diagnostic",
                )
            )
    terminal_dimensions = (
        "acquisition",
        "query_fetch",
        "timeout",
        "transport",
        "authentication",
        "schema",
        "semantic",
        "one_read",
        "settlement_cleanup",
        "process_boundary",
    )
    for dimension in terminal_dimensions:
        entries.append(
            _entry(
                "D",
                "D-terminal-read",
                f"D-terminal-{dimension}",
                f"{_TOOL_ROOT}/scale15_actual_path_readback.py:read_terminal_backend_summary",
                "terminal_read",
                (("dimension", dimension),),
                "observed",
                executor="fix1.executor.d.terminal",
                observation=_BASE_OBSERVATION
                + (
                    "dimension",
                    "acquisition",
                    "read_count",
                    "reader_settled",
                ),
                cleanup="terminal_reader_settled",
                process="one_read_no_automatic_fallback",
            )
        )
    return tuple(entries)


def _group_e() -> tuple[CatalogEntry, ...]:
    entries: list[CatalogEntry] = []
    terminal_cohorts = (
        ("success_quiet", 10),
        ("success_after_observer", 10),
        ("success_connection_churn", 10),
        ("controlled_query_expiry", 20),
        ("acquisition_transport_failure", 10),
    )
    for cohort, count in terminal_cohorts:
        for case in range(1, count + 1):
            entries.append(
                _entry(
                    "E",
                    f"E-{cohort}",
                    f"E-{cohort}-{case:02d}",
                    f"{_TOOL_ROOT}/scale15_actual_path_readback.py:read_terminal_backend_summary",
                    "terminal_live_cohort",
                    (("cohort", cohort), ("case", case), ("read_count", 1)),
                    "terminal",
                )
            )
    terminal_stages = (
        "connection_acquisition_delay",
        "query_flush_delay",
        "server_result_readiness_delay",
        "result_access_delay",
        "connection_settlement_delay",
        "transport_failure",
        "authentication_failure",
        "semantic_schema_failure",
    )
    for stage in terminal_stages:
        entries.append(
            _entry(
                "E",
                "E-deterministic-stage",
                f"E-stage-{stage}",
                f"{_TOOL_ROOT}/scale15_actual_path_readback.py:read_terminal_backend_summary",
                "terminal_stage_matrix",
                (("stage", stage), ("deadline_ms", 500)),
                "stage_classified",
            )
        )
    return tuple(entries)
