"""Bounded zunit extraction and canonicalization summaries."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from repomap_kg.canonicalization.records import CanonicalizationResult
from repomap_kg.observations.raw import RawObservation


ZUNIT_PREFIX = "zunit."


@dataclass(frozen=True)
class ZunitEvidenceSummary:
    raw_observations: int
    zunit: dict[str, int | dict[str, int]]
    canonical: dict[str, int | dict[str, int]]
    safety: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_observations": self.raw_observations,
            "zunit": self.zunit,
            "canonical": self.canonical,
            "safety": self.safety,
        }


def summarize_zunit_evidence(
    observations: Sequence[RawObservation],
    canonical_result: CanonicalizationResult,
) -> ZunitEvidenceSummary:
    """Return a count-only summary for zunit fixture dogfooding.

    The summary intentionally omits raw payloads, source snippets, test bodies,
    expected output strings, command strings, helper bodies, fixture contents,
    mock bodies, path examples, and secret values. It is useful for tests and
    future bounded readback without adding a storage, CLI, or MCP surface in
    ZUNIT3.
    """

    zunit_observations = [
        observation
        for observation in observations
        if _is_zunit_observation(observation)
    ]
    raw_kind_counts = Counter(observation.kind for observation in zunit_observations)
    zunit_evidence_keys = {
        evidence.evidence_key
        for evidence in canonical_result.graph.evidence
        if _is_zunit_evidence_kind(evidence.raw_kind, evidence.metadata)
    }
    zunit_node_keys = {
        link.canonical_key
        for link in canonical_result.graph.node_evidence_links
        if link.evidence_key in zunit_evidence_keys
    }
    zunit_edge_keys = {
        link.edge_key
        for link in canonical_result.graph.edge_evidence_links
        if link.evidence_key in zunit_evidence_keys
    }
    canonical_node_kinds = Counter(
        node.kind
        for node in canonical_result.graph.nodes
        if node.canonical_key in zunit_node_keys
    )
    canonical_edge_kinds = Counter(
        edge.kind
        for edge in canonical_result.graph.edges
        if edge.edge_key in zunit_edge_keys
    )
    return ZunitEvidenceSummary(
        raw_observations=len(zunit_observations),
        zunit={
            "files": raw_kind_counts["zunit.file"],
            "suites": raw_kind_counts["zunit.suite"],
            "test_cases": raw_kind_counts["zunit.test_case"],
            "test_names": raw_kind_counts["zunit.test_name"],
            "dynamic_tests": raw_kind_counts["zunit.dynamic_test"],
            "setups": raw_kind_counts["zunit.setup"],
            "teardowns": raw_kind_counts["zunit.teardown"],
            "before_each": raw_kind_counts["zunit.before_each"],
            "after_each": raw_kind_counts["zunit.after_each"],
            "hooks": raw_kind_counts["zunit.hook"],
            "assertions": raw_kind_counts["zunit.assertion"],
            "expectations": raw_kind_counts["zunit.expectation"],
            "commands_under_test": raw_kind_counts["zunit.command_under_test"],
            "helpers": raw_kind_counts["zunit.helper"],
            "fixture_references": raw_kind_counts["zunit.fixture_reference"],
            "mocks": raw_kind_counts["zunit.mock"],
            "stubs": raw_kind_counts["zunit.stub"],
            "skips": raw_kind_counts["zunit.skip"],
            "todos": raw_kind_counts["zunit.todo"],
            "parameterized_cases": raw_kind_counts["zunit.parameterized_case"],
            "dynamic_or_unknown": sum(
                1
                for observation in zunit_observations
                if _is_dynamic_or_unknown(observation)
            ),
            "secret_like_redacted": raw_kind_counts["zunit.secret_like"],
            "raw_kind_counts": dict(sorted(raw_kind_counts.items())),
        },
        canonical={
            "nodes": len(zunit_node_keys),
            "edges": len(zunit_edge_keys),
            "node_kinds": dict(sorted(canonical_node_kinds.items())),
            "edge_kinds": dict(sorted(canonical_edge_kinds.items())),
        },
        safety={
            "bounded": True,
            "raw_payloads_included": False,
            "source_snippets_included": False,
            "test_bodies_included": False,
            "expected_outputs_included": False,
            "command_strings_included": False,
            "helper_bodies_included": False,
            "fixture_contents_included": False,
            "mock_bodies_included": False,
            "secret_values_included": False,
            "path_examples_included": False,
            "zunit_executed": False,
            "zsh_executed": False,
            "shell_executed": False,
            "tests_executed": False,
            "assertions_executed": False,
            "commands_executed": False,
            "hooks_executed": False,
            "helpers_loaded": False,
            "fixtures_loaded": False,
            "mocks_applied": False,
            "stubs_applied": False,
            "filesystem_checked": False,
            "test_passed_known": False,
            "live_graph_refreshed": False,
        },
    )


def _is_zunit_observation(observation: RawObservation) -> bool:
    return _is_zunit_evidence_kind(observation.kind, observation.metadata)


def _is_zunit_evidence_kind(kind: str, metadata: Mapping[str, Any]) -> bool:
    return (
        kind.startswith(ZUNIT_PREFIX)
        or metadata.get("test_framework") == "zunit"
    )


def _is_dynamic_or_unknown(observation: RawObservation) -> bool:
    metadata = observation.metadata
    return (
        observation.confidence == "unknown"
        or metadata.get("resolution") in {"dynamic", "unknown"}
        or metadata.get("target_kind") in {"dynamic", "unknown", "redacted"}
        or metadata.get("command_kind") in {"dynamic", "unknown", "redacted"}
        or metadata.get("expected_value_kind") in {"dynamic", "unknown", "redacted"}
        or metadata.get("reason_kind") in {"dynamic", "unknown", "redacted"}
        or metadata.get("suite_name_kind") in {"dynamic", "unknown", "redacted"}
        or metadata.get("test_name_kind") in {"dynamic", "unknown", "redacted"}
        or "dynamic" in str(metadata.get("dynamic_reason", ""))
    )
