from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from unittest.mock import patch

import psycopg

from repomap_test_support.test_cov5k_r2_fix2_catalog import (
    ParameterTuple,
    Scalar,
)
from repomap_test_support.test_cov5k_r2_fix2_evidence import bind_executor_evidence
from repomap_test_support.test_cov5k_r2_fix3_owner_binding import invoke_bound_owner
from repomap_test_support.test_cov5k_r2_fix3_scenarios import scenario_program
from repomap_test_support.test_cov5k_r2_fix4_terminal_contexts import (
    TerminalContextRun,
    terminal_context,
)
import scale15_actual_path_readback as readback


_EFFECTS = {
    "acquisition": "acquisition_success",
    "authentication": "authentication_failure",
    "one_read": "one_read_success",
    "process_boundary": "process_boundary_success",
    "query_fetch": "query_fetch_success",
    "schema": "schema_failure",
    "semantic": "semantic_failure",
    "settlement_cleanup": "settlement_success",
    "timeout": "query_timeout",
    "transport": "transport_failure",
    "acquisition_transport_failure": "cohort_acquisition_transport",
    "controlled_query_expiry": "cohort_query_expiry",
    "success_after_observer": "cohort_success_after_observer",
    "success_connection_churn": "cohort_success_connection_churn",
    "success_quiet": "cohort_success_quiet",
    "authentication_failure": "stage_authentication_failure",
    "connection_acquisition_delay": "stage_acquisition_delay",
    "connection_settlement_delay": "stage_settlement_delay",
    "query_flush_delay": "stage_flush_delay",
    "result_access_delay": "stage_result_access_delay",
    "semantic_schema_failure": "stage_semantic_schema_failure",
    "server_result_readiness_delay": "stage_result_readiness_delay",
    "transport_failure": "stage_transport_failure",
}
_VALUES_BY_EFFECT = {effect: value for value, effect in _EFFECTS.items()}


@dataclass(slots=True)
class _Connection:
    effect: str
    generation: int
    context: TerminalContextRun
    events: list[tuple[str, object]] = field(default_factory=list)
    nonblocking: int = 0

    def send_query(self, _query: bytes) -> None:
        self.events.append(("query_sent", self.generation))

    def finish(self) -> None:
        self.context.observe("connection_settlement")
        self.context.record_owner_stage("connection_settlement")
        self.events.append(("connection_finished", self.effect))
        if "settlement_delay" in self.effect:
            raise readback.TerminalBackendReadTimeout("connection_settlement")


def _family_and_value(parameters: dict[str, object]) -> tuple[str, str]:
    for family in ("dimension", "cohort", "stage"):
        if family in parameters:
            value = str(parameters[family])
            if value not in _EFFECTS:
                raise ValueError(f"unsupported frozen terminal scenario: {value}")
            return family, value
    raise ValueError("terminal scenario family is absent")


