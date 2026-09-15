from __future__ import annotations

from actual_refresh_failure_causality import FailureCausalityAuthority
from repomap_test_support.test_cov5k_r2_fix2_catalog import CatalogEntry
from repomap_test_support.test_cov5k_r2_fix2_evidence import ExecutorEvidence
from repomap_test_support.test_cov5k_r2_fix3_scenarios import integer_parameter as _integer_parameter

from collections.abc import Callable

from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest
from repomap_test_support.test_cov5k_r2_fix2_evidence import bind_executor_evidence
from repomap_test_support.test_cov5k_r2_fix3_owner_binding import invoke_bound_owner
from repomap_test_support.test_cov5k_r2_fix3_scenarios import scenario_program
from scale28_backend_observer_session import (
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverOperationClass,
    ObserverSessionState,
)


_FAMILY_BOUNDARIES = {
    "request-origin": ObserverFailureBoundary.CONSTRUCTION,
    "request-publication": ObserverFailureBoundary.REGISTRATION,
    "pre-dispatch-refusal": ObserverFailureBoundary.CONNECTION_CREATE,
    "operation-class": ObserverFailureBoundary.ACTIVE_SUMMARY,
    "d-op-classification": ObserverFailureBoundary.CONTRACT_VALIDATION,
    "close-quarantine": ObserverFailureBoundary.LOCAL_CLOSE,
    "cleanup-attempt": ObserverFailureBoundary.SETTLEMENT_TIMEOUT,
    "terminal-read": ObserverFailureBoundary.TERMINAL_WAIT,
    "triple-fault": ObserverFailureBoundary.UNEXPECTED_CANCELLATION,
    "three-party": ObserverFailureBoundary.EVENT_APPLY,
    "close-under-use": ObserverFailureBoundary.OPERATION_WAIT_TIMEOUT,
    "source-causality": ObserverFailureBoundary.RESOURCE_READ,
    "terminal-claim": ObserverFailureBoundary.IDENTITY_CHANGED,
    "reacquisition": ObserverFailureBoundary.CONNECTION_TIMEOUT,
    "caller-context": ObserverFailureBoundary.STARTUP_SUMMARY,
    "final-release": ObserverFailureBoundary.CONNECTION_LOST,
}
_BOUNDARY_FAMILIES = {boundary.value: family for family, boundary in _FAMILY_BOUNDARIES.items()}


def enact_request(entry, *, executor: Callable[..., object], session: BackendObserverSession):
    parameters = dict(entry.parameter_values)
    request = int(parameters["request"])
    deadline_ms = int(parameters["request_deadline_ms"])
    program = scenario_program(
        owner_identity="BackendObserverSession.run",
        seam_identity="fix3.observer.request_dispatch",
        input_action=(("request_seed", request), ("deadline_ms", deadline_ms)),
        expected_product_event_classes=("request_dispatch", "request_settlement"),
        cleanup_contract="observer_session_closed",
        process_boundary_contract="in_process_exact_owner",
    )
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)

    def operation():
        def request_action(_observer, _connection):
            snapshot = session.snapshot()
            assert snapshot.active_operation is not None
            assert session._operation_dispatched_at is not None
            return (
                ("request_seed", request),
                ("active_boundary", snapshot.active_operation.value),
                ("operation_generation", session._operation_generation),
                ("dispatch_timestamp_ns", int(session._operation_dispatched_at * 1_000_000_000)),
                ("session_state_at_dispatch", snapshot.state.value),
            )

        return session.run(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            request_action,
            allowed_states=(ObserverSessionState.ACTIVE,),
            operation_class=ObserverOperationClass.SERIALIZATION_ONLY,
            timeout_seconds=deadline_ms / 1_000,
        )

    event, owner_evidence, owner_frames = invoke_bound_owner(
        executor=executor,
        owner=BackendObserverSession.run,
        scenario_seam_active=True,
        operation=operation,
    )
    session.close(timeout_seconds=1)
    event_values = dict(event)
    timeout_raw = owner_frames[0]["timeout_seconds"]
    assert isinstance(timeout_raw, (int, float, str))
    supplied_deadline_ms = round(float(timeout_raw) * 1_000)
    enacted = (
        ("request", int(event_values["request_seed"])),
        ("request_deadline_ms", supplied_deadline_ms),
    )
    operation_identity = canonical_digest(
        {
            "scenario": program.scenario_id,
            "generation": event_values["operation_generation"],
            "dispatch_timestamp_ns": event_values["dispatch_timestamp_ns"],
        }
    )
    observed = (
        ("primary_result_category", "request_terminal"),
        ("request_deadline_ms", supplied_deadline_ms),
        ("dispatch_timestamp_ns", event_values["dispatch_timestamp_ns"]),
        ("operation_identity", operation_identity),
        ("request_publication_event", event_values["session_state_at_dispatch"]),
        ("request_settlement_event", session.snapshot().state.value),
    )
    product_events = ("request_dispatch", event), ("request_settlement", "closed")
    return bind_executor_evidence(
        entry,
        enacted_parameters=tuple(enacted),
        observed_fields=observed,
        owner_entry_evidence=owner_evidence,
        scenario_program_identity=program.scenario_id,
        observed_product_events=product_events,
    )


