"""Real SQLite Local and PostgreSQL publication and retained-attempt loaders for mixed-v1 (S2)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from common_lore_index.artifacts import (
    ArtifactReference,
    FileSystemArtifactStore,
    PortableSnapshotManifest,
    PublicationExpectation,
    PublisherBundleValidator,
)
from common_lore_index.artifacts.bundle import PublicationBundle
from common_lore_index.artifacts.receipt import ExtractionReceipt
from common_lore_index.artifacts.references import ArtifactLocator
from common_lore_index.coordinator._portable_semantic_adapter import (
    WORKER_CAPABILITY_IDENTITY,
)
from common_lore_index.ops.config_local import (
    LocalSqliteConfig,
    load_graph_registry_config_home,
    local_graph_binding,
    sqlite_graph_database_path,
)
from common_lore_index.ops.config_records import OpsConfig, OpsGraphConfig
from common_lore_index.ops.local_refresh import (
    initialize_local_graph,
    refresh_local_graph,
)
from common_lore_index.ops.local_state_layout import attempts_namespace
from common_lore_index.ops.portable_refresh import (
    execute_portable_refresh,
    portable_attempts_parent,
)
from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy
from common_lore_index.retrieval.publication_binding import (
    AcceptedPublicationReference,
    ProjectionInputs,
)
from common_lore_index.storage._staged_ingestion_authority import (
    IngestionAuthority,
    stage_id_for_authority,
)
from common_lore_index.storage.authority import OperationId
from common_lore_index.storage.main import apply_migrations
from common_lore_index.storage.publication import (
    RunPublicationReceipt,
    publication_receipt_from_mapping,
)
from common_lore_index.storage.publication_readback import (
    read_latest_receipt_bearing_publication,
)
from common_lore_index.storage.sqlite_local.connection import read_transaction
from common_lore_index.storage.sqlite_local.schema import accepted_identity
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    build_mixed_v1_projection_policy,
)


@dataclass(frozen=True)
class PublishedCorpusState:
    """Accepted store state and verified retained portable inputs for one published generation."""

    backend: str
    graph_id: str
    home_root: Path
    attempt_root: Path
    accepted_reference: AcceptedPublicationReference
    receipt: RunPublicationReceipt
    extraction_receipt: ExtractionReceipt
    manifest: PortableSnapshotManifest
    manifest_reference: ArtifactReference
    bundle: PublicationBundle
    bundle_reference: ArtifactReference
    receipt_reference: ArtifactReference
    store: FileSystemArtifactStore
    policy: BodyProjectionPolicy

    def projection_inputs(self) -> ProjectionInputs:
        return ProjectionInputs(
            accepted_reference=self.accepted_reference,
            receipt=self.receipt,
            manifest=self.manifest,
            bundle=self.bundle,
            store=self.store,
            manifest_reference=self.manifest_reference,
            bundle_reference=self.bundle_reference,
            receipt_reference=self.receipt_reference,
            extraction_receipt=self.extraction_receipt,
            spool_dir=self.attempt_root / "workspace",
        )


def _find_manifest_in_store(
    store: FileSystemArtifactStore,
    expected_manifest_id: str,
) -> tuple[PortableSnapshotManifest, ArtifactReference]:
    objects_dir = store.root / "objects"
    for obj_file in sorted(objects_dir.iterdir()):
        if not obj_file.is_file():
            continue
        digest_hex = obj_file.name
        try:
            raw = obj_file.read_bytes()
            if not raw.startswith(b"{"):
                continue
            parsed = PortableSnapshotManifest.from_bytes(raw)
        except Exception:
            continue
        if parsed.manifest_id == expected_manifest_id:
            ref = ArtifactReference(
                content_digest=f"sha256:{digest_hex}",
                size_bytes=len(raw),
                media_type="application/x-repomap-snapshot-manifest-v1+json",
                record_format="canonical-json-v1",
                locator=ArtifactLocator(kind="filesystem", value=f"objects/{digest_hex}"),
                privacy=parsed.effective_privacy,
            )
            verified_bytes = store.read(ref)
            return PortableSnapshotManifest.from_bytes(verified_bytes), ref
    raise LookupError(f"manifest {expected_manifest_id!r} not found in retained ArtifactStore")


def _load_and_validate_retained_attempt(
    attempt_root: Path,
    receipt: RunPublicationReceipt,
    graph_id: str,
) -> tuple[
    FileSystemArtifactStore,
    PortableSnapshotManifest,
    ArtifactReference,
    ExtractionReceipt,
    ArtifactReference,
    PublicationBundle,
    ArtifactReference,
]:
    portable = receipt.portable
    if portable is None:
        raise ValueError("accepted receipt is missing portable binding")
    result_path = attempt_root / "portable-result.json"
    if not result_path.is_file():
        raise FileNotFoundError(f"retained portable-result.json missing at {result_path}")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    if payload.get("manifest_id") != portable.snapshot_manifest_id:
        raise ValueError("retained portable-result.json manifest_id mismatch")

    receipt_ref = ArtifactReference.from_mapping(payload["receipt"]).with_store_version(None)
    bundle_ref = ArtifactReference.from_mapping(payload["bundle"]).with_store_version(None)
    store = FileSystemArtifactStore(attempt_root / "objects")

    manifest, manifest_ref = _find_manifest_in_store(store, portable.snapshot_manifest_id)
    extraction_receipt = ExtractionReceipt.from_bytes(store.read(receipt_ref))
    bundle = PublicationBundle.from_bytes(store.read(bundle_ref))

    authority = IngestionAuthority(
        operation_id=OperationId(str(receipt.attempt.job_id)),
        attempt=receipt.attempt.attempt,
        execution_mode=portable.execution_mode,
        source_generation=receipt.generations.source_generation,
        config_generation=receipt.generations.config_generation,
        extractor_generation=receipt.generations.extractor_generation,
        canonicalizer_generation=receipt.generations.canonicalizer_generation,
        singleton_fencing_epoch=portable.singleton_fencing_epoch,
        graph_lease_fencing_epoch=portable.graph_lease_fencing_epoch,
    )
    stage_id = stage_id_for_authority(authority)
    expectation = PublicationExpectation(
        request_id=receipt.attempt.job_id,
        job_id=receipt.attempt.job_id,
        attempt=receipt.attempt.attempt,
        graph_id=graph_id,
        candidate_id=portable.candidate_id,
        snapshot_manifest_id=manifest.manifest_id,
        snapshot_vector=manifest.snapshot_vector,
        source_generation=manifest.source_generation,
        config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation,
        canonicalizer_generation=manifest.canonicalizer_generation,
        extractor_capability_identity=manifest.extractor_capability_identity,
        resolver_identity=manifest.resolver_identity,
        canonicalizer_identity=manifest.canonicalizer_identity,
        semantic_contract_identity=manifest.semantic_contract_identity,
        quality_rule_identity=manifest.quality_rule_identity,
        mutating_owner_count=1,
        worker_capability_identity=WORKER_CAPABILITY_IDENTITY,
        expected_privacy=manifest.effective_privacy.value,
    )
    validated = PublisherBundleValidator().validate_bundle_stream(
        store=store,
        bundle_reference=bundle_ref,
        receipt_reference=receipt_ref,
        expectation=expectation,
        stage_id=stage_id,
        spool_dir=attempt_root / "workspace",
    )
    validated.close()
    return store, manifest, manifest_ref, extraction_receipt, receipt_ref, bundle, bundle_ref


def read_sqlite_accepted_publication(
    config: LocalSqliteConfig,
    graph_id: str = MIXED_V1_GRAPH_ID,
) -> tuple[AcceptedPublicationReference, RunPublicationReceipt]:
    """Read current accepted publication marker and full RunPublicationReceipt from SQLite Local."""
    graph: OpsGraphConfig | None = next((c for c in config.graphs if c.id == graph_id), None)
    if graph is None:
        raise ValueError(f"unknown graph_id {graph_id!r}")
    db_path = sqlite_graph_database_path(config, graph)
    binding = local_graph_binding(graph)
    sqlite_omitted = {
        "portable_singleton_fencing_epoch",
        "portable_graph_lease_fencing_epoch",
    }
    field_names = tuple(
        col for col in RunPublicationReceipt.field_names() if col not in sqlite_omitted
    )
    select_cols = ", ".join(field_names)
    with read_transaction(db_path, binding) as connection:
        accepted = accepted_identity(connection)
        if accepted is None:
            raise LookupError(f"SQLite graph {graph_id!r} has no accepted publication")
        row = connection.execute(
            f"SELECT {select_cols} FROM runs WHERE id = ? AND status = 'complete'",
            (accepted.run_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"SQLite run {accepted.run_id} not found in runs table")
        mapping: dict[str, object] = {
            col: row[idx] for idx, col in enumerate(field_names)
        }
        mapping["portable_singleton_fencing_epoch"] = 0
        mapping["portable_graph_lease_fencing_epoch"] = 0
    receipt = publication_receipt_from_mapping(mapping)
    if receipt is None or receipt.portable is None:
        raise ValueError("SQLite accepted run is missing portable publication receipt")
    accepted_ref = AcceptedPublicationReference(
        graph_id=graph_id,
        repository_id=binding.repository_identity,
        backend="sqlite",
        run_id=int(accepted.run_id),
        publication_bundle_id=receipt.portable.publication_bundle_id,
        job_id=str(receipt.attempt.job_id),
        attempt=int(receipt.attempt.attempt),
        accepted_generation=int(accepted.generation),
        snapshot_manifest_id=receipt.portable.snapshot_manifest_id,
        extraction_receipt_id=receipt.portable.extraction_receipt_id,
        trusted_caller=True,
    ).validate()
    return accepted_ref, receipt


def publish_and_load_sqlite_corpus(
    home_root: Path,
    *,
    graph_id: str = MIXED_V1_GRAPH_ID,
    selected_aliases: Sequence[str] = ("core", "companion"),
) -> PublishedCorpusState:
    """Initialize/refresh a SQLite Local mixed-v1 home and load its verified retained state."""
    config = load_graph_registry_config_home(home_root)
    if not isinstance(config, LocalSqliteConfig):
        raise TypeError("expected LocalSqliteConfig for SQLite home")
    initialize_local_graph(config, graph_id)
    refresh_local_graph(config, graph_id)
    accepted_ref, receipt = read_sqlite_accepted_publication(config, graph_id)
    token = hashlib.sha256(
        f"{receipt.attempt.job_id}\0{receipt.attempt.attempt}".encode("utf-8")
    ).hexdigest()
    attempt_root = portable_attempts_parent(config, attempts_namespace(graph_id)) / token
    store, manifest, manifest_ref, ext_receipt, receipt_ref, bundle, bundle_ref = (
        _load_and_validate_retained_attempt(attempt_root, receipt, graph_id)
    )
    policy = build_mixed_v1_projection_policy(graph_id, selected_aliases=selected_aliases)
    return PublishedCorpusState(
        backend="sqlite",
        graph_id=graph_id,
        home_root=home_root,
        attempt_root=attempt_root,
        accepted_reference=accepted_ref,
        receipt=receipt,
        extraction_receipt=ext_receipt,
        manifest=manifest,
        manifest_reference=manifest_ref,
        bundle=bundle,
        bundle_reference=bundle_ref,
        receipt_reference=receipt_ref,
        store=store,
        policy=policy,
    )


def read_postgres_accepted_publication(
    config: OpsConfig,
    graph_id: str = MIXED_V1_GRAPH_ID,
    *,
    psql_command: str = "psql",
) -> tuple[AcceptedPublicationReference, RunPublicationReceipt]:
    """Read current accepted publication record from PostgreSQL."""
    graph: OpsGraphConfig | None = next((c for c in config.graphs if c.id == graph_id), None)
    if graph is None:
        raise ValueError(f"unknown graph_id {graph_id!r}")
    database = graph.database or config.postgres.database
    psql_args = config.postgres.psql_args_for_database(database)
    record = read_latest_receipt_bearing_publication(psql_args, psql_command=psql_command)
    if record is None or record.receipt.portable is None:
        raise LookupError(f"PostgreSQL graph {graph_id!r} has no accepted portable publication")
    receipt = record.receipt
    portable = receipt.portable
    assert portable is not None
    binding = local_graph_binding(graph)
    accepted_ref = AcceptedPublicationReference(
        graph_id=graph_id,
        repository_id=binding.repository_identity,
        backend="postgresql",
        run_id=int(record.run_id),
        publication_bundle_id=portable.publication_bundle_id,
        job_id=str(receipt.attempt.job_id),
        attempt=int(receipt.attempt.attempt),
        accepted_generation=None,
        snapshot_manifest_id=portable.snapshot_manifest_id,
        extraction_receipt_id=portable.extraction_receipt_id,
        trusted_caller=True,
    ).validate()
    return accepted_ref, receipt


def publish_and_load_postgres_corpus(
    home_root: Path,
    *,
    graph_id: str = MIXED_V1_GRAPH_ID,
    selected_aliases: Sequence[str] = ("core", "companion"),
    psql_command: str = "psql",
) -> PublishedCorpusState:
    """Refresh a PostgreSQL mixed-v1 home via execute_portable_refresh and load its state."""
    config = load_graph_registry_config_home(home_root)
    if not isinstance(config, OpsConfig):
        raise TypeError("expected OpsConfig for PostgreSQL home")
    graph: OpsGraphConfig | None = next((c for c in config.graphs if c.id == graph_id), None)
    if graph is None:
        raise ValueError(f"unknown graph_id {graph_id!r}")
    database = graph.database or config.postgres.database
    psql_args = config.postgres.psql_args_for_database(database)
    apply_migrations(None, psql_args, psql_command=psql_command)
    execute_portable_refresh(config, graph, database, authority=None)
    accepted_ref, receipt = read_postgres_accepted_publication(
        config, graph_id, psql_command=psql_command
    )
    token = hashlib.sha256(
        f"{receipt.attempt.job_id}\0{receipt.attempt.attempt}".encode("utf-8")
    ).hexdigest()
    attempt_root = portable_attempts_parent(config, None) / token
    store, manifest, manifest_ref, ext_receipt, receipt_ref, bundle, bundle_ref = (
        _load_and_validate_retained_attempt(attempt_root, receipt, graph_id)
    )
    policy = build_mixed_v1_projection_policy(graph_id, selected_aliases=selected_aliases)
    return PublishedCorpusState(
        backend="postgresql",
        graph_id=graph_id,
        home_root=home_root,
        attempt_root=attempt_root,
        accepted_reference=accepted_ref,
        receipt=receipt,
        extraction_receipt=ext_receipt,
        manifest=manifest,
        manifest_reference=manifest_ref,
        bundle=bundle,
        bundle_reference=bundle_ref,
        receipt_reference=receipt_ref,
        store=store,
        policy=policy,
    )


__all__ = [
    "PublishedCorpusState",
    "publish_and_load_postgres_corpus",
    "publish_and_load_sqlite_corpus",
    "read_postgres_accepted_publication",
    "read_sqlite_accepted_publication",
]
