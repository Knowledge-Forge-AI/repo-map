"""One production portable-worker route into the sole staged publisher."""

from __future__ import annotations

from common_lore_index.runtime.postgres_route import PostgresRoute, effective_postgres_route

import secrets
from typing import Any

from common_lore_index.artifacts import (
    ArtifactReference as ArtifactReference, FileSystemArtifactStore,
    PortableSnapshotManifest as PortableSnapshotManifest, PublicationExpectation,
    PublisherBundleValidator,
)
from common_lore_index.artifacts.sealing_governance import SealingBudget, governance_kwargs
from common_lore_index.artifacts._bundle_stream_parse import ValidatedBundleDescriptor
from common_lore_index.artifacts.bundle import STREAMING_MAX_BUNDLE_BYTES
from common_lore_index.artifacts.receipt import ExtractionReceipt
from common_lore_index.artifacts.source_sealer import seal_configured_sources
from common_lore_index.coordinator._portable_capability import PortableExecutionCapability, create_portable_capability
from common_lore_index.coordinator._portable_worker_launch import run_portable_worker
from common_lore_index.coordinator._portable_materialization import _directory_identity
from common_lore_index.coordinator._portable_semantic_adapter import WORKER_CAPABILITY_IDENTITY
from common_lore_index.ops._portable_worker_terms import (
    PORTABLE_MAX_ARTIFACT_BYTES, _worker_references, effective_leaf_limits,
)
from common_lore_index.ops.resource_view import (
    ResourceObserver, end_stage, mark, note_manifest, note_validated,
    note_worker_launch, note_worker_usage, observer_kwargs,
)
from common_lore_index.ops._portable_governance import seal_with_meter, start_sealing_meter, usage_kwargs
from common_lore_index.ops.config_records import OpsConfig, OpsGraphConfig
from common_lore_index.ops.generations import canonicalizer_generation, extractor_generation
from common_lore_index.ops.graph_registry import GraphRegistryConfig
from common_lore_index.storage.main import LoadSummary
from common_lore_index.storage.authority import AttemptNumber, OperationId
from common_lore_index.storage.backend_telemetry import BackendTelemetry
from common_lore_index.storage.publication import PortablePublicationBinding
from common_lore_index.storage.publication_phase_witness import (
    PublicationPhase, PublicationPhaseWitness,
)
from common_lore_index.ops.resolved_config import configured_repository_identity
from common_lore_index.ops._portable_retention import (
    PortableRefreshError,
    _annotate_retained_attempt as _annotate_retained_attempt,
    _mark_retained_terminal as _mark_retained_terminal,
    _prune_expired_terminal_attempts,
    _retained_result,
    _write_retained_result,
)
from common_lore_index.ops._portable_refresh_custody import close_validated, note_secondary, prepare_server_publication_root, settle_after_publisher_error
from common_lore_index.ops._portable_refresh_custody import remove_capture_attempt as _remove_attempt_root
from common_lore_index.ops._portable_capture_record import (
    PortableCapture as PortableCapture, PortableRefreshOutcome as PortableRefreshOutcome,
)
from common_lore_index.ops._portable_paths import (
    _attempt_root as _attempt_root, _private_directory as _private_directory,
    _publication_root as _publication_root, portable_attempts_parent as portable_attempts_parent,
)
from common_lore_index.storage.staging_observability import StagingMeasurements
from common_lore_index.storage._staged_ingestion_authority import IngestionAuthority, stage_id_for_authority


def run_staged_portable_refresh(*args: Any, **kwargs: Any) -> LoadSummary:
    """Forward to the PostgreSQL staged publisher, imported only when publishing.

    The deferred import keeps SQLite Local startup independent of the PostgreSQL
    driver; this module-level name stays the patch seam for the staged route.
    """
    from common_lore_index.storage.staged_ingestion import run_staged_portable_refresh as publish

    return publish(*args, **kwargs)


