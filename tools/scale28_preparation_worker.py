"""Spawn-safe isolated preparation worker and parent terminal settlement."""

from __future__ import annotations

from dataclasses import dataclass
from multiprocessing import get_context
from multiprocessing.connection import Connection, wait as wait
import os
import time
from typing import Callable

from scale28_preparation_frames import (
    PreparationObservation,
    PreparationObservationAcknowledgement,
)
from scale28_preparation_ipc import (
    ACKNOWLEDGEMENT_MESSAGE,
    BoundedMessageSpec,
    OBSERVATION_MESSAGE,
    READINESS_MESSAGE as READINESS_MESSAGE,
    RECEIPT_MESSAGE,
    receive_one_bounded as receive_one_bounded,
    send_one_bounded as send_one_bounded,
)
from scale28_preparation_receipts import (
    AcceptedPreparationEvidence,
    ParentObservedTerminalFacts,
    PreparationTerminalReceiptV3,
    validate_parent_terminal_facts,
)
from scale28_preparation_resources import (
    PreparationResourceSpecification,
    PreparedResourceHandleLike,
    prepare_resources,
)
from scale28_preparation_values import (
    PreparationDeadlinePolicy,
    PreparationRequest,
    SIGTERM_JOIN_MS as SIGTERM_JOIN_MS,
)
from scale28_preparation_worker_bootstrap import (
    _EventLike as _EventLike,
    _preparation_worker_main as _bootstrap_preparation_worker_main,
    _retain_minimal_worker_environment as _retain_minimal_worker_environment,
    await_worker_readiness,
    receive_success_or_failure,
    semantic_deadline,
)
from scale28_preparation_worker_process import (
    PreparationWorkerError as PreparationWorkerError,
    _Closeable,
    _SpawnProcessLike,
    _StartableProcess,
    _TerminableProcess,
    _attempt_deadline_from_process_start as _attempt_deadline_from_process_start,
    _process_group_exists as _process_group_exists,
    _start_preparation_process as _process_start_preparation_process,
    _start_without_ambient_parent_main as _start_without_ambient_parent_main,
    _wait_process_group_settled as _wait_process_group_settled,
    settle_failed_process,
)


def _start_preparation_process(
    process: _SpawnProcessLike,
    connections: tuple[_Closeable, ...],
    *,
    start_fn: Callable[[_StartableProcess], int] | None = None,
) -> int:
    """Classify spawn failure and close every not-yet-transferred IPC endpoint."""
    return _process_start_preparation_process(
        process,
        connections,
        start_fn=_start_without_ambient_parent_main if start_fn is None else start_fn,
    )


def _preparation_worker_main(
    request_bytes: bytes,
    request: PreparationRequest,
    specification: PreparationResourceSpecification,
    observation_sender: Connection,
    acknowledgement_receiver: Connection,
    receipt_sender: Connection,
    failure_sender: Connection,
    readiness_sender: Connection,
    acknowledgement_timeout_seconds: float,
    cancellation_event: _EventLike,
    preparer: Callable[[PreparationResourceSpecification], PreparedResourceHandleLike],
    *,
    send_one_bounded_fn: Callable[..., None] | None = None,
    receive_one_bounded_fn: Callable[..., bytes] | None = None,
) -> None:
    _bootstrap_preparation_worker_main(
        request_bytes,
        request,
        specification,
        observation_sender,
        acknowledgement_receiver,
        receipt_sender,
        failure_sender,
        readiness_sender,
        acknowledgement_timeout_seconds,
        cancellation_event,
        preparer,
        send_one_bounded_fn=send_one_bounded if send_one_bounded_fn is None else send_one_bounded_fn,
        receive_one_bounded_fn=receive_one_bounded if receive_one_bounded_fn is None else receive_one_bounded_fn,
    )


@dataclass(frozen=True, slots=True)
class PreparationWorkerResult:
    """Accepted evidence and parent-owned timing for one settled attempt."""

    evidence: AcceptedPreparationEvidence
    observation_received_parent_ns: int
    receipt_received_parent_ns: int
    worker_settled_parent_ns: int
    worker_pid: int
    attempt_elapsed_parent_ns: int
    worker_ready_parent_ns: int | None = None
    bootstrap_elapsed_parent_ns: int | None = None


