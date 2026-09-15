"""Parent-owned freshness and final release authority for preparation."""

from __future__ import annotations

import secrets
import time
from typing import Callable, Mapping, NoReturn, Protocol

from scale28_preparation_authority_cleanup import (
    PreparationAuthorityError,
    PreparationAuthoritySnapshot,
    PreparedStartupResourceSample,
    ceil_milliseconds,
    compute_final_release_elapsed_ms,
)
from scale28_preparation_receipts import AcceptedPreparationEvidence
from scale28_preparation_values import (
    BINDING_FIELDS,
    PreparationAttemptExpectations,
    PreparationDeadlinePolicy,
    PreparationRequest,
    PreparationState,
)
from scale28_preparation_worker import (
    PreparationWorkerAttempt,
    PreparationWorkerResult,
)


class _PreparationAttempt(Protocol):
    def run(self) -> PreparationWorkerResult: ...


class _SpecificationLike(Protocol):
    @property
    def digest(self) -> str: ...


class HybridPreparationAuthority:
    """Own preparation acceptance, freshness, and final-release transitions."""

    def __init__(
        self,
        specification: _SpecificationLike,
        bindings: Mapping[str, str],
        policy: PreparationDeadlinePolicy,
        *,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        nonce_factory: Callable[[], str] = lambda: secrets.token_hex(16),
        attempt_factory: Callable[
            ...,
            _PreparationAttempt,
        ] = PreparationWorkerAttempt,
    ) -> None:
        if not isinstance(bindings, Mapping) or set(bindings) != set(BINDING_FIELDS):
            raise ValueError("preparation authority bindings are invalid")
        self._specification = specification
        self._bindings = tuple((name, bindings[name]) for name in BINDING_FIELDS)
        self._policy = policy
        self._clock_ns = clock_ns
        self._nonce_factory = nonce_factory
        self._attempt_factory = attempt_factory
        self._state = PreparationState.UNPREPARED
        self._state_history = [self._state]
        self._accepted: AcceptedPreparationEvidence | None = None
        self._freshness_origin_ns: int | None = None
        self._final_deadline_ns: int | None = None
        self._stable_samples = 0
        self._attempt_failures: list[tuple[str, str]] = []
        self._refusal: str | None = None
        self._worker_observation_elapsed_ms: int | None = None
        self._parent_protocol_elapsed_ms: int | None = None
        self._acknowledgement_to_receipt_elapsed_ms: int | None = None
        self._process_settlement_elapsed_ms: int | None = None
        self._attempt_elapsed_ms: int | None = None
        self._final_release_elapsed_ms: int | None = None

    @property
    def state(self) -> PreparationState:
        return self._state

    @property
    def state_history(self) -> tuple[PreparationState, ...]:
        return tuple(self._state_history)

    @property
    def accepted_evidence(self) -> AcceptedPreparationEvidence | None:
        return self._accepted

    @property
    def startup_handoff_timeout_seconds(self) -> float:
        """Return the frozen attempt bound for pre-preparation ownership."""

        return self._policy.attempt_timeout_ms / 1_000

    @property
    def final_release_remaining_seconds(self) -> float:
        """Project the one parent-owned final deadline without resetting it."""

        if self._final_deadline_ns is None:
            raise PreparationAuthorityError(
                "preparation final release window is unavailable"
            )
        return max(0.0, (self._final_deadline_ns - self._clock_ns()) / 1_000_000_000)

    def snapshot(self) -> PreparationAuthoritySnapshot:
        return PreparationAuthoritySnapshot(
            self._state,
            tuple(self._state_history),
            tuple(self._attempt_failures),
            self._refusal,
            self._worker_observation_elapsed_ms,
            self._parent_protocol_elapsed_ms,
            self._acknowledgement_to_receipt_elapsed_ms,
            self._process_settlement_elapsed_ms,
            self._attempt_elapsed_ms,
            self._final_release_elapsed_ms,
        )

    def prepare(self) -> PreparedStartupResourceSample:
        """Acquire one complete accepted generation within two attempts."""

        if self._state is not PreparationState.UNPREPARED:
            self._refuse("preparation authority state is invalid")
        total_deadline_ns = self._clock_ns() + self._policy.total_timeout_ms * 1_000_000
        last_error: Exception | None = None
        for attempt_number in range(1, self._policy.maximum_attempts + 1):
            if self._clock_ns() >= total_deadline_ns:
                break
            self._transition(PreparationState.PREPARING)
            expectations = PreparationAttemptExpectations(
                self._nonce_factory(),
                attempt_number,
                dict(self._bindings),
            )
            request = PreparationRequest.create(
                expectations,
                self._specification.digest,
            )
            try:
                result = self._attempt_factory(
                    request,
                    self._specification,
                    self._policy,
                ).run()
                self._accept_worker_result(result)
                return PreparedStartupResourceSample(
                    result.evidence.resource_baseline
                )
            except Exception as error:
                last_error = error
                category = str(getattr(error, "category", "worker_failed"))
                boundary = str(getattr(error, "boundary", "worker"))
                self._attempt_failures.append(
                    (category, boundary)
                )
                self._accepted = None
                self._freshness_origin_ns = None
                if (
                    category != "cleanup_limitation"
                    and attempt_number < self._policy.maximum_attempts
                ):
                    continue
                break
        self._transition(PreparationState.REFUSED)
        message = "startup resource preparation failed"
        if last_error is None:
            raise PreparationAuthorityError(message)
        raise PreparationAuthorityError(message) from last_error

    def _accept_worker_result(self, result: PreparationWorkerResult) -> None:
        result.evidence.assert_canonical()
        if not (
            result.observation_received_parent_ns
            <= result.receipt_received_parent_ns
            <= result.worker_settled_parent_ns
        ):
            raise PreparationAuthorityError(
                "preparation parent ordering is invalid"
            )
        self._transition(PreparationState.OBSERVATION_RECEIVED)
        self._transition(PreparationState.OBSERVATION_ACKNOWLEDGED)
        self._transition(PreparationState.RECEIPT_RECEIVED)
        self._transition(PreparationState.RECEIPT_VALIDATED)
        self._accepted = result.evidence
        worker_elapsed_ns = (
            result.evidence.observation.observation_completed_ns
            - result.evidence.observation.observation_started_ns
        )
        parent_protocol_ns = (
            result.worker_settled_parent_ns
            - result.observation_received_parent_ns
        )
        acknowledgement_to_receipt_ns = (
            result.receipt_received_parent_ns
            - result.observation_received_parent_ns
        )
        process_settlement_ns = (
            result.worker_settled_parent_ns
            - result.receipt_received_parent_ns
        )
        self._worker_observation_elapsed_ms = _ceil_milliseconds(
            worker_elapsed_ns
        )
        self._parent_protocol_elapsed_ms = _ceil_milliseconds(
            parent_protocol_ns
        )
        self._acknowledgement_to_receipt_elapsed_ms = _ceil_milliseconds(
            acknowledgement_to_receipt_ns
        )
        self._process_settlement_elapsed_ms = _ceil_milliseconds(
            process_settlement_ns
        )
        self._attempt_elapsed_ms = _ceil_milliseconds(
            result.attempt_elapsed_parent_ns
        )
        self._freshness_origin_ns = max(
            0,
            result.observation_received_parent_ns
            - self._policy.observation_transfer_reserve_ms * 1_000_000,
        )
        self._assert_fresh()
        self._transition(PreparationState.WORKER_SETTLED)
        self._assert_fresh()
        self._transition(PreparationState.FRESHNESS_VALIDATED)

    def open_final_readiness(self) -> None:
        self._require_state(PreparationState.FRESHNESS_VALIDATED)
        self._assert_fresh()
        self._final_deadline_ns = (
            self._clock_ns()
            + self._policy.final_release_timeout_ms * 1_000_000
        )
        self._transition(PreparationState.FINAL_READINESS_OPEN)

    def mark_transient_ownership_clear(self) -> None:
        self._require_state(PreparationState.FINAL_READINESS_OPEN)
        self._assert_final_window()
        self._assert_fresh()
        self._transition(PreparationState.TRANSIENT_OWNERSHIP_CLEAR)

    def mark_stable_sample(self) -> None:
        expected = (
            PreparationState.TRANSIENT_OWNERSHIP_CLEAR
            if self._stable_samples == 0
            else PreparationState.STABLE_SAMPLE_ONE
        )
        self._require_state(expected)
        self._assert_final_window()
        self._assert_fresh()
        self._stable_samples += 1
        self._transition(
            PreparationState.STABLE_SAMPLE_ONE
            if self._stable_samples == 1
            else PreparationState.STABLE_SAMPLE_TWO
        )

    def mark_stable_samples(
        self,
        first_parent_ns: int,
        second_parent_ns: int,
    ) -> None:
        self._require_state(PreparationState.TRANSIENT_OWNERSHIP_CLEAR)
        if (
            isinstance(first_parent_ns, bool)
            or not isinstance(first_parent_ns, int)
            or isinstance(second_parent_ns, bool)
            or not isinstance(second_parent_ns, int)
            or first_parent_ns < 0
            or first_parent_ns > second_parent_ns
        ):
            self._refuse("preparation stable sample ordering is invalid")
        self._assert_final_window(at_ns=first_parent_ns)
        self._assert_fresh(at_ns=first_parent_ns)
        self._stable_samples = 1
        self._transition(PreparationState.STABLE_SAMPLE_ONE)
        self._assert_final_window(at_ns=second_parent_ns)
        self._assert_fresh(at_ns=second_parent_ns)
        self._stable_samples = 2
        self._transition(PreparationState.STABLE_SAMPLE_TWO)

    def mark_ready_to_release(self) -> None:
        self._require_state(PreparationState.STABLE_SAMPLE_TWO)
        self._assert_final_window()
        self._assert_fresh()
        self._transition(PreparationState.READY_TO_RELEASE)

    def mark_child_released(self) -> None:
        self._require_state(PreparationState.READY_TO_RELEASE)
        if self._final_deadline_ns is None:
            self._refuse("preparation final release window is unavailable")
        final_started_ns = (
            self._final_deadline_ns
            - self._policy.final_release_timeout_ms * 1_000_000
        )
        self._final_release_elapsed_ms = _ceil_milliseconds(
            self._clock_ns() - final_started_ns
        )
        self._transition(PreparationState.CHILD_RELEASED)

    def refuse(self) -> None:
        if self._state not in {
            PreparationState.CHILD_RELEASED,
            PreparationState.SETTLED,
        }:
            self._record_final_release_elapsed()
            self._transition(PreparationState.REFUSED)

    def settle(self) -> None:
        if self._state not in {
            PreparationState.CHILD_RELEASED,
            PreparationState.REFUSED,
        }:
            self.refuse()
        self._transition(PreparationState.SETTLED)

    def _assert_fresh(self, *, at_ns: int | None = None) -> None:
        if self._freshness_origin_ns is None:
            self._refuse("preparation freshness authority is unavailable")
        age_ns = (
            self._clock_ns() if at_ns is None else at_ns
        ) - self._freshness_origin_ns
        if (
            age_ns < 0
            or age_ns > self._policy.freshness_lease_ms * 1_000_000
        ):
            self._refuse("preparation evidence is stale")

    def _assert_final_window(self, *, at_ns: int | None = None) -> None:
        observed_ns = self._clock_ns() if at_ns is None else at_ns
        if (
            self._final_deadline_ns is None
            or observed_ns > self._final_deadline_ns
        ):
            self._refuse("preparation final release window expired")

    def _record_final_release_elapsed(self) -> None:
        elapsed = compute_final_release_elapsed_ms(
            self._final_deadline_ns,
            self._policy.final_release_timeout_ms,
            self._clock_ns,
            ceil_milliseconds_fn=_ceil_milliseconds,
        )
        if elapsed is not None:
            self._final_release_elapsed_ms = elapsed

    def _require_state(self, expected: PreparationState) -> None:
        if self._state is not expected:
            self._refuse("preparation authority state is invalid")

    def _refuse(self, message: str) -> NoReturn:
        self._refusal = message
        self._record_final_release_elapsed()
        if self._state is not PreparationState.REFUSED:
            self._transition(PreparationState.REFUSED)
        raise PreparationAuthorityError(message)

    def _transition(self, state: PreparationState) -> None:
        self._state = state
        self._state_history.append(state)


_ceil_milliseconds = ceil_milliseconds


__all__ = [
    "HybridPreparationAuthority",
    "PreparationAuthorityError",
    "PreparationAuthoritySnapshot",
    "PreparedStartupResourceSample",
]
