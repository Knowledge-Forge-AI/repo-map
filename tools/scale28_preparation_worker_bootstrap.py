"""Child process entrypoint, environment sanitization, and readiness."""

from __future__ import annotations

from multiprocessing.connection import Connection, wait
import os
import time
from typing import Any, Callable, Protocol, runtime_checkable

from scale28_preparation_failures import PreparationFailureNotice
from scale28_preparation_frames import (
    PreparationObservation,
    PreparationObservationAcknowledgement,
)
from scale28_preparation_ipc import (
    ACKNOWLEDGEMENT_MESSAGE,
    BoundedMessageSpec,
    FAILURE_MESSAGE,
    OBSERVATION_MESSAGE,
    PreparationIpcError,
    READINESS_MESSAGE,
    RECEIPT_MESSAGE,
    receive_one_bounded,
    send_one_bounded,
)
from scale28_preparation_receipts import PreparationTerminalReceiptV3
from scale28_preparation_resources import (
    PreparationResourceSpecification,
)
from scale28_preparation_values import (
    PreparationAttemptExpectations,
    PreparationRequest,
    ResourceBaseline,
)
from scale28_preparation_worker_process import PreparationWorkerError


@runtime_checkable
class _EventLike(Protocol):
    def is_set(self) -> bool: ...
    def set(self) -> None: ...


@runtime_checkable
class PreparedResourceHandleLike(Protocol):
    @property
    def baseline(self) -> ResourceBaseline: ...
    def close(self) -> None: ...


def _retain_minimal_worker_environment(*, dont_write_bytecode: bool) -> None:
    retained_names = (
        "PATH",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HOME",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
    )
    retained = {
        name: os.environ[name]
        for name in retained_names
        if name in os.environ
    }
    os.environ.clear()
    os.environ.update(retained)
    if dont_write_bytecode:
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


def await_worker_readiness(
    readiness_receiver: Connection,
    failure_receiver: Connection,
    *,
    expected_nonce: str,
    attempt_deadline: float,
    reserve_ms: int,
    remaining_until_fn: Callable[[float], float],
    wait_fn: Callable[..., Any] = wait,
    receive_one_bounded_fn: Callable[..., bytes] = receive_one_bounded,
) -> int | None:
    """Observe bounded worker activation without granting it any authority."""
    ready = wait_fn(
        (readiness_receiver, failure_receiver),
        timeout=remaining_until_fn(attempt_deadline),
    )
    if readiness_receiver not in ready:
        return None
    try:
        token = receive_one_bounded_fn(
            readiness_receiver,
            READINESS_MESSAGE,
            timeout_seconds=remaining_until_fn(attempt_deadline),
            settlement_timeout_seconds=reserve_ms / 1_000,
        )
    except PreparationIpcError as error:
        if error.category != "sender_exit_before_message":
            raise
        return None
    if token != expected_nonce.encode("ascii"):
        raise PreparationWorkerError(
            "preparation worker readiness is unbound"
        )
    return time.monotonic_ns()


def semantic_deadline(
    attempt_deadline: float,
    worker_ready_ns: int | None,
    semantic_operation_timeout_ms: int | None,
) -> float:
    """Nest the semantic operation bound inside the attempt authority."""
    if worker_ready_ns is None or semantic_operation_timeout_ms is None:
        return attempt_deadline
    return min(
        attempt_deadline,
        worker_ready_ns / 1_000_000_000 + semantic_operation_timeout_ms / 1_000,
    )


