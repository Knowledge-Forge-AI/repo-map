from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from process_rss_monitor import (
    ProcessRssMonitor,
    ProcessRssMonitorError,
    ProcessRssRetention,
    rss_kib_to_bytes,
)
from scale12_resource_sampling import read_process_rss_bytes


def test_kib_reader_units_are_normalized_to_bytes() -> None:
    assert rss_kib_to_bytes(1) == 1024
    assert rss_kib_to_bytes(4096) == 4_194_304


@pytest.mark.parametrize("value", (True, -1, 1.5, "1"))
def test_invalid_kib_reader_values_are_rejected(value) -> None:
    with pytest.raises(ProcessRssMonitorError, match="RSS reading is invalid"):
        rss_kib_to_bytes(value)


def test_monotonic_growth_then_shrink_retains_the_sampled_maximum() -> None:
    retention = ProcessRssRetention(limit_bytes=200)

    assert retention.observe(0.0, 100) is False
    assert retention.observe(0.1, 250) is True
    retention.mark_signal_sent()
    assert retention.observe(0.2, 400) is False
    assert retention.observe(0.3, 150) is False
    result = retention.finish(process_exited=True)

    assert result.first_crossing_bytes == 250
    assert result.first_crossing_timestamp_seconds == 0.1
    assert result.maximum_observed_bytes == 400
    assert result.maximum_pre_signal_bytes == 250
    assert result.maximum_post_signal_bytes == 400
    assert result.signal_sent is True


def test_crossing_at_the_exact_limit_is_causal() -> None:
    retention = ProcessRssRetention(limit_bytes=200)

    assert retention.observe(0.0, 200) is True
    result = retention.finish(process_exited=False)

    assert result.first_crossing_bytes == 200
    assert result.crossing_timing == "before_signal"


def test_terminal_only_crossing_is_retained_but_not_actionable() -> None:
    retention = ProcessRssRetention(limit_bytes=200)

    assert retention.observe(0.0, 300, terminal=True) is False
    result = retention.finish(process_exited=True)

    assert result.first_crossing_bytes == 300
    assert result.crossing_timing == "terminal_only"
    assert result.terminal_sample_bytes == 300
    assert result.signal_sent is False


def test_lookup_loss_after_valid_samples_does_not_erase_the_maximum() -> None:
    retention = ProcessRssRetention(limit_bytes=500)

    retention.observe(0.0, 300)
    retention.observe(0.1, None)
    retention.observe(0.2, None, reader_error=True, terminal=True)
    result = retention.finish(process_exited=True)

    assert result.maximum_observed_bytes == 300
    assert result.valid_sample_count == 1
    assert result.missing_sample_count == 2
    assert result.reader_error_count == 1


def test_no_valid_sample_before_exit_remains_unavailable_not_zero() -> None:
    retention = ProcessRssRetention(limit_bytes=500)

    retention.observe(0.0, None, terminal=True)
    result = retention.finish(process_exited=True)

    assert result.maximum_observed_bytes is None
    assert result.terminal_sample_bytes is None
    assert result.valid_sample_count == 0


@pytest.mark.parametrize(
    "first,second,message",
    (
        ((0.0, 1), (0.0, 2), "timestamp is not increasing"),
        ((0.1, 1), (0.0, 2), "timestamp is not increasing"),
        ((0.0, 1), (0.1, -1), "RSS reading is invalid"),
        ((0.0, 1), (0.1, True), "RSS reading is invalid"),
    ),
)
def test_malformed_or_nonmonotonic_samples_fail_closed(first, second, message) -> None:
    retention = ProcessRssRetention(limit_bytes=500)
    retention.observe(*first)

    with pytest.raises(ProcessRssMonitorError, match=message):
        retention.observe(*second)


def test_signal_cannot_be_marked_twice() -> None:
    retention = ProcessRssRetention(limit_bytes=100)
    retention.observe(0.0, 150)
    retention.mark_signal_sent()

    with pytest.raises(ProcessRssMonitorError, match="signal is duplicate"):
        retention.mark_signal_sent()


class _Process:
    def __init__(self, poll_results) -> None:
        self.poll_results = iter(poll_results)

    def poll(self):
        return next(self.poll_results)


class _Clock:
    def __init__(self) -> None:
        self.value = -0.01

    def __call__(self) -> float:
        self.value += 0.01
        return self.value


