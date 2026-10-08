"""Nix summary over one SQLite Local graph.

The named SQLite counterpart of ``sql_summaries_nix.build_nix_summary_query_sql``:
the same counters over every retained run's raw observations, the current
canonical nodes and the canonical node/edge evidence links, decoded through
``nix_summary_from_storage_payload``. ``root_path`` is the literal
``[root-path]`` exactly as the PostgreSQL builder emits it. Nothing evaluates
Nix, reads a lock file or inspects a store; the counters restate what
extraction recorded (program/path resolution and output-shape classifications)
and add no classification of their own.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any

from repomap_kg.storage.sqlite_local.queries import require_accepted_publication
from repomap_kg.storage.sqlite_local.raw_payload import basename, flag, has_key, is_in, like, meta, text_at
from repomap_kg.storage.sqlite_local.summary_queries import (
    canonical_counts,
    raw_count,
    raw_rows,
    repository_name,
)
from repomap_kg.storage.summary_rows import NixSummaryRecord, nix_summary_from_storage_payload

_OUTPUTS = ("nix.app", "nix.package", "nix.devShell", "nix.check")
_SECTIONS = ("packages", "apps", "devShells", "checks", "nixosModules", "darwinModules",
             "homeManagerModules", "overlays", "formatter", "templates", "legacyPackages")
_FAMILIES = ("output", "module", "overlay", "formatter", "template", "legacy_package")
_SHAPES = ("direct_assignment", "nested_attrset", "inherit", "merged_attrset", "dynamic",
           "helper_framework", "unknown")
_DYNAMIC = ("eachDefaultSystem", "genAttrs", "forAllSystems", "flake-utils", "flake-parts",
            "string_interpolation")
_UNSUPPORTED = ("imported_outputs", "merged_attrset", "inherit_outputs",
                "nested_attrset_without_direct_identity", "template_section",
                "legacy_packages_section", "unknown_dynamic")
_SOURCE_TYPES = ("github", "git", "path", "tarball", "follows", "unknown", "dynamic")
_RESOLUTIONS = ("local", "dynamic", "external", "unknown")


def _child(payload: Any, key: str) -> Any:
    """``payload -> key`` (``None`` for a missing key or a non-object parent)."""
    return payload.get(key) if isinstance(payload, dict) else None


def _edge_evidence(connection: sqlite3.Connection) -> Counter[tuple[str, str]]:
    """Distinct ``(edge, edge_kind, raw_kind)`` triples with a ``nix.`` raw kind."""
    return Counter(
        (str(edge_kind), str(raw_kind))
        for _edge, edge_kind, raw_kind in connection.execute(
            "SELECT DISTINCT canonical_edges.id, canonical_edges.edge_kind, canonical_evidence.raw_kind "
            "FROM canonical_edges JOIN canonical_edge_evidence "
            "ON canonical_edge_evidence.canonical_edge_id = canonical_edges.id "
            "JOIN canonical_evidence ON canonical_evidence.id = canonical_edge_evidence.canonical_evidence_id "
            "WHERE canonical_edges.graph_key_version = 1 "
            "AND substr(canonical_evidence.raw_kind, 1, 4) = 'nix.'"
        )
    )


def _output_sections(connection: sqlite3.Connection) -> int:
    return int(connection.execute(
        "SELECT count(DISTINCT canonical_nodes.id) FROM canonical_nodes "
        "JOIN canonical_node_evidence ON canonical_node_evidence.canonical_node_id = canonical_nodes.id "
        "JOIN canonical_evidence ON canonical_evidence.id = canonical_node_evidence.canonical_evidence_id "
        "WHERE canonical_nodes.graph_key_version = 1 AND canonical_nodes.kind = 'nix.output' "
        "AND canonical_evidence.raw_kind = 'nix.output_section'"
    ).fetchone()[0])


def nix_summary(connection: sqlite3.Connection, *, root_path: str) -> NixSummaryRecord:
    del root_path  # the PostgreSQL owner reports the literal placeholder, not the root
    require_accepted_publication(connection)
    kinds: Counter[str] = Counter()
    c: Counter[str] = Counter()
    output_files: set[str] = set()
    for kind, path, p in raw_rows(connection, prefix="nix."):
        kinds[kind] += 1
        if kind in _OUTPUTS:
            if path:
                output_files.add(path)
            if any((meta(p, key) or "") == "" for key in ("flake_ref", "system", "name")):
                c["missing_output_identity"] += 1
        if kind == "nix.app":
            resolution = meta(p, "program_resolution")
            if resolution is not None or has_key(_child(p, "metadata"), "program"):
                c["app_programs_total"] += 1
            for value in _RESOLUTIONS:
                c[f"program:{value}"] += resolution == value
        elif kind == "nix.path_ref":
            resolution = meta(p, "resolution")
            for value in ("local", "dynamic", "unknown"):
                c[f"path:{value}"] += resolution == value
            if (like(text_at(p, "target"), "unknown:file:%")
                    or is_in(resolution, ("repo-escaping", "rejected"))
                    or like(meta(p, "resolution_reason"), "repo-escaping%")):
                c["repo_escaping_or_rejected"] += 1
        elif kind == "nix.flake_input":
            for key in ("has_url", "has_follows", "source_redacted"):
                c[key] += meta(p, key) == "true"
            c[f"source:{meta(p, 'source_type')}"] += 1
        elif kind == "nix.output_section":
            c[f"section:{meta(p, 'section')}"] += 1
            c[f"family:{meta(p, 'section_family')}"] += 1
            c[f"shape:{meta(p, 'shape')}"] += 1
        elif kind == "nix.dynamic_output_shape":
            c[f"dynamic:{meta(p, 'pattern')}"] += 1
        elif kind == "nix.unsupported_flake_shape":
            c[f"unsupported:{meta(p, 'pattern')}"] += 1
        elif kind == "nix.import":
            if (flag(meta(p, "dynamic")) or meta(p, "resolution") == "dynamic"
                    or meta(p, "dynamic_reason") is not None):
                c["dynamic_imports"] += 1
            if like(text_at(p, "target"), "unknown:%") or meta(p, "resolution") == "unknown":
                c["unknown_imports"] += 1
    flake_files: set[str] = set()
    for kind, path, p in raw_rows(connection, kinds=("file", "config.redaction", "config.path")):
        if kind == "file":
            language = meta(p, "language")
            c["nix_files"] += language == "nix"
            if basename(path) == "flake.nix" and (language == "nix" or language is None):
                flake_files.add(path)
        else:
            c["config_redactions"] += kind == "config.redaction" or flag(meta(p, "redacted"))
    canonical = canonical_counts(connection, (*_OUTPUTS, "config.document", "config.path"))
    edges = _edge_evidence(connection)
    k = kinds
    return nix_summary_from_storage_payload({
        "root_path": "[root-path]",
        "repository_name": repository_name(connection),
        "nix_observations": sum(kinds.values()),
        "nix_files": c["nix_files"],
        "flake_files": len(flake_files),
        "raw": {
            "imports": k["nix.import"], "path_refs": k["nix.path_ref"], "apps": k["nix.app"],
            "packages": k["nix.package"], "dev_shells": k["nix.devShell"], "checks": k["nix.check"],
        },
        "canonical": {
            "apps": canonical["nix.app"], "packages": canonical["nix.package"],
            "dev_shells": canonical["nix.devShell"], "checks": canonical["nix.check"],
            "output_sections": _output_sections(connection),
        },
        "edges": {
            "import_sources": edges[("sources", "nix.import")],
            "output_defines": sum(edges[("defines", kind)] for kind in _OUTPUTS),
            "output_section_defines": edges[("defines", "nix.output_section")],
            "app_program_edges": edges[("exposes_script", "nix.app")],
        },
        "programs": {
            "app_programs_total": c["app_programs_total"],
            **{value: c[f"program:{value}"] for value in _RESOLUTIONS},
        },
        "paths": {
            "path_refs_total": k["nix.path_ref"],
            **{value: c[f"path:{value}"] for value in ("local", "dynamic", "unknown")},
            "repo_escaping_or_rejected": c["repo_escaping_or_rejected"],
        },
        "flake_inputs": {
            "total": k["nix.flake_input"],
            "with_url": c["has_url"],
            "with_follows": c["has_follows"],
            "redacted_sources": c["source_redacted"],
            "source_types": {value: c[f"source:{value}"] for value in _SOURCE_TYPES},
        },
        "output_sections": {
            "total": k["nix.output_section"],
            "by_section": {value: c[f"section:{value}"] for value in _SECTIONS},
            "by_family": {value: c[f"family:{value}"] for value in _FAMILIES},
            "by_shape": {value: c[f"shape:{value}"] for value in _SHAPES},
        },
        "dynamic_output_shapes": {
            "total": k["nix.dynamic_output_shape"],
            "by_pattern": {value: c[f"dynamic:{value}"] for value in _DYNAMIC},
        },
        "unsupported_flake_shapes": {
            "total": k["nix.unsupported_flake_shape"],
            "by_pattern": {value: c[f"unsupported:{value}"] for value in _UNSUPPORTED},
        },
        "generic_config": {
            "config_documents": canonical["config.document"],
            "config_paths": canonical["config.path"],
            "config_references": raw_count(connection, "config.reference"),
            "config_parse_errors": raw_count(connection, "config.parse_error"),
            "config_redactions": c["config_redactions"],
        },
        "diagnostics": {
            "missing_output_identity": c["missing_output_identity"],
            "dynamic_imports": c["dynamic_imports"],
            "unknown_imports": c["unknown_imports"],
            "unknown_app_programs": c["program:unknown"],
            "raw_only_path_refs": k["nix.path_ref"],
            "flake_files_without_output_observations": len(flake_files - output_files),
        },
        "limitations": {
            "flake_inputs_not_extracted": False,
            **dict.fromkeys((
                "overlays_not_extracted", "modules_not_classified",
                "packages_are_static_attr_counts_only", "no_nix_eval", "no_flake_lock_resolution",
                "path_values_omitted", "weak_output_sections_are_not_concrete_outputs"), True),
        },
        "safety": dict.fromkeys((
            "read_only", "no_execution", "no_nix_cli", "no_fetch", "no_flake_lock_resolution",
            "no_store_inspection", "no_path_values", "private_paths_redacted", "raw_profile_only"),
            True),
    })


__all__ = ("nix_summary",)
