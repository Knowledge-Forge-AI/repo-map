"""Runtime and execution qualification catalog definitions for FIX1."""

from __future__ import annotations

from repomap_test_support.scale28_fix9_failure_inventory import FORMER_FAILURES
from repomap_test_support.test_cov5k_r2_fix1_catalog_storage import _group_e
from repomap_test_support.test_cov5k_r2_fix1_catalog_values import (
    CatalogEntry,
    _BASE_OBSERVATION,
    _GROUP_G_OBSERVATION,
    _TOOL_ROOT,
    _entry,
)


def _group_a() -> tuple[CatalogEntry, ...]:
    paths = (
        ("A01", "attempt_one_success", "success", "not_started", "admitted"),
        ("A02", "resource_failure_second_success", "success", "complete", "admitted"),
        ("A03", "timeout_second_success", "success", "complete", "admitted"),
        ("A04", "two_generic_worker_failures", "failed", "complete", "admitted"),
        ("A05", "generic_worker_failure_then_timeout", "failed", "complete", "admitted"),
        ("A06", "timeout_then_generic_worker_failure", "failed", "complete", "admitted"),
        ("A07", "two_timeouts", "failed", "complete", "admitted"),
        ("A08", "retry_gate_refusal", "refused", "complete", "refused"),
        ("A09", "parent_settlement_cleanup_limitation_no_retry", "refused", "limited", "refused"),
        ("A10", "final_refused_projection", "refused", "complete", "refused"),
    )
    observation = _BASE_OBSERVATION + (
        "attempt_ids",
        "resource_ids",
        "failure_sources",
        "cleanup_started",
        "cleanup_completed",
        "cleanup_limited",
        "worker_settled",
        "descriptor_settled",
        "retry_disposition",
        "third_attempt_absent",
        "forced_tail_signal",
        "forced_tail_pid",
        "forced_tail_returncode",
        "final_projection_category",
    )
    return tuple(
        _entry(
            "PARENT_SETTLEMENT" if name == "A09" else "A",
            name,
            case,
            f"{_TOOL_ROOT}/scale28_preparation_worker.py:PreparationWorkerAttempt",
            "preparation_state_path",
            (
                ("path", case),
                ("cleanup", cleanup),
                ("retry", retry),
            ),
            expected,
            observation=observation,
            cleanup=f"cleanup_{cleanup}",
            process="parent_authority_settlement" if name == "A09" else "owned_worker_settlement",
        )
        for name, case, expected, cleanup, retry in paths
    )


def _group_b() -> tuple[CatalogEntry, ...]:
    entries: list[CatalogEntry] = []
    preparation_conditions = (
        "quiet_success",
        "cpu_contention",
        "filesystem_contention",
        "connection_churn",
        "complete_gate_prelude",
        "immediate_second_attempt",
    )
    for condition in preparation_conditions:
        for attempt in range(1, 31):
            entries.append(
                _entry(
                    "B",
                    f"B-{condition}",
                    f"B-{condition}-{attempt:02d}",
                    f"{_TOOL_ROOT}/scale28_preparation_worker.py:PreparationWorkerAttempt",
                    "preparation_condition",
                    (("condition", condition), ("attempt", attempt)),
                    "settled",
                )
            )
    return tuple(entries)


def _group_c() -> tuple[CatalogEntry, ...]:
    entries: list[CatalogEntry] = []
    failure_sources = (
        "resource_reader",
        "preparation_timeout",
        "observation_transfer",
        "ack",
        "receipt",
        "process_settlement",
        "cleanup_limitation",
        "total_wall_retry_gate",
    )
    for source in failure_sources:
        for case in range(1, 21):
            entries.append(
                _entry(
                    "C",
                    f"C-{source}",
                    f"C-{source}-{case:02d}",
                    f"{_TOOL_ROOT}/actual_refresh_failure_causality.py:FailureCausalityAuthority",
                    "failure_causality",
                    (("failure_source", source), ("case", case)),
                    "classified",
                )
            )
    return tuple(entries)


