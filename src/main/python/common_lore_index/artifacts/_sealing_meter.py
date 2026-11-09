"""One call-owned, monotone sealing I/O meter (ADR 0173 A1-A4).

The meter is created by the caller of one ``seal_configured_sources`` call and
passed explicitly to every owned reader, walker and store writer. It is never a
global, thread-local or context variable. Counters only increase: they are
never reset or refunded across bindings, scans, attempts, retries or
collisions. Every admission runs before the governed operation, so a counter
never exceeds its budget.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Callable

from common_lore_index.artifacts.sealing_governance import (
    SealingBudget,
    SealingBudgetExceeded,
    effective_max_directory_entries,
    normalize_budget,
    planned_min_read_bytes,
)

READERS = ("discovery", "classification", "capture", "copy", "store")


class SealingMeterMisuse(RuntimeError):
    """A meter was used outside its owning thread or contract."""


@dataclass(frozen=True)
class SealingPlanFacts:
    """Metadata-only inventory facts of one governed preflight walk."""

    bindings: int
    inventory_files: int
    inventory_bytes: int
    inventory_symlinked_files: int


@dataclass(frozen=True)
class SealingMeterSnapshot:
    """Detached counters; ``complete`` is true only after :meth:`SealingMeter.close`."""

    complete: bool
    governed: bool
    read_bytes: int
    reader_bytes: tuple[tuple[str, int], ...]
    write_bytes: int
    read_calls: int
    opens: int
    directory_entries: int
    fsyncs: int
    capture_retries: int
    refused_limit: str | None
    plan: SealingPlanFacts | None
    budget: SealingBudget | None
    effective_max_directory_entries: int | None

    def reader(self, name: str) -> int:
        return dict(self.reader_bytes)[name]


class SealingMeter:
    """Count and admit the program I/O of one sealing call."""

    def __init__(
        self,
        budget: SealingBudget | None,
        *,
        governed: bool,
        _monotonic_ns: Callable[[], int] | None = None,
    ) -> None:
        self._budget = normalize_budget(budget)
        if self._budget is not None and not governed:
            raise ValueError("a sealing budget requires governed mode")
        self._governed = bool(governed)
        self._owner = threading.get_ident()
        self._clock = _monotonic_ns if _monotonic_ns is not None else time.monotonic_ns
        self._started = self._clock()
        self._entry_ceiling = (
            effective_max_directory_entries(self._budget) if self._governed else None
        )
        self._reader_bytes = dict.fromkeys(READERS, 0)
        self._read_bytes = self._write_bytes = self._read_calls = 0
        self._opens = self._entries = self._fsyncs = self._retries = 0
        self._refused: str | None = None
        self._plan: SealingPlanFacts | None = None
        self._closed = False

    @property
    def governed(self) -> bool:
        return self._governed

    @property
    def budget(self) -> SealingBudget | None:
        return self._budget

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def refused_limit(self) -> str | None:
        return self._refused

    def _own(self) -> None:
        if threading.get_ident() != self._owner:
            raise SealingMeterMisuse("sealing meter used outside its owning thread")
        if self._closed:
            raise SealingMeterMisuse("sealing meter is closed")

    def _refuse(self, limit: str) -> SealingBudgetExceeded:
        if self._refused is None:
            self._refused = limit
        return SealingBudgetExceeded(limit)

    def _admit(self) -> None:
        self._own()
        limit = None if self._budget is None else self._budget.max_elapsed_ms
        if limit is not None and self._clock() - self._started >= limit * 1_000_000:
            raise self._refuse("elapsed_ms")

    def remaining_read(self) -> int | None:
        limit = None if self._budget is None else self._budget.max_read_bytes
        return None if limit is None else limit - self._read_bytes

    def remaining_write(self) -> int | None:
        limit = None if self._budget is None else self._budget.max_write_bytes
        return None if limit is None else limit - self._write_bytes

    def probe_length(self, chunk: int) -> int:
        """A2 end-of-file probe size; at least one byte is always admitted."""
        remaining = self.remaining_read()
        return chunk if remaining is None else max(1, min(chunk, remaining))

    def admit_read(self, length: int) -> None:
        self._admit()
        if type(length) is not int or length < 1:
            raise SealingMeterMisuse("read admission requires a positive length")
        remaining = self.remaining_read()
        if remaining is not None and length > remaining:
            raise self._refuse("read_bytes")

    def charge_read(self, reader: str, returned: int, admitted: int) -> None:
        self._own()
        if reader not in self._reader_bytes or not 0 <= returned <= admitted:
            raise SealingMeterMisuse("read charge does not match its admission")
        self._read_calls += 1
        self._read_bytes += returned
        self._reader_bytes[reader] += returned

    def require_read_headroom(self, size: int) -> None:
        """A5: refuse a full-body read before opening when it cannot fit."""
        self._admit()
        remaining = self.remaining_read()
        if remaining is not None and size > remaining:
            raise self._refuse("read_bytes")

    def admit_write(self, length: int) -> None:
        self._admit()
        if type(length) is not int or length < 1:
            raise SealingMeterMisuse("write admission requires a positive length")
        remaining = self.remaining_write()
        if remaining is not None and length > remaining:
            raise self._refuse("write_bytes")

    def charge_write(self, written: int, admitted: int) -> None:
        self._own()
        if not 0 <= written <= admitted:
            raise SealingMeterMisuse("write charge does not match its admission")
        self._write_bytes += written

    def admit_open(self) -> None:
        """Admit and count one open, listing or temporary-file creation attempt."""
        self._admit()
        limit = None if self._budget is None else self._budget.max_opens
        if limit is not None and self._opens + 1 > limit:
            raise self._refuse("opens")
        self._opens += 1

    def admit_entry(self) -> None:
        """Admit one retrieved directory entry before it is retained."""
        self._admit()
        if self._entry_ceiling is not None and self._entries + 1 > self._entry_ceiling:
            raise self._refuse("directory_entries")
        self._entries += 1

    def admit_fsync(self) -> None:
        self._admit()
        self._fsyncs += 1

    def note_retry(self) -> None:
        self._own()
        self._retries += 1

    def refuse_retention(self) -> SealingBudgetExceeded:
        self._own()
        return self._refuse("classification_retention")

    def note_plan(self, plan: SealingPlanFacts) -> None:
        """Record preflight facts and refuse a provable planned overrun."""
        self._own()
        if not self._governed or self._plan is not None:
            raise SealingMeterMisuse("plan facts require one governed preflight")
        self._plan = plan
        remaining_read = self.remaining_read()
        if remaining_read is not None and planned_min_read_bytes(plan.inventory_bytes) > remaining_read:
            raise self._refuse("planned_read_bytes")
        remaining_write = self.remaining_write()
        if remaining_write is not None and plan.inventory_bytes > remaining_write:
            raise self._refuse("planned_write_bytes")

    def close(self) -> None:
        self._own()
        self._closed = True

    def snapshot(self) -> SealingMeterSnapshot:
        if threading.get_ident() != self._owner:
            raise SealingMeterMisuse("sealing meter used outside its owning thread")
        return SealingMeterSnapshot(
            complete=self._closed,
            governed=self._governed,
            read_bytes=self._read_bytes,
            reader_bytes=tuple(self._reader_bytes.items()),
            write_bytes=self._write_bytes,
            read_calls=self._read_calls,
            opens=self._opens,
            directory_entries=self._entries,
            fsyncs=self._fsyncs,
            capture_retries=self._retries,
            refused_limit=self._refused,
            plan=self._plan,
            budget=self._budget,
            effective_max_directory_entries=self._entry_ceiling,
        )


def meter_kwargs(meter: SealingMeter | None) -> dict[str, Any]:
    """Forward ``io_meter`` only when a meter exists, keeping default seams intact."""

    return {} if meter is None else {"io_meter": meter}


__all__ = (
    "READERS",
    "SealingMeter",
    "SealingMeterMisuse",
    "SealingMeterSnapshot",
    "SealingPlanFacts",
    "meter_kwargs",
)