def receive_success_or_failure(
    receiver: Connection,
    specification: BoundedMessageSpec,
    failure_receiver: Connection,
    *,
    attempt_deadline: float,
    reserve_ms: int,
    maximum_read_seconds: float | None = None,
    remaining_until_fn: Callable[..., float],
    expectations: PreparationAttemptExpectations | None = None,
    wait_fn: Callable[..., Any] = wait,
    receive_one_bounded_fn: Callable[..., bytes] = receive_one_bounded,
) -> bytes:
    timeout_seconds = remaining_until_fn(
        attempt_deadline,
        maximum_seconds=maximum_read_seconds,
    )
    ready = wait_fn((receiver, failure_receiver), timeout=timeout_seconds)
    if failure_receiver in ready:
        try:
            encoded = receive_one_bounded_fn(
                failure_receiver,
                FAILURE_MESSAGE,
                timeout_seconds=remaining_until_fn(
                    attempt_deadline,
                    maximum_seconds=maximum_read_seconds,
                ),
                settlement_timeout_seconds=reserve_ms / 1_000,
            )
        except PreparationIpcError as error:
            if error.category != "sender_exit_before_message":
                raise
            ready = wait_fn(
                (receiver,),
                timeout=remaining_until_fn(
                    attempt_deadline,
                    maximum_seconds=maximum_read_seconds,
                ),
            )
            if receiver not in ready:
                raise PreparationWorkerError(
                    "preparation worker attempt timed out",
                    category="preparation_timeout",
                    boundary="worker",
                ) from error
        else:
            if expectations is not None:
                notice = PreparationFailureNotice.from_bytes(
                    encoded,
                    expectations,
                )
                category = notice.category
                boundary = notice.boundary
                verified = True
            else:
                category = "worker_failed"
                boundary = "worker"
                verified = False
            raise PreparationWorkerError(
                "preparation worker reported a source failure",
                category=category,
                boundary=boundary,
                verified_failure_notice_observed=verified,
            )
    if receiver not in ready:
        raise PreparationWorkerError(
            "preparation worker attempt timed out",
            category="preparation_timeout",
            boundary="worker",
        )
    return receive_one_bounded_fn(
        receiver,
        specification,
        timeout_seconds=remaining_until_fn(
            attempt_deadline,
            maximum_seconds=maximum_read_seconds,
        ),
        settlement_timeout_seconds=reserve_ms / 1_000,
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
    preparer: Callable[
        [PreparationResourceSpecification],
        PreparedResourceHandleLike,
    ],
    *,
    send_one_bounded_fn: Callable[..., None] = send_one_bounded,
    receive_one_bounded_fn: Callable[..., bytes] = receive_one_bounded,
) -> None:
    resources: PreparedResourceHandleLike | None = None
    try:
        if os.name == "posix":
            os.setsid()
        _retain_minimal_worker_environment(dont_write_bytecode=True)
        if cancellation_event.is_set():
            raise PreparationWorkerError("preparation attempt was cancelled")
        accepted_request = PreparationRequest.from_bytes(
            request_bytes,
            request.expectations,
        )
        if (
            accepted_request != request
            or accepted_request.resource_specification_digest
            != specification.digest
        ):
            raise PreparationWorkerError("preparation request is invalid")
        send_one_bounded_fn(
            readiness_sender,
            accepted_request.expectations.run_nonce.encode("ascii"),
            READINESS_MESSAGE,
        )
        observation_started_ns = time.monotonic_ns()
        resources = preparer(specification)
        observation_completed_ns = time.monotonic_ns()
        observation = PreparationObservation.create(
            request.expectations,
            resources.baseline,
            observation_started_ns=observation_started_ns,
            observation_completed_ns=observation_completed_ns,
        )
        send_one_bounded_fn(
            observation_sender,
            observation.to_bytes(),
            OBSERVATION_MESSAGE,
        )
        acknowledgement_bytes = receive_one_bounded_fn(
            acknowledgement_receiver,
            ACKNOWLEDGEMENT_MESSAGE,
            timeout_seconds=acknowledgement_timeout_seconds,
            settlement_timeout_seconds=acknowledgement_timeout_seconds,
        )
        acknowledgement = PreparationObservationAcknowledgement.from_bytes(
            acknowledgement_bytes,
            request.expectations,
            observation,
        )
        if cancellation_event.is_set():
            raise PreparationWorkerError("preparation attempt was cancelled")
        acknowledgement_received_ns = time.monotonic_ns()
        baseline = resources.baseline
        resources.close()
        resources = None
        result_completed_ns = time.monotonic_ns()
        receipt = PreparationTerminalReceiptV3.create(
            request.expectations,
            observation=observation,
            acknowledgement=acknowledgement,
            baseline=baseline,
            observation_acknowledged_ns=acknowledgement_received_ns,
            result_completed_ns=result_completed_ns,
        )
        send_one_bounded_fn(
            receipt_sender,
            receipt.to_bytes(observation, acknowledgement),
            RECEIPT_MESSAGE,
        )
        failure_sender.close()
    except BaseException as error:
        category = str(getattr(error, "category", "worker_failed"))
        boundary = str(getattr(error, "boundary", "worker"))
        try:
            failure = PreparationFailureNotice.create(
                request.expectations,
                category=category,
                boundary=boundary,
            )
            send_one_bounded_fn(
                failure_sender,
                failure.to_bytes(),
                FAILURE_MESSAGE,
            )
        except BaseException:
            try:
                failure_sender.close()
            except OSError:
                pass
        for connection in (
            observation_sender,
            acknowledgement_receiver,
            receipt_sender,
            readiness_sender,
        ):
            try:
                connection.close()
            except OSError:
                pass
        if resources is not None:
            try:
                resources.close()
            except BaseException:
                pass
        raise SystemExit(1) from None


__all__ = [
    "PreparedResourceHandleLike",
    "_EventLike",
    "_preparation_worker_main",
    "_retain_minimal_worker_environment",
    "await_worker_readiness",
    "receive_success_or_failure",
    "semantic_deadline",
]
