"""Bounded Bash extraction and canonicalization summaries."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from repomap_kg.canonicalization.records import CanonicalizationResult
from repomap_kg.observations.raw import RawObservation


BASH_PREFIX = "bash."


@dataclass(frozen=True)
class BashEvidenceSummary:
    raw_observations: int
    bash: dict[str, int | dict[str, int]]
    canonical: dict[str, int | dict[str, int]]
    safety: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_observations": self.raw_observations,
            "bash": self.bash,
            "canonical": self.canonical,
            "safety": self.safety,
        }


def summarize_bash_evidence(
    observations: Sequence[RawObservation],
    canonical_result: CanonicalizationResult,
) -> BashEvidenceSummary:
    """Return a count-only summary for Bash fixture dogfooding.

    The summary intentionally omits raw payloads, source snippets, path
    examples, heredoc bodies, trap bodies, and secret values. It is useful for
    tests and future bounded readback without adding a storage, CLI, or MCP
    surface in BASH5.
    """

    bash_observations = [
        observation for observation in observations if _is_bash_observation(observation)
    ]
    raw_kind_counts = Counter(observation.kind for observation in bash_observations)
    mutation_categories = Counter(
        str(observation.metadata["mutation_category"])
        for observation in bash_observations
        if observation.kind == "shell.host_mutation"
        and isinstance(observation.metadata.get("mutation_category"), str)
    )
    bash_evidence_keys = {
        evidence.evidence_key
        for evidence in canonical_result.graph.evidence
        if _is_bash_evidence_kind(evidence.raw_kind, evidence.metadata)
    }
    bash_node_keys = {
        link.canonical_key
        for link in canonical_result.graph.node_evidence_links
        if link.evidence_key in bash_evidence_keys
    }
    bash_edge_keys = {
        link.edge_key
        for link in canonical_result.graph.edge_evidence_links
        if link.evidence_key in bash_evidence_keys
    }
    canonical_node_kinds = Counter(
        node.kind
        for node in canonical_result.graph.nodes
        if node.canonical_key in bash_node_keys
    )
    canonical_edge_kinds = Counter(
        edge.kind
        for edge in canonical_result.graph.edges
        if edge.edge_key in bash_edge_keys
    )
    return BashEvidenceSummary(
        raw_observations=len(bash_observations),
        bash={
            "files": raw_kind_counts["shell.script"],
            "functions": raw_kind_counts["shell.function"],
            "commands": raw_kind_counts["shell.command"],
            "external_commands": raw_kind_counts["shell.external_command"],
            "pipelines": raw_kind_counts["shell.pipeline"],
            "command_chains": raw_kind_counts["shell.command_chain"],
            "redirects": raw_kind_counts["shell.redirect"],
            "heredocs": raw_kind_counts["shell.heredoc"],
            "sources": raw_kind_counts["shell.source"],
            "env_reads": raw_kind_counts["shell.env_read"],
            "env_writes": raw_kind_counts["shell.env_write"],
            "file_reads": raw_kind_counts["shell.file_read"],
            "file_writes": raw_kind_counts["shell.file_write"],
            "host_mutations": raw_kind_counts["shell.host_mutation"],
            "host_mutation_categories": dict(sorted(mutation_categories.items())),
            "network_calls": raw_kind_counts["shell.network_call"],
            "package_managers": raw_kind_counts["shell.package_manager"],
            "aliases": raw_kind_counts["bash.alias"],
            "array_assignments": raw_kind_counts["bash.array_assignment"]
            + raw_kind_counts["bash.associative_array_assignment"],
            "traps": raw_kind_counts["bash.trap"],
            "dynamic_invocations": raw_kind_counts["shell.dynamic_invocation"],
            "secret_like_redacted": raw_kind_counts["shell.secret_like"],
            "raw_kind_counts": dict(sorted(raw_kind_counts.items())),
        },
        canonical={
            "nodes": len(bash_node_keys),
            "edges": len(bash_edge_keys),
            "node_kinds": dict(sorted(canonical_node_kinds.items())),
            "edge_kinds": dict(sorted(canonical_edge_kinds.items())),
        },
        safety={
            "bounded": True,
            "raw_payloads_included": False,
            "path_examples_included": False,
            "source_snippets_included": False,
            "heredoc_bodies_included": False,
            "trap_bodies_included": False,
            "secret_values_included": False,
            "shell_executed": False,
            "live_graph_refreshed": False,
        },
    )


def _is_bash_observation(observation: RawObservation) -> bool:
    return _is_bash_evidence_kind(observation.kind, observation.metadata)


def _is_bash_evidence_kind(kind: str, metadata: Mapping[str, Any]) -> bool:
    return kind.startswith(BASH_PREFIX) or metadata.get("dialect") == "bash"
