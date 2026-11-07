"""Offline published navigation search corpus for phase SCOPED-SEARCH1.

Disclosure:
    - Synthetic file observations and snapshot manifests.
    - Real static Markdown extraction (page, headings, ADR, skill metadata).
    - Real static Python AST extraction (extract_python_file_observations).
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from common_lore_index.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from common_lore_index.extractors.documents.markdown import extract_markdown_file_observations
from common_lore_index.extractors.languages.python import extract_python_file_observations
from common_lore_index.extractors.languages.python_modules import PythonModuleIndex
from common_lore_index.graph.keys import doc_page_key
from common_lore_index.graph.multi_source import (
    SnapshotManifestEntry,
    SourceSnapshot,
    graph_source_binding_id,
)
from common_lore_index.graph.multi_source_capture import _CapturedSource
from common_lore_index.graph.multi_source_routing import _namespaced_observation, _validate_provenance
from common_lore_index.observations.raw import RawObservation
from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsGraphConfig
from common_lore_index.storage.sqlite_local.connection import initialize_graph_database
from common_lore_index.storage.sqlite_local.publisher import publish_generation
from common_lore_index.storage.staged_ingestion import build_staged_rows
from common_lore_index.storage.staging_family_contracts import PrivacyClassification
from repomap_test_support.sqlite_local_fixtures import (
    graph_toml,
    local_binding,
    publication_for,
    write_sqlite_home,
)

GRAPH = "navigation"
BINDING = graph_source_binding_id(GRAPH, "root")
BEACON_STORE_SYMBOL = "python.function:src.pkg.beacon:beacon_store"
BEACON_OTHER_SYMBOL = "python.function:src.pkg_extra.beacon:beacon_other"
ALPHA_DOC = doc_page_key("root/docs/alpha.md")
BETA_DOC = doc_page_key("root/docs/beta.md")
GAMMA_DOC = doc_page_key("root/docs/gamma.md")

ALPHA_HEADINGS = "\n\n".join(
    f"## Beacon Alpha Section {index}\nDetails for beacon section {index}."
    for index in range(1, 28)
)

MARKDOWN_SOURCES: dict[str, str] = {
    "docs/alpha.md": f"# Beacon Alpha Guide\n\nPrimary beacon guide.\n\n{ALPHA_HEADINGS}\n",
    "docs/beta.md": (
        "# Deployment Operations\n\n"
        "Deployment guide with unmatched title.\n\n"
        "## Beacon Configuration\n\n"
        "Beacon node configuration and runtime parameters.\n"
    ),
    "docs/gamma.md": (
        "# Beacon Gamma Diagnostics\n\n"
        "Telemetry and health monitoring.\n\n"
        "## Beacon Metrics\n\n"
        "Exported telemetry metrics.\n"
    ),
    "docs/adr/0001-beacon.md": (
        "# ADR 0001: Beacon Architecture\n\n"
        "## Status\n\nAccepted\n\n"
        "## Date\n\n2026-10-14\n\n"
        "## Context\n\nBeacon architecture decision record.\n"
    ),
    "docs/skills/beacon/SKILL.md": (
        "---\n"
        "name: beacon-ops\n"
        "description: Beacon operations skill\n"
        "---\n"
        "# Beacon Operations\n\n"
        "Operational procedures for beacon components.\n"
    ),
    "docs/naïve_%/guide.md": (
        "# beacon 100%_café\n\n"
        "## beacon\\display\n\n"
        "Literal wildcard, backslash and Unicode guide.\n"
    ),
    "src/pkg/link.md": (
        "# Beacon Link Documentation\n\n"
        "Reference link to alpha: [Beacon Alpha](../../docs/alpha.md).\n"
    ),
}

PYTHON_SOURCES: dict[str, str] = {
    "src/pkg/beacon.py": (
        '"""Beacon package module."""\n\n\n'
        'def beacon_store() -> str:\n'
        '    """Beacon store function."""\n'
        '    return "store"\n'
    ),
    "src/pkg_extra/beacon.py": (
        '"""Beacon extra sibling module."""\n\n\n'
        'def beacon_other() -> str:\n'
        '    """Beacon other function in sibling directory."""\n'
        '    return "other"\n'
    ),
}

ALL_SOURCES: dict[str, str] = {**MARKDOWN_SOURCES, **PYTHON_SOURCES}


def navigation_bundle(
    graph: str = GRAPH,
    *,
    generation: int = 1,
    markdown_sources: dict[str, str] | None = None,
    python_sources: dict[str, str] | None = None,
    additional_markdown: dict[str, dict[str, str]] | None = None,
    revision: int = 1,
) -> PublicationBundle:
    """Route real Markdown and Python extractions through provenance and staging."""
    md_sources = MARKDOWN_SOURCES if markdown_sources is None else markdown_sources
    py_sources = PYTHON_SOURCES if python_sources is None else python_sources
    all_paths = sorted(set(md_sources.keys()) | set(py_sources.keys()))

    config = OpsGraphConfig(
        graph, graph, "unused", "unused", graph, "public-dev",
        True, True, "default", "manual",
    ).effective_source_bindings[0]
    config = replace(config, revision=revision)

    digest = hashlib.sha256(f"{generation}:{graph}".encode()).hexdigest()
    ascii_paths = [p for p in all_paths if p.isascii()]
    snapshot = SourceSnapshot.create(
        config.domain_binding(graph),
        manifest_entries=tuple(SnapshotManifestEntry(path, digest, 32) for path in ascii_paths),
        git_commit=None,
        git_tree=None,
        ignore_policy_id="ignore1:fixture",
        metadata_identity="meta1:fixture",
    )
    source = _CapturedSource(config, Path("unused"), (), snapshot, ())

    observations: list[RawObservation] = []
    for path in all_paths:
        lang = "python" if path.endswith(".py") else "markdown"
        role = "source" if lang == "python" else "documentation"
        observations.append(
            RawObservation(
                kind="file",
                source_id=f"{path}#file",
                path=path,
                confidence="extracted",
                extractor="fixture",
                extractor_version="1",
                metadata={"language": lang, "role": role},
            )
        )

    py_idx = PythonModuleIndex.from_python_paths(py_sources.keys())
    for path, content in py_sources.items():
        observations.extend(
            extract_python_file_observations(path, content, module_index=py_idx)
        )

    repo_paths = set(all_paths)
    for path, content in md_sources.items():
        observations.extend(
            extract_markdown_file_observations(path, content, repository_paths=repo_paths)
        )

    routed = [_namespaced_observation(row, source) for row in observations]
    sources = [source]
    for alias, documents in (additional_markdown or {}).items():
        other_config = replace(config, binding_id=graph_source_binding_id(graph, alias), alias=alias,
                               logical_root=alias, repository_name=alias + "-repository")
        other_snapshot = SourceSnapshot.create(
            other_config.domain_binding(graph),
            manifest_entries=tuple(SnapshotManifestEntry(path, digest, 32) for path in sorted(documents)),
            git_commit=None, git_tree=None, ignore_policy_id="ignore1:fixture", metadata_identity="meta1:fixture",
        )
        other = _CapturedSource(other_config, Path("unused"), (), other_snapshot, ())
        sources.append(other)
        for path, content in documents.items():
            routed.extend(_namespaced_observation(row, other) for row in
                          extract_markdown_file_observations(path, content, repository_paths=set(documents)))
    _validate_provenance(routed, tuple(sources))
    prepared = build_staged_rows(routed, repository_name=graph, stage_id="stage-unassigned")
    try:
        families = {
            family: tuple(dict(row) for row in prepared.family_rows[family])
            for family in PUBLICATION_FAMILIES
        }
    finally:
        prepared.close()

    return PublicationBundle.create(
        request_id=f"job-{graph}-{generation}",
        job_id=f"job-{graph}-{generation}",
        attempt=1,
        graph_id=graph,
        candidate_id="cand1:" + digest,
        snapshot_manifest_id="snapmanifest1:" + digest,
        snapshot_vector=tuple((item.config.binding_id, item.config.revision, item.snapshot.snapshot_id)
                              for item in sources),
        source_generation="sg1:" + digest,
        config_generation="cg1:" + "6" * 64,
        extractor_generation="eg1:" + "7" * 64,
        canonicalizer_generation="kg1:" + "8" * 64,
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:isolated",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        families=families,
        row_stage_contract="stage-unassigned-v1",
    )


def publish_navigation_generation(database: Path, generation: int = 1) -> None:
    bundle = navigation_bundle(generation=generation)
    publish_generation(
        database,
        publication_for(bundle, GRAPH),
        bundle.families,
        expected_generation=generation - 1,
    )


def navigation_home(tmp_path: Path) -> tuple[Path, Path]:
    """Reusable public disposable SQLite home with navigation graphs."""
    root = tmp_path / "never-created-source"
    home = write_sqlite_home(
        tmp_path / "home",
        (
            graph_toml(GRAPH, root)
            + graph_toml("sibling", root)
            + graph_toml("hidden", root, visible=False)
            + graph_toml("disabled", root, enabled=False)
            + graph_toml("unpublished", root)
        ),
    )
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    config.graph_store_root.mkdir(parents=True, mode=0o700)
    for graph in (GRAPH, "sibling", "unpublished"):
        path = config.graph_store_root / f"{graph}.sqlite3"
        initialize_graph_database(path, local_binding(graph), applied_at="2026-10-14T00:00:00Z")
        if graph == "unpublished":
            continue
        bundle = (navigation_bundle(graph, markdown_sources={
            "docs/only-sibling.md": "# Beacon Sibling\n## Beacon Foreign Destination\n",
        }, python_sources={}) if graph == "sibling" else navigation_bundle(graph))
        publish_generation(
            path,
            publication_for(bundle, graph),
            bundle.families,
            expected_generation=0,
        )
    return home, config.graph_store_root / f"{GRAPH}.sqlite3"
