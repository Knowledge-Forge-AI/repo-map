"""Plain typed rows of the frozen first-use recipe.

These are data, not behavior. Each field is a constant taken from a current
owner contract or from public fixture text; none is derived from a report,
plan or other current output. ``payload()`` gives the canonical projection that
``recipe_digest`` binds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Location = tuple[str, str]


@dataclass(frozen=True)
class ReportSpec:
    """Expected identity labels of one decoded resource-report member."""

    schema: int
    operation: str
    backend: str
    outcomes: tuple[str, ...]
    instrumentation: str | None

    def payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "operation": self.operation, "backend": self.backend,
            "outcomes": list(self.outcomes), "instrumentation": self.instrumentation,
        }


@dataclass(frozen=True)
class PackSpec:
    """One context pack inside a pack action, identified by its tag."""

    tag: str
    mode: str
    query: str | None
    intent: str | None
    selection: str
    statuses: tuple[str, ...]
    reason: str | None = None
    canonical_key: str | None = None
    expected: tuple[Location, ...] = ()
    forbidden: tuple[Location, ...] = ()
    investigation: bool = False

    def payload(self) -> dict[str, Any]:
        return {
            "tag": self.tag, "mode": self.mode, "query": self.query, "intent": self.intent,
            "selection": self.selection, "statuses": list(self.statuses), "reason": self.reason,
            "canonical_key": self.canonical_key,
            "expected": [list(item) for item in self.expected],
            "forbidden": [list(item) for item in self.forbidden],
            "investigation": self.investigation,
        }


@dataclass(frozen=True)
class LexicalSpec:
    """One lexical call: the fixed query text and its manual location checks."""

    results: tuple[str, ...]
    query: str | None = None
    query_aliases: tuple[str, ...] = ()
    expected: tuple[Location, ...] = ()
    forbidden: tuple[Location, ...] = ()
    unavailable_reason: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "results": list(self.results), "query": self.query,
            "query_aliases": list(self.query_aliases),
            "expected": [list(item) for item in self.expected],
            "forbidden": [list(item) for item in self.forbidden],
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True)
class RecipeStep:
    """One required observation row of one scenario."""

    scenario: str
    step: int
    action: str
    backend: str
    aliases: tuple[str, ...]
    sub: int = 0
    expectation: str = "pass"
    generation: int | None = None
    refusal_codes: tuple[str, ...] = ()
    report: ReportSpec | None = None
    plan: bool = False
    fact_backends: tuple[str, ...] = ()
    pin_relation: str | None = None
    budget_multiplier: int | None = None
    packs: tuple[PackSpec, ...] = ()
    lexical: LexicalSpec | None = None
    harness_cleanup: bool = False
    calls: tuple[str, ...] = field(default=())

    @property
    def key(self) -> tuple[int, int]:
        return (self.step, self.sub)

    def catalog_row(self) -> list[Any]:
        return [self.scenario, self.backend, self.step, self.sub, self.action, self.expectation]

    def payload(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario, "step": self.step, "sub": self.sub,
            "action": self.action, "backend": self.backend, "aliases": list(self.aliases),
            "expectation": self.expectation, "generation": self.generation,
            "refusal_codes": list(self.refusal_codes),
            "report": None if self.report is None else self.report.payload(),
            "plan": self.plan, "fact_backends": list(self.fact_backends),
            "pin_relation": self.pin_relation, "budget_multiplier": self.budget_multiplier,
            "packs": [item.payload() for item in self.packs],
            "lexical": None if self.lexical is None else self.lexical.payload(),
            "harness_cleanup": self.harness_cleanup, "calls": list(self.calls),
        }


Recipe = tuple[RecipeStep, ...]

__all__ = ["LexicalSpec", "Location", "PackSpec", "Recipe", "RecipeStep", "ReportSpec"]
