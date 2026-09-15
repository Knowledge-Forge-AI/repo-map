from __future__ import annotations

from collections.abc import Callable
from multiprocessing import get_context
import time

import pytest

from repomap_test_support.test_cov5c_qualification import (
    PROCESS_ACTIVATION_TIMEOUT_SECONDS,
    build_evidence,
    build_expectations,
    process_activate_then_run,
    process_activate_then_withhold,
    process_close_sender,
    process_delay_activation_then_run,
    process_send_messages,
    process_send_raw_frame,
)
from scale28_preparation_frames import PreparationObservation
from scale28_preparation_ipc import (
    OBSERVATION_MESSAGE,
    PreparationIpcError,
    receive_one_bounded,
)


def _require_activation(process, activation, receiver) -> None:
    """Bound spawn bootstrap outside the production transport deadline."""

    if activation.wait(PROCESS_ACTIVATION_TIMEOUT_SECONDS):
        return
    receiver.close()
    if process.is_alive():
        process.terminate()
        process.join(3.0)
    if process.is_alive():
        process.kill()
        process.join(3.0)
    exitcode = process.exitcode
    process.close()
    pytest.fail(
        "spawned sender never reached activation within "
        f"{PROCESS_ACTIVATION_TIMEOUT_SECONDS} seconds "
        f"(child bootstrap unfinished, exitcode {exitcode})"
    )


@pytest.mark.parametrize("case_number", range(30))
def test_actual_production_bounded_ipc_process_matrix(
    case_number: int,
) -> None:
    mode = case_number % 10
    evidence = build_evidence(case_number=case_number)
    payload = evidence.observation_bytes
    expected_category = None
    target: Callable[..., object]
    arguments: tuple[object, ...]
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)

    if mode == 0:
        target = process_send_messages
        arguments = (
            sender,
            (b"x" * OBSERVATION_MESSAGE.maximum_bytes,),
        )
    elif mode == 1:
        target = process_send_messages
        arguments = (
            sender,
            (b"x" * (OBSERVATION_MESSAGE.maximum_bytes + 1),),
        )
        expected_category = "message_overflow"
    elif mode == 2:
        target = process_close_sender
        arguments = (sender,)
        expected_category = "sender_exit_before_message"
    elif mode == 3:
        target = process_send_messages
        arguments = (sender, (payload, payload))
        expected_category = "unexpected_second_message"
    elif mode == 4:
        target = process_send_raw_frame
        arguments = (sender, b"\x00\x00")
        expected_category = "sender_exit_during_message"
    elif mode == 5:
        target = process_send_raw_frame
        arguments = (sender, b"\x00\x00\x00\x10partial")
        expected_category = "sender_exit_during_message"
    elif mode == 6:
        target = process_send_messages
        arguments = (sender, (b"",))
        expected_category = "zero_length_message"
    else:
        target = process_send_messages
        arguments = (sender, (payload,))

    activation = context.Event()
    process = context.Process(
        target=process_activate_then_run,
        args=(activation, target, arguments),
    )
    process.start()
    sender.close()
    _require_activation(process, activation, receiver)
    try:
        if expected_category is not None:
            with pytest.raises(PreparationIpcError) as captured:
                receive_one_bounded(
                    receiver,
                    OBSERVATION_MESSAGE,
                    timeout_seconds=1.0,
                    settlement_timeout_seconds=1.0,
                )
            assert captured.value.category == expected_category
        else:
            received = receive_one_bounded(
                receiver,
                OBSERVATION_MESSAGE,
                timeout_seconds=1.0,
                settlement_timeout_seconds=1.0,
            )
            if mode == 0:
                assert len(received) == OBSERVATION_MESSAGE.maximum_bytes
            elif mode == 7:
                with pytest.raises(ValueError):
                    PreparationObservation.from_bytes(
                        received[:-1] + b" ",
                        evidence.observation.expectations,
                    )
            elif mode == 8:
                with pytest.raises(ValueError, match="generation"):
                    PreparationObservation.from_bytes(
                        received,
                        build_expectations(attempt=2, nonce="b" * 32),
                    )
            elif mode == 9:
                changed = received.replace(
                    b'"frame_sequence":1',
                    b'"frame_sequence":2',
                )
                with pytest.raises(ValueError):
                    PreparationObservation.from_bytes(
                        changed,
                        evidence.observation.expectations,
                    )
    finally:
        receiver.close()
        process.join(3.0)
        assert process.is_alive() is False
        assert process.exitcode == 0
        process.close()


def test_delayed_bootstrap_does_not_consume_the_production_receive_deadline() -> None:
    evidence = build_evidence(case_number=0)
    payload = evidence.observation_bytes
    context = get_context("spawn")
    activation = context.Event()
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=process_delay_activation_then_run,
        args=(activation, 1.5, process_send_messages, (sender, (payload,))),
    )
    process.start()
    sender.close()
    _require_activation(process, activation, receiver)
    started = time.monotonic()
    try:
        received = receive_one_bounded(
            receiver,
            OBSERVATION_MESSAGE,
            timeout_seconds=1.0,
            settlement_timeout_seconds=1.0,
        )
        assert received == payload
        assert time.monotonic() - started < 1.0
    finally:
        receiver.close()
        process.join(3.0)
        assert process.is_alive() is False
        assert process.exitcode == 0
        process.close()


def test_activated_sender_withholding_still_fails_with_message_timeout() -> None:
    context = get_context("spawn")
    activation = context.Event()
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=process_activate_then_withhold,
        args=(activation, sender, 2.5),
    )
    process.start()
    sender.close()
    _require_activation(process, activation, receiver)
    started = time.monotonic()
    try:
        with pytest.raises(PreparationIpcError) as captured:
            receive_one_bounded(
                receiver,
                OBSERVATION_MESSAGE,
                timeout_seconds=1.0,
                settlement_timeout_seconds=1.0,
            )
        elapsed = time.monotonic() - started
        assert captured.value.category == "message_timeout"
        assert 1.0 <= elapsed < 2.0
    finally:
        receiver.close()
        process.join(5.0)
        assert process.is_alive() is False
        assert process.exitcode == 0
        process.close()