class PreparationWorkerAttempt:
    """Parent owner for one worker, five one-shot channels, and settlement."""

    def __init__(
        self,
        request: PreparationRequest,
        specification: PreparationResourceSpecification,
        policy: PreparationDeadlinePolicy,
        *,
        preparer: Callable[
            [PreparationResourceSpecification],
            PreparedResourceHandleLike,
        ] = prepare_resources,
    ) -> None:
        if request.resource_specification_digest != specification.digest:
            raise ValueError("preparation resource specification is invalid")
        self._request = request
        self._specification = specification
        self._policy = policy
        self._preparer = preparer

    def run(self) -> PreparationWorkerResult:
        if os.name != "posix":  # pragma: no cover - native Windows runner
            raise PreparationWorkerError(
                "preparation worker containment is unavailable"
            )
        context = get_context("spawn")
        observation_receiver, observation_sender = context.Pipe(duplex=False)
        acknowledgement_receiver, acknowledgement_sender = context.Pipe(duplex=False)
        receipt_receiver, receipt_sender = context.Pipe(duplex=False)
        failure_receiver, failure_sender = context.Pipe(duplex=False)
        readiness_receiver, readiness_sender = context.Pipe(duplex=False)
        cancellation_event = context.Event()
        process = context.Process(
            target=_preparation_worker_main,
            args=(
                self._request.to_bytes(),
                self._request,
                self._specification,
                observation_sender,
                acknowledgement_receiver,
                receipt_sender,
                failure_sender,
                readiness_sender,
                self._policy.acknowledgement_timeout_ms / 1_000,
                cancellation_event,
                self._preparer,
            ),
            name="scale28-startup-resource-preparation",
            daemon=False,
        )
        attempt_started_ns = _start_preparation_process(
            process,
            (
                observation_receiver, observation_sender,
                acknowledgement_receiver, acknowledgement_sender,
                receipt_receiver, receipt_sender,
                failure_receiver, failure_sender,
                readiness_receiver, readiness_sender,
            ),
            start_fn=_start_without_ambient_parent_main,
        )
        attempt_deadline = _attempt_deadline_from_process_start(
            attempt_started_ns,
            self._policy.attempt_timeout_ms,
        )
        worker_pid = process.pid
        if worker_pid is None:
            self._settle_failed_process(process)
            raise PreparationWorkerError("preparation worker did not start")
        observation_sender.close()
        acknowledgement_receiver.close()
        receipt_sender.close()
        failure_sender.close()
        readiness_sender.close()
        observation = None
        acknowledgement = None
        receipt = None
        worker_ready_ns: int | None = None
        try:
            worker_ready_ns = self._await_worker_readiness(
                readiness_receiver,
                failure_receiver,
                attempt_deadline=attempt_deadline,
            )
            observation_bytes = self._receive_success_or_failure(
                observation_receiver,
                OBSERVATION_MESSAGE,
                failure_receiver,
                attempt_deadline=self._semantic_deadline(
                    attempt_deadline,
                    worker_ready_ns,
                ),
            )
            observation_received_ns = time.monotonic_ns()
            observation = PreparationObservation.from_bytes(
                observation_bytes,
                self._request.expectations,
            )
            acknowledgement = PreparationObservationAcknowledgement.create(
                self._request.expectations,
                observation,
            )
            send_one_bounded(
                acknowledgement_sender,
                acknowledgement.to_bytes(
                    self._request.expectations,
                    observation,
                ),
                ACKNOWLEDGEMENT_MESSAGE,
            )
            receipt_bytes = self._receive_success_or_failure(
                receipt_receiver,
                RECEIPT_MESSAGE,
                failure_receiver,
                attempt_deadline=attempt_deadline,
                maximum_read_seconds=self._policy.receipt_timeout_ms / 1_000,
            )
            receipt_received_ns = time.monotonic_ns()
            receipt = PreparationTerminalReceiptV3.from_bytes(
                receipt_bytes,
                self._request.expectations,
                observation,
                acknowledgement,
            )
            process.join(
                timeout=min(
                    self._remaining_until(attempt_deadline),
                    self._policy.process_settlement_timeout_ms / 1_000,
                )
            )
            if process.is_alive() or process.exitcode != 0:
                raise PreparationWorkerError(
                    "preparation worker did not settle normally"
                )
            settled_ns = time.monotonic_ns()
            for conn in (observation_receiver, acknowledgement_sender, receipt_receiver, failure_receiver, readiness_receiver):
                conn.close()
            facts = ParentObservedTerminalFacts(
                exit_code=0, signal=None,
                process_tree_settled=not _process_group_exists(worker_pid),
                active_observers=1, descendants=0, worker_connections=0,
                readers=0, threads=0, descriptors_and_channels=0,
            )
            validate_parent_terminal_facts(receipt, facts)
            evidence = AcceptedPreparationEvidence.create(
                observation, acknowledgement, receipt,
            )
            evidence.assert_canonical()
            process.close()
            return PreparationWorkerResult(
                evidence, observation_received_ns, receipt_received_ns,
                settled_ns, worker_pid, settled_ns - attempt_started_ns,
                worker_ready_ns,
                None if worker_ready_ns is None else worker_ready_ns - attempt_started_ns,
            )
        except BaseException as error:
            cancellation_event.set()
            grace = (
                min(self._remaining_seconds(attempt_deadline), self._policy.process_settlement_timeout_ms / 1_000)
                if isinstance(error, PreparationWorkerError) and getattr(error, "verified_failure_notice_observed", False)
                else 0.0
            )
            cleanup_failure = None
            try:
                self._settle_failed_process(process, natural_settlement_grace_seconds=grace)
            except Exception as cleanup_err:
                cleanup_failure = cleanup_err
            for conn in (observation_receiver, acknowledgement_sender, receipt_receiver, failure_receiver, readiness_receiver):
                try:
                    conn.close()
                except OSError:
                    pass
            try:
                process.close()
            except ValueError:
                pass
            if isinstance(error, PreparationWorkerError):
                error.activation_observed = worker_ready_ns is not None
                error.secondary_failure = cleanup_failure
                raise
            wrapped = PreparationWorkerError(
                "preparation worker attempt failed",
                activation_observed=worker_ready_ns is not None,
            )
            wrapped.secondary_failure = cleanup_failure
            raise wrapped from error

    def _await_worker_readiness(
        self,
        readiness_receiver: Connection,
        failure_receiver: Connection,
        *,
        attempt_deadline: float,
    ) -> int | None:
        """Observe bounded worker activation without granting it any authority."""
        return await_worker_readiness(
            readiness_receiver,
            failure_receiver,
            expected_nonce=self._request.expectations.run_nonce,
            attempt_deadline=attempt_deadline,
            reserve_ms=self._policy.observation_transfer_reserve_ms,
            remaining_until_fn=self._remaining_until,
            wait_fn=wait,
            receive_one_bounded_fn=receive_one_bounded,
        )

    def _semantic_deadline(
        self,
        attempt_deadline: float,
        worker_ready_ns: int | None,
    ) -> float:
        """Nest the semantic operation bound inside the attempt authority."""
        return semantic_deadline(
            attempt_deadline,
            worker_ready_ns,
            self._policy.semantic_operation_timeout_ms,
        )

    def _receive_success_or_failure(
        self,
        receiver: Connection,
        specification: BoundedMessageSpec,
        failure_receiver: Connection,
        *,
        attempt_deadline: float,
        maximum_read_seconds: float | None = None,
    ) -> bytes:
        expectations = getattr(getattr(self, "_request", None), "expectations", None)
        return receive_success_or_failure(
            receiver,
            specification,
            failure_receiver,
            expectations=expectations,
            attempt_deadline=attempt_deadline,
            reserve_ms=self._policy.observation_transfer_reserve_ms,
            maximum_read_seconds=maximum_read_seconds,
            remaining_until_fn=self._remaining_until,
            wait_fn=wait,
            receive_one_bounded_fn=receive_one_bounded,
        )

    @staticmethod
    def _remaining_until(
        deadline: float,
        *,
        maximum_seconds: float | None = None,
    ) -> float:
        remaining = deadline - time.monotonic()
        if maximum_seconds is not None:
            remaining = min(remaining, maximum_seconds)
        if remaining <= 0:
            raise PreparationWorkerError(
                "preparation worker attempt timed out",
                category="preparation_timeout",
                boundary="worker",
            )
        return remaining

    @staticmethod
    def _remaining_seconds(deadline: float) -> float:
        return max(0.0, deadline - time.monotonic())

    def _settle_failed_process(
        self, process: _TerminableProcess, *, natural_settlement_grace_seconds: float = 0.0,
    ) -> None:
        settle_failed_process(
            process, self._policy, sigterm_join_ms=SIGTERM_JOIN_MS,
            killpg_fn=os.killpg, process_group_exists_fn=_process_group_exists,
            wait_process_group_settled_fn=_wait_process_group_settled,
            natural_settlement_grace_seconds=natural_settlement_grace_seconds,
        )


__all__ = ["PreparationWorkerAttempt", "PreparationWorkerError", "PreparationWorkerResult"]
