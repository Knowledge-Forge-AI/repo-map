"""Test-owned startup ordering and deadline feasibility oracle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class StartupAlternative:
    """One public-safe startup ordering alternative."""

    name: str
    ordered_authorities: tuple[str, ...]
    required_budget_units: int
    preserves_contract: bool


ALTERNATIVES = (
    StartupAlternative(
        "reported_candidate",
        (
            "resource_start",
            "observer_register",
            "ownership_first",
            "ownership_second",
            "resource_settle",
        ),
        6,
        True,
    ),
    StartupAlternative(
        "resource_settlement_before_final_ownership",
        (
            "resource_start",
            "observer_register",
            "ownership_first",
            "resource_settle",
            "ownership_second",
        ),
        5,
        True,
    ),
    StartupAlternative(
        "observer_before_resource_sampling",
        (
            "observer_register",
            "resource_start",
            "resource_settle",
            "ownership_first",
            "ownership_second",
        ),
        5,
        True,
    ),
    StartupAlternative(
        "reuse_authoritative_snapshot",
        ("resource_start", "observer_register", "resource_settle", "ownership_second"),
        4,
        False,
    ),
    StartupAlternative(
        "reserve_complete_operation_budget",
        (
            "observer_register",
            "resource_start",
            "resource_settle",
            "ownership_first",
            "ownership_second",
        ),
        5,
        True,
    ),
)


def release_is_authorized(observed: Iterable[str]) -> bool:
    """Require every startup authority and settlement before release."""

    sequence = tuple(observed)
    required = {
        "observer_register",
        "resource_start",
        "resource_settle",
        "ownership_first",
        "ownership_second",
    }
    if not required.issubset(sequence):
        return False
    return (
        sequence.index("resource_start") < sequence.index("resource_settle")
        and sequence.index("ownership_first") < sequence.index("ownership_second")
        and sequence.index("resource_settle") < sequence.index("ownership_second")
    )


def fits_unchanged_ceiling(
    alternative: StartupAlternative,
    *,
    available_budget_units: int,
) -> bool:
    """Reject work that cannot reserve its complete inner authority."""

    return (
        alternative.preserves_contract
        and alternative.required_budget_units <= available_budget_units
    )


__all__ = [
    "ALTERNATIVES",
    "StartupAlternative",
    "fits_unchanged_ceiling",
    "release_is_authorized",
]
