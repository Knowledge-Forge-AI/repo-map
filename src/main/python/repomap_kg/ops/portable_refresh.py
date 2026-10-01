"""One production portable-worker route into the sole staged publisher."""

from __future__ import annotations

from repomap_kg.runtime.postgres_route import PostgresRoute, effective_postgres_route

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib, os, secrets, stat
from pathlib import Path
from typing import Any

from repomap_kg.artifacts import (
    ArtifactReference, FileSystemArtifactStore, PortableSnapshotManifest, PublicationExpectation,
    PublisherBundleValidator,
)
from repomap_kg.artifacts._bundle_stream_parse import ValidatedBundleDescriptor
from repomap_kg.artifacts.bundle import STREAMING_MAX_BUNDLE_BYTES
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.source_sealer import seal_configured_sources
from repomap_kg.coordinator._portable_capability import PortableExecutionCapability, create_portable_capability
from repomap_kg.coordinator._portable_worker_launch import run_portable_worker
from repomap_kg.coordinator._portable_materialization import _directory_identity, _remove_attempt_root
from repomap_kg.coordinator._portable_semantic_adapter import WORKER_CAPABILITY_IDENTITY
from repomap_kg.coordinator.limits import DEFAULT_LIMITS
from repomap_kg.ops.config_records import OpsConfig, OpsGraphConfig
from repomap_kg.ops.generations import canonicalizer_generation, extractor_generation
from repomap_kg.ops.graph_registry import GraphRegistryConfig
from repomap_kg.storage.main import LoadSummary
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.backend_telemetry import BackendTelemetry
from repomap_kg.storage.errors import StorageCommitUnknownError
from repomap_kg.storage.publication import PortablePublicationBinding
from repomap_kg.ops.resolved_config import configured_repository_identity
from repomap_kg.ops._portable_retention import (
    PortableRefreshError,
    _annotate_retained_attempt,
    _mark_retained_terminal,
    _prune_expired_terminal_attempts,
    _retained_result,
    _write_retained_result,
)
from repomap_kg.storage.staging_observability import StagingMeasurements
from repomap_kg.storage._staged_ingestion_authority import IngestionAuthority, stage_id_for_authority


def run_staged_portable_refresh(*args: Any, **kwargs: Any) -> LoadSummary:
    """Forward to the PostgreSQL staged publisher, imported only when publishing.

    The deferred import keeps SQLite Local startup independent of the PostgreSQL
    driver; this module-level name stays the patch seam for the staged route.
    """
    from repomap_kg.storage.staged_ingestion import run_staged_portable_refresh as publish

    return publish(*args, **kwargs)


@dataclass(frozen=True)
class PortableRefreshOutcome:
    summary: LoadSummary
    files: int
    observations: int




@dataclass(frozen=True)
class PortableCapture:
    """One sealed, executed portable candidate awaiting parent validation."""

    graph: OpsGraphConfig
    store: FileSystemArtifactStore
    manifest: PortableSnapshotManifest
    candidate_id: str
    authority: IngestionAuthority
    result_path: Path
    workspace_root: Path
    receipt_reference: ArtifactReference
    bundle_reference: ArtifactReference

    def mark_terminal(self, *, accepted: bool, sync_directory: bool = False) -> None:
        _mark_retained_terminal(
            self.result_path,
            "terminal-accepted" if accepted else "terminal-failed",
            sync_directory=sync_directory,
        )

    def annotate(
        self, key: str, value: Mapping[str, object], *, sync_directory: bool = False
    ) -> None:
        _annotate_retained_attempt(self.result_path, key, value, sync_directory=sync_directory)


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
) -> PortableRefreshOutcome:
    """Seal, execute once, validate, and publish through one trusted adapter."""

    execution_postgres = (postgres_route or effective_postgres_route(config)).apply(config.postgres)
    capture = capture_portable_candidate(config, graph, authority=authority, limits=limits)
    stage_id = stage_id_for_authority(capture.authority)
    receipt, validated = validate_portable_capture(capture, stage_id=stage_id)
    try:
        binding = portable_publication_binding(capture, receipt, validated, stage_id=stage_id)
        try:
            summary = run_staged_portable_refresh(
                execution_postgres.psql_args_for_database(database),
                validated,
                prepared_override=validated.to_prepared_stage_rows(),
                repository_name=graph.repository_name,
                root_path=f"graph:{graph.id}",
                authority=capture.authority,
                portable_binding=binding,
                repository_identity=str(configured_repository_identity(graph.id)),
                backend_telemetry=backend_telemetry,
                staging_measurements=staging_measurements,
            )
            capture.mark_terminal(accepted=True)
            return PortableRefreshOutcome(
                summary,
                validated.family_counts["files"],
                validated.family_counts["raw_observations"],
            )
        except BaseException as error:
            if not isinstance(error, StorageCommitUnknownError) and not getattr(error, "is_commit_unknown", False):
                capture.mark_terminal(accepted=False)
            raise
    except BaseException:
        validated.close()
        raise