def execute_portable_refresh(
    config: OpsConfig,
    graph: OpsGraphConfig,
    database: str,
    *,
    authority: IngestionAuthority | None,
    backend_telemetry: BackendTelemetry | None = None,
    staging_measurements: StagingMeasurements | None = None,
    limits: object | None = None,
    postgres_route: PostgresRoute | None = None,
    resource_observer: ResourceObserver | None = None,
    publication_witness: PublicationPhaseWitness | None = None,
    sealing_budget: SealingBudget | None = None,
) -> PortableRefreshOutcome:
    """Seal, execute once, validate, and publish through one trusted adapter."""

    if publication_witness is None:
        publication_witness = PublicationPhaseWitness()
    execution_postgres = (postgres_route or effective_postgres_route(config)).apply(config.postgres)
    mark(resource_observer, "capture")
    capture = capture_portable_candidate(
        config, graph, authority=authority, limits=limits,
        **observer_kwargs(resource_observer), **governance_kwargs(sealing_budget),
    )
    end_stage(resource_observer, "capture")
    stage_id = stage_id_for_authority(capture.authority)
    mark(resource_observer, "validation")
    receipt, validated = validate_portable_capture(capture, stage_id=stage_id)
    primary: BaseException | None = None
    publisher_started = publisher_returned = False
    try:
        end_stage(resource_observer, "validation")
        note_validated(resource_observer, validated)
        binding = portable_publication_binding(capture, receipt, validated, stage_id=stage_id)
        publisher_started = True
        mark(resource_observer, "publication")
        publisher_kwargs = {
            "prepared_override": validated.to_prepared_stage_rows(),
            "repository_name": graph.repository_name,
            "root_path": f"graph:{graph.id}",
            "authority": capture.authority,
            "portable_binding": binding,
            "repository_identity": str(configured_repository_identity(graph.id)),
            "backend_telemetry": backend_telemetry,
            "staging_measurements": staging_measurements,
        }
        publisher_kwargs["publication_witness"] = publication_witness
        summary = run_staged_portable_refresh(
            execution_postgres.psql_args_for_database(database),
            validated,
            **publisher_kwargs,
        )
        publisher_returned = True
        publication_witness.advance(PublicationPhase.RETURNED)
        capture.mark_terminal(accepted=True)
        return PortableRefreshOutcome(
            summary, validated.family_counts["files"],
            validated.family_counts["raw_observations"],
        )
    except BaseException as error:
        primary = error
        if publisher_started:
            settle_after_publisher_error(
                capture,
                error,
                publication_witness=publication_witness,
                publisher_returned=publisher_returned,
            )
        raise
    finally:
        close_validated(validated, primary)


def capture_portable_candidate(
    config: GraphRegistryConfig,
    graph: OpsGraphConfig,
    *,
    authority: IngestionAuthority | None,
    limits: object | None = None,
    attempts_namespace: str | None = None,
    resource_observer: ResourceObserver | None = None,
    sealing_budget: SealingBudget | None = None,
) -> PortableCapture:
    """Seal the configured sources and run the database-independent worker once.

    ``attempts_namespace`` scopes the attempt directory (SQLite Local uses one
    per graph); ``None`` keeps the shared PostgreSQL-route layout. A budget or
    a v2 observer meters the parent sealing boundary (ADR 0173).
    """

    meter = start_sealing_meter(resource_observer, sealing_budget)

    operation_id = (
        authority.operation_id if authority is not None else OperationId(f"direct-{secrets.token_hex(16)}")
    )
    attempt = authority.attempt if authority is not None else AttemptNumber(1)
    attempt_root = _attempt_root(config, graph, operation_id, attempt, attempts_namespace)
    attempt_parent = attempt_root.parent
    if attempts_namespace is not None:
        # Every namespace level is owner-only, not just the leaf.
        publication_root = _publication_root(config)
        for level in reversed(attempt_parent.relative_to(publication_root).parents):
            _private_directory(publication_root / level)
    else:
        prepare_server_publication_root(attempt_parent.parent)
    _private_directory(attempt_parent)
    _prune_expired_terminal_attempts(attempt_parent, exclude=attempt_root)
    store_root = attempt_root / "objects"
    workspace_root = attempt_root / "workspace"
    _private_directory(attempt_root)
    _private_directory(workspace_root)
    store = FileSystemArtifactStore(store_root)
    extractor = extractor_generation(graph)
    canonicalizer = canonicalizer_generation()
    manifest, manifest_reference, candidate_id = seal_with_meter(
        resource_observer, meter,
        lambda **metered: seal_configured_sources(
            graph, store, extractor_generation=extractor,
            canonicalizer_generation=canonicalizer, **metered,
        ),
    )
    note_manifest(resource_observer, manifest)
    resolved_authority = authority or IngestionAuthority(
        operation_id=operation_id,
        attempt=attempt,
        execution_mode="direct",
        source_generation=manifest.source_generation,
        config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation,
        canonicalizer_generation=manifest.canonicalizer_generation,
    )
    if (
        resolved_authority.source_generation,
        resolved_authority.config_generation,
        resolved_authority.extractor_generation,
        resolved_authority.canonicalizer_generation,
    ) != (
        manifest.source_generation,
        manifest.config_generation,
        manifest.extractor_generation,
        manifest.canonicalizer_generation,
    ):
        raise PortableRefreshError("portable source authority changed")
    resolved_authority.validate()
    result_path = attempt_root / "portable-result.json"
    references = _retained_result(result_path, manifest.manifest_id)
    if references is None:
        capability = PortableExecutionCapability(
            schema_version=1,
            job_id=resolved_authority.job_id or resolved_authority.operation_id,
            attempt=resolved_authority.attempt,
            graph_id=graph.id,
            store_root=store_root.resolve(),
            workspace_root=workspace_root.resolve(),
            manifest_reference=manifest_reference,
            source_generation=manifest.source_generation,
            config_generation=manifest.config_generation,
            extractor_generation=manifest.extractor_generation,
            canonicalizer_generation=manifest.canonicalizer_generation,
            max_artifact_bytes=PORTABLE_MAX_ARTIFACT_BYTES,
            max_bundle_bytes=STREAMING_MAX_BUNDLE_BYTES,
        ).validate()
        capability_path = create_portable_capability(workspace_root, capability)
        leaf_limits = effective_leaf_limits(limits, authority)
        try:
            note_worker_launch(resource_observer, capability, leaf_limits)
            worker = run_portable_worker(
                capability_path,
                {"job_id": capability.job_id, "attempt": capability.attempt},
                leaf_limits, **usage_kwargs(resource_observer),
            )
            note_worker_usage(resource_observer, getattr(worker, "resource_usage", None))
            references = _worker_references(worker.terminal)
            _write_retained_result(result_path, manifest.manifest_id, references, manifest_reference=manifest_reference)
        except BaseException as error:
            try:
                _remove_attempt_root(attempt_root, _directory_identity(attempt_root))
            except BaseException as cleanup_error:
                note_secondary(error, cleanup_error)
            raise
    receipt_reference, bundle_reference = references
    return PortableCapture(
        graph=graph,
        store=store,
        manifest=manifest,
        candidate_id=candidate_id,
        authority=resolved_authority,
        result_path=result_path,
        workspace_root=workspace_root,
        receipt_reference=receipt_reference,
        bundle_reference=bundle_reference,
    )


