"""Bounded Bats extraction and canonicalization summaries."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from repomap_kg.canonicalization.records import CanonicalizationResult
from repomap_kg.observations.raw import RawObservation


BATS_PREFIX = "bats."
BATS_HOOK_KINDS = (
    "bats.setup",
    "bats.teardown",
    "bats.setup_file",
    "bats.teardown_file",
)


@dataclass(frozen=True)
class BatsEvidenceSummary:
    raw_observations: int
    bats: dict[str, int | dict[str, int]]
    canonical: dict[str, int | dict[str, int]]
    safety: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_observations": self.raw_observations,
            "bats": self.bats,
            "canonical": self.canonical,
            "safety": self.safety,
        }


def summarize_bats_evidence(
    observations: Sequence[RawObservation],
    canonical_result: CanonicalizationResult,
) -> BatsEvidenceSummary:
    """Return a count-only summary for Bats fixture dogfooding.

    The summary intentionally omits raw payloads, source snippets, expected
    output strings, path examples, heredoc bodies, and secret values. It is
    useful for tests and future bounded readback without adding a storage, CLI,
    or MCP surface in BATS3.
    """

    bats_observations = [
        observation for observation in observations if _is_bats_observation(observation)
    ]
    raw_kind_counts = Counter(observation.kind for observation in bats_observations)
    hook_kind_counts = Counter(
        observation.kind
        for observation in bats_observations
        if observation.kind in BATS_HOOK_KINDS
    )
    bats_evidence_keys = {
        evidence.evidence_key
        for evidence in canonical_result.graph.evidence
        if _is_bats_evidence_kind(evidence.raw_kind, evidence.metadata)
    }
    bats_node_keys = {
        link.canonical_key
        for link in canonical_result.graph.node_evidence_links
        if link.evidence_key in bats_evidence_keys
    }
    bats_edge_keys = {
        link.edge_key
        for link in canonical_result.graph.edge_evidence_links
        if link.evidence_key in bats_evidence_keys
    }
    canonical_node_kinds = Counter(
        node.kind
        for node in canonical_result.graph.nodes
        if node.canonical_key in bats_node_keys
    )
    canonical_edge_kinds = Counter(
        edge.kind
        for edge in canonical_result.graph.edges
        if edge.edge_key in bats_edge_keys
    )
    return BatsEvidenceSummary(
        raw_observations=len(bats_observations),
        bats={
            "files": raw_kind_counts["bats.file"],
            "test_cases": raw_kind_counts["bats.test_case"],
            "hooks": sum(raw_kind_counts[kind] for kind in BATS_HOOK_KINDS),
            "hook_kind_counts": dict(sorted(hook_kind_counts.items())),
            "loads": raw_kind_counts["bats.load"],
            "library_loads": raw_kind_counts["bats.library_load"],
            "runs": raw_kind_counts["bats.run"],
            "assertions": raw_kind_counts["bats.assertion"],
            "refutations": raw_kind_counts["bats.refutation"],
            "skips": raw_kind_counts["bats.skip"],
            "fixture_references": raw_kind_counts["bats.fixture_reference"],
            "helper_references": raw_kind_counts["bats.helper_reference"],
            "output_expectations": raw_kind_counts["bats.output_expectation"],
            "status_expectations": raw_kind_counts["bats.status_expectation"],
            "dynamic_or_unknown": sum(
                1
                for observation in bats_observations
                if _is_dynamic_or_unknown(observation)
            ),
            "secret_like_redacted": raw_kind_counts["shell.secret_like"],
            "raw_kind_counts": dict(sorted(raw_kind_counts.items())),
        },
        canonical={
            "nodes": len(bats_node_keys),
            "edges": len(bats_edge_keys),
            "node_kinds": dict(sorted(canonical_node_kinds.items())),
            "edge_kinds": dict(sorted(canonical_edge_kinds.items())),
        },
        safety={
            "bounded": True,
            "raw_payloads_included": False,
            "source_snippets_included": False,
            "expected_outputs_included": False,
            "heredoc_bodies_included": False,
            "secret_values_included": False,
            "path_examples_included": False,
            "bats_executed": False,
            "shell_executed": False,
            "commands_executed": False,
            "helpers_executed": False,
            "live_graph_refreshed": False,
        },
    )


def _is_bats_observation(observation: RawObservation) -> bool:
    return _is_bats_evidence_kind(observation.kind, observation.metadata)


def _is_bats_evidence_kind(kind: str, metadata: Mapping[str, Any]) -> bool:
    return kind.startswith(BATS_PREFIX) or metadata.get("dialect") == "bats"


def _is_dynamic_or_unknown(observation: RawObservation) -> bool:
    metadata = observation.metadata
    return (
        observation.confidence == "unknown"
        or metadata.get("resolution") in {"dynamic", "unknown", "temp"}
        or metadata.get("target_kind") in {"dynamic", "unknown"}
        or metadata.get("command_kind") in {"dynamic", "unknown"}
        or metadata.get("expected_value_kind") == "dynamic"
        or metadata.get("reason_kind") == "dynamic"
    )