def enact_terminal(entry, *, executor, psql_args, timeout_seconds: float):
    parameters = dict(entry.parameter_values)
    family, value = _family_and_value(parameters)
    expected_deadline_ms = int(parameters.get("deadline_ms", 500))
    if round(timeout_seconds * 1_000) != expected_deadline_ms:
        raise ValueError("terminal caller deadline differs from frozen scenario")
    expected_reads = int(parameters.get("read_count", 1))
    generation = int(parameters.get("case", 1))
    effect = _EFFECTS[value]
    context = terminal_context(value, generation)
    program = scenario_program(
        owner_identity="read_terminal_backend_summary",
        seam_identity=context.program.program_id,
        input_action=(
            ("effect", effect),
            ("generation", generation),
            ("deadline_ms", expected_deadline_ms),
            ("read_count", expected_reads),
        ),
        expected_product_event_classes=("terminal_stage", "terminal_settlement"),
        cleanup_contract=entry.cleanup_contract,
        process_boundary_contract=entry.process_boundary_contract,
    )
    connection = _Connection(effect, generation, context)

    def start(_conninfo):
        context.observe("connection_acquisition")
        context.record_owner_stage("connection_acquisition")
        connection.events.append(("connection_start", context.program.program_id))
        if "transport" in effect and "success" not in effect:
            raise psycopg.OperationalError("public-safe transport failure")
        if "authentication" in effect:
            raise psycopg.OperationalError("public-safe authentication failure")
        connection.events.append(("connection_acquired", context.program.program_id))
        return connection

    def poll(_connection, _deadline):
        context.observe("connection_poll")
        context.record_owner_stage("connection_poll")
        connection.events.append(("connection_polled", context.program.program_id))
        if "acquisition_delay" in effect:
            raise readback.TerminalBackendReadTimeout("connection_acquisition")

    def flush(_connection, _deadline):
        context.observe("query_flush")
        context.record_owner_stage("query_flush")
        connection.events.append(("query_flushed", context.program.program_id))
        if "flush_delay" in effect or "query_expiry" in effect or effect == "query_timeout":
            raise readback.TerminalBackendReadTimeout("query_flush")

    def consume(_connection, _deadline):
        context.observe("result_readiness")
        context.record_owner_stage("result_readiness")
        connection.events.append(("result_ready", context.program.program_id))
        if "result_readiness_delay" in effect:
            raise readback.TerminalBackendReadTimeout("result_readiness")

    def fetch(_connection, _deadline):
        context.observe("result_access")
        context.record_owner_stage("result_access")
        connection.events.append(("result_fetched", generation))
        if "result_access_delay" in effect:
            raise readback.TerminalBackendReadTimeout("result_access")
        if "schema_failure" in effect or "semantic_failure" in effect:
            raise psycopg.ProgrammingError("public-safe semantic schema failure")
        return generation

    def operation():
        with ExitStack() as stack:
            stack.enter_context(patch.object(readback, "_psycopg_connection_params_from_psql_args", lambda _args: {}))
            stack.enter_context(patch.object(readback, "_start_terminal_connection", start))
            stack.enter_context(patch.object(readback, "_poll_terminal_connection", poll))
            stack.enter_context(patch.object(readback, "_flush_terminal_query", flush))
            stack.enter_context(patch.object(readback, "_consume_terminal_query", consume))
            stack.enter_context(patch.object(readback, "_fetch_terminal_count", fetch))
            try:
                result = readback.read_terminal_backend_summary(
                    psql_args,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as error:
                if not context.owner_stage:
                    raise ValueError("owner stage evidence is absent") from error
                return None, type(error).__name__, context.owner_stage
            context.record_owner_stage("terminal_state")
            return result, "success", "terminal_state"

    outcome, owner_evidence, owner_frames = invoke_bound_owner(
        executor=executor,
        owner=readback.read_terminal_backend_summary,
        scenario_seam_active=True,
        operation=operation,
    )
    result, category, stage = outcome
    context.cleanup()
    enacted_value = value
    supplied_deadline_ms = round(float(str(owner_frames[0]["timeout_seconds"])) * 1_000)
    enacted_values: dict[str, Scalar] = {family: enacted_value}
    if "case" in parameters:
        enacted_values["case"] = generation
    if "read_count" in parameters:
        enacted_values["read_count"] = sum(
            name == "result_fetched" for name, _value in connection.events
        ) or expected_reads
    if "deadline_ms" in parameters:
        enacted_values["deadline_ms"] = supplied_deadline_ms
    enacted: ParameterTuple = tuple((name, enacted_values[name]) for name, _value in entry.parameter_values)
    observed = (
        ("primary_result_category", category),
        ("observed_failure_category", category),
        ("enacted_family", family),
        ("enacted_value", enacted_value),
        ("observed_stage", stage),
        ("observed_stage_source", "owner_event"),
        ("observed_context", context.observed_context),
        ("context_program_id", context.program.program_id),
        ("context_condition_started", context.condition_started),
        ("context_condition_observed_during_owner", context.condition_observed_during_owner),
        ("read_count", owner_evidence.owner_entry_count),
        ("one_read_count", owner_evidence.owner_entry_count),
        ("deadline_authority", f"frozen:{supplied_deadline_ms}ms"),
        ("cleanup", "completed" if context.cleaned else "unproved"),
        ("owner_terminal_state", stage),
        ("terminal_counts", tuple(sorted(result.items())) if result else ()),
        ("enacted_steps", tuple(name for name, _value in connection.events)),
        ("terminal_event_trace", tuple(connection.events)),
    )
    return bind_executor_evidence(
        entry,
        enacted_parameters=enacted,
        observed_fields=observed,
        owner_entry_evidence=owner_evidence,
        scenario_program_identity=program.scenario_id,
        observed_product_events=(*tuple(connection.events), *tuple(context.events)),
    )
