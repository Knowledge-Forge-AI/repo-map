"""Public-safe portable publication fixtures shared by integration owners."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from psycopg import Connection

from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_test_support.portable_worker_scenarios import (
    assert_supervised_run_portable_worker_lifecycle as assert_supervised_run_portable_worker_lifecycle,
    coordinator_test_limits as coordinator_test_limits,
    make_missing_manifest_reference as make_missing_manifest_reference,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.main import LoadSummary
from repomap_kg.storage.publication import PortablePublicationBinding
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    build_staged_rows,
    run_staged_portable_refresh,
    stage_id_for_authority,
)
from repomap_kg.storage.staging_family_contracts import PrivacyClassification

def _bundle() -> PublicationBundle:
    prepared = build_staged_rows(
        (
            RawObservation(
                kind="file",
                source_id="main.py",
                path="main.py",
                confidence="extracted",
                extractor="fixture",
                extractor_version="1",
                metadata={"language": "python", "role": "source"},
            ),
        ),
        repository_name="portable-fixture",
        stage_id="stage-unassigned",
    )
    try:
        families = {
            family: tuple(dict(row) for row in prepared.family_rows[family])
            for family in PUBLICATION_FAMILIES
        }
    finally:
        prepared.close()
    return PublicationBundle.create(
        request_id="job-str-pub5",
        job_id="job-str-pub5",
        attempt=1,
        graph_id="portable-fixture",
        candidate_id="cand1:" + "1" * 64,
        snapshot_manifest_id="snapmanifest1:" + "2" * 64,
        snapshot_vector=(("bind1:" + "3" * 64, 1, "snap1:" + "4" * 64),),
        source_generation="sg1:" + "5" * 64,
        config_generation="cg1:" + "6" * 64,
        extractor_generation="eg1:" + "7" * 64,
        canonicalizer_generation="kg1:" + "8" * 64,
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:nix-static-v2",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        families=families,
        row_stage_contract="stage-unassigned-v1",
    )


def _seven_family_bundle(
    *,
    job_id: str = "job-str-pub5",
    attempt: int = 1,
    candidate_id: str | None = None,
    graph_id: str = "portable-fixture",
    repository_name: str = "portable-fixture",
    privacy: PrivacyClassification = PrivacyClassification.CANONICAL_PROVENANCE,
    file_path: str = "pkg/main.py",
    module_name: str = "pkg.main",
    function_name: str = "serve",
    stage_id: str = "stage-unassigned",
) -> PublicationBundle:
    prepared = build_staged_rows(
        (
            RawObservation(
                kind="file",
                source_id=file_path,
                path=file_path,
                confidence="extracted",
                extractor="fixture",
                extractor_version="1",
                metadata={"language": "python", "role": "source"},
            ),
            RawObservation(
                kind="python.module",
                source_id=f"{file_path}#module:{module_name}",
                path=file_path,
                start_line=1,
                end_line=20,
                name=module_name,
                target=f"python.module:{module_name}",
                confidence="extracted",
                extractor="repo-python",
                extractor_version="0.1.0",
                metadata={"module": module_name, "package_root": "pkg", "parser": "ast"},
            ),
            RawObservation(
                kind="python.function",
                source_id=f"{file_path}#function:5:{function_name}",
                path=file_path,
                start_line=5,
                end_line=15,
                name=function_name,
                target=f"python.function:{module_name}.{function_name}",
                confidence="extracted",
                extractor="repo-python",
                extractor_version="0.1.0",
                metadata={"module": module_name, "async": False, "decorators": []},
            ),
        ),
        repository_name=repository_name,
        stage_id=stage_id,
    )
    try:
        families = {
            family: tuple(dict(row) for row in prepared.family_rows[family])
            for family in PUBLICATION_FAMILIES
        }
    finally:
        prepared.close()
    return PublicationBundle.create(
        request_id=job_id,
        job_id=job_id,
        attempt=attempt,
        graph_id=graph_id,
        candidate_id=candidate_id or ("cand1:" + "1" * 64),
        snapshot_manifest_id="snapmanifest1:" + "2" * 64,
        snapshot_vector=(("bind1:" + "3" * 64, 1, "snap1:" + "4" * 64),),
        source_generation="sg1:" + "5" * 64,
        config_generation="cg1:" + "6" * 64,
        extractor_generation="eg1:" + "7" * 64,
        canonicalizer_generation="kg1:" + "8" * 64,
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:nix-static-v2",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
        privacy=privacy,
        families=families,
        row_stage_contract="stage-unassigned-v1",
    )


def _authority(bundle: PublicationBundle) -> IngestionAuthority:
    return IngestionAuthority(
        operation_id=OperationId(bundle.job_id),
        attempt=AttemptNumber(bundle.attempt),
        execution_mode="coordinator",
        source_generation=bundle.source_generation,
        config_generation=bundle.config_generation,
        extractor_generation=bundle.extractor_generation,
        canonicalizer_generation=bundle.canonicalizer_generation,
        job_id=JobId(bundle.job_id),
        coordinator_instance_id="coord-str-pub5",
        singleton_fencing_epoch=7,
        graph_lease_fencing_epoch=9,
    )


def _binding(bundle: PublicationBundle, authority: IngestionAuthority) -> PortablePublicationBinding:
    return PortablePublicationBinding(
        route="portable-worker-v1",
        snapshot_manifest_id=bundle.snapshot_manifest_id,
        snapshot_vector=bundle.snapshot_vector,
        extraction_receipt_id="receipt1:" + "9" * 64,
        publication_bundle_id=bundle.bundle_id,
        candidate_id=bundle.candidate_id,
        resolver_identity=bundle.resolver_identity,
        canonicalizer_identity=bundle.canonicalizer_identity,
        semantic_contract_identity=bundle.semantic_contract_identity,
        quality_rule_identity=bundle.quality_rule_identity,
        protocol_version="1.0",
        worker_capability_identity="cap1:portable-python-worker-v1",
        stage_id=stage_id_for_authority(authority),
        execution_mode="coordinator",
        singleton_fencing_epoch=authority.singleton_fencing_epoch,
        graph_lease_fencing_epoch=authority.graph_lease_fencing_epoch,
        family_receipts={
            item.family: {
                "count": item.record_count,
                "byte_length": item.byte_length,
                "digest": item.content_digest,
            }
            for item in bundle.family_summaries
        },
    ).validate()




def _row(connection: Connection, query: str, params: tuple[object, ...] | None = None) -> tuple[object, ...]:
    """Require an actual database row before asserting its typed fields."""
    result = connection.execute(query, params).fetchone()
    assert result is not None
    return result


def publish_portable_bundle(
    psql_args: Sequence[str],
    bundle_instance: PublicationBundle | None = None,
    *,
    repository_name: str = "portable-fixture",
    root_path: str = "graph:portable-fixture",
    authority_override: IngestionAuthority | None = None,
    binding_override: PortablePublicationBinding | None = None,
) -> LoadSummary:
    """Admit and publish a portable bundle through the standard publication sole writer."""
    b = bundle_instance if bundle_instance is not None else seven_family_bundle(
        repository_name=repository_name, graph_id=repository_name,
    )
    auth = authority_override if authority_override is not None else authority(b)
    bind = binding_override if binding_override is not None else binding(b, auth)
    return run_staged_portable_refresh(
        psql_args,
        b,
        repository_name=repository_name,
        root_path=root_path,
        authority=auth,
        portable_binding=bind,
    )


def make_test_binding(
    graph_id: str,
    alias: str,
    src: Path,
    role: str = "entry",
    *,
    privacy: str = "public-dev",
) -> OpsGraphSourceBindingConfig:
    """Build a deterministic source binding configuration."""
    return OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id(graph_id, alias),
        source_definition_id=f"src1:{alias}",
        alias=alias,
        revision=1,
        source_kind=SourceKind.FOLDER,
        root_path=str(src),
        root_path_expanded=str(src),
        repository_name=f"repo-{alias}",
        logical_root=".",
        privacy=privacy,
        evidence_retention="metadata-only",
        extractor_profile="default",
        include_paths=(),
        exclude_paths=(),
        selection_policy_id=source_selection_policy_id((), ()),
        resolution_policy="allow-declared",
        enabled=True,
        role=role,
        input_name=None,
    )


def create_single_source_graph_config(
    source_dir: Path,
    *,
    graph_id: str = "test-composition-graph",
    repository_name: str = "test-comp-repo",
    privacy: str = "public-dev",
) -> OpsGraphConfig:
    """Build a single-binding OpsGraphConfig for composition tests."""
    test_binding = make_test_binding(graph_id, "primary", source_dir, "entry", privacy=privacy)
    return OpsGraphConfig(
        id=graph_id,
        name=f"Graph {graph_id}",
        root_path="",
        root_path_expanded="",
        repository_name=repository_name,
        privacy=privacy,
        enabled=True,
        mcp_visible=True,
        extractor_profile="default",
        refresh_policy="manual",
        source_bindings=(test_binding,),
        explicit_source_bindings=True,
    )


# Public aliases
bundle = _bundle
seven_family_bundle = _seven_family_bundle
authority = _authority
binding = _binding
row = _row


def assert_successor_family_rows(
    connection: Connection[tuple[object, ...]],
    bundle: PublicationBundle,
    *,
    run_id: int,
    failed_run_id: int,
    stage_id: str,
    failed_stage_id: str,
) -> None:
    """Compare run-owned semantic projections after rollback and successor merge."""
    # Merges retain prior runs: compare the successor-owned semantic rows.
    projections = {
        "files": ("SELECT path FROM files WHERE last_seen_run_id = %s", ("path",)),
        "raw_observations": (
            "SELECT ordinal, kind, source_id, path FROM raw_observations WHERE run_id = %s",
            ("source_ordinal", "kind", "source_id", "path"),
        ),
        "canonical_nodes": (
            "SELECT canonical_key, kind FROM canonical_nodes WHERE last_seen_run_id = %s",
            ("canonical_key", "kind"),
        ),
        "canonical_edges": (
            "SELECT source_canonical_key, edge_kind, target_canonical_key "
            "FROM canonical_edges WHERE last_seen_run_id = %s",
            ("source_canonical_key", "edge_kind", "target_canonical_key"),
        ),
        "canonical_evidence": (
            "SELECT evidence_key, path FROM canonical_evidence WHERE run_id = %s",
            ("evidence_key", "path"),
        ),
        "canonical_node_evidence": (
            "SELECT n.canonical_key, e.evidence_key, l.link_kind "
            "FROM canonical_node_evidence l "
            "JOIN canonical_nodes n ON n.id = l.canonical_node_id "
            "JOIN canonical_evidence e ON e.id = l.canonical_evidence_id "
            "WHERE e.run_id = %s",
            ("canonical_key", "evidence_key", "link_kind"),
        ),
        "canonical_edge_evidence": (
            "SELECT n.source_canonical_key, n.edge_kind, n.target_canonical_key, "
            "e.evidence_key, l.link_kind FROM canonical_edge_evidence l "
            "JOIN canonical_edges n ON n.id = l.canonical_edge_id "
            "JOIN canonical_evidence e ON e.id = l.canonical_evidence_id "
            "WHERE e.run_id = %s",
            ("source_canonical_key", "edge_kind", "target_canonical_key", "evidence_key", "link_kind"),
        ),
    }
    assert set(projections) == set(PUBLICATION_FAMILIES)
    for family in PUBLICATION_FAMILIES:
        query, columns = projections[family]
        actual = connection.execute(query, (run_id,)).fetchall()
        expected = [tuple(row[column] for column in columns) for row in bundle.families[family]]
        assert actual and sorted(actual) == sorted(expected)
        assert len(actual) == bundle.family_counts[family]
    assert connection.execute(
        "SELECT count(*) FROM raw_observations WHERE run_id = %s",
        (failed_run_id,),
    ).fetchone() == (0,)

    assert connection.execute(
        "SELECT status, publication_bundle_id, graph_candidate_id FROM runs WHERE id = %s",
        (failed_run_id,),
    ).fetchone() == ("failed", None, None)
    for selected_stage, expected_state, expected_merge in (
        (stage_id, "published", "committed"),
        (failed_stage_id, "failed", "rolled_back"),
    ):
        assert connection.execute(
            "SELECT state, merge_status, publication_reconciliation_state, cleanup_eligibility "
            "FROM ingestion_stages WHERE stage_id = %s",
            (selected_stage,),
        ).fetchone() == (expected_state, expected_merge, "reconciled", "eligible")
