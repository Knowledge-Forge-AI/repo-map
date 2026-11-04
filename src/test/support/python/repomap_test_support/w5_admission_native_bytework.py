"""Checked accessors for admission native byte-work evidence."""

from __future__ import annotations

from collections.abc import Mapping


def _nested_mapping(
    record: Mapping[str, object], field: str
) -> Mapping[str, object]:
    value = record.get(field)
    if not isinstance(value, Mapping):
        raise AssertionError(f"native byte-work {field} mapping missing")
    return value


def byte_work_identity(record: Mapping[str, object]) -> Mapping[str, object]:
    return _nested_mapping(record, "identity")


def byte_work_accounting(record: Mapping[str, object]) -> Mapping[str, object]:
    return _nested_mapping(record, "accounting")


__all__ = ["byte_work_accounting", "byte_work_identity"]