def enact_schedule(entry, *, executor: Callable[..., object], session: BackendObserverSession):
    parameters = dict(entry.parameter_values)
    requested_family = str(parameters["schedule"])
    requested_count = int(parameters["schedule_index"])
    boundary = _FAMILY_BOUNDARIES[requested_family]
    program = scenario_program(
        owner_identity="BackendObserverSession.run",
        seam_identity="fix3.observer.schedule_dispatch",
        input_action=(("boundary", boundary.value), ("operation_count", requested_count)),
        expected_product_event_classes=("observer_operation", "observer_settlement"),
        cleanup_contract="observer_session_closed",
        process_boundary_contract="in_process_exact_owner",
    )
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)

    def operation():
        events = []
        for _ in range(requested_count):
            def schedule_action(_observer, _connection):
                snapshot = session.snapshot()
                assert snapshot.active_operation is not None
                return (
                    ("active_boundary", snapshot.active_operation.value),
                    ("operation_generation", session._operation_generation),
                    ("session_state", snapshot.state.value),
                )

            events.append(
                session.run(
                    boundary,
                    schedule_action,
                    allowed_states=(ObserverSessionState.ACTIVE,),
                )
            )
        return tuple(events)

    events, owner_evidence, _frames = invoke_bound_owner(
        executor=executor,
        owner=BackendObserverSession.run,
        scenario_seam_active=True,
        operation=operation,
        expected_owner_entries=requested_count,
    )
    session.close(timeout_seconds=1)
    final = dict(events[-1])
    enacted_family = _BOUNDARY_FAMILIES[str(final["active_boundary"])]
    enacted_count = int(final["operation_generation"])
    enacted = (("schedule", enacted_family), ("schedule_index", enacted_count))
    event_trace = tuple(
        (dict(event)["active_boundary"], dict(event)["operation_generation"])
        for event in events
    )
    observed = (
        ("primary_result_category", f"schedule_terminal:{final['active_boundary']}"),
        ("observed_boundary", final["active_boundary"]),
        ("operation_generation", enacted_count),
        ("event_trace", event_trace),
        ("session_state", session.snapshot().state.value),
    )
    product_events = (
        ("observer_operations", event_trace),
        ("observer_settlement", session.snapshot().state.value),
    )
    return bind_executor_evidence(
        entry,
        enacted_parameters=tuple(enacted),
        observed_fields=observed,
        owner_entry_evidence=owner_evidence,
        scenario_program_identity=program.scenario_id,
        observed_product_events=product_events,
    )


_SOURCE_CODES = {
    "resource_reader": "resource_reader_unavailable",
    "preparation_timeout": "startup_readiness_failed",
    "observation_transfer": "event_transport_failed",
    "ack": "backend_observer_failed",
    "receipt": "receipt_readback_failed",
    "process_settlement": "lifecycle_incomplete",
    "cleanup_limitation": "cleanup_eligibility_unproved",
    "total_wall_retry_gate": "launch_authority_late",
}

def enact_failure_causality(entry: CatalogEntry, *, executor: Callable[..., ExecutorEvidence]) -> ExecutorEvidence:
    """Record C source authority through the accepted causality owner."""

    parameters = dict(entry.parameter_values)
    source = str(parameters["failure_source"])
    case = _integer_parameter(parameters["case"])
    program = scenario_program(
        owner_identity="FailureCausalityAuthority.record_code",
        seam_identity="fix3.causality.source_event",
        input_action=(("source_code", _SOURCE_CODES[source]), ("event_generation", case)),
        expected_product_event_classes=("first_source", "later_limitation"),
        cleanup_contract=entry.cleanup_contract,
        process_boundary_contract=entry.process_boundary_contract,
    )
    clock = iter((10, 20))
    authority = FailureCausalityAuthority(clock_ns=lambda: next(clock))

    def operation():
        first = authority.record_code(
            _SOURCE_CODES[source],
            authority_owner="source_event_dispatch",
            lifecycle_boundary="qualification_executor_seam",
            existed_before_child_release=True,
            test_injected=True,
            source_event_key=program.scenario_id,
        )
        authority.observe(first)
        later_code = next(code for code in _SOURCE_CODES.values() if code != _SOURCE_CODES[source])
        later = authority.record_code(
            later_code,
            authority_owner="later_limitation_dispatch",
            lifecycle_boundary="qualification_executor_seam",
            existed_before_child_release=True,
            test_injected=True,
            source_event_key=f"{program.scenario_id}:later",
        )
        authority.observe(later)

    _, owner_evidence, _frames = invoke_bound_owner(
        executor=executor,
        owner=FailureCausalityAuthority.record_code,
        scenario_seam_active=True,
        operation=operation,
        expected_owner_entries=2,
    )
    snapshot = authority.freeze()
    sources_by_code = {code: name for name, code in _SOURCE_CODES.items()}
    observed_source = sources_by_code[snapshot.candidates[0].code]
    observed_case = _integer_parameter(dict(program.input_action)["event_generation"])
    observed = (
        ("primary_result_category", "classified"),
        ("first_source", observed_source),
        ("later_limitations", tuple(item.code for item in snapshot.candidates[1:])),
        ("causal_sequence", snapshot.candidates[0].causal_sequence),
    )
    product_events = tuple(
        ("causality_candidate", (item.code, item.source_event_key, item.causal_sequence))
        for item in snapshot.candidates
    )
    enacted = (("failure_source", observed_source), ("case", observed_case))
    return bind_executor_evidence(
        entry,
        enacted_parameters=enacted,
        observed_fields=observed,
        owner_entry_evidence=owner_evidence,
        scenario_program_identity=program.scenario_id,
        observed_product_events=product_events,
    )
