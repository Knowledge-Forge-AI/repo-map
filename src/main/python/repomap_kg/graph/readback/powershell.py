"""Bounded PowerShell extraction and canonicalization summaries."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from repomap_kg.canonicalization.records import CanonicalizationResult
from repomap_kg.observations.raw import RawObservation


POWERSHELL_PREFIX = "powershell."


@dataclass(frozen=True)
class PowerShellEvidenceSummary:
    raw_observations: int
    power_shell: dict[str, int | dict[str, int]]
    canonical: dict[str, int | dict[str, int]]
    safety: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_observations": self.raw_observations,
            "power_shell": self.power_shell,
            "canonical": self.canonical,
            "safety": self.safety,
        }


def summarize_powershell_evidence(
    observations: Sequence[RawObservation],
    canonical_result: CanonicalizationResult,
) -> PowerShellEvidenceSummary:
    """Return a count-only summary for PowerShell fixture dogfooding.

    The summary intentionally omits raw payloads, source snippets, path examples,
    and secret values. It is useful for tests and future bounded readback without
    adding a storage or CLI surface in PWSH6.
    """

    powershell_observations = [
        observation
        for observation in observations
        if observation.kind.startswith(POWERSHELL_PREFIX)
    ]
    raw_kind_counts = Counter(observation.kind for observation in powershell_observations)
    mutation_categories = Counter(
        str(observation.metadata["mutation_category"])
        for observation in powershell_observations
        if observation.kind == "powershell.host_mutation"
        and isinstance(observation.metadata.get("mutation_category"), str)
    )
    powershell_evidence_keys = {
        evidence.evidence_key
        for evidence in canonical_result.graph.evidence
        if evidence.raw_kind.startswith(POWERSHELL_PREFIX)
    }
    powershell_node_keys = {
        link.canonical_key
        for link in canonical_result.graph.node_evidence_links
        if link.evidence_key in powershell_evidence_keys
    }
    powershell_edge_keys = {
        link.edge_key
        for link in canonical_result.graph.edge_evidence_links
        if link.evidence_key in powershell_evidence_keys
    }
    canonical_node_kinds = Counter(
        node.kind
        for node in canonical_result.graph.nodes
        if node.canonical_key in powershell_node_keys
    )
    canonical_edge_kinds = Counter(
        edge.kind
        for edge in canonical_result.graph.edges
        if edge.edge_key in powershell_edge_keys
    )
    return PowerShellEvidenceSummary(
        raw_observations=len(powershell_observations),
        power_shell={
            "files": sum(
                raw_kind_counts[kind]
                for kind in (
                    "powershell.script",
                    "powershell.module",
                    "powershell.manifest",
                )
            ),
            "functions": raw_kind_counts["powershell.function"],
            "commands": raw_kind_counts["powershell.command"],
            "external_commands": raw_kind_counts["powershell.external_command"],
            "pipelines": raw_kind_counts["powershell.pipeline"],
            "splats": raw_kind_counts["powershell.splat"]
            + raw_kind_counts["powershell.splat_assignment"],
            "manifest_dependencies": raw_kind_counts[
                "powershell.manifest_dependency"
            ],
            "manifest_exports": raw_kind_counts["powershell.manifest_export"],
            "host_mutations": raw_kind_counts["powershell.host_mutation"],
            "host_mutation_categories": dict(sorted(mutation_categories.items())),
            "network_calls": raw_kind_counts["powershell.network_call"],
            "remoting": raw_kind_counts["powershell.remoting"],
            "dynamic_invocations": raw_kind_counts[
                "powershell.dynamic_invocation"
            ],
            "secret_like_redacted": raw_kind_counts["powershell.secret_like"],
            "raw_kind_counts": dict(sorted(raw_kind_counts.items())),
        },
        canonical={
            "nodes": len(powershell_node_keys),
            "edges": len(powershell_edge_keys),
            "node_kinds": dict(sorted(canonical_node_kinds.items())),
            "edge_kinds": dict(sorted(canonical_edge_kinds.items())),
        },
        safety={
            "bounded": True,
            "raw_payloads_included": False,
            "path_examples_included": False,
            "source_snippets_included": False,
            "powershell_executed": False,
            "secret_values_included": False,
        },
    )