def test_monitor_signals_once_and_samples_until_process_exit() -> None:
    values = iter((90, 110, 175, None))
    signals: list[str] = []
    sleeps: list[float] = []
    monitor = ProcessRssMonitor(
        limit_bytes=100,
        cadence_seconds=0.2,
        reader=lambda: next(values),
        signal=lambda: signals.append("signal"),
        clock=_Clock(),
        sleeper=sleeps.append,
    )

    result = monitor.run(_Process((None, None, None, 0)))

    assert signals == ["signal"]
    assert sleeps == [0.2, 0.2, 0.2]
    assert result.first_crossing_bytes == 110
    assert result.maximum_observed_bytes == 175
    assert result.maximum_post_signal_bytes == 175
    assert result.process_exited is True


def test_monitor_retains_crossing_when_process_exits_between_samples() -> None:
    values = iter((110, None))
    signals: list[str] = []
    monitor = ProcessRssMonitor(
        limit_bytes=100,
        cadence_seconds=0.25,
        reader=lambda: next(values),
        signal=lambda: signals.append("signal"),
        clock=_Clock(),
        sleeper=lambda _seconds: None,
    )

    result = monitor.run(_Process((None, 0)))

    assert signals == ["signal"]
    assert result.first_crossing_bytes == 110
    assert result.maximum_observed_bytes == 110
    assert result.terminal_sample_bytes is None


def test_monitor_classifies_reader_error_after_a_valid_sample() -> None:
    reads = iter((200, ProcessLookupError()))

    def reader():
        value = next(reads)
        if isinstance(value, BaseException):
            raise value
        return value

    monitor = ProcessRssMonitor(
        limit_bytes=500,
        cadence_seconds=0.1,
        reader=reader,
        signal=lambda: None,
        clock=_Clock(),
        sleeper=lambda _seconds: None,
    )

    result = monitor.run(_Process((None, 0)))

    assert result.maximum_observed_bytes == 200
    assert result.reader_error_count == 1
    assert result.process_exited is True


@pytest.mark.parametrize("cadence", (0, -0.1, 0.251, True))
def test_monitor_rejects_invalid_or_too_slow_cadence(cadence) -> None:
    with pytest.raises(ProcessRssMonitorError, match="cadence is invalid"):
        ProcessRssMonitor(
            limit_bytes=100,
            cadence_seconds=cadence,
            reader=lambda: 1,
            signal=lambda: None,
        )


def test_public_payload_is_bounded_and_contains_no_process_identity() -> None:
    retention = ProcessRssRetention(limit_bytes=100)
    retention.observe(0.0, 120)
    retention.mark_signal_sent()
    retention.observe(0.1, 150, terminal=True)
    payload = retention.finish(process_exited=True).to_payload()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    assert len(encoded.encode("utf-8")) <= 2048
    assert "pid" not in encoded.lower()
    assert "command" not in encoded.lower()
    assert "argv" not in encoded.lower()
    assert "path" not in encoded.lower()
    assert payload["maximum_authority"] == "sampled"


def _ps_is_executable() -> bool:
    """Probe whether /bin/ps can actually run, not merely whether it exists.

    Existence and mode bits are not sufficient: a sandbox can permit stat while
    denying exec, in which case the reader raises PermissionError and this test
    fails with a bare assertion instead of skipping.
    """
    if not Path("/bin/ps").is_file():
        return False
    try:
        subprocess.run(
            ("/bin/ps", "-o", "rss=", "-p", str(os.getpid())),
            check=False,
            capture_output=True,
            timeout=5.0,
        )
    except OSError:
        return False
    return True


@pytest.mark.skipif(not _ps_is_executable(), reason="ps cannot be executed")
def test_monitor_samples_and_reaps_one_native_short_lived_process() -> None:
    process = subprocess.Popen(
        (
            sys.executable,
            "-c",
            "import time; payload = bytearray(8 * 1024 * 1024); time.sleep(0.1)",
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    signaled = False

    def signal() -> None:
        nonlocal signaled
        signaled = True
        process.terminate()

    try:
        result = ProcessRssMonitor(
            limit_bytes=512 * 1024 * 1024,
            cadence_seconds=0.02,
            reader=lambda: read_process_rss_bytes(process.pid),
            signal=signal,
        ).run(process)
        assert process.wait(timeout=2.0) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2.0)

    assert signaled is False
    assert result.process_exited is True
    assert result.maximum_observed_bytes is not None
    assert result.maximum_observed_bytes > 0
