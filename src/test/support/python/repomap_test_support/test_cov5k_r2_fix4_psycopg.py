"""Registered-owner Psycopg programs and frozen raw-evidence classifier."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Iterator, Mapping, Sequence
from unittest.mock import patch

import psycopg

from repomap_kg.storage.authority import PublicationGenerations
from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest
from repomap_test_support.test_cov5k_r2_fix2_evidence import (
    ExecutorEvidence,
    bind_executor_evidence,
)
from repomap_test_support.test_cov5k_r2_fix3_owner_binding import invoke_bound_owner
from repomap_test_support.test_cov5k_r2_fix3_scenarios import scenario_program
import scale15_actual_path_readback as readback
from scale15_terminal_contracts import (
    CleanupState,
    ExpectedRefreshAuthority,
    PublicationState,
    StageState,
    TerminalReadback,
)


class PsycopgTaxonomyError(ValueError):
    """Raw owner evidence cannot support one frozen category."""


def registered_psycopg_owner() -> Callable[..., TerminalReadback]:
    """Return the immutable registered owner used by the delegated executor."""

    return readback.read_scale15_terminal_state


@dataclass(frozen=True, slots=True)
class PsycopgOwnerProgram:
    program_id: str
    evidence_kind: str
    publication_state: PublicationState | None = None
    sqlstate: str | None = None
    exception_family: str | None = None
    transport_cause: bool = False


@dataclass(frozen=True, slots=True)
class PsycopgOwnerObservation:
    publication_state: str | None
    exception_class: str | None
    sqlstate: str | None
    transport_marker: str | None
    authentication_marker: str | None
    semantic_schema_marker: str | None
    observed_stage: str
    owner_events: tuple[tuple[str, object], ...]


class _ProgramOperationalError(psycopg.OperationalError):
    def __init__(self, sqlstate: str | None) -> None:
        super().__init__("public-safe Psycopg operational failure")
        self.sqlstate = sqlstate


class _ProgramProgrammingError(psycopg.ProgrammingError):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("public-safe Psycopg semantic schema failure")
        self.sqlstate = sqlstate


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, *_args, **_kwargs):
        return self

    def fetchone(self):
        return None


def public_expected_authority() -> ExpectedRefreshAuthority:
    """Return the public-safe authority used by deterministic owner programs."""

    return ExpectedRefreshAuthority(
        repository_identity="repo1:public-fixture",
        repository_name="public-fixture",
        generations=PublicationGenerations(
            "sg1:source", "cg1:config", "eg1:extractor", "kg1:canonicalizer"
        ),
        execution_mode="direct",
        zero_state_first_publication=True,
        expected_family_counts={
            "files": 1,
            "raw_observations": 2,
            "canonical_nodes": 3,
            "canonical_edges": 1,
            "canonical_evidence": 2,
            "canonical_node_evidence": 2,
            "canonical_edge_evidence": 1,
        },
        expected_structural_digest="a" * 64,
    ).validate()


def _program(
    *,
    evidence_kind: str,
    publication_state: PublicationState | None = None,
    sqlstate: str | None = None,
    exception_family: str | None = None,
    transport_cause: bool = False,
) -> PsycopgOwnerProgram:
    material = {
        "evidence_kind": evidence_kind,
        "publication_state": publication_state,
        "sqlstate": sqlstate,
        "exception_family": exception_family,
        "transport_cause": transport_cause,
    }
    return PsycopgOwnerProgram(
        canonical_digest(("test-cov5k-r2-fix4-psycopg-program-v1", material)),
        evidence_kind=evidence_kind,
        publication_state=publication_state,
        sqlstate=sqlstate,
        exception_family=exception_family,
        transport_cause=transport_cause,
    )


_PROGRAMS: Mapping[str, PsycopgOwnerProgram] = MappingProxyType(
    {
        "TEST-COV5K-R2-AUTH-0381": _program(
            evidence_kind="driver_exception", sqlstate="28P01", exception_family="operational"
        ),
        "TEST-COV5K-R2-AUTH-0382": _program(
            evidence_kind="driver_exception", sqlstate="08006", exception_family="operational"
        ),
        "TEST-COV5K-R2-AUTH-0383": _program(
            evidence_kind="driver_exception", sqlstate="42P01", exception_family="programming"
        ),
        "TEST-COV5K-R2-AUTH-0384": _program(
            evidence_kind="publication_state", publication_state=PublicationState.PUBLISHED
        ),
        "TEST-COV5K-R2-AUTH-0385": _program(
            evidence_kind="driver_exception", exception_family="operational", transport_cause=True
        ),
        "TEST-COV5K-R2-AUTH-0386": _program(
            evidence_kind="publication_state", publication_state=PublicationState.NOT_PUBLISHED
        ),
    }
)


@dataclass(slots=True)
class PsycopgProgramRun:
    program: PsycopgOwnerProgram
    events: list[tuple[str, object]] = field(default_factory=list)
    condition_started: bool = False
    condition_observed_during_owner: bool = False
    cleaned: bool = False

    def start(self) -> None:
        self.condition_started = True
        self.events.append(("context_condition_started", self.program.program_id))

    def observe(self, boundary: str) -> None:
        self.condition_observed_during_owner = True
        self.events.append(("context_condition_observed", boundary))
        self.events.append(("owner_stage", boundary))

    def cleanup(self) -> None:
        self.cleaned = True
        self.events.append(("context_cleanup", "completed"))


def _terminal_readback(state: PublicationState) -> TerminalReadback:
    return TerminalReadback(
        state,
        StageState.PUBLISHED_RECONCILED,
        CleanupState.COMPLETED,
        {},
        "0" * 64,
        1,
        1,
    )


def _raise_program_exception(run: PsycopgProgramRun):
    run.observe("driver_connect")
    program = run.program
    if program.exception_family == "programming":
        raise _ProgramProgrammingError(program.sqlstate or "42P01")
    error = _ProgramOperationalError(program.sqlstate)
    if program.transport_cause:
        error.__cause__ = ConnectionRefusedError("public-safe connection refusal")
    raise error


@contextmanager
def enact_psycopg_program(authority_id: str) -> Iterator[PsycopgProgramRun]:
    try:
        program = _PROGRAMS[authority_id]
    except KeyError as error:
        raise PsycopgTaxonomyError("Psycopg authority has no frozen owner program") from error
    run = PsycopgProgramRun(program)
    run.start()
    with ExitStack() as stack:
        if program.evidence_kind == "driver_exception":
            stack.enter_context(
                patch.object(
                    readback,
                    "read_run_authority",
                    lambda *_args, **_kwargs: _raise_program_exception(run),
                )
            )
        else:
            def read_authority(*_args, **_kwargs):
                run.observe("publication_readback")
                return object()

            stack.enter_context(patch.object(readback, "read_run_authority", read_authority))
            stack.enter_context(
                patch.object(
                    readback,
                    "read_latest_receipt_bearing_publication",
                    lambda *_args, **_kwargs: object(),
                )
            )
            stack.enter_context(
                patch.object(
                    readback,
                    "_psycopg_connection_params_from_psql_args",
                    lambda _args: {},
                )
            )
            stack.enter_context(
                patch.object(readback.psycopg, "connect", lambda **_kwargs: _Connection())
            )
            stack.enter_context(
                patch.object(
                    readback,
                    "classify_terminal_evidence",
                    lambda *_args, **_kwargs: _terminal_readback(
                        program.publication_state or PublicationState.UNPROVED
                    ),
                )
            )
        try:
            yield run
        finally:
            run.cleanup()


def observe_psycopg_owner(
    result: TerminalReadback | None,
    error: BaseException | None,
    events: tuple[tuple[str, object], ...],
) -> PsycopgOwnerObservation:
    publication_state = None if result is None else result.publication_state.value
    exception_class = None if error is None else f"{type(error).__module__}.{type(error).__qualname__}"
    sqlstate = None if error is None else getattr(error, "sqlstate", None)
    cause = None if error is None else error.__cause__
    transport = "connection_refused" if isinstance(cause, ConnectionRefusedError) else None
    authentication = "sqlstate_class_28" if sqlstate and sqlstate.startswith("28") else None
    semantic = (
        "sqlstate_class_42"
        if sqlstate and sqlstate.startswith("42")
        else "programming_error"
        if isinstance(error, psycopg.ProgrammingError)
        else None
    )
    stage = next(
        (str(value) for name, value in reversed(events) if name == "owner_stage"),
        "owner_stage_missing",
    )
    return PsycopgOwnerObservation(
        publication_state,
        exception_class,
        sqlstate,
        transport,
        authentication,
        semantic,
        stage,
        events,
    )


def classify_psycopg_observation(observation: PsycopgOwnerObservation) -> str:
    """Map only typed raw owner evidence onto the frozen six-category taxonomy."""

    if observation.transport_marker == "connection_refused":
        return "transport_refusal"
    if observation.authentication_marker == "sqlstate_class_28":
        return "authentication"
    if observation.sqlstate and observation.sqlstate.startswith("08"):
        return "class_08"
    if observation.semantic_schema_marker in {"sqlstate_class_42", "programming_error"}:
        return "semantic_schema"
    if observation.publication_state == PublicationState.PUBLISHED.value:
        return "success"
    if observation.publication_state == PublicationState.NOT_PUBLISHED.value:
        return "unavailable"
    raise PsycopgTaxonomyError("owner evidence does not support a frozen Psycopg category")


def execute_registered_psycopg_read(
    entry,
    *,
    executor: Callable[..., object],
    psql_args: Sequence[str],
    expected_authority: ExpectedRefreshAuthority,
    psql_executable: str,
) -> ExecutorEvidence:
    parameters = dict(entry.parameter_values)
    with enact_psycopg_program(entry.authority_id) as run:
        program = scenario_program(
            owner_identity="read_scale15_terminal_state",
            seam_identity=run.program.program_id,
            input_action=(
                ("mode", str(parameters["mode"])),
                ("owner_program_id", run.program.program_id),
                ("automatic_fallback", False),
            ),
            expected_product_event_classes=("owner_stage", "raw_owner_observation"),
            cleanup_contract=entry.cleanup_contract,
            process_boundary_contract=entry.process_boundary_contract,
        )

        def operation() -> PsycopgOwnerObservation:
            result = None
            error = None
            try:
                result = readback.read_scale15_terminal_state(
                    psql_args,
                    expected_authority,
                    psql_command=psql_executable,
                )
            except Exception as caught:
                error = caught
            return observe_psycopg_owner(result, error, tuple(run.events))

        observation, owner_evidence, _frames = invoke_bound_owner(
            executor=executor,
            owner=readback.read_scale15_terminal_state,
            scenario_seam_active=True,
            operation=operation,
        )
        category = classify_psycopg_observation(observation)
    observed = (
        ("driver", "psycopg"),
        ("mode", parameters["mode"]),
        ("failure_category", category),
        ("observed_failure_category", category),
        ("automatic_fallback", False),
        ("publication_state", observation.publication_state),
        ("exception_class", observation.exception_class),
        ("sqlstate", observation.sqlstate),
        ("transport_marker", observation.transport_marker),
        ("authentication_marker", observation.authentication_marker),
        ("semantic_schema_marker", observation.semantic_schema_marker),
        ("observed_stage", observation.observed_stage),
        ("observed_stage_source", "owner_event"),
        ("observed_context", run.program.program_id),
        ("context_program_id", run.program.program_id),
        ("context_condition_started", run.condition_started),
        ("context_condition_observed_during_owner", run.condition_observed_during_owner),
        ("host_process_count", 1),
        ("nested_psql_intent_count", 0),
        ("one_read_disposition", "single_owner_operation"),
        ("cleanup", "completed" if run.cleaned else "unproved"),
    )
    enacted = (
        ("driver", "psycopg"),
        ("mode", parameters["mode"]),
        ("failure_category", category),
        ("automatic_fallback", False),
    )
    product_events = (
        *observation.owner_events,
        ("raw_owner_observation", observation),
        ("context_cleanup", "completed" if run.cleaned else "unproved"),
    )
    return bind_executor_evidence(
        entry,
        enacted_parameters=enacted,
        observed_fields=observed,
        owner_entry_evidence=owner_evidence,
        scenario_program_identity=program.scenario_id,
        observed_product_events=product_events,
    )
