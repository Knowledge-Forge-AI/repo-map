"""Opt-in sealing governance and worker attribution for one portable capture.

These helpers keep ``capture_portable_candidate`` small. Without a budget and
without a ``cloe-resource-view-v2`` observer they return nothing and forward
nothing, so default calls keep their incumbent seams and I/O. A nonempty budget
combined with a v1 observer is refused before any work: v1 would otherwise
claim that the active sealing limit is absent.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts.sealing_governance import (
    SealingBudget,
    SealingBudgetExceeded,
    normalize_budget,
)
from common_lore_index.ops.resource_view import (
    ResourceObserver,
    note_sealing_meter,
    note_sealing_refusal,
)
from common_lore_index.ops.resource_view._contracts_v2 import SCHEMA_V2

BUDGET_REQUIRES_SCHEMA_2 = "sealing-budget-requires-report-schema-2"
_Result = TypeVar("_Result")


def reports_v2(observer: object | None) -> bool:
    return type(observer) is ResourceObserver and observer.report_schema == SCHEMA_V2


def require_budget_schema(observer: object | None, budget: object) -> SealingBudget | None:
    """Normalize ``budget`` and refuse it with a v1 observer before any work."""

    normalized = normalize_budget(budget)
    # isinstance (not the exact-type feed rule): any v1-schema observer, including a
    # subclass, must never pair with an active budget it would report as absent.
    if (
        normalized is not None
        and isinstance(observer, ResourceObserver)
        and getattr(observer, "report_schema", None) != SCHEMA_V2
    ):
        raise ValueError(BUDGET_REQUIRES_SCHEMA_2)
    return normalized


def start_sealing_meter(observer: object | None, budget: object) -> SealingMeter | None:
    """Create the call-owned meter for a budget (governed) or a v2 observer (observe-only)."""

    normalized = require_budget_schema(observer, budget)
    if normalized is None and not reports_v2(observer):
        return None
    meter = SealingMeter(normalized, governed=normalized is not None)
    note_sealing_meter(observer, meter)
    return meter


def seal_with_meter(
    observer: object | None, meter: SealingMeter | None, seal: Callable[..., _Result]
) -> _Result:
    """Run ``seal`` with ``io_meter`` only when metered; close the meter on success."""

    if meter is None:
        return seal()
    try:
        result = seal(io_meter=meter)
    except SealingBudgetExceeded as error:
        note_sealing_refusal(observer, error)
        raise
    meter.close()
    return result


def usage_kwargs(observer: object | None) -> dict[str, Any]:
    """Collect owned-worker usage only for a v2 observer (opt-in B1/B4)."""

    return {"collect_usage": True} if reports_v2(observer) else {}


__all__ = (
    "BUDGET_REQUIRES_SCHEMA_2",
    "reports_v2",
    "require_budget_schema",
    "seal_with_meter",
    "start_sealing_meter",
    "usage_kwargs",
)
