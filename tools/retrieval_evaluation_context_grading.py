"""Exact W4 graph/native locator grading helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from common_lore_index.retrieval.query_contracts import EvaluationLocator, QueryEnvelope
from retrieval_evaluation_context_catalog import ContextEvaluationTask


def _gold_keys(task: ContextEvaluationTask) -> set[tuple[str, str, str]]:
    primary_grade = max(g.relevance_grade for g in task.gold_targets)
    return {
        (g.canonical_key, g.source_binding_id, g.source_relative_path)
        for g in task.gold_targets
        if g.relevance_grade == primary_grade
    }


def grade_graph_packet(task: ContextEvaluationTask, packet: Mapping[str, Any]) -> int | None:
    """Return first rank credited by canonical key plus exact binding/path identity."""
    gold = _gold_keys(task)
    rank = 0
    for item in (*packet.get("items", ()), *packet.get("neighbors", ())):
        rank += 1
        canonical_key = item.get("canonical_key")
        for loc in item.get("locations", ()):
            if (
                canonical_key,
                loc.get("source_binding_id"),
                loc.get("source_relative_path"),
            ) in gold:
                return rank
    return None


def grade_native_envelope(task: ContextEvaluationTask, envelope: QueryEnvelope) -> int | None:
    """Grade native output by primary binding/path only; spans and canonical keys are unclaimed."""
    primary_grade = max(g.relevance_grade for g in task.gold_targets)
    gold_paths = {
        (g.source_binding_id, g.source_relative_path) for g in task.gold_targets
        if g.relevance_grade == primary_grade
    }
    for rank, hit in enumerate(envelope.hits, start=1):
        locator = hit.locator
        if (locator.binding_id, locator.source_relative_path) in gold_paths:
            return rank
    return None


NATIVE_GRADING_SCOPE = "binding_path_only"


def returned_graph_locators(packet: Mapping[str, Any]) -> tuple[EvaluationLocator, ...]:
    locators: list[EvaluationLocator] = []
    for item in (*packet.get("items", ()), *packet.get("neighbors", ())):
        for loc in item.get("locations", ()):
            try:
                locators.append(
                    EvaluationLocator(
                        binding_id=loc["source_binding_id"],
                        source_relative_path=loc["source_relative_path"],
                        start_line=loc.get("start_line"),
                        end_line=loc.get("end_line"),
                        canonical_key=item.get("canonical_key"),
                    ).validate()
                )
            except (KeyError, TypeError, ValueError):
                continue
    return tuple(locators)


__all__ = [
    "NATIVE_GRADING_SCOPE",
    "grade_graph_packet",
    "grade_native_envelope",
    "returned_graph_locators",
]
