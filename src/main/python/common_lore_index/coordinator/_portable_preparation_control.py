"""Call-owned early admission of the portable worker's prepared spool payload."""
from __future__ import annotations


class _PreparedRowAdmission:
    """Keep the spooled subset within already selected encoder bounds."""

    def __init__(self, byte_budget: int, record_budget: int) -> None:
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (byte_budget, record_budget)):
            raise ValueError("invalid prepared spool bounds")
        self._byte_budget = byte_budget
        self._record_budget = record_budget
        self._records = 0
        self._family_bytes: dict[str, int] = {}

    def __call__(self, family: str, projected_bytes: int) -> None:
        previous = self._family_bytes.get(family, 0)
        if not isinstance(projected_bytes, int) or isinstance(projected_bytes, bool) or projected_bytes <= previous:
            raise ValueError("invalid prepared spool growth")
        records = self._records + 1
        total = sum(self._family_bytes.values()) + projected_bytes - previous
        if records > self._record_budget:
            raise ValueError("publication bundle record bounds exceeded")
        if total > self._byte_budget:
            raise ValueError("publication bundle byte bounds exceeded")
        self._records = records
        self._family_bytes[family] = projected_bytes
