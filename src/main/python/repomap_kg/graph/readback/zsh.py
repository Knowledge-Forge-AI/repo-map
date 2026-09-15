"""Bounded zsh extraction and canonicalization summaries."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from repomap_kg.canonicalization.records import CanonicalizationResult
from repomap_kg.observations.raw import RawObservation


ZSH_PREFIX = "zsh."


@dataclass(frozen=True)
class ZshEvidenceSummary:
    raw_observations: int
    zsh: dict[str, int | dict[str, int]]
    canonical: dict[str, int | dict[str, int]]
    safety: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_observations": self.raw_observations,
            "zsh": self.zsh,
            "canonical": self.canonical,
            "safety": self.safety,
        }


def summarize_zsh_evidence(
    observations: Sequence[RawObservation],
    canonical_result: CanonicalizationResult,
) -> ZshEvidenceSummary:
    """Return a count-only summary for zsh fixture dogfooding.

    The summary intentionally omits raw payloads, source snippets, command
    strings, prompt strings, path examples, and secret values. It is useful for
    tests and future bounded readback without adding a storage, CLI, or MCP
    surface in ZSH4.
    """

    zsh_observations = [
        observation for observation in observations if _is_zsh_observation(observation)
    ]
    raw_kind_counts = Counter(observation.kind for observation in zsh_observations)
    zsh_evidence_keys = {
        evidence.evidence_key
        for evidence in canonical_result.graph.evidence
        if _is_zsh_evidence_kind(evidence.raw_kind, evidence.metadata)
    }
    zsh_node_keys = {
        link.canonical_key
        for link in canonical_result.graph.node_evidence_links
        if link.evidence_key in zsh_evidence_keys
    }
    zsh_edge_keys = {
        link.edge_key
        for link in canonical_result.graph.edge_evidence_links
        if link.evidence_key in zsh_evidence_keys
    }
    canonical_node_kinds = Counter(
        node.kind
        for node in canonical_result.graph.nodes
        if node.canonical_key in zsh_node_keys
    )
    canonical_edge_kinds = Counter(
        edge.kind
        for edge in canonical_result.graph.edges
        if edge.edge_key in zsh_edge_keys
    )
    return ZshEvidenceSummary(
        raw_observations=len(zsh_observations),
        zsh={
            "scripts": raw_kind_counts["zsh.script"],
            "startup_files": raw_kind_counts["zsh.startup_file"],
            "options": raw_kind_counts["zsh.option"],
            "functions": raw_kind_counts["shell.function"],
            "assignments": raw_kind_counts["shell.assignment"],
            "exports": raw_kind_counts["shell.export"],
            "sources": raw_kind_counts["shell.source"],
            "commands": raw_kind_counts["shell.command"],
            "external_commands": raw_kind_counts["shell.external_command"],
            "arguments": raw_kind_counts["shell.command_argument"],
            "pipelines": raw_kind_counts["shell.pipeline"],
            "command_chains": raw_kind_counts["shell.command_chain"],
            "redirects": raw_kind_counts["shell.redirect"],
            "heredocs": raw_kind_counts["shell.heredoc"],
            "autoloads": raw_kind_counts["zsh.autoload"],
            "fpaths": raw_kind_counts["zsh.fpath"],
            "zstyles": raw_kind_counts["zsh.zstyle"],
            "zmodloads": raw_kind_counts["zsh.zmodload"],
            "bindkeys": raw_kind_counts["zsh.bindkey"],
            "compinits": raw_kind_counts["zsh.compinit"],
            "completion_functions": raw_kind_counts["zsh.completion_function"],
            "plugin_managers": raw_kind_counts["zsh.plugin_manager"],
            "plugins": raw_kind_counts["zsh.plugin"],
            "themes": raw_kind_counts["zsh.theme"],
            "prompts": raw_kind_counts["zsh.prompt"],
            "array_assignments": raw_kind_counts["zsh.array_assignment"],
            "associative_array_assignments": raw_kind_counts[
                "zsh.associative_array_assignment"
            ],
            "parameter_expansions": raw_kind_counts["zsh.parameter_expansion"],
            "glob_qualifiers": raw_kind_counts["zsh.glob_qualifier"],
            "extended_globs": raw_kind_counts["zsh.extended_glob"],
            "path_references": raw_kind_counts["zsh.path_reference"],
            "dynamic_invocations": raw_kind_counts["shell.dynamic_invocation"]
            + raw_kind_counts["zsh.dynamic_invocation"],
            "command_substitutions": raw_kind_counts["shell.command_substitution"],
            "env_reads": raw_kind_counts["shell.env_read"],
            "env_writes": raw_kind_counts["shell.env_write"],
            "file_reads": raw_kind_counts["shell.file_read"],
            "file_writes": raw_kind_counts["shell.file_write"],
            "network_calls": raw_kind_counts["shell.network_call"],
            "package_managers": raw_kind_counts["shell.package_manager"],
            "host_mutations": raw_kind_counts["shell.host_mutation"],
            "dynamic_or_unknown": sum(
                1
                for observation in zsh_observations
                if _is_dynamic_or_unknown(observation)
            ),
            "secret_like_redacted": raw_kind_counts["shell.secret_like"],
            "raw_kind_counts": dict(sorted(raw_kind_counts.items())),
        },
        canonical={
            "nodes": len(zsh_node_keys),
            "edges": len(zsh_edge_keys),
            "node_kinds": dict(sorted(canonical_node_kinds.items())),
            "edge_kinds": dict(sorted(canonical_edge_kinds.items())),
        },
        safety={
            "bounded": True,
            "raw_payloads_included": False,
            "source_snippets_included": False,
            "command_strings_included": False,
            "prompt_strings_included": False,
            "secret_values_included": False,
            "path_examples_included": False,
            "zsh_executed": False,
            "shell_executed": False,
            "startup_executed": False,
            "commands_executed": False,
            "plugins_loaded": False,
            "plugin_managers_executed": False,
            "completions_loaded": False,
            "modules_loaded": False,
            "globs_expanded": False,
            "parameters_expanded": False,
            "files_opened": False,
            "filesystem_checked": False,
            "host_mutation_proven": False,
            "live_graph_refreshed": False,
        },
    )


def _is_zsh_observation(observation: RawObservation) -> bool:
    return _is_zsh_evidence_kind(observation.kind, observation.metadata)


def _is_zsh_evidence_kind(kind: str, metadata: Mapping[str, Any]) -> bool:
    return (
        kind.startswith(ZSH_PREFIX)
        or metadata.get("language") == "zsh"
        or metadata.get("dialect") == "zsh"
    )


def _is_dynamic_or_unknown(observation: RawObservation) -> bool:
    metadata = observation.metadata
    return (
        observation.confidence == "unknown"
        or metadata.get("resolution") in {"dynamic", "unknown"}
        or metadata.get("target_kind") in {"dynamic", "unknown", "redacted"}
        or metadata.get("argument_kind") in {"dynamic", "unknown", "redacted"}
        or metadata.get("value_kind") in {"dynamic", "unknown", "redacted"}
        or metadata.get("command_text_kind") in {"dynamic", "unknown", "redacted"}
        or "dynamic" in str(metadata.get("dynamic_reason", ""))
    )