def capture_portable_candidate(
    config: GraphRegistryConfig,
    graph: OpsGraphConfig,
    *,
    authority: IngestionAuthority | None,
    limits: object | None = None,
    attempts_namespace: str | None = None,
) -> PortableCapture:
    """Seal the configured sources and run the database-independent worker once.

    ``attempts_namespace`` scopes the attempt directory (SQLite Local uses one
    per graph); ``None`` keeps the shared PostgreSQL-route layout.
    """

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
    _private_directory(attempt_parent)
    _prune_expired_terminal_attempts(attempt_parent, exclude=attempt_root)
    store_root = attempt_root / "objects"
    workspace_root = attempt_root / "workspace"
    _private_directory(attempt_root)
    _private_directory(workspace_root)
    store = FileSystemArtifactStore(store_root)
    extractor = extractor_generation(graph)
    canonicalizer = canonicalizer_generation()
    manifest, manifest_reference, candidate_id = seal_configured_sources(
        graph,
        store,
        extractor_generation=extractor,
        canonicalizer_generation=canonicalizer,
    )
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
            max_artifact_bytes=4 * 1024 * 1024 * 1024,
            max_bundle_bytes=STREAMING_MAX_BUNDLE_BYTES,
        ).validate()
        capability_path = create_portable_capability(workspace_root, capability)
        leaf_limits = limits
        if leaf_limits is None:
            leaf_deadline = authority.process_deadline_seconds if authority is not None else None
            if leaf_deadline is not None:
                from dataclasses import replace
                leaf_limits = replace(DEFAULT_LIMITS, process_deadline_seconds=leaf_deadline)
            else:
                leaf_limits = DEFAULT_LIMITS
        try:
            worker = run_portable_worker(
                capability_path,
                {"job_id": capability.job_id, "attempt": capability.attempt},
                leaf_limits,
            )
            references = _worker_references(worker.terminal)
            _write_retained_result(result_path, manifest.manifest_id, references)
        except BaseException as error:
            try:
                _remove_attempt_root(attempt_root, _directory_identity(attempt_root))
            except BaseException as cleanup_error:
                error.add_note(
                    "portable attempt cleanup failure: "
                    f"{type(cleanup_error).__name__}"
                )
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


def _publication_root(config):
    control_root = Path(config.config_home or Path(config.config_path).resolve().parent)
    return (control_root / "state" / "portable-publication").resolve()


def portable_attempts_parent(config: GraphRegistryConfig, namespace: str | None = None) -> Path:
    """The directory holding one route's retained attempts; never created here."""
    root = _publication_root(config)
    return root / "attempts" if namespace is None else root / namespace / "attempts"


def _attempt_root(config, graph, operation_id, attempt, namespace=None):
    root = _publication_root(config)
    for binding in graph.effective_source_bindings:
        source = Path(binding.root_path_expanded).resolve()
        if root == source or root.is_relative_to(source):
            raise PortableRefreshError("portable artifact root overlaps source")
    token = hashlib.sha256(f"{operation_id}\0{attempt}".encode()).hexdigest()
    return portable_attempts_parent(config, namespace) / token


def _private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid():
            raise PortableRefreshError("portable control directory is not private")
        os.fchmod(descriptor, 0o700)
    finally:
        os.close(descriptor)


def _worker_references(terminal):
    extension = terminal.get("portable_snapshot")
    if terminal.get("status") != "succeeded" or not isinstance(extension, dict):
        from repomap_kg.coordinator._protocol_validation import _ERROR_CATEGORIES

        raw = terminal.get("error_category")
        category = raw if isinstance(raw, str) and raw in _ERROR_CATEGORIES else "worker_crash"
        # Preserve deterministic refusals. Other classes retain the previous
        # retry policy until independently qualified; no diagnostic parsing.
        if category not in {"contract_validation", "unsupported_contract", "unsupported_capability"}:
            category = "worker_crash"
        reason = terminal.get("reason")
        if reason in {"process_timeout", "heartbeat_timeout"}:
            category = "worker_timeout"
        elif reason == "protocol":
            category = "protocol"
        raise PortableRefreshError(
            f"portable worker did not complete ({category})", category=category
        )
    try:
        return (
            ArtifactReference.from_mapping(extension["receipt"]),
            ArtifactReference.from_mapping(extension["bundle"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PortableRefreshError("portable worker result is malformed") from error


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
