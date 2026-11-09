"""Read-only, identity-free ``cloe-sealing-plan-v1`` (ADR 0173 section 5.4).

After ordinary read-only configuration resolution, the plan runs only the
governed metadata walk of every binding: no selected-source body read, database
connection, graph lock, worker or write. ``planned_min_read_bytes`` (``4S+1``)
is a ``derived_lower_bound`` for one *successful* seal of the metadata
inventory at that instant; a refusal reads less, and the value is not a promise
about a later refresh. ``projected_directory_entries`` is a labelled estimate:
three times the observed preflight visits for an unchanged metadata tree,
because preflight and both scans are distinct walks. Configuration reads and
path metadata are real I/O that the plan does not count.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common_lore_index.artifacts._manifest_records import DEFAULT_ARTIFACT_LIMITS
from common_lore_index.artifacts._sealing_meter import SealingMeter, SealingPlanFacts
from common_lore_index.artifacts.sealing_governance import (
    COLLISION_EXTRA_READS_PER_FILE,
    FULL_BODY_READS_PER_FILE,
    STABLE_CAPTURE_MAX_ATTEMPTS,
    SealingBudget,
    SealingBudgetExceeded,
    planned_min_read_bytes,
)
from common_lore_index.ops.config_records import OpsGraphConfig
from common_lore_index.ops.resource_view._canonical import canonical_bytes

PLAN_SCHEMA = "cloe-sealing-plan-v1"
MAX_PLAN_BYTES = 4096
_PROJECTION = "three_walks_of_unchanged_metadata_tree_estimate"


class SealingPlanRefusal(ValueError):
    """A cheap, path-free plan refusal before any source traversal."""


@dataclass(frozen=True)
class SealingPlan:
    """One metadata-only plan; fields are counts, never paths or identities."""

    refusal: str | None
    facts: SealingPlanFacts | None
    directory_entries: int
    opens: int
    effective_max_directory_entries: int

    def to_payload(self) -> dict[str, object]:
        facts = self.facts
        files = None if facts is None else facts.inventory_files
        total = None if facts is None else facts.inventory_bytes
        return {
            "schema": PLAN_SCHEMA,
            "instrumentation": "complete" if self.refusal is None else "incomplete",
            "refusal": self.refusal,
            "bindings": None if facts is None else facts.bindings,
            "inventory_files": files,
            "inventory_bytes": total,
            "inventory_symlinked_files": None if facts is None else facts.inventory_symlinked_files,
            "directory_entries": self.directory_entries,
            "opens": self.opens,
            "planned_min_read_bytes": None if total is None else planned_min_read_bytes(total),
            "planned_min_read_bytes_basis": "derived_lower_bound",
            "planned_min_write_bytes": total,
            "factors": {
                "full_body_reads_per_file": FULL_BODY_READS_PER_FILE,
                "collision_extra_reads_per_file": COLLISION_EXTRA_READS_PER_FILE,
                "stable_capture_max_attempts": STABLE_CAPTURE_MAX_ATTEMPTS,
            },
            "effective_max_directory_entries": self.effective_max_directory_entries,
            "projected_directory_entries": 3 * self.directory_entries,
            "projection_basis": _PROJECTION,
        }

    def canonical_json(self) -> bytes:
        return canonical_bytes(self.to_payload(), MAX_PLAN_BYTES)


def _selected_graph(config: Any, graph_id: str) -> OpsGraphConfig:
    for graph in getattr(config, "graphs", ()):
        if graph.id == graph_id:
            return graph
    raise SealingPlanRefusal("sealing-plan-unknown-graph")


def build_sealing_plan(
    config: Any, graph_id: str, budget: SealingBudget | None = None
) -> SealingPlan:
    """Cheap refusals, then one governed metadata walk under ``budget``."""

    graph = _selected_graph(config, graph_id)
    if not graph.enabled:
        raise SealingPlanRefusal("sealing-plan-graph-disabled")
    if graph.refresh_unsupported_classification is not None:
        raise SealingPlanRefusal("sealing-plan-graph-unsupported")
    for binding in graph.effective_source_bindings:
        if not Path(binding.root_path_expanded).is_dir():
            raise SealingPlanRefusal("sealing-plan-root-unavailable")
    from common_lore_index.graph._metered_discovery import preflight_inventory

    meter = SealingMeter(budget, governed=True)
    refusal = None
    facts = None
    try:
        facts = preflight_inventory(graph, meter, DEFAULT_ARTIFACT_LIMITS)
    except SealingBudgetExceeded as error:
        refusal = error.limit
    except ValueError as error:  # the ADR 0162 inventory predicate or a capture category
        refusal = getattr(error, "category", None) or _inventory_refusal(str(error))
    snapshot = meter.snapshot()
    if refusal is None and snapshot.plan is not None:
        facts = snapshot.plan
    return SealingPlan(
        refusal, facts, snapshot.directory_entries, snapshot.opens,
        snapshot.effective_max_directory_entries or 0,
    )


def _inventory_refusal(message: str) -> str:
    return {
        "artifact count bounds exceeded": "inventory_max_artifacts",
        "artifact byte bounds exceeded": "inventory_max_total_bytes",
        "artifact path bounds exceeded": "inventory_max_path_bytes",
    }.get(message, "inventory_invalid")


def render_plan_text(plan: SealingPlan) -> str:
    payload = plan.to_payload()
    lines = [f"schema: {PLAN_SCHEMA}", "scope: metadata only; lower bounds, not promises"]
    for key in (
        "refusal", "bindings", "inventory_files", "inventory_bytes", "inventory_symlinked_files",
        "directory_entries", "opens", "planned_min_read_bytes", "planned_min_write_bytes",
        "effective_max_directory_entries", "projected_directory_entries",
    ):
        value = payload[key]
        lines.append(f"{key}: {'none' if value is None else value}")
    return "\n".join(lines)


__all__ = (
    "MAX_PLAN_BYTES",
    "PLAN_SCHEMA",
    "SealingPlan",
    "SealingPlanRefusal",
    "build_sealing_plan",
    "render_plan_text",
)
