"""Small offline published provenance corpus for the source locator."""

from __future__ import annotations

import hashlib
from pathlib import Path

from common_lore_index.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from common_lore_index.extractors.documents.markdown import extract_markdown_file_observations
from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsGraphConfig
from common_lore_index.graph.keys import doc_page_key
from common_lore_index.graph.multi_source import SnapshotManifestEntry, SourceSnapshot, graph_source_binding_id
from common_lore_index.graph.multi_source_capture import _CapturedSource
from common_lore_index.graph.multi_source_routing import _namespaced_observation, _validate_provenance
from common_lore_index.observations.raw import RawObservation
from common_lore_index.storage.sqlite_local.connection import initialize_graph_database
from common_lore_index.storage.sqlite_local.publisher import publish_generation
from common_lore_index.storage.staged_ingestion import build_staged_rows
from common_lore_index.storage.staging_family_contracts import PrivacyClassification
from repomap_test_support.sqlite_local_fixtures import (
    generation_bundle, graph_toml, local_binding, publication_for, write_sqlite_home,
)

GRAPH = "locator"
SYMBOL = "python.function:sample.service:serve"
DOC = doc_page_key("root/docs/guide.md")
BINDING = graph_source_binding_id(GRAPH, "root")


def _reference_observations(path: str, repository_paths: list[str]) -> list[RawObservation]:
    return [*extract_markdown_file_observations(
        path, "[Guide](guide.md)\n", repository_paths=set(repository_paths),
    ), RawObservation(
        kind="markdown.link", source_id=f"{path}#symbol-link", path=path,
        target=SYMBOL, start_line=1, end_line=1,
        confidence="extracted", extractor="fixture", extractor_version="1",
    )]


def locator_bundle(
    graph: str = GRAPH, *, generation: int = 1, start_line: int = 5, alternatives: bool = True,
    reference_count: int = 0, definitions: bool = True,
    trailing_reference: bool = False,
) -> PublicationBundle:
    """Route real Markdown extraction and generic Python observations before publication."""
    config = OpsGraphConfig(graph, graph, "unused", "unused", graph, "public-dev",
                            True, True, "default", "manual").effective_source_bindings[0]
    paths = ["src/service.py", "docs/guide.md"]
    if alternatives:
        paths.append("alternate/service.py")
    paths.extend(f"docs/reference-{index}.md" for index in range(reference_count))
    if trailing_reference:
        paths.append("docs/trailing-reference.md")
    digest = hashlib.sha256(
        f"{generation}:{start_line}:{alternatives}:{reference_count}:{definitions}:{trailing_reference}".encode()
    ).hexdigest()
    snapshot = SourceSnapshot.create(
        config.domain_binding(graph),
        manifest_entries=tuple(SnapshotManifestEntry(path, digest, 32) for path in paths),
        git_commit=None, git_tree=None, ignore_policy_id="ignore1:fixture",
        metadata_identity="meta1:fixture",
    )
    source = _CapturedSource(config, Path("unused"), (), snapshot, ())
    observations = [RawObservation(kind="file", source_id=f"{path}#file", path=path,
                                   confidence="extracted", extractor="fixture", extractor_version="1")
                    for path in paths]
    for index in range(reference_count):
        observations.extend(_reference_observations(f"docs/reference-{index}.md", paths))
    if definitions:
        observations.append(RawObservation(
            kind="python.function", source_id="src/service.py#serve", path="src/service.py",
            name="serve", target=SYMBOL, start_line=start_line, end_line=start_line + 10,
            confidence="extracted", extractor="fixture", extractor_version="1",
            metadata={"module": "sample.service"},
        ))
    if alternatives and definitions:
        observations.append(RawObservation(
            kind="python.function", source_id="alternate/service.py#serve", path="alternate/service.py",
            name="serve", target=SYMBOL, start_line=20, end_line=23,
            confidence="extracted", extractor="fixture", extractor_version="1",
            metadata={"module": "sample.service"},
        ))
    if definitions:
        observations.extend(extract_markdown_file_observations("docs/guide.md", "Fixture guide.\n"))
    if trailing_reference:
        observations.extend(_reference_observations("docs/trailing-reference.md", paths))
    routed = tuple(_namespaced_observation(row, source) for row in observations)
    _validate_provenance(routed, (source,))
    prepared = build_staged_rows(routed, repository_name=graph, stage_id="stage-unassigned")
    try:
        families = {family: tuple(dict(row) for row in prepared.family_rows[family])
                    for family in PUBLICATION_FAMILIES}
    finally:
        prepared.close()
    return PublicationBundle.create(
        request_id=f"job-locator-{generation}", job_id=f"job-locator-{generation}", attempt=1,
        graph_id=graph, candidate_id="cand1:" + digest,
        snapshot_manifest_id="snapmanifest1:" + digest,
        snapshot_vector=((config.binding_id, config.revision, snapshot.snapshot_id),),
        source_generation="sg1:" + digest, config_generation="cg1:" + "6" * 64,
        extractor_generation="eg1:" + "7" * 64, canonicalizer_generation="kg1:" + "8" * 64,
        extractor_capability_identity="cap1:python-static-v1", resolver_identity="resolver1:isolated",
        canonicalizer_identity="canon1:graph-key-v1-binding-path", semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default", privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        families=families, row_stage_contract="stage-unassigned-v1",
    )


def publish_locator_generation(
    database: Path, generation: int, *, start_line: int = 5, alternatives: bool = True,
    reference_count: int = 0, definitions: bool = True,
    trailing_reference: bool = False,
) -> None:
    bundle = locator_bundle(generation=generation, start_line=start_line, alternatives=alternatives,
                            reference_count=reference_count, definitions=definitions,
                            trailing_reference=trailing_reference)
    publish_generation(database, publication_for(bundle, GRAPH), bundle.families,
                       expected_generation=generation - 1)


def locator_home(tmp_path: Path, *, reference_count: int = 0) -> tuple[Path, Path]:
    """Use actual canonicalization/publication; no source tree needs to exist."""
    root = tmp_path / "never-created-source"
    home = write_sqlite_home(tmp_path / "home", (
        graph_toml(GRAPH, root) + graph_toml("sibling", root)
        + graph_toml("hidden", root, visible=False)
        + graph_toml("disabled", root, enabled=False)
        + graph_toml("unpublished", root)
    ))
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    config.graph_store_root.mkdir(parents=True, mode=0o700)
    for graph in (GRAPH, "sibling", "unpublished"):
        path = config.graph_store_root / f"{graph}.sqlite3"
        initialize_graph_database(path, local_binding(graph), applied_at="2026-10-14T00:00:00Z")
        if graph == "unpublished":
            continue
        bundle = generation_bundle(1) if graph == "sibling" else locator_bundle(graph, reference_count=reference_count)
        publish_generation(path, publication_for(bundle, graph), bundle.families, expected_generation=0)
    return home, config.graph_store_root / f"{GRAPH}.sqlite3"
