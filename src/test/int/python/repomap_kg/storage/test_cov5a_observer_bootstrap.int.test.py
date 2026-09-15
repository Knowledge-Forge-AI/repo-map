from __future__ import annotations

import multiprocessing

import pytest

from repomap_test_support.postgres_protocol_faults import (
    run_startup_fault_probe,
)


pytestmark = pytest.mark.skipif(
    "spawn" not in multiprocessing.get_all_start_methods(),
    reason="loopback qualification requires isolated process cleanup",
)


@pytest.mark.parametrize("repetition", range(10))
def test_stalled_handshake_has_bounded_connection_timeout(
    repetition: int,
) -> None:
    assert repetition >= 0
    result = run_startup_fault_probe("stall")

    assert result.process_alive_after_deadline is False
    assert result.outcome == "error"
    assert result.boundary == "observer_connection_timeout"
    assert result.process_clean is True
    assert result.accepted_socket_clean is True
    assert result.listener_clean is True


@pytest.mark.parametrize("repetition", range(10))
def test_peer_close_during_startup_is_bounded_and_clean(
    repetition: int,
) -> None:
    assert repetition >= 0
    result = run_startup_fault_probe("close")

    assert result.process_alive_after_deadline is False
    assert result.outcome == "error"
    assert result.boundary == "observer_connection_create"
    assert result.process_clean is True
    assert result.accepted_socket_clean is True
    assert result.listener_clean is True
