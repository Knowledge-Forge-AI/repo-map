"""Real preparation-owner executors for Groups A and B."""

from __future__ import annotations

from pathlib import Path
import signal
import subprocess
import sys

from repomap_test_support.test_cov5k_r2_fix2_catalog import CatalogEntry
from repomap_test_support.test_cov5k_r2_fix2_evidence import (
    OwnerEntryEvidence,
    ExecutorEvidence,
    bind_executor_evidence,
)
from repomap_test_support.test_cov5k_r2_fix2_preparation_conditions import (
    _condition_activity,
)
from repomap_test_support.test_cov5k_r2_fix2_preparation_execution import (
    _GROUP_A_ATTEMPT_TIMEOUT_MS,
    _GROUP_A_ORDINARY_TOTAL_TIMEOUT_MS,
    _GROUP_A_PROCESS_SETTLEMENT_TIMEOUT_MS,
    _GROUP_A_RETRY_TOTAL_TIMEOUT_MS,
    _GROUP_A_SEMANTIC_OPERATION_TIMEOUT_MS,
    _GROUP_A_TIMEOUT_FAULT_SECONDS,
    _PREPARERS,
    _SCENARIO_FAULTS,
    _EnactedAttempt,
    _ParentSettlementAttempt,
    _generic_worker_failure,
    _policy,
    _resource_failure,
    _run_authority,
    _specification,
    _timeout_failure,
    _warm_preparation_worker_imports,
    _without_subprocess_coverage_injection,
)
from repomap_test_support.test_cov5k_r2_fix2_preparation_observations import (
    _RAW_BOUNDARIES,
    _RAW_CATEGORIES,
    AttemptEvidenceLayers,
    AttemptObservation,
    ChildLocalExceptionFact,
    FrozenExpectedFact,
    ParentObservedAttemptFact,
    PublicProjectionFact,
    ScenarioIntentFact,
    WireFailureNoticeFact,
    _observation,
    _public_raw,
    validate_attempt_evidence_layers,
)
from repomap_test_support.test_cov5k_r2_fix2_process_recorder import (
    ProcessBoundaryRecorder,
)
from repomap_test_support.test_cov5k_r2_contracts import invoke_bound_owner
from repomap_test_support.test_cov5k_r2_fix3_scenarios import scenario_program
from repomap_test_support.test_cov5k_r2_groupa_contract import (
    canonical_attempt_category,
    derive_forced_tail_policy,
    derive_observed_cleanup_disposition,
    derive_observed_group_a_contract_category,
    derive_observed_retry_disposition,
    verify_parent_settlement_contract,
)
from scale28_preparation_authority import HybridPreparationAuthority


