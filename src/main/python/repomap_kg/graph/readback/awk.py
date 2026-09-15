"""Bounded awk extraction and canonicalization summaries."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from repomap_kg.canonicalization.records import CanonicalizationResult
from repomap_kg.observations.raw import RawObservation


AWK_PREFIX = "awk."


@dataclass(frozen=True)
class AwkEvidenceSummary:
    raw_observations: int
    awk: dict[str, int | dict[str, int]]
    canonical: dict[str, int | dict[str, int]]
    safety: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_observations": self.raw_observations,
            "awk": self.awk,
            "canonical": self.canonical,
            "safety": self.safety,
        }


def summarize_awk_evidence(
    observations: Sequence[RawObservation],
    canonical_result: CanonicalizationResult,
) -> AwkEvidenceSummary:
    """Return a count-only summary for awk fixture dogfooding.

    The summary intentionally omits raw payloads, source snippets, command
    strings, path examples, and secret values. It is useful for tests and
    future bounded readback without adding a storage, CLI, or MCP surface in
    AWK3.
    """

    awk_observations = [
        observation for observation in observations if _is_awk_observation(observation)
    ]
    raw_kind_counts = Counter(observation.kind for observation in awk_observations)
    awk_evidence_keys = {
        evidence.evidence_key
        for evidence in canonical_result.graph.evidence
        if _is_awk_evidence_kind(evidence.raw_kind, evidence.metadata)
    }
    awk_node_keys = {
        link.canonical_key
        for link in canonical_result.graph.node_evidence_links
        if link.evidence_key in awk_evidence_keys
    }
    awk_edge_keys = {
        link.edge_key
        for link in canonical_result.graph.edge_evidence_links
        if link.evidence_key in awk_evidence_keys
    }
    canonical_node_kinds = Counter(
        node.kind
        for node in canonical_result.graph.nodes
        if node.canonical_key in awk_node_keys
    )
    canonical_edge_kinds = Counter(
        edge.kind
        for edge in canonical_result.graph.edges
        if edge.edge_key in awk_edge_keys
    )
    return AwkEvidenceSummary(
        raw_observations=len(awk_observations),
        awk={
            "programs": raw_kind_counts["awk.program"],
            "begins": raw_kind_counts["awk.begin"],
            "ends": raw_kind_counts["awk.end"],
            "pattern_actions": raw_kind_counts["awk.pattern_action"],
            "functions": raw_kind_counts["awk.function"],
            "variable_assignments": raw_kind_counts["awk.variable_assignment"],
            "field_references": raw_kind_counts["awk.field_reference"],
            "record_references": raw_kind_counts["awk.record_reference"],
            "builtin_calls": raw_kind_counts["awk.builtin_call"],
            "user_function_calls": raw_kind_counts["awk.user_function_call"],
            "file_reads": raw_kind_counts["awk.file_read"],
            "file_writes": raw_kind_counts["awk.file_write"],
            "pipe_reads": raw_kind_counts["awk.pipe_read"],
            "pipe_writes": raw_kind_counts["awk.pipe_write"],
            "system_calls": raw_kind_counts["awk.system_call"],
            "redirects": raw_kind_counts["awk.redirect"],
            "includes": raw_kind_counts["awk.include"],
            "extensions": raw_kind_counts["awk.extension"],
            "dynamic_or_unknown": sum(
                1
                for observation in awk_observations
                if _is_dynamic_or_unknown(observation)
            ),
            "secret_like_redacted": raw_kind_counts["awk.secret_like"],
            "raw_kind_counts": dict(sorted(raw_kind_counts.items())),
        },
        canonical={
            "nodes": len(awk_node_keys),
            "edges": len(awk_edge_keys),
            "node_kinds": dict(sorted(canonical_node_kinds.items())),
            "edge_kinds": dict(sorted(canonical_edge_kinds.items())),
        },
        safety={
            "bounded": True,
            "raw_payloads_included": False,
            "source_snippets_included": False,
            "command_strings_included": False,
            "secret_values_included": False,
            "path_examples_included": False,
            "awk_executed": False,
            "shell_executed": False,
            "commands_executed": False,
            "files_opened": False,
            "filesystem_checked": False,
            "host_mutation_proven": False,
            "live_graph_refreshed": False,
        },
    )


def _is_awk_observation(observation: RawObservation) -> bool:
    return _is_awk_evidence_kind(observation.kind, observation.metadata)


def _is_awk_evidence_kind(kind: str, metadata: Mapping[str, Any]) -> bool:
    return kind.startswith(AWK_PREFIX) or metadata.get("language") == "awk"


def _is_dynamic_or_unknown(observation: RawObservation) -> bool:
    metadata = observation.metadata
    return (
        observation.confidence == "unknown"
        or metadata.get("resolution") in {"dynamic", "unknown"}
        or metadata.get("target_kind") in {"dynamic", "unknown", "redacted"}
        or metadata.get("command_text_kind") in {"dynamic", "unknown", "redacted"}
        or "dynamic" in str(metadata.get("dynamic_reason", ""))
    )
