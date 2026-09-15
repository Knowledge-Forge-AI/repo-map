"""Payload-record merging for RepoMap local operations configuration."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from repomap_kg.ops.config_helpers import OpsConfigDiagnostic as OpsConfigDiagnostic


SUPPORTED_SCHEMA_VERSION = 1


def merge_ops_config_payloads(
    file_payloads: Sequence[tuple[str, Mapping[str, Any]]],
) -> tuple[dict[str, Any], list[OpsConfigDiagnostic]]:
    """Merge ordered config-file payloads while retaining overlay diagnostics."""

    diagnostics: list[OpsConfigDiagnostic] = []
    merged: dict[str, Any] = {"schema_version": SUPPORTED_SCHEMA_VERSION}
    singleton_sources: dict[tuple[str, str], str] = {}
    graph_entries: dict[str, dict[str, Any]] = {}
    graph_order: list[str] = []
    graph_sources: dict[str, str] = {}
    source_entries: dict[str, dict[str, dict[str, Any]]] = {
        "feed": {},
        "github": {},
        "api": {},
    }
    source_order: dict[str, list[str]] = {"feed": [], "github": [], "api": []}
    source_sources: dict[str, dict[str, str]] = {"feed": {}, "github": {}, "api": {}}

    for source, payload in file_payloads:
        for section_name in ("service", "postgres", "runtime", "server_memory"):
            section = payload.get(section_name)
            if isinstance(section, dict):
                merged_section = dict(merged.get(section_name, {}))
                for field, value in section.items():
                    key = (section_name, field)
                    if field in merged_section and merged_section[field] != value:
                        diagnostics.append(
                            OpsConfigDiagnostic(
                                "warning",
                                f"{section_name.replace('_', '-')}-overlay",
                                f"{source}:{section_name}.{field}",
                                (
                                    f"{section_name}.{field} overlays a value "
                                    f"from {singleton_sources.get(key, 'an earlier file')}"
                                ),
                            )
                        )
                    if (
                        section_name == "runtime"
                        and field == "postgres"
                        and isinstance(merged_section.get(field), dict)
                        and isinstance(value, dict)
                    ):
                        nested = dict(merged_section[field])
                        nested.update(value)
                        merged_section[field] = nested
                    else:
                        merged_section[field] = value
                    singleton_sources[key] = source
                merged[section_name] = merged_section

        graphs = payload.get("graphs", [])
        if isinstance(graphs, list):
            seen_graph_ids: set[str] = set()
            for index, graph in enumerate(graphs):
                if not isinstance(graph, dict):
                    continue
                graph_id = graph.get("id")
                if not isinstance(graph_id, str) or not graph_id.strip():
                    unique_id = f"{source}:graphs[{index}]"
                    graph_entries[unique_id] = dict(graph)
                    graph_order.append(unique_id)
                    continue
                if graph_id in seen_graph_ids:
                    diagnostics.append(
                        OpsConfigDiagnostic(
                            "warning",
                            "duplicate-graph-id",
                            f"{source}:graphs[{index}].id",
                            f"duplicate graph id {graph_id!r} in {source}; later entry overlays earlier fields",
                        )
                    )
                seen_graph_ids.add(graph_id)
                if graph_id not in graph_entries:
                    graph_entries[graph_id] = {}
                    graph_order.append(graph_id)
                elif graph_sources.get(graph_id) != source:
                    diagnostics.append(
                        OpsConfigDiagnostic(
                            "warning",
                            "graph-overlay",
                            f"{source}:graphs[{index}].id",
                            f"graph {graph_id!r} overlays fields from {graph_sources.get(graph_id, 'an earlier file')}",
                        )
                    )
                graph_entries[graph_id].update(graph)
                graph_sources[graph_id] = source

        sources = payload.get("sources", {})
        if isinstance(sources, dict):
            for source_type in ("feed", "github", "api"):
                entries = sources.get(source_type, [])
                if not isinstance(entries, list):
                    continue
                seen_source_ids: set[str] = set()
                for index, entry in enumerate(entries):
                    if not isinstance(entry, dict):
                        continue
                    source_id = entry.get("id")
                    if not isinstance(source_id, str) or not source_id.strip():
                        unique_id = f"{source}:sources.{source_type}[{index}]"
                        source_entries[source_type][unique_id] = dict(entry)
                        source_order[source_type].append(unique_id)
                        continue
                    if source_id in seen_source_ids:
                        diagnostics.append(
                            OpsConfigDiagnostic(
                                "warning",
                                "duplicate-source-id",
                                f"{source}:sources.{source_type}[{index}].id",
                                f"duplicate {source_type} source id {source_id!r} in {source}; later entry overlays earlier fields",
                            )
                        )
                    seen_source_ids.add(source_id)
                    if source_id not in source_entries[source_type]:
                        source_entries[source_type][source_id] = {}
                        source_order[source_type].append(source_id)
                    elif source_sources[source_type].get(source_id) != source:
                        diagnostics.append(
                            OpsConfigDiagnostic(
                                "warning",
                                "source-overlay",
                                f"{source}:sources.{source_type}[{index}].id",
                                f"{source_type} source {source_id!r} overlays fields from {source_sources[source_type].get(source_id, 'an earlier file')}",
                            )
                        )
                    source_entries[source_type][source_id].update(entry)
                    source_sources[source_type][source_id] = source

    if graph_entries:
        merged["graphs"] = [graph_entries[graph_id] for graph_id in graph_order]
    merged_sources = {
        source_type: [
            source_entries[source_type][source_id]
            for source_id in source_order[source_type]
        ]
        for source_type in ("feed", "github", "api")
        if source_order[source_type]
    }
    if merged_sources:
        merged["sources"] = merged_sources
    return merged, diagnostics