def execute_preparation_state_path(
    temp_root: Path, entry: CatalogEntry
) -> ExecutorEvidence:
    """Execute the parent preparation state machine for one A scenario."""

    raw_scenario_id = dict(entry.parameter_values)["scenario_id"]
    if not isinstance(raw_scenario_id, (int, str)):
        raise TypeError(
            f"scenario_id must be int or str, got {type(raw_scenario_id).__name__}"
        )
    scenario_id = int(raw_scenario_id)
    faults = _SCENARIO_FAULTS[scenario_id]
    program = scenario_program(
        owner_identity="HybridPreparationAuthority.prepare",
        seam_identity="fix3.preparation.state_path",
        input_action=(
            ("scenario_numeric_id", scenario_id),
            ("fault_program", faults),
            ("retry_gate", scenario_id == 846),
            ("refuse_after_success", scenario_id == 1067),
        ),
        expected_product_event_classes=(
            "preparation_attempt",
            "preparation_settlement",
            "forced_tail",
        ),
        cleanup_contract=entry.cleanup_contract,
        process_boundary_contract=entry.process_boundary_contract,
    )

    def operation():
        with _without_subprocess_coverage_injection():
            _warm_preparation_worker_imports()
            authority_result = _run_authority(
                temp_root,
                entry.authority_id,
                faults,
                retry_gate=scenario_id == 846,
                refuse_after_success=scenario_id == 1067,
                owner_type=HybridPreparationAuthority,
            )
        attempts = authority_result[3]
        forced = _forced_tail_for_observations(
            tuple(
                item.raw_category
                for item in attempts
                if item.raw_category != "cleanup_limitation"
            )
        )
        return authority_result, forced

    recorded, owner_evidence, _frames = invoke_bound_owner(
        evidence_factory=OwnerEntryEvidence,
        executor=execute_preparation_state_path,
        owner=HybridPreparationAuthority.prepare,
        scenario_seam_active=True,
        operation=lambda: ProcessBoundaryRecorder().run(operation),
    )
    (
        (
            authority,
            attempt_ids,
            resource_ids,
            attempts,
            maximum_attempts,
        ),
        forced,
    ), process = recorded
    snapshot = authority.snapshot()
    raw_outcomes = tuple(item.raw_outcome for item in attempts)
    raw_categories = tuple(item.raw_category for item in attempts)
    raw_boundaries = tuple(item.raw_boundary for item in attempts)
    parent_attempt_facts = tuple(
        (
            item.parent.attempt_id,
            item.parent.outcome,
            item.parent.category,
            item.parent.boundary,
        )
        for item in attempts
    )
    parent_failures = tuple(
        (item.parent.category, item.parent.boundary)
        for item in attempts
        if item.parent.outcome == "failure"
    )
    if tuple(snapshot.attempt_failures) != parent_failures:
        raise ValueError("parent attempt facts disagree with authority snapshot")
    if attempt_ids != tuple(item.parent.attempt_id for item in attempts):
        raise ValueError("parent attempt identities disagree with authority requests")
    failures = tuple(category for category in raw_categories if category != "none")
    cleanup_started = bool(failures) or snapshot.refusal is not None
    cleanup_limited = "cleanup_limitation" in failures
    forced_signal, forced_pid, forced_returncode, forced_tail_stdout_closed = forced
    state_history = tuple(state.value for state in snapshot.state_history)
    final_projection = "refused" if "refused" in state_history else "released"
    cleanup_disposition = derive_observed_cleanup_disposition(raw_categories)
    retry_disposition = derive_observed_retry_disposition(
        raw_outcomes, raw_categories, raw_boundaries, state_history
    )
    observed_contract_category = derive_observed_group_a_contract_category(
        raw_outcomes,
        raw_categories,
        raw_boundaries,
        state_history,
        final_projection,
        maximum_attempts,
    )
    observed = (
        ("primary_result_category", snapshot.state.value),
        ("secondary_limitations", failures),
        ("host_process_count", process.host_process_count),
        ("nested_psql_intent_count", process.nested_psql_intent_count),
        ("cleanup_disposition", cleanup_disposition),
        ("attempt_ids", attempt_ids),
        ("resource_ids", resource_ids),
        ("failure_sources", failures),
        ("raw_worker_outcomes", raw_outcomes),
        ("raw_worker_categories", raw_categories),
        ("raw_worker_boundaries", raw_boundaries),
        ("parent_observed_attempt_facts", parent_attempt_facts),
        (
            "child_local_exception_states",
            tuple(item.layers.child_local.status for item in attempts),
        ),
        (
            "wire_failure_notice_states",
            tuple(item.layers.wire.status for item in attempts),
        ),
        (
            "public_projection_facts",
            tuple(
                (
                    item.layers.public_projection.outcome,
                    item.layers.public_projection.category,
                    item.layers.public_projection.boundary,
                )
                for item in attempts
            ),
        ),
        (
            "interpreted_evidence_origins",
            tuple(item.interpreted_evidence_origin for item in attempts),
        ),
        (
            "scenario_injection_intents",
            tuple(item.scenario_intent for item in attempts),
        ),
        (
            "canonical_attempt_outcomes",
            tuple(item.canonical_outcome for item in attempts),
        ),
        (
            "canonical_attempt_categories",
            tuple(item.canonical_category for item in attempts),
        ),
        (
            "scenario_contract_categories",
            tuple(item.scenario_contract_category for item in attempts),
        ),
        ("authority_attempt_failures", tuple(snapshot.attempt_failures)),
        ("authority_attempt_count", state_history.count("preparing")),
        (
            "parent_observed_failure_pair",
            parent_failures[0] if parent_failures else ("none", "none"),
        ),
        ("retry_observed", len(attempt_ids) > 1),
        ("maximum_attempts", maximum_attempts),
        ("observed_contract_category", observed_contract_category),
        ("cleanup_started", cleanup_started),
        ("cleanup_completed", snapshot.state.value == "settled"),
        ("cleanup_limited", cleanup_limited),
        ("worker_settled", snapshot.state.value == "settled"),
        ("forced_tail_stdout_closed", forced_tail_stdout_closed),
        ("retry_disposition", retry_disposition),
        ("third_attempt_absent", len(attempt_ids) <= maximum_attempts),
        ("forced_tail_signal", forced_signal),
        ("forced_tail_pid", forced_pid),
        ("forced_tail_returncode", forced_returncode),
        ("final_projection_category", final_projection),
        ("attempt_elapsed_ms", snapshot.attempt_elapsed_ms),
        (
            "activation_observed",
            tuple(item.activation_observed for item in attempts),
        ),
    )
    product_events = (
        ("preparation_state_history", state_history),
        ("attempt_identities", attempt_ids),
        ("resource_identities", resource_ids),
        ("process_creations", process.host_process_count),
        ("forced_tail_stdout_closed", forced_tail_stdout_closed),
        ("forced_tail", forced),
        ("final_projection", final_projection),
    )
    raw_action_scenario_id = dict(program.input_action)["scenario_numeric_id"]
    if not isinstance(raw_action_scenario_id, (int, str)):
        raise TypeError(
            f"scenario_numeric_id must be int or str, got {type(raw_action_scenario_id).__name__}"
        )
    enacted = (("scenario_id", int(raw_action_scenario_id)),)
    evidence = bind_executor_evidence(
        entry,
        enacted_parameters=enacted,
        observed_fields=observed,
        owner_entry_evidence=owner_evidence,
        scenario_program_identity=program.scenario_id,
        observed_product_events=product_events,
    )
    if entry.semantic_group == "PARENT_SETTLEMENT":
        verify_parent_settlement_contract(entry, evidence)
    return evidence


