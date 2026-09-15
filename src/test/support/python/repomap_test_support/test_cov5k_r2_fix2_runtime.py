"""Real failure, readback, process, and runtime-data-plane executors."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Sequence

from process_rss_monitor import ProcessRssMonitor
from repomap_test_support.test_cov5k_r2_fix2_catalog import CatalogEntry
from scale15_terminal_contracts import ExpectedRefreshAuthority
from repomap_test_support.test_cov5k_r2_fix2_evidence import (
    OwnerEntryEvidence,
    ExecutorEvidence,
    bind_executor_evidence,
)
from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest
from repomap_test_support.test_cov5k_r2_fix3_terminal_programs import enact_terminal
from repomap_test_support.test_cov5k_r2_contracts import (
    external_owner_evidence,
    invoke_bound_owner,
)
from repomap_test_support.test_cov5k_r2_fix3_scenarios import (
    scenario_program, integer_parameter as _integer_parameter,
)
from repomap_test_support.test_cov5k_r2_fix3_observer_programs import (
    enact_failure_causality,
    _SOURCE_CODES as _SOURCE_CODES,
)
from repomap_test_support.test_cov5k_r2_fix4_psycopg import (
    execute_registered_psycopg_read,
    registered_psycopg_owner,
)
from repomap_test_support.test_cov5k_r2_fix3_container_pairs import (
    enact_container_rss,
    enact_container_rss_equivalence,
)
from scale15_actual_path_readback import (
    read_scale15_terminal_state,
    read_terminal_backend_summary,
)
from scale28_runtime_identity import capture_runtime_identity




def execute_failure_causality(entry: CatalogEntry) -> ExecutorEvidence:
    """Keep the registered executor frame while delegating causality enactment."""
    return enact_failure_causality(entry, executor=execute_failure_causality)


class _SettlingProcess:
    def __init__(self) -> None:
        self._polls = 0

    def poll(self) -> int | None:
        self._polls += 1
        return 0 if self._polls >= 2 else None


def execute_process_rss(entry: CatalogEntry) -> ExecutorEvidence:
    """Enact every D process case through ProcessRssMonitor seams."""

    process_case = str(dict(entry.parameter_values)["process_case"])
    readings: list[int | None | BaseException]
    if process_case in {"invalid_pid", "no_such_process", "root_disappearance"}:
        readings = [ProcessLookupError(), None]
    elif process_case in {"access_denied", "child_denial_or_zombie", "zombie_process"}:
        readings = [PermissionError(), None]
    elif process_case == "invalid_rss_value":
        readings = [-1, None]
    else:
        readings = [1024 + len(process_case), 2048 + len(process_case)]

    def reader() -> int | None:
        value = readings.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    signaled: list[bool] = []
    monitor = ProcessRssMonitor(
        limit_bytes=10_000,
        cadence_seconds=0.01,
        reader=reader,
        signal=lambda: signaled.append(True),
        sleeper=lambda _: None,
    )
    program = scenario_program(
        owner_identity="ProcessRssMonitor.run",
        seam_identity="fix3.process_rss.reader_effect",
        input_action=(("process_case", process_case),),
        expected_product_event_classes=("monitor_result", "reader_effect"),
        cleanup_contract=entry.cleanup_contract,
        process_boundary_contract=entry.process_boundary_contract,
    )

    def operation():
        try:
            result = monitor.run(_SettlingProcess())
        except ValueError as error:
            return "controlled_reader_rejection", {"error_type": type(error).__name__}
        return "sampled", result.to_payload()

    (category, payload), owner_evidence, _frames = invoke_bound_owner(
        evidence_factory=OwnerEntryEvidence,
        executor=execute_process_rss,
        owner=ProcessRssMonitor.run,
        scenario_seam_active=True,
        operation=operation,
    )
    observed = (
        ("primary_result_category", category),
        ("process_case", process_case),
        ("process_result", payload),
        ("signal_count", len(signaled)),
    )
    return bind_executor_evidence(
        entry,
        enacted_parameters=(("process_case", dict(program.input_action)["process_case"]),),
        observed_fields=observed,
        owner_entry_evidence=owner_evidence,
        scenario_program_identity=program.scenario_id,
        observed_product_events=(
            ("monitor_result", payload),
            ("reader_effect", category),
        ),
    )


def execute_runtime_driver_read(
    entry: CatalogEntry,
    *,
    psql_args: Sequence[str],
    expected_authority: ExpectedRefreshAuthority,
    psql_executable: str = "psql",
    psql_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ExecutorEvidence:
    """Enact psycopg readback or the structurally separate explicit psql owner."""

    parameters = dict(entry.parameter_values)
    driver = str(parameters["driver"])
    if driver == "psycopg":
        if read_scale15_terminal_state is not registered_psycopg_owner():
            raise ValueError("registered Psycopg owner identity changed")
        return execute_registered_psycopg_read(
            entry,
            executor=execute_runtime_driver_read,
            psql_args=psql_args,
            expected_authority=expected_authority,
            psql_executable=psql_executable,
        )
    else:
        command = [psql_executable, *psql_args, "-c", "SELECT 1"]
        completed = psql_runner(
            command,
            shell=False,
            timeout=3,
            check=False,
            capture_output=True,
            text=True,
        )
        category = _psql_failure_category(completed)
        stdout = str(getattr(completed, "stdout", ""))
        stderr = str(getattr(completed, "stderr", ""))
        program = scenario_program(
            owner_identity="external:psql",
            seam_identity="fix3.psql.process_evidence",
            input_action=(
                ("mode", str(parameters["mode"])),
                ("automatic_fallback", False),
            ),
            expected_product_event_classes=("process_completion", "diagnostic_classification"),
            cleanup_contract=entry.cleanup_contract,
            process_boundary_contract=entry.process_boundary_contract,
        )
        enacted = (
            ("driver", Path(command[0]).name),
            ("mode", str(dict(program.input_action)["mode"])),
            ("failure_category", category),
            ("automatic_fallback", False),
        )
        observed = (
            ("driver", "psql"),
            ("mode", parameters["mode"]),
            ("failure_category", category),
            ("automatic_fallback", False),
            ("effective_argv_digest", canonical_digest(tuple(command))),
            ("returncode", int(completed.returncode)),
            ("diagnostic_evidence_digest", canonical_digest((stdout, stderr))),
            ("timeout_disposition", "completed"),
            ("host_executable", Path(command[0]).name),
            ("nested_psql_intent", Path(command[0]).name == "psql"),
        )
        product_events = (
            ("process_completion", (int(completed.returncode), Path(command[0]).name)),
            ("diagnostic_classification", category),
        )
        return bind_executor_evidence(
            entry,
            enacted_parameters=enacted,
            observed_fields=observed,
            owner_entry_evidence=external_owner_evidence(
                evidence_factory=OwnerEntryEvidence,
                executor=execute_runtime_driver_read,
                executable=psql_executable,
                owner_entry_count=1,
                scenario_seam_active=True,
            ),
            scenario_program_identity=program.scenario_id,
            observed_product_events=product_events,
        )


def _psql_failure_category(completed: subprocess.CompletedProcess[str]) -> str:
    """Classify explicit psql from its actual return and diagnostic evidence."""

    if completed.returncode == 0:
        return "success"
    diagnostic = f"{completed.stdout}\n{completed.stderr}".casefold()
    if "sqlstate 08" in diagnostic or "connection failure" in diagnostic:
        return "class_08"
    if "password authentication failed" in diagnostic or "no password supplied" in diagnostic:
        return "authentication"
    if "relation" in diagnostic and "does not exist" in diagnostic:
        return "semantic_schema"
    if "connection refused" in diagnostic or "could not connect" in diagnostic:
        return "transport_refusal"
    return "unavailable"


def execute_container_rss(
    entry: CatalogEntry, *, runtime: str, container_name: str,
    runtime_source_commit: str, postgresql_server_version: str,
    capture: Callable[..., object] = capture_runtime_identity,
) -> ExecutorEvidence:
    return enact_container_rss(
        entry, executor=execute_container_rss,
        capture_runtime_identity=capture_runtime_identity, capture=capture,
        runtime=runtime, container_name=container_name,
        runtime_source_commit=runtime_source_commit,
        postgresql_server_version=postgresql_server_version,
    )


def execute_container_rss_equivalence(
    entry: CatalogEntry, *, api_reader: Callable[[], int] | None = None,
    diagnostic_reader: Callable[[], int] | None = None,
    runtime_identity_context: dict[str, str] | None = None,
    workload_probe: Callable[[], tuple[str, object]] | None = None,
) -> ExecutorEvidence:
    return enact_container_rss_equivalence(
        entry, executor=execute_container_rss_equivalence,
        capture_runtime_identity=capture_runtime_identity, api_reader=api_reader,
        diagnostic_reader=diagnostic_reader,
        runtime_identity_context=runtime_identity_context, workload_probe=workload_probe,
    )


def execute_terminal_read(
    entry: CatalogEntry,
    *,
    psql_args: Sequence[str],
    timeout_seconds: float,
    reader: Callable[..., dict[str, int]] = read_terminal_backend_summary,
) -> ExecutorEvidence:
    """Call the accepted terminal owner with the frozen D/E dimension."""

    if reader is not read_terminal_backend_summary:
        raise ValueError("unfrozen terminal caller reader is prohibited")
    return enact_terminal(
        entry,
        executor=execute_terminal_read,
        psql_args=psql_args,
        timeout_seconds=timeout_seconds,
    )


def execute_terminal_live_cohort(
    entry: CatalogEntry,
    *,
    psql_args: Sequence[str],
    timeout_seconds: float,
    reader: Callable[..., dict[str, int]] = read_terminal_backend_summary,
) -> ExecutorEvidence:
    if reader is not read_terminal_backend_summary:
        raise ValueError("unfrozen terminal caller reader is prohibited")
    return enact_terminal(
        entry,
        executor=execute_terminal_live_cohort,
        psql_args=psql_args,
        timeout_seconds=timeout_seconds,
    )


def execute_terminal_stage_matrix(
    entry: CatalogEntry,
    *,
    psql_args: Sequence[str],
    timeout_seconds: float,
    reader: Callable[..., dict[str, int]] = read_terminal_backend_summary,
) -> ExecutorEvidence:
    if reader is not read_terminal_backend_summary:
        raise ValueError("unfrozen terminal caller reader is prohibited")
    return enact_terminal(
        entry,
        executor=execute_terminal_stage_matrix,
        psql_args=psql_args,
        timeout_seconds=timeout_seconds,
    )


def execute_process_containment_companion(entry: CatalogEntry) -> ExecutorEvidence:
    """Run an F process companion through the actual containment monitor."""

    requested_case = _integer_parameter(dict(entry.parameter_values)["case"])
    values = [4096 + requested_case, 4096 + requested_case]
    monitor = ProcessRssMonitor(
        limit_bytes=8192,
        cadence_seconds=0.01,
        reader=lambda: values.pop(0),
        signal=lambda: None,
        sleeper=lambda _: None,
    )
    program = scenario_program(
        owner_identity="ProcessRssMonitor.run",
        seam_identity="fix3.process_companion.rss_seed",
        input_action=(("rss_seed", 4096 + requested_case),),
        expected_product_event_classes=("containment_result",),
        cleanup_contract=entry.cleanup_contract,
        process_boundary_contract=entry.process_boundary_contract,
    )
    result, owner_evidence, _frames = invoke_bound_owner(
        evidence_factory=OwnerEntryEvidence,
        executor=execute_process_containment_companion,
        owner=ProcessRssMonitor.run,
        scenario_seam_active=True,
        operation=lambda: monitor.run(_SettlingProcess()),
    )
    payload = result.to_payload()
    maximum = payload["maximum_observed_bytes"]
    assert isinstance(maximum, int)
    observed_case = maximum - 4096
    return bind_executor_evidence(
        entry,
        enacted_parameters=(("case", observed_case),),
        observed_fields=(
            ("primary_result_category", "process_contained"),
            ("process_result", payload),
        ),
        owner_entry_evidence=owner_evidence,
        scenario_program_identity=program.scenario_id,
        observed_product_events=(("containment_result", payload),),
    )