def validate_portable_capture(
    capture: PortableCapture,
    *,
    stage_id: str,
) -> tuple[ExtractionReceipt, ValidatedBundleDescriptor]:
    """Validate the worker output in the parent; failures retire the attempt."""

    manifest = capture.manifest
    resolved_authority = capture.authority
    try:
        receipt = ExtractionReceipt.from_bytes(capture.store.read(capture.receipt_reference))
        job_or_op = resolved_authority.job_id or resolved_authority.operation_id
        expectation = PublicationExpectation(
            request_id=job_or_op, job_id=job_or_op, attempt=resolved_authority.attempt,
            graph_id=capture.graph.id, candidate_id=capture.candidate_id,
            snapshot_manifest_id=manifest.manifest_id, snapshot_vector=manifest.snapshot_vector,
            source_generation=manifest.source_generation, config_generation=manifest.config_generation,
            extractor_generation=manifest.extractor_generation,
            canonicalizer_generation=manifest.canonicalizer_generation,
            extractor_capability_identity=manifest.extractor_capability_identity,
            resolver_identity=manifest.resolver_identity,
            canonicalizer_identity=manifest.canonicalizer_identity,
            semantic_contract_identity=manifest.semantic_contract_identity,
            quality_rule_identity=manifest.quality_rule_identity,
            mutating_owner_count=1, worker_capability_identity=WORKER_CAPABILITY_IDENTITY,
            expected_privacy=manifest.effective_privacy.value,
        )
        validated = PublisherBundleValidator().validate_bundle_stream(
            store=capture.store, bundle_reference=capture.bundle_reference,
            receipt_reference=capture.receipt_reference,
            expectation=expectation, stage_id=stage_id, spool_dir=capture.workspace_root,
        )
    except (OSError, TypeError, ValueError):
        capture.mark_terminal(accepted=False)
        raise
    return receipt, validated


def portable_publication_binding(
    capture: PortableCapture,
    receipt: ExtractionReceipt,
    validated: ValidatedBundleDescriptor,
    *,
    stage_id: str,
) -> PortablePublicationBinding:
    """Build the complete portable evidence either publisher commits."""

    resolved_authority = capture.authority
    return PortablePublicationBinding(
        route="portable-worker-v1", snapshot_manifest_id=capture.manifest.manifest_id,
        snapshot_vector=capture.manifest.snapshot_vector, extraction_receipt_id=receipt.receipt_id,
        publication_bundle_id=validated.bundle_id, candidate_id=validated.candidate_id,
        resolver_identity=validated.resolver_identity,
        canonicalizer_identity=validated.canonicalizer_identity,
        semantic_contract_identity=validated.semantic_contract_identity,
        quality_rule_identity=validated.quality_rule_identity,
        protocol_version=receipt.contract_version,
        worker_capability_identity=receipt.worker_capability_identity, stage_id=stage_id,
        execution_mode=resolved_authority.execution_mode,
        singleton_fencing_epoch=resolved_authority.singleton_fencing_epoch,
        graph_lease_fencing_epoch=resolved_authority.graph_lease_fencing_epoch,
        family_receipts={
            item.family: {"count": item.record_count, "byte_length": item.byte_length, "digest": item.content_digest}
            for item in validated.family_summaries
        },
    ).validate()


__all__ = (
    "PortableCapture",
    "PortableRefreshError",
    "PortableRefreshOutcome",
    "capture_portable_candidate",
    "execute_portable_refresh",
    "portable_attempts_parent",
    "portable_publication_binding",
    "validate_portable_capture",
)