def _forced_tail_for_observations(
    raw_categories: tuple[str, ...],
) -> tuple[str | None, int | None, int | None, bool | None]:
    required, force_kill = derive_forced_tail_policy(raw_categories)
    if not required:
        return None, None, None, None
    script = "import signal,time;"
    if force_kill:
        script += "signal.signal(signal.SIGTERM,lambda *_:None);"
    script += "print('ready',flush=True);time.sleep(60)"
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    signal_name: str | None = None
    returncode: int | None = None
    try:
        assert process.stdout is not None
        if process.stdout.readline().strip() != "ready":
            raise RuntimeError("forced-tail child did not become ready")
        process.send_signal(signal.SIGTERM)
        if force_kill:
            try:
                process.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
            signal_name = "SIGKILL"
        else:
            process.wait(timeout=1)
            signal_name = "SIGTERM"
        returncode = int(process.returncode)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)
        if process.stdout is not None:
            process.stdout.close()
    return signal_name, process.pid, returncode, bool(process.stdout.closed)


def execute_preparation_condition(
    temp_root: Path, entry: CatalogEntry
) -> ExecutorEvidence:
    """Enact each B condition through the same real parent/worker family."""

    parameters = dict(entry.parameter_values)
    condition = str(parameters["condition"])
    faults = (
        ("resource", "success")
        if condition == "immediate_second_attempt"
        else ("success",)
    )
    with _condition_activity(condition, temp_root, entry.authority_id) as fact:
        authority, attempts, _, _observations, _maximum_attempts = _run_authority(
            temp_root, entry.authority_id, faults
        )
    snapshot = authority.snapshot()
    raw_attempt = parameters["attempt"]
    if not isinstance(raw_attempt, (int, str)):
        raise TypeError(f"attempt must be int or str, got {type(raw_attempt).__name__}")
    attempt_identity = int(raw_attempt)
    observed = (
        ("primary_result_category", snapshot.state.value),
        ("condition_enacted", condition),
        ("condition_fact", fact),
        ("attempt_identity", attempt_identity),
        ("product_attempt_count", len(attempts)),
    )
    return ExecutorEvidence(entry.authority_id, True, entry.parameter_values, observed)


__all__ = (
    "AttemptEvidenceLayers",
    "AttemptObservation",
    "ChildLocalExceptionFact",
    "FrozenExpectedFact",
    "ParentObservedAttemptFact",
    "PublicProjectionFact",
    "ScenarioIntentFact",
    "WireFailureNoticeFact",
    "_EnactedAttempt",
    "_GROUP_A_ATTEMPT_TIMEOUT_MS",
    "_GROUP_A_ORDINARY_TOTAL_TIMEOUT_MS",
    "_GROUP_A_PROCESS_SETTLEMENT_TIMEOUT_MS",
    "_GROUP_A_RETRY_TOTAL_TIMEOUT_MS",
    "_GROUP_A_SEMANTIC_OPERATION_TIMEOUT_MS",
    "_GROUP_A_TIMEOUT_FAULT_SECONDS",
    "_PREPARERS",
    "_ParentSettlementAttempt",
    "_RAW_BOUNDARIES",
    "_RAW_CATEGORIES",
    "_SCENARIO_FAULTS",
    "_condition_activity",
    "_forced_tail_for_observations",
    "_generic_worker_failure",
    "_observation",
    "_policy",
    "_public_raw",
    "_resource_failure",
    "_run_authority",
    "_specification",
    "_timeout_failure",
    "_warm_preparation_worker_imports",
    "_without_subprocess_coverage_injection",
    "canonical_attempt_category",
    "execute_preparation_condition",
    "execute_preparation_state_path",
    "validate_attempt_evidence_layers",
)
