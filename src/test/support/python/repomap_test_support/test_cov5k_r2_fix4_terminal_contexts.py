"""Behavioral terminal contexts observed during the registered owner call."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Mapping, Protocol

from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest


@dataclass(frozen=True, slots=True)
class TerminalContextProgram:
    program_id: str
    action: str
    observe_at: str


def _program(action: str, observe_at: str) -> TerminalContextProgram:
    return TerminalContextProgram(
        canonical_digest(
            ("test-cov5k-r2-fix4-terminal-context-v1", action, observe_at)
        ),
        action,
        observe_at,
    )


_PROGRAMS: Mapping[str, TerminalContextProgram] = MappingProxyType(
    {
        "acquisition": _program("verify_connector_acquisition", "connection_acquisition"),
        "authentication": _program("typed_authentication_rejection", "connection_acquisition"),
        "one_read": _program("verify_single_owner_read", "result_access"),
        "process_boundary": _program("verify_owner_process_boundary", "connection_poll"),
        "query_fetch": _program("verify_query_fetch", "result_access"),
        "schema": _program("typed_schema_rejection", "result_access"),
        "semantic": _program("typed_semantic_rejection", "result_access"),
        "settlement_cleanup": _program("verify_connection_settlement", "connection_settlement"),
        "timeout": _program("typed_query_timeout", "query_flush"),
        "transport": _program("typed_transport_rejection", "connection_acquisition"),
        "acquisition_transport_failure": _program(
            "cohort_transport_rejection", "connection_acquisition"
        ),
        "controlled_query_expiry": _program("cohort_query_expiry", "query_flush"),
        "success_after_observer": _program(
            "observe_prior_observer_generation", "connection_acquisition"
        ),
        "success_connection_churn": _program(
            "observe_connection_churn", "connection_acquisition"
        ),
        "success_quiet": _program("observe_quiet_window", "connection_acquisition"),
        "authentication_failure": _program(
            "stage_authentication_rejection", "connection_acquisition"
        ),
        "connection_acquisition_delay": _program(
            "stage_acquisition_timeout", "connection_poll"
        ),
        "connection_settlement_delay": _program(
            "stage_settlement_timeout", "connection_settlement"
        ),
        "query_flush_delay": _program("stage_flush_timeout", "query_flush"),
        "result_access_delay": _program("stage_result_access_timeout", "result_access"),
        "semantic_schema_failure": _program(
            "stage_semantic_schema_rejection", "result_access"
        ),
        "server_result_readiness_delay": _program(
            "stage_result_readiness_timeout", "result_readiness"
        ),
        "transport_failure": _program(
            "stage_transport_rejection", "connection_acquisition"
        ),
    }
)


@dataclass(slots=True)
class TerminalContextRun:
    program: TerminalContextProgram
    generation: int
    events: list[tuple[str, object]] = field(default_factory=list)
    condition_started: bool = False
    condition_observed_during_owner: bool = False
    observed_context: str = ""
    owner_stage: str = ""
    cleaned: bool = False
    observer_generation: int = 0
    connection_attempts: int = 0

    def start(self) -> None:
        self.condition_started = True
        if self.program.action == "observe_prior_observer_generation":
            self.observer_generation = self.generation
            self.events.append(("observer_activity", self.observer_generation))
        elif self.program.action == "observe_connection_churn":
            self.connection_attempts = 2
            self.events.append(("connection_churn", self.connection_attempts))
        self.events.append(("context_condition_started", self.program.program_id))

    def observe(self, stage: str) -> None:
        self.events.append(("context_hook", stage))
        if stage != self.program.observe_at or self.condition_observed_during_owner:
            return
        self.condition_observed_during_owner = True
        if self.program.action == "observe_prior_observer_generation":
            self.observed_context = f"observer_generation:{self.observer_generation}"
        elif self.program.action == "observe_connection_churn":
            self.observed_context = f"connection_attempts:{self.connection_attempts}"
        elif self.program.action == "observe_quiet_window":
            self.observed_context = "quiet_activity:0"
        else:
            self.observed_context = f"owner_hook:{stage}"
        self.events.append(("context_condition_observed", self.observed_context))

    def record_owner_stage(self, stage: str) -> None:
        self.owner_stage = stage
        self.events.append(("owner_stage", stage))

    def cleanup(self) -> None:
        self.cleaned = True
        self.events.append(("context_cleanup", "completed"))


def terminal_context(value: str, generation: int) -> TerminalContextRun:
    try:
        program = _PROGRAMS[value]
    except KeyError as error:
        raise ValueError("terminal context has no immutable program") from error
    run = TerminalContextRun(program, generation)
    run.start()
    return run


class TerminalResultContext(Protocol):
    observed_fields: Iterable[tuple[str, object]]
    scenario_program_identity: str


def verify_terminal_context_distinctions(results: Iterable[TerminalResultContext]) -> None:
    """Reject one successful trace reused as authority for distinct contexts."""

    material = tuple(results)
    contexts = tuple(dict(result.observed_fields)["context_program_id"] for result in material)
    scenarios = tuple(result.scenario_program_identity for result in material)
    traces = tuple(
        dict(result.observed_fields)["terminal_event_trace"] for result in material
    )
    if len(set(contexts)) != len(contexts):
        raise ValueError("terminal context program was reused")
    if len(set(scenarios)) != len(scenarios):
        raise ValueError("terminal scenario program was reused")
    if len(set(traces)) != len(traces):
        raise ValueError("terminal owner trace was reused")
