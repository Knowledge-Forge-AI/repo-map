"""Small strict value checks shared by the paired-report projections."""

from __future__ import annotations

from collections.abc import Mapping
import math

from retrieval_semantic_pair_artifacts import refuse


def metric_mapping(value: object, code: str) -> Mapping[str, object] | None:
    """Accept only finite numeric stored metrics; booleans are not numbers here."""

    if value is None:
        return None
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise refuse(code)
    for item in value.values():
        if type(item) is bool or not isinstance(item, (int, float)):
            raise refuse(code)
        if isinstance(item, float) and not math.isfinite(item):
            raise refuse(code)
    return value


def unit_interval(value: object, code: str) -> float | int | None:
    """Validate an optional stored [0, 1] metric without converting it."""

    if value is None:
        return None
    if type(value) is bool or not isinstance(value, (int, float)):
        raise refuse(code)
    if isinstance(value, float) and not math.isfinite(value):
        raise refuse(code)
    if not 0 <= value <= 1:
        raise refuse(code)
    return value


def grade_values_equal(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    """Compare dual stored grade slots without comparing their source labels."""

    ignored = {"grade_source", "file_grading_policy_version_source"}
    return {
        key: value for key, value in left.items() if key not in ignored
    } == {
        key: value for key, value in right.items() if key not in ignored
    }


__all__ = ["grade_values_equal", "metric_mapping", "unit_interval"]
