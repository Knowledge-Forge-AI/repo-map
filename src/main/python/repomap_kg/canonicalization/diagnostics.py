"""Canonicalization diagnostic records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"
SEVERITIES = frozenset({SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO})
SEVERITY_SORT_ORDER = {
    SEVERITY_ERROR: 0,
    SEVERITY_WARNING: 1,
    SEVERITY_INFO: 2,
}


@dataclass(frozen=True)
class CanonicalizationDiagnostic:
    severity: str
    category: str
    message: str
    raw_observation_ordinal: int | None = None
    raw_source_id: str | None = None
    path: str | None = None
    field: str | None = None
    value: Any | None = None
    placeholder_key: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError("diagnostic severity must be error, warning, or info")
        if not self.category:
            raise ValueError("diagnostic category is required")
        if not self.message:
            raise ValueError("diagnostic message is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "raw_observation_ordinal": self.raw_observation_ordinal,
            "raw_source_id": self.raw_source_id,
            "path": self.path,
            "field": self.field,
            "value": self.value,
            "placeholder_key": self.placeholder_key,
        }


def diagnostic_sort_key(
    diagnostic: CanonicalizationDiagnostic,
) -> tuple[object, ...]:
    ordinal = (
        diagnostic.raw_observation_ordinal
        if diagnostic.raw_observation_ordinal is not None
        else float("inf")
    )
    return (
        ordinal,
        SEVERITY_SORT_ORDER[diagnostic.severity],
        diagnostic.category,
        diagnostic.path or "",
        diagnostic.field or "",
        diagnostic.message,
    )


def diagnostics_have_errors(
    diagnostics: tuple[CanonicalizationDiagnostic, ...],
) -> bool:
    return any(diagnostic.severity == SEVERITY_ERROR for diagnostic in diagnostics)
