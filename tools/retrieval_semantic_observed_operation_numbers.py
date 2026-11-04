"""Finite non-negative numeric fields for observed-operation evidence."""

from __future__ import annotations

import math
from typing import cast

from retrieval_semantic_experiment_contracts import ExperimentRefusal


def validate_nonnegative_number(
    value: object, field: str, *, nullable: bool = False,
) -> float | None:
    if value is None and nullable:
        return None
    if type(value) not in (int, float):
        raise ExperimentRefusal("observed_operation_" + field)
    try:
        number = float(cast(int | float, value))
    except OverflowError:
        raise ExperimentRefusal("observed_operation_" + field) from None
    if not math.isfinite(number) or number < 0:
        raise ExperimentRefusal("observed_operation_" + field)
    return number



__all__ = ["validate_nonnegative_number"]
