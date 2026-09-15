"""Multi-band scaling analysis for SCALE11 profile results."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence

from scale11_profile_contracts import (
    FAMILIES,
    ProfileAggregate,
    ProfileResult,
    Scale11ContractError,
)


def analyze_scaling(results: Sequence[ProfileResult]) -> ProfileAggregate:
    """Characterize multiple bands without discarding source repetitions."""

    if not results:
        raise Scale11ContractError("scaling results are required")
    retained = tuple(results)
    profile = retained[0].profile
    if any(result.profile != profile for result in retained):
        raise Scale11ContractError("scaling profile is inconsistent")
    groups = {
        size: tuple(result for result in retained if result.size_band == size)
        for size in sorted({result.size_band for result in retained})
    }
    medians = tuple(
        statistics.median(item.elapsed_seconds for item in group)
        for group in groups.values()
    )
    coefficients = tuple(
        _coefficient_of_variation(item.elapsed_seconds for item in group)
        for group in groups.values()
    )
    ratios = tuple(
        current / previous if previous else math.inf
        for previous, current in zip(medians, medians[1:])
    )
    family_medians = {
        family: tuple(
            statistics.median(
                next(
                    item.row_count
                    for item in result.families
                    if item.family == family
                )
                for result in group
            )
            for group in groups.values()
        )
        for family in FAMILIES
    }
    return ProfileAggregate(
        profile=profile,
        size_bands=tuple(groups),
        repetition_count=len(retained),
        elapsed_medians=medians,
        elapsed_coefficients_of_variation=coefficients,
        elapsed_ratios=ratios,
        classification=_classify(tuple(groups), groups, ratios, coefficients),
        repetitions=retained,
        family_row_medians=family_medians,
    )


def _classify(
    size_bands: Sequence[int],
    groups: Mapping[int, Sequence[ProfileResult]],
    ratios: Sequence[float],
    coefficients: Sequence[float],
) -> str:
    if len(size_bands) < 4 or any(
        len(group) < 3 for group in groups.values()
    ):
        return "insufficient_evidence"
    if any(value > 0.15 for value in coefficients):
        return "measurement_unstable"
    size_ratios = tuple(
        current / previous
        for previous, current in zip(size_bands, size_bands[1:])
    )
    normalized = tuple(
        elapsed / size
        for elapsed, size in zip(ratios, size_ratios, strict=True)
    )
    if sum(value > 1.1 for value in normalized) >= 2:
        return "superlinear_suspect"
    if all(value < 0.5 for value in normalized):
        return "fixed_overhead_dominated"
    if all(0.75 <= value <= 1.25 for value in normalized):
        return "stable_linear_characterization"
    return "data_shape_sensitive"


def _coefficient_of_variation(values: Iterable[float]) -> float:
    retained = tuple(float(value) for value in values)
    mean = statistics.fmean(retained)
    return statistics.pstdev(retained) / mean if mean else 0.0
