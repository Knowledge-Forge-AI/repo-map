"""Bounded work accounting, statement ceilings, and SQLite progress handler (W4 §4.3)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import time
from typing import Any

MAX_LOGICAL_READ_UNITS = 16
MAX_SQL_STATEMENTS_SQLITE = 36
MAX_SQL_STATEMENTS_POSTGRES = 12
MAX_SCAN_UNITS = 8
MAX_SEED_EXPANSIONS = 5
MAX_EXPANSION_EDGES_PER_SEED = 64
MAX_CANDIDATE_NEIGHBORS = 128
MAX_AGGREGATE_RELATIONS = 256

SQLITE_PROGRESS_HANDLER_INTERVAL = 1000
SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT = 250
SQLITE_VM_STEPS_PER_STATEMENT_ESTIMATE = (
    SQLITE_PROGRESS_HANDLER_INTERVAL * SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT
)
WALL_CLOCK_DEADLINE_MS = 10_000

WORK_LEDGER_KEYS: tuple[str, ...] = (
    "config_revalidations_executed",
    "logical_read_units",
    "max_logical_read_units",
    "sql_statements_executed",
    "max_sql_statements",
    "scan_units_executed",
    "max_scan_units",
    "seed_expansions_executed",
    "max_seed_expansions",
    "candidate_rows_scanned",
    "evidence_rows_scanned",
    "sqlite_vm_steps_estimate",
    "elapsed_ms",
    "actual_bytes",
    "sqlite_progress_callbacks",
    "sqlite_progress_interval_ops",
)


class ContextWorkExhaustedError(RuntimeError):
    """Raised when a statement ceiling, progress callback limit, or deadline is reached."""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


class GuardedSQLiteConnection:
    """Duck-typed SQLite connection that reserves each statement before execute."""

    def __init__(self, connection: Any, ledger: "WorkLedger") -> None:
        self._connection = connection
        self._ledger = ledger

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        if not self._ledger.record_statement_start():
            raise ContextWorkExhaustedError(
                self._ledger.exhausted_reason or "statement_limit"
            )
        return self._connection.execute(*args, **kwargs)

    def create_function(self, *args: Any, **kwargs: Any) -> Any:
        return self._connection.create_function(*args, **kwargs)


@dataclass
class WorkLedger:
    """Mutable work ledger tracking bounded database and assembly work."""

    backend: str = "sqlite"
    max_logical_read_units: int = MAX_LOGICAL_READ_UNITS
    max_sql_statements: int = MAX_SQL_STATEMENTS_SQLITE
    max_scan_units: int = MAX_SCAN_UNITS
    max_seed_expansions: int = MAX_SEED_EXPANSIONS
    deadline_ms: int = WALL_CLOCK_DEADLINE_MS
    sqlite_progress_callback_limit: int = SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT
    sqlite_progress_interval_ops: int = SQLITE_PROGRESS_HANDLER_INTERVAL
    clock: Callable[[], float] = time.monotonic

    config_revalidations_executed: int = 0
    logical_read_units: int = 0
    sql_statements_executed: int = 0
    scan_units_executed: int = 0
    seed_expansions_executed: int = 0
    candidate_rows_scanned: int = 0
    evidence_rows_scanned: int = 0
    sqlite_progress_callbacks: int = 0
    current_statement_callbacks: int = 0
    elapsed_ms: int = 0
    actual_bytes: int = 0
    exhausted_reason: str | None = None
    _start_time: float = field(init=False)

    def __post_init__(self) -> None:
        self._start_time = self.clock()
        max_statements = (
            MAX_SQL_STATEMENTS_POSTGRES
            if self.backend == "postgresql"
            else MAX_SQL_STATEMENTS_SQLITE
        )
        self.max_sql_statements = min(self.max_sql_statements, max_statements)
        self.max_logical_read_units = min(self.max_logical_read_units, MAX_LOGICAL_READ_UNITS)
        self.max_scan_units = min(self.max_scan_units, MAX_SCAN_UNITS)
        self.max_seed_expansions = min(self.max_seed_expansions, MAX_SEED_EXPANSIONS)
        self.sqlite_progress_callback_limit = min(
            self.sqlite_progress_callback_limit, SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT
        )
        self.sqlite_progress_interval_ops = max(
            1, min(self.sqlite_progress_interval_ops, SQLITE_PROGRESS_HANDLER_INTERVAL)
        )
        self.deadline_ms = min(self.deadline_ms, WALL_CLOCK_DEADLINE_MS)

    def refresh_elapsed_ms(self) -> int:
        elapsed = int(max(0.0, (self.clock() - self._start_time) * 1000.0))
        self.elapsed_ms = max(self.elapsed_ms, elapsed)
        return self.elapsed_ms

    def check_deadline(self) -> bool:
        if self.refresh_elapsed_ms() > self.deadline_ms:
            self.exhausted_reason = self.exhausted_reason or "deadline_exceeded"
            return False
        return True

    def can_execute_logical_unit(self) -> bool:
        if not self.check_deadline():
            return False
        if self.logical_read_units >= self.max_logical_read_units:
            self.exhausted_reason = self.exhausted_reason or "work_budget_exhausted"
            return False
        return True

    def can_execute_statements(self, count: int = 1) -> bool:
        if not self.check_deadline():
            return False
        if self.sql_statements_executed + count > self.max_sql_statements:
            self.exhausted_reason = self.exhausted_reason or "statement_limit"
            return False
        return True

    def record_logical_unit(self) -> None:
        self.logical_read_units += 1
        self.refresh_elapsed_ms()

    def record_statement_start(self) -> bool:
        """Called when a SQL statement begins; returns False if over statement ceiling."""
        self.current_statement_callbacks = 0
        if not self.check_deadline():
            return False
        if self.sql_statements_executed >= self.max_sql_statements:
            self.exhausted_reason = self.exhausted_reason or "statement_limit"
            return False
        self.sql_statements_executed += 1
        return True

    def make_sqlite_progress_handler(self) -> Callable[[], int]:
        """Return a sqlite3 progress handler enforcing callback and deadline limits."""

        def _handler() -> int:
            if self.exhausted_reason == "statement_limit":
                return 1
            self.sqlite_progress_callbacks += 1
            self.current_statement_callbacks += 1
            if self.current_statement_callbacks >= self.sqlite_progress_callback_limit:
                self.exhausted_reason = self.exhausted_reason or "work_budget_exhausted"
                return 1
            if not self.check_deadline():
                return 1
            return 0

        return _handler

    def to_dict(self) -> dict[str, Any]:
        is_sqlite = self.backend == "sqlite"
        vm_est = (
            self.sqlite_progress_callbacks * self.sqlite_progress_interval_ops
            if is_sqlite
            else None
        )
        return {
            "config_revalidations_executed": self.config_revalidations_executed,
            "logical_read_units": self.logical_read_units,
            "max_logical_read_units": self.max_logical_read_units,
            "sql_statements_executed": self.sql_statements_executed,
            "max_sql_statements": self.max_sql_statements,
            "scan_units_executed": self.scan_units_executed,
            "max_scan_units": self.max_scan_units,
            "seed_expansions_executed": self.seed_expansions_executed,
            "max_seed_expansions": self.max_seed_expansions,
            "candidate_rows_scanned": self.candidate_rows_scanned,
            "evidence_rows_scanned": self.evidence_rows_scanned,
            "sqlite_vm_steps_estimate": vm_est,
            "elapsed_ms": self.elapsed_ms,
            "actual_bytes": self.actual_bytes,
            "sqlite_progress_callbacks": self.sqlite_progress_callbacks if is_sqlite else None,
            "sqlite_progress_interval_ops": self.sqlite_progress_interval_ops if is_sqlite else None,
        }