def _group_f() -> tuple[CatalogEntry, ...]:
    entries: list[CatalogEntry] = []
    for request in range(1, 501):
        entries.append(
            _entry(
                "F",
                "F-request-cohort",
                f"F-request-{request:04d}",
                f"{_TOOL_ROOT}/scale28_backend_observer_session.py:BackendObserverSession",
                "observer_request",
                (("request", request), ("request_deadline_ms", 300)),
                "request_terminal",
            )
        )
    for case in range(1, 21):
        entries.append(
            _entry(
                "F",
                "F-process-companion",
                f"F-process-companion-{case:02d}",
                f"{_TOOL_ROOT}/process_rss_monitor.py:ProcessRssMonitor",
                "process_containment_companion",
                (("case", case),),
                "process_contained",
            )
        )
    return tuple(entries)


def _groups_b_c_e_f() -> tuple[CatalogEntry, ...]:
    return (*_group_b(), *_group_c(), *_group_e(), *_group_f())


_GROUP_G_SCHEDULES = (
    ("request-origin", 30),
    ("request-publication", 30),
    ("pre-dispatch-refusal", 12),
    ("operation-class", 8),
    ("d-op-classification", 12),
    ("close-quarantine", 12),
    ("cleanup-attempt", 12),
    ("terminal-read", 12),
    ("triple-fault", 12),
    ("three-party", 50),
    ("close-under-use", 100),
    ("source-causality", 200),
    ("terminal-claim", 18),
    ("reacquisition", 36),
    ("caller-context", 9),
    ("final-release", 20),
)


def _group_g() -> tuple[CatalogEntry, ...]:
    entries = [
        _entry(
            "G",
            f"G-{schedule}",
            f"G-{schedule}-{index:04d}",
            f"{_TOOL_ROOT}/scale28_backend_observer_session.py:BackendObserverSession",
            "observer_schedule",
            (("schedule", schedule), ("schedule_index", index)),
            "schedule_terminal",
            executor=f"fix1.executor.g.{schedule}",
            observation=_GROUP_G_OBSERVATION,
        )
        for schedule, count in _GROUP_G_SCHEDULES
        for index in range(1, count + 1)
    ]
    owner_by_area = {
        "SCALE14": (
            f"{_TOOL_ROOT}/scale14_actual_refresh_supervisor.py:"
            "ActualRefreshSupervisor"
        ),
        "SCALE23": (
            f"{_TOOL_ROOT}/scale15_actual_path_readback.py:"
            "read_scale15_terminal_state"
        ),
        "SCALE28": (
            f"{_TOOL_ROOT}/scale28_hybrid_startup.py:"
            "prepare_parent_startup_authorities"
        ),
        "SCALE28-FIX1": (
            f"{_TOOL_ROOT}/scale28_preparation_worker.py:"
            "PreparationWorkerAttempt"
        ),
        "hybrid/FIX9": (
            f"{_TOOL_ROOT}/scale28_hybrid_startup.py:"
            "prepare_startup_resources"
        ),
    }
    for failure in FORMER_FAILURES:
        entries.append(
            _entry(
                "G",
                "G-former-failure",
                f"G-{failure.case_id}",
                owner_by_area[failure.owning_area],
                "former_failure_node",
                (
                    ("node_id", failure.node_id),
                    ("source_category", failure.source_category),
                    ("outer_category", failure.outer_category),
                ),
                "source_category_preserved",
                executor=f"fix1.executor.g.former.{failure.case_id}",
                observation=_GROUP_G_OBSERVATION,
                fixed_argv_shape=("pytest", failure.node_id),
                pytest_node_id=failure.node_id,
            )
        )
    return tuple(entries)


