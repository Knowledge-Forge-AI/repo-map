"""Bounded PostgreSQL plan-label validation for observed operation records."""

from __future__ import annotations

import re
from typing import cast


_PLAN_NODE = re.compile(r"[A-Za-z][A-Za-z0-9 _-]{0,127}\Z")


def validate_plan_node_list(value: object, field: str, *, max_items: int = 128) -> list[str]:
    """Accept actual PostgreSQL labels such as ``Seq Scan`` without widening identities."""
    if type(value) is not list or len(value) > max_items:
        raise ValueError(field)
    items = cast(list[object], value)
    if not items:
        raise ValueError(field)
    if any(type(item) is not str or _PLAN_NODE.fullmatch(item) is None for item in items):
        raise ValueError(field)
    result = cast(list[str], items)
    return result


__all__ = ["validate_plan_node_list"]
