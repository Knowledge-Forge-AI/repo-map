"""Bounded stdio with real stdlib child processes: overflow, timeout, deadlock order (spec 7)."""

from __future__ import annotations

import sys

import pytest

from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot.bounded_exec import run_bounded

PY = [sys.executable, "-I", "-S", "-c"]


def test_stdin_is_delivered_and_both_streams_are_bounded_records() -> None:
    script = "import sys; d=sys.stdin.buffer.read(); sys.stdout.buffer.write(d[::-1]); sys.stderr.write('e'*7)"
    outcome = run_bounded([*PY, script], stdin=b"abc", stdout_limit=16, deadline=20)
    assert (outcome.returncode, outcome.stdout, outcome.stderr_bytes) == (0, b"cba", 7)
    assert outcome.clean and outcome.events == () and outcome.settled
    assert len(outcome.stderr_sha256) == 64 and not hasattr(outcome, "stderr")


def test_child_that_writes_before_reading_cannot_deadlock_the_parent() -> None:
    script = ("import sys; sys.stdout.buffer.write(b'x'*2_000_000); sys.stdout.flush(); "
              "data=sys.stdin.buffer.read(); sys.stdout.buffer.write(str(len(data)).encode())")
    outcome = run_bounded([*PY, script], stdin=b"y" * 2_000_000, stdout_limit=4_100_000, deadline=30)
    assert outcome.returncode == 0 and outcome.stdout.endswith(b"2000000") and outcome.events == ()


def test_stdout_overflow_stops_buffering_and_runs_exact_kill_first() -> None:
    killed: list[str] = []
    script = "import sys,time\nwhile True: sys.stdout.buffer.write(b'z'*65536); sys.stdout.flush()"
    outcome = run_bounded([*PY, script], stdout_limit=100_000, deadline=20, on_deadline=lambda end: killed.append("exact"))
    assert outcome.events == ("output_bound",) and len(outcome.stdout) == 100_000
    assert killed == ["exact"] and outcome.returncode != 0 and outcome.settled and not outcome.clean


def test_stderr_overflow_is_a_diagnostic_bound_and_bytes_are_not_kept() -> None:
    script = "import sys,time\nsys.stderr.buffer.write(b'q'*200_000); sys.stderr.flush(); time.sleep(10)"
    outcome = run_bounded([*PY, script], stdout_limit=10, stderr_limit=65_536, deadline=20)
    assert "diagnostic_bound" in outcome.events and outcome.stderr_bytes > 65_536 and outcome.stdout == b""


def test_deadline_runs_settlement_and_records_a_time_bound() -> None:
    killed: list[bool] = []
    outcome = run_bounded([*PY, "import time; time.sleep(30)"], stdout_limit=10, deadline=0.5,
                          on_deadline=lambda end: killed.append(True))
    assert outcome.events == ("time_bound",) and killed == [True] and outcome.elapsed < 15 and outcome.settled


def test_closed_stdin_after_early_exit_is_not_an_error() -> None:
    outcome = run_bounded([*PY, "import sys; sys.exit(3)"], stdin=b"w" * 3_000_000, stdout_limit=10, deadline=20)
    assert outcome.returncode == 3 and outcome.events == ()
    assert not outcome.clean and not outcome.input_complete and outcome.io_failed


def test_invalid_requests_and_missing_clients_are_categorical() -> None:
    with pytest.raises(ContractError, match="invalid_exec_request"):
        run_bounded([*PY, "pass"], stdout_limit=0, deadline=1)
    with pytest.raises(ContractError, match="invalid_exec_request"):
        run_bounded([*PY, "pass"], stdout_limit=1, deadline=0)
    with pytest.raises(ContractError, match="invalid_exec_request"):
        run_bounded([], stdout_limit=1, deadline=1)
    with pytest.raises(ContractError, match="client_unavailable"):
        run_bounded(["/nonexistent/docker-client"], stdout_limit=1, deadline=1)
