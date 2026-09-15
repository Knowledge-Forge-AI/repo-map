from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import psycopg
from psycopg import Cursor
from psycopg.abc import Params, Query

from repomap_test_support.test_cov5g_r1_characterization import PROTOCOL
from repomap_test_support.test_cov5g_r1_measurement import (
    _backend_disappeared,
)
from repomap_test_support.test_cov5k_r2_observer_protocol import (
    ADR_0046_EXPECTATIONS,
)
import repomap_test_support.test_cov5g_r1_measurement as measurement


_CLEANUP_BUDGET_SECONDS = ADR_0046_EXPECTATIONS.cleanup_attempt_ms / 1_000
_HISTORICAL_WINDOW_SECONDS = PROTOCOL.observation_ceiling_ms / 1_000
_APPLICATION_NAME = "cov5g_r1_A_cpu_02"


class _FakeClock:
    """Deterministic monotonic/sleep seam with no wall-clock dependence."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _FakeResult(Cursor[tuple[int]]):
    def __init__(self, count: int) -> None:
        self._count = count

    def fetchone(self) -> tuple[int]:
        return (self._count,)


class _FakeAdmin(psycopg.Connection[tuple[int]]):
    """Admin observer whose backend disappears at a modelled instant."""

    def __init__(
        self,
        clock: _FakeClock,
        disappears_at: float,
        *,
        error: Exception | None = None,
        query_cost: float = 0.0,
    ) -> None:
        self._clock = clock
        self._disappears_at = disappears_at
        self._error = error
        self._query_cost = query_cost
        self.parameters: list[tuple[object, ...]] = []

    def execute(
        self,
        query: Query,
        params: Params | None = None,
        *,
        prepare: bool | None = None,
        binary: bool = False,
    ) -> _FakeResult:
        if params is not None:
            self.parameters.append(
                tuple(params) if isinstance(params, (list, tuple)) else (params,)
            )
        self._clock.now += self._query_cost
        if self._error is not None:
            raise self._error
        present = self._clock.now < self._disappears_at
        return _FakeResult(1 if present else 0)


def _observe(
    monkeypatch: pytest.MonkeyPatch,
    disappears_at: float,
    *,
    error: Exception | None = None,
    query_cost: float = 0.0,
    timeout_seconds: float | None = None,
) -> tuple[bool, _FakeClock, _FakeAdmin]:
    clock = _FakeClock()
    monkeypatch.setattr(measurement, "time", clock)
    admin = _FakeAdmin(
        clock, disappears_at, error=error, query_cost=query_cost
    )
    if timeout_seconds is None:
        disappeared = _backend_disappeared(admin, _APPLICATION_NAME)
    else:
        disappeared = _backend_disappeared(
            admin, _APPLICATION_NAME, timeout_seconds=timeout_seconds
        )
    return disappeared, clock, admin


def test_cleanup_budget_is_the_adr_cleanup_attempt_authority() -> None:
    default = inspect.signature(
        _backend_disappeared
    ).parameters["timeout_seconds"].default
    assert default == _CLEANUP_BUDGET_SECONDS
    assert default == 5.0
    assert default != _HISTORICAL_WINDOW_SECONDS


def test_backend_absent_on_first_poll_is_immediately_proven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disappeared, clock, admin = _observe(monkeypatch, 0.0)
    assert disappeared is True
    assert len(admin.parameters) == 1
    assert admin.parameters[0] == (_APPLICATION_NAME,)
    assert clock.now == 0.0


def test_disappearance_after_the_historical_window_still_proves_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disappears_at = _HISTORICAL_WINDOW_SECONDS + 1.0
    assert disappears_at < _CLEANUP_BUDGET_SECONDS
    disappeared, clock, _ = _observe(monkeypatch, disappears_at)
    assert disappeared is True
    assert clock.now >= _HISTORICAL_WINDOW_SECONDS
    assert clock.now < _CLEANUP_BUDGET_SECONDS


def test_backend_present_through_the_cleanup_budget_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disappeared, clock, _ = _observe(monkeypatch, float("inf"))
    assert disappeared is False
    assert clock.now >= _CLEANUP_BUDGET_SECONDS


def test_disappearance_after_the_cleanup_budget_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disappeared, _, _ = _observe(
        monkeypatch, _CLEANUP_BUDGET_SECONDS + 0.5
    )
    assert disappeared is False


def test_contended_admin_query_cost_is_charged_against_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disappeared, clock, admin = _observe(
        monkeypatch, _HISTORICAL_WINDOW_SECONDS + 1.0, query_cost=0.05
    )
    assert disappeared is True
    assert clock.now < _CLEANUP_BUDGET_SECONDS
    assert len(admin.parameters) < 100


def test_explicit_timeout_bounds_the_cleanup_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disappeared, clock, _ = _observe(
        monkeypatch, 1.0, timeout_seconds=0.5
    )
    assert disappeared is False
    assert clock.now < 1.0
    disappeared, _, _ = _observe(
        monkeypatch, 1.0, timeout_seconds=1.5
    )
    assert disappeared is True


def test_admin_observation_failure_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RuntimeError, match="admin observation failed"):
        _observe(
            monkeypatch, 0.0, error=RuntimeError("admin observation failed")
        )


def _cleanup_wait_follows_timing(function_name: str) -> None:
    source = Path(measurement.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=measurement.__file__)
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == function_name
    )
    timing_lines = [
        target.lineno
        for statement in ast.walk(node)
        if isinstance(statement, ast.Assign)
        for target in statement.targets
        if isinstance(target, ast.Name)
        and target.id in {"request_elapsed", "projection_order"}
    ]
    cleanup_lines = [
        call.lineno
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "_backend_disappeared"
    ]
    assert timing_lines and cleanup_lines
    assert max(timing_lines) < min(cleanup_lines)


@pytest.mark.parametrize(
    "function_name",
    ("run_direct_observation", "run_configured_observation"),
)
def test_timing_values_are_computed_before_the_cleanup_wait(
    function_name: str,
) -> None:
    _cleanup_wait_follows_timing(function_name)
