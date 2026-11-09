"""Opt-in, call-owned sealing budgets and their closed refusal (ADR 0173).

A :class:`SealingBudget` bounds the program I/O of one explicit
``seal_configured_sources`` call: bytes returned by the owned readers, bytes
admitted to the owned store writer, descriptor and listing opens, directory
entries, and cooperative elapsed time. Every bound is admitted before the
operation it governs, so a counter never exceeds its budget. These are program
counters, not physical storage traffic.

No budget is the default. An all-``None`` budget normalizes to no budget, and
default calls keep their incumbent outputs, exit codes, patch seams and I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

MAX_COUNTER = 2**63 - 1
MAX_ELAPSED_MS = 86_400_000
CLASSIFICATION_MAX_RETAINED_CHARS = 1_048_576
GOVERNED_DEFAULT_MAX_DIRECTORY_ENTRIES = 100_000
STABLE_CAPTURE_MAX_ATTEMPTS = 3
FULL_BODY_READS_PER_FILE = 4
COLLISION_EXTRA_READS_PER_FILE = 1
RESOURCE_BUDGET_EXCEEDED = "resource_budget_exceeded"
BUDGET_LIMITS = (
    "read_bytes",
    "write_bytes",
    "opens",
    "directory_entries",
    "elapsed_ms",
    "planned_read_bytes",
    "planned_write_bytes",
    "classification_retention",
)


class SealingBudgetExceeded(ValueError):
    """A governed sealing call refused before exceeding one closed limit.

    The message is path-free and names only the limit, so it can be printed
    or embedded in a public diagnostic without redaction.
    """

    category = RESOURCE_BUDGET_EXCEEDED

    def __init__(self, limit: str) -> None:
        if limit not in BUDGET_LIMITS:
            raise ValueError("invalid sealing budget limit")
        self.limit = limit
        super().__init__(f"sealing budget exceeded: {limit}")


def _bounded(value: object, maximum: int) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("invalid sealing budget")
    return value


@dataclass(frozen=True)
class SealingBudget:
    """Optional per-call ceilings; ``None`` leaves a dimension unbounded."""

    max_read_bytes: int | None = None
    max_write_bytes: int | None = None
    max_opens: int | None = None
    max_directory_entries: int | None = None
    max_elapsed_ms: int | None = None

    def __post_init__(self) -> None:
        for item in fields(self):
            maximum = MAX_ELAPSED_MS if item.name == "max_elapsed_ms" else MAX_COUNTER
            _bounded(getattr(self, item.name), maximum)

    @property
    def empty(self) -> bool:
        return all(getattr(self, item.name) is None for item in fields(self))


def normalize_budget(budget: object) -> SealingBudget | None:
    """Return a nonempty budget or ``None``; refuse any other object."""

    if budget is None:
        return None
    if type(budget) is not SealingBudget:
        raise ValueError("invalid sealing budget")
    return None if budget.empty else budget


def governance_kwargs(budget: object) -> dict[str, Any]:
    """Forward ``sealing_budget`` only when a nonempty budget was selected."""

    normalized = normalize_budget(budget)
    return {} if normalized is None else {"sealing_budget": normalized}


def effective_max_directory_entries(budget: SealingBudget | None) -> int:
    """The finite visit ceiling of an explicitly governed operation."""

    if budget is not None and budget.max_directory_entries is not None:
        return budget.max_directory_entries
    return GOVERNED_DEFAULT_MAX_DIRECTORY_ENTRIES


def planned_min_read_bytes(total_bytes: int) -> int:
    """Lower bound for one successful seal of a static inventory of ``S`` bytes."""

    return FULL_BODY_READS_PER_FILE * total_bytes + 1


__all__ = (
    "BUDGET_LIMITS",
    "CLASSIFICATION_MAX_RETAINED_CHARS",
    "COLLISION_EXTRA_READS_PER_FILE",
    "FULL_BODY_READS_PER_FILE",
    "GOVERNED_DEFAULT_MAX_DIRECTORY_ENTRIES",
    "MAX_COUNTER",
    "MAX_ELAPSED_MS",
    "RESOURCE_BUDGET_EXCEEDED",
    "STABLE_CAPTURE_MAX_ATTEMPTS",
    "SealingBudget",
    "SealingBudgetExceeded",
    "effective_max_directory_entries",
    "governance_kwargs",
    "normalize_budget",
    "planned_min_read_bytes",
)
