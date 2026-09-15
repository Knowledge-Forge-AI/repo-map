"""Small durable updates for polling reconciliation conditions."""

from __future__ import annotations

from collections.abc import Sequence
import re

from repomap_kg.coordinator._control_submission import _safe_category
from repomap_kg.coordinator._control_types import ConnectionFactory

_GRAPH_ID = re.compile(r"[a-z][a-z0-9._-]{0,127}\Z")


def record_current(
    connect: ConnectionFactory,
    graph_id: str,
    generations: Sequence[str],
    *,
    next_reconcile_seconds: float,
) -> bool:
    """Record one current desired state without creating a control row."""

    values = _validate(graph_id, generations, next_reconcile_seconds)
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE coalescing_state
                SET desired_source_generation = %s,
                    desired_config_generation = %s,
                    desired_extractor_generation = %s,
                    desired_canonicalizer_generation = %s,
                    dirty = false,
                    reason_categories = ARRAY['current']::text[],
                    next_reconcile_at = now() + make_interval(secs => %s),
                    last_hint_at = now()
                WHERE graph_id = %s AND job_kind_family = 'refresh_graph'
                """,
                (*values[1], values[2], values[0]),
            )
            return cursor.rowcount == 1


def record_condition(
    connect: ConnectionFactory,
    graph_id: str,
    category: str,
    *,
    next_reconcile_seconds: float,
) -> bool:
    """Record a bounded polling condition while preserving desired intent."""

    safe_graph_id = _safe_graph_id(graph_id)
    safe_category = _safe_category(category, "condition")
    if next_reconcile_seconds <= 0:
        raise ValueError("reconciliation delay is invalid")
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE coalescing_state
                SET reason_categories = ARRAY[%s]::text[],
                    next_reconcile_at = now() + make_interval(secs => %s),
                    last_hint_at = now()
                WHERE graph_id = %s AND job_kind_family = 'refresh_graph'
                """,
                (safe_category, next_reconcile_seconds, safe_graph_id),
            )
            return cursor.rowcount == 1


def _validate(
    graph_id: str,
    generations: Sequence[str],
    next_reconcile_seconds: float,
) -> tuple[str, tuple[str, str, str, str], float]:
    safe_graph_id = _safe_graph_id(graph_id)
    values = tuple(generations)
    if len(values) != 4 or any(not isinstance(value, str) for value in values):
        raise ValueError("reconciliation generations are invalid")
    if next_reconcile_seconds <= 0:
        raise ValueError("reconciliation delay is invalid")
    return (
        safe_graph_id,
        (values[0], values[1], values[2], values[3]),
        next_reconcile_seconds,
    )


def _safe_graph_id(value: str) -> str:
    if not isinstance(value, str) or _GRAPH_ID.fullmatch(value) is None:
        raise ValueError("graph_id is invalid")
    return value


__all__ = ["record_condition", "record_current"]
