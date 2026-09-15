"""Observed campaign-result authority for SCALE28-ADR2-FIX2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


PROTOCOL_REVISION = "scale28-adr2-revision-4"


class PreparationCaseFailure(RuntimeError):
    """Structured failure emitted by the exercised authority boundary."""

    def __init__(
        self,
        *,
        category: str,
        source_boundary: str,
        state_machine_terminal_state: str,
        secondary_categories: tuple[str, ...] = (),
    ) -> None:
        _validate_text(category, "failure category")
        _validate_text(source_boundary, "failure source boundary")
        _validate_text(
            state_machine_terminal_state,
            "failure terminal state",
        )
        _validate_categories(category, secondary_categories)
        self.category = category
        self.source_boundary = source_boundary
        self.state_machine_terminal_state = state_machine_terminal_state
        self.secondary_categories = secondary_categories
        super().__init__(f"{category} at {source_boundary}")


@dataclass(frozen=True, slots=True)
class ObservedPreparationCleanup:
    """Counts measured after one case's process and channel settlement."""

    process_tree_settled: bool
    worker_connection_count: int
    reader_count: int
    thread_count: int
    descriptor_channel_count: int

    def __post_init__(self) -> None:
        for count in (
            self.worker_connection_count,
            self.reader_count,
            self.thread_count,
            self.descriptor_channel_count,
        ):
            _validate_count(count)

    @property
    def complete(self) -> bool:
        """Return cleanup derived only from measured settlement facts."""

        return self.process_tree_settled is True and not any(
            (
                self.worker_connection_count,
                self.reader_count,
                self.thread_count,
                self.descriptor_channel_count,
            )
        )


@dataclass(frozen=True, slots=True)
class PreparationCaseObservation:
    """Actual post-exercise state read by the campaign harness."""

    release_occurred: bool
    state_machine_terminal_state: str
    process_exit_code: int | None
    process_signal: str | None
    cleanup: ObservedPreparationCleanup
    frame_count: int
    acknowledgement_count: int
    receipt_count: int
    attempt: int
    generation_class: str
    readiness_order: tuple[str, ...] = ()
    preparation_ms: int | None = None
    frame_to_receipt_ms: int | None = None
    frame_to_release_ms: int | None = None
    final_release_ms: int | None = None

    def __post_init__(self) -> None:
        _validate_text(self.state_machine_terminal_state, "terminal state")
        _validate_text(self.generation_class, "generation class")
        if self.process_exit_code is not None:
            _validate_count(self.process_exit_code)
        if self.process_signal is not None:
            _validate_text(self.process_signal, "process signal")
        if self.process_exit_code is not None and self.process_signal is not None:
            raise ValueError("process exit and signal are mutually exclusive")
        for count in (
            self.frame_count,
            self.acknowledgement_count,
            self.receipt_count,
        ):
            _validate_count(count)
        if self.attempt not in (1, 2):
            raise ValueError("observed attempt is invalid")
        if not isinstance(self.readiness_order, tuple):
            raise ValueError("readiness order must be an immutable tuple")
        if len(set(self.readiness_order)) != len(self.readiness_order):
            raise ValueError("readiness order contains duplicate facts")
        for fact in self.readiness_order:
            _validate_text(fact, "readiness fact")
        for duration in (
            self.preparation_ms,
            self.frame_to_receipt_ms,
            self.frame_to_release_ms,
            self.final_release_ms,
        ):
            if duration is not None:
                _validate_count(duration)


@dataclass(frozen=True, slots=True)
class ObservedPreparationCaseResult:
    """One closed result containing observations and no expected outcome."""

    case_id: str
    cohort: str
    scenario: str
    protocol_revision: str
    first_causal_category: str
    source_boundary: str
    secondary_categories: tuple[str, ...]
    release_decision: str
    state_machine_terminal_state: str
    process_exit_code: int | None
    process_signal: str | None
    process_tree_settled: bool
    worker_connection_count: int
    reader_count: int
    thread_count: int
    descriptor_channel_count: int
    cleanup_complete: bool
    frame_count: int
    acknowledgement_count: int
    receipt_count: int
    attempt: int
    generation_class: str
    valid: bool
    readiness_order: tuple[str, ...] = ()
    preparation_ms: int | None = None
    frame_to_receipt_ms: int | None = None
    frame_to_release_ms: int | None = None
    final_release_ms: int | None = None
    owning_path_identity: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.case_id, "case id"),
            (self.cohort, "cohort"),
            (self.scenario, "scenario"),
            (self.first_causal_category, "first causal category"),
            (self.source_boundary, "source boundary"),
            (self.state_machine_terminal_state, "terminal state"),
            (self.generation_class, "generation class"),
        ):
            _validate_text(value, label)
        if self.protocol_revision != PROTOCOL_REVISION:
            raise ValueError("campaign protocol revision is invalid")
        _validate_categories(
            self.first_causal_category,
            self.secondary_categories,
        )
        if self.release_decision not in {"released", "refused"}:
            raise ValueError("release decision is invalid")
        cleanup = ObservedPreparationCleanup(
            self.process_tree_settled,
            self.worker_connection_count,
            self.reader_count,
            self.thread_count,
            self.descriptor_channel_count,
        )
        if self.cleanup_complete is not cleanup.complete:
            raise ValueError("cleanup result is not derived from observed facts")
        if self.release_decision == "released" and not self.cleanup_complete:
            raise ValueError("release requires complete cleanup")
        PreparationCaseObservation(
            release_occurred=self.release_decision == "released",
            state_machine_terminal_state=self.state_machine_terminal_state,
            process_exit_code=self.process_exit_code,
            process_signal=self.process_signal,
            cleanup=cleanup,
            frame_count=self.frame_count,
            acknowledgement_count=self.acknowledgement_count,
            receipt_count=self.receipt_count,
            attempt=self.attempt,
            generation_class=self.generation_class,
            readiness_order=self.readiness_order,
            preparation_ms=self.preparation_ms,
            frame_to_receipt_ms=self.frame_to_receipt_ms,
            frame_to_release_ms=self.frame_to_release_ms,
            final_release_ms=self.final_release_ms,
        )
        if self.valid is not True:
            raise ValueError("observed campaign result is invalid")
        if self.owning_path_identity is not None:
            _validate_text(self.owning_path_identity, "owning path identity")

    def to_mapping(self) -> dict[str, object]:
        """Return a detached JSON-safe observation without expectations."""

        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class PreparationCaseExpectation:
    """Separate test expectation never serialized as an observation."""

    first_causal_category: str
    source_boundary: str
    release_decision: str
    state_machine_terminal_state: str
    cleanup_complete: bool