def _group_h() -> tuple[CatalogEntry, ...]:
    axes = (
        (
            "H01",
            "psycopg_success",
            f"{_TOOL_ROOT}/scale15_actual_path_readback.py:read_scale15_terminal_state",
        ),
        (
            "H02",
            "psycopg_connection_failure",
            f"{_TOOL_ROOT}/scale15_actual_path_readback.py:read_scale15_terminal_state",
        ),
        (
            "H03",
            "process_rss",
            f"{_TOOL_ROOT}/process_rss_monitor.py:ProcessRssMonitor",
        ),
        (
            "H04",
            "process_tree_rss",
            f"{_TOOL_ROOT}/process_rss_monitor.py:ProcessRssMonitor",
        ),
        (
            "H05",
            "container_rss",
            f"{_TOOL_ROOT}/scale28_runtime_identity.py:Scale28RuntimeIdentity",
        ),
        (
            "H06",
            "terminal_read_success",
            f"{_TOOL_ROOT}/scale15_actual_path_readback.py:read_terminal_backend_summary",
        ),
        (
            "H07",
            "terminal_read_timeout",
            f"{_TOOL_ROOT}/scale15_actual_path_readback.py:read_terminal_backend_summary",
        ),
        (
            "H08",
            "complete_preparation_resource_read",
            f"{_TOOL_ROOT}/scale28_preparation_worker.py:PreparationWorkerAttempt",
        ),
    )
    return tuple(
        _entry(
            "H",
            axis,
            f"{axis}-{name}",
            owner,
            "zero_process_boundary",
            (("axis", name),),
            "zero_process",
            executor=f"fix1.executor.h.{axis.lower()}",
            cleanup="axis_resource_settled",
            process="independent_axis_process_count",
        )
        for axis, name, owner in axes
    )


def _groups_i_j() -> tuple[CatalogEntry, ...]:
    entries: list[CatalogEntry] = []
    owners = (
        (
            "scale14",
            f"{_TOOL_ROOT}/scale14_actual_refresh_supervisor.py:ActualRefreshSupervisor",
        ),
        (
            "scale23",
            f"{_TOOL_ROOT}/scale15_actual_path_readback.py:read_scale15_terminal_state",
        ),
        (
            "scale28_long_extraction",
            f"{_TOOL_ROOT}/scale28_hybrid_startup.py:prepare_startup_resources",
        ),
        (
            "scale28_fix1",
            f"{_TOOL_ROOT}/scale28_preparation_worker.py:PreparationWorkerAttempt",
        ),
        (
            "mixed_hybrid",
            f"{_TOOL_ROOT}/scale28_hybrid_startup.py:prepare_parent_startup_authorities",
        ),
    )
    for owning_area, owner in owners:
        for execution in range(1, 11):
            entries.append(
                _entry(
                    "I",
                    f"I-{owning_area}",
                    f"I-{owning_area}-{execution:02d}",
                    owner,
                    "owning_area_execution",
                    (
                        ("owning_area", owning_area),
                        ("execution", execution),
                    ),
                    "passed",
                    executor=f"fix1.executor.i.{owning_area}",
                )
            )
    mixed_owner = (
        f"{_TOOL_ROOT}/scale28_hybrid_startup.py:"
        "prepare_parent_startup_authorities"
    )
    for campaign in range(1, 16):
        entries.append(
            _entry(
                "J",
                "J-mixed-campaign",
                f"J-mixed-campaign-{campaign:02d}",
                mixed_owner,
                "mixed_configured_campaign",
                (("campaign", campaign), ("streak_required", 15)),
                "passed",
            )
        )
    for rehearsal in range(1, 4):
        entries.append(
            _entry(
                "J",
                "J-fresh-rehearsal",
                f"J-fresh-rehearsal-{rehearsal:02d}",
                mixed_owner,
                "fresh_public_rehearsal",
                (("rehearsal", rehearsal), ("fresh_resources", True)),
                "passed",
            )
        )
    entries.append(
        _entry(
            "J",
            "J-prior-state",
            "J-prior-state-preservation-01",
            mixed_owner,
            "prior_state_preservation",
            (("rehearsal", 1), ("prior_publication_preserved", True)),
            "passed",
        )
    )
    return tuple(entries)
