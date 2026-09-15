from __future__ import annotations

from multiprocessing import get_context

import pytest

from repomap_test_support.scale28_adr2_bounded_ipc import (
    OBSERVATION_MESSAGE,
    BoundedIpcFailure,
    process_send_delayed_second_message,
    receive_bounded_message,
)


@pytest.mark.parametrize("changed", (False, True))
def test_delayed_identical_or_changed_second_message_is_rejected(
    changed: bool,
) -> None:
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    second = b"second" if changed else b"first"
    process = context.Process(
        target=process_send_delayed_second_message,
        args=(sender, b"first", second, 0.05),
    )
    process.start()
    sender.close()
    try:
        with pytest.raises(BoundedIpcFailure) as captured:
            receive_bounded_message(
                receiver,
                OBSERVATION_MESSAGE,
                timeout_seconds=1.0,
            )
        assert captured.value.category == "unexpected_second_message"
        assert captured.value.source_boundary == "transport_sequence"
        assert receiver.closed is True
    finally:
        receiver.close()
        process.join(3.0)
        assert process.is_alive() is False
        assert process.exitcode == 0
        process.close()


def test_one_shot_message_requires_sender_channel_settlement() -> None:
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    sender.send_bytes(b"first")
    try:
        with pytest.raises(BoundedIpcFailure) as captured:
            receive_bounded_message(
                receiver,
                OBSERVATION_MESSAGE,
                timeout_seconds=1.0,
                channel_settlement_timeout_seconds=0.01,
            )
        assert captured.value.category == "message_channel_not_closed"
        assert captured.value.source_boundary == "transport_settlement"
        assert receiver.closed is True
    finally:
        receiver.close()
        sender.close()