ObservationReader = Callable[[], PreparationCaseObservation]
Operation = Callable[[], object]


def exercise_and_observe_case(
    *,
    case_id: str,
    cohort: str,
    scenario: str,
    operation: Operation,
    observe: ObservationReader,
    owning_path_identity: str | None = None,
) -> ObservedPreparationCaseResult:
    """Exercise first, read facts second, then construct one observed result."""

    failure: PreparationCaseFailure | None = None
    try:
        operation()
    except PreparationCaseFailure as error:
        failure = error
    observation = observe()
    if failure is None:
        category = "complete"
        boundary = "successful_completion"
        secondaries: tuple[str, ...] = ()
    else:
        category = failure.category
        boundary = failure.source_boundary
        secondaries = failure.secondary_categories
        if observation.state_machine_terminal_state != (
            failure.state_machine_terminal_state
        ):
            raise ValueError("observed terminal state differs from failure authority")
    return ObservedPreparationCaseResult(
        case_id=case_id,
        cohort=cohort,
        scenario=scenario,
        protocol_revision=PROTOCOL_REVISION,
        first_causal_category=category,
        source_boundary=boundary,
        secondary_categories=secondaries,
        release_decision=(
            "released" if observation.release_occurred else "refused"
        ),
        state_machine_terminal_state=observation.state_machine_terminal_state,
        process_exit_code=observation.process_exit_code,
        process_signal=observation.process_signal,
        process_tree_settled=observation.cleanup.process_tree_settled,
        worker_connection_count=observation.cleanup.worker_connection_count,
        reader_count=observation.cleanup.reader_count,
        thread_count=observation.cleanup.thread_count,
        descriptor_channel_count=(
            observation.cleanup.descriptor_channel_count
        ),
        cleanup_complete=observation.cleanup.complete,
        frame_count=observation.frame_count,
        acknowledgement_count=observation.acknowledgement_count,
        receipt_count=observation.receipt_count,
        attempt=observation.attempt,
        generation_class=observation.generation_class,
        valid=True,
        readiness_order=observation.readiness_order,
        preparation_ms=observation.preparation_ms,
        frame_to_receipt_ms=observation.frame_to_receipt_ms,
        frame_to_release_ms=observation.frame_to_release_ms,
        final_release_ms=observation.final_release_ms,
        owning_path_identity=owning_path_identity,
    )


def assert_case_expectation(
    result: ObservedPreparationCaseResult,
    expectation: PreparationCaseExpectation,
) -> None:
    """Compare an observed result with a separate exact expectation."""

    actual = (
        result.first_causal_category,
        result.source_boundary,
        result.release_decision,
        result.state_machine_terminal_state,
        result.cleanup_complete,
    )
    expected = (
        expectation.first_causal_category,
        expectation.source_boundary,
        expectation.release_decision,
        expectation.state_machine_terminal_state,
        expectation.cleanup_complete,
    )
    if actual != expected:
        raise AssertionError(f"observed result {actual!r} != expectation {expected!r}")


def _validate_categories(first: str, secondaries: tuple[str, ...]) -> None:
    if not isinstance(secondaries, tuple):
        raise ValueError("secondary categories must be an immutable tuple")
    if first in secondaries or len(set(secondaries)) != len(secondaries):
        raise ValueError("causal categories are not uniquely ordered")
    for category in secondaries:
        _validate_text(category, "secondary category")


def _validate_count(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("observed count is invalid")


def _validate_text(value: object, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is invalid")
