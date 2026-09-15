from __future__ import annotations

import inspect

import psycopg
import pytest

import scale15_actual_path_readback as readback


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Result:
    status = psycopg.pq.ExecStatus.TUPLES_OK
    ntuples = 1
    nfields = 1

    def __init__(self, clock: _Clock, *, fetch_delay: float = 0.0) -> None:
        self._clock = clock
        self._fetch_delay = fetch_delay

    def get_value(self, row: int, column: int) -> bytes:
        assert (row, column) == (0, 0)
        self._clock.advance(self._fetch_delay)
        return b"2"


class _Connection:
    socket = 17
    error_message = b"public-safe failure"
    status = psycopg.pq.ConnStatus.OK

    def __init__(
        self,
        clock: _Clock,
        *,
        polls: tuple[psycopg.pq.PollingStatus, ...] = (
            psycopg.pq.PollingStatus.OK,
        ),
        wait_delays: tuple[float, ...] = (),
        flushes: tuple[int, ...] = (0,),
        busy: tuple[int, ...] = (0,),
        fetch_delay: float = 0.0,
        close_delay: float = 0.0,
    ) -> None:
        self._clock = clock
        self._polls = list(polls)
        self._wait_delays = list(wait_delays)
        self._flushes = list(flushes)
        self._busy = list(busy)
        self._result = _Result(clock, fetch_delay=fetch_delay)
        self._result_reads = 0
        self._close_delay = close_delay
        self.wait_authorities: list[float] = []
        self.sent_queries = 0
        self.finish_count = 0
        self.nonblocking = 0

    def connect_poll(self) -> psycopg.pq.PollingStatus:
        return self._polls.pop(0)

    def wait(self, timeout_seconds: float) -> bool:
        self.wait_authorities.append(timeout_seconds)
        delay = self._wait_delays.pop(0)
        if delay >= timeout_seconds:
            self._clock.advance(timeout_seconds)
            return False
        self._clock.advance(delay)
        return True

    def send_query(self, query: bytes) -> None:
        assert query.startswith(b"SELECT count(*)")
        self.sent_queries += 1

    def flush(self) -> int:
        return self._flushes.pop(0)

    def is_busy(self) -> int:
        return self._busy.pop(0)

    def consume_input(self) -> None:
        return None

    def get_result(self):
        self._result_reads += 1
        return self._result if self._result_reads == 1 else None

    def finish(self) -> None:
        self.finish_count += 1
        self._clock.advance(self._close_delay)


def _install(monkeypatch, connection: _Connection, clock: _Clock) -> None:
    monkeypatch.setattr(readback, "monotonic", clock)
    monkeypatch.setattr(
        readback,
        "_psycopg_connection_params_from_psql_args",
        lambda _args: {},
    )
    monkeypatch.setattr(
        readback,
        "_start_terminal_connection",
        lambda _conninfo: connection,
    )
    monkeypatch.setattr(
        readback,
        "_wait_terminal_io",
        lambda _fd, *, readable, writable, timeout_seconds: connection.wait(
            timeout_seconds
        ),
    )


@pytest.mark.parametrize(
    ("connection", "stage"),
    (
        (
            lambda clock: _Connection(
                clock,
                polls=(
                    psycopg.pq.PollingStatus.READING,
                    psycopg.pq.PollingStatus.OK,
                ),
                wait_delays=(0.75,),
            ),
            "connection_acquisition",
        ),
        (
            lambda clock: _Connection(
                clock,
                wait_delays=(0.75,),
                flushes=(1, 0),
            ),
            "query_execution",
        ),
        (
            lambda clock: _Connection(
                clock,
                wait_delays=(0.75,),
                busy=(1, 0),
            ),
            "result_fetch",
        ),
        (
            lambda clock: _Connection(clock, close_delay=0.75),
            "connection_settlement",
        ),
    ),
)
def test_terminal_stages_share_one_enforced_deadline(
    monkeypatch,
    connection,
    stage: str,
) -> None:
    clock = _Clock()
    exact = connection(clock)
    _install(monkeypatch, exact, clock)

    with pytest.raises(readback.TerminalBackendReadTimeout) as raised:
        readback.read_terminal_backend_summary(("public-safe",))

    assert raised.value.stage == stage
    assert raised.value.backend_quiescent is False
    assert raised.value.read_count == 1
    assert clock.now <= 0.75
    assert exact.finish_count == 1


def test_terminal_nested_stages_receive_decreasing_remaining_authority(
    monkeypatch,
) -> None:
    clock = _Clock()
    connection = _Connection(
        clock,
        polls=(
            psycopg.pq.PollingStatus.READING,
            psycopg.pq.PollingStatus.OK,
        ),
        wait_delays=(0.1, 0.1),
        busy=(1, 0),
    )
    _install(monkeypatch, connection, clock)

    summary = readback.read_terminal_backend_summary(("public-safe",))

    assert summary == {"observer": 1, "unknown": 2}
    assert connection.wait_authorities == pytest.approx((0.5, 0.4))
    assert connection.sent_queries == 1
    assert connection.finish_count == 1


def test_terminal_deadline_starts_before_connection_acquisition(
    monkeypatch,
) -> None:
    clock = _Clock()
    connection = _Connection(
        clock,
        polls=(
            psycopg.pq.PollingStatus.READING,
            psycopg.pq.PollingStatus.OK,
        ),
        wait_delays=(0.4,),
    )
    _install(monkeypatch, connection, clock)

    def delayed_start(_conninfo: bytes) -> _Connection:
        clock.advance(0.2)
        return connection

    monkeypatch.setattr(readback, "_start_terminal_connection", delayed_start)

    with pytest.raises(readback.TerminalBackendReadTimeout) as raised:
        readback.read_terminal_backend_summary(("public-safe",))

    assert raised.value.stage == "connection_acquisition"
    assert connection.wait_authorities == pytest.approx((0.3,))
    assert clock.now == pytest.approx(0.5)
    assert connection.finish_count == 1


def test_terminal_transport_failure_retains_its_category(monkeypatch) -> None:
    clock = _Clock()
    connection = _Connection(
        clock,
        polls=(psycopg.pq.PollingStatus.FAILED,),
    )
    _install(monkeypatch, connection, clock)

    with pytest.raises(psycopg.OperationalError):
        readback.read_terminal_backend_summary(("public-safe",))

    assert connection.finish_count == 1


def test_terminal_reader_has_no_host_process_or_psql_fallback() -> None:
    source = inspect.getsource(readback.read_terminal_backend_summary)

    assert "subprocess" not in source
    assert "docker exec" not in source
    assert "psql_command" not in source
