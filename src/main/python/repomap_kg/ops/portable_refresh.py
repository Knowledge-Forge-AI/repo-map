"""One production portable-worker route into the sole staged publisher."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib, json, os, re, secrets, stat, time
from pathlib import Path

from repomap_kg.artifacts import (
    ArtifactReference,
    FileSystemArtifactStore,
    PublicationExpectation,
    PublisherBundleValidator,
)
from repomap_kg.artifacts.bundle import PublicationBundle
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.source_sealer import seal_configured_sources
from repomap_kg.coordinator._portable_capability import (
    PortableExecutionCapability,
    create_portable_capability,
)
from repomap_kg.coordinator._portable_worker_launch import run_portable_worker
from repomap_kg.coordinator._portable_materialization import (
    _directory_identity,
    _remove_attempt_root,
)
from repomap_kg.coordinator._portable_semantic_adapter import WORKER_CAPABILITY_IDENTITY
from repomap_kg.coordinator.limits import DEFAULT_LIMITS
from repomap_kg.ops.config_records import OpsConfig, OpsGraphConfig
from repomap_kg.ops.generations import canonicalizer_generation, extractor_generation
from repomap_kg.storage.main import LoadSummary
from repomap_kg.storage.authority import AttemptNumber, OperationId
from repomap_kg.storage.backend_telemetry import BackendTelemetry
from repomap_kg.storage.errors import StorageCommitUnknownError, StorageSchemaError
from repomap_kg.storage.publication import PortablePublicationBinding
from repomap_kg.ops.resolved_config import configured_repository_identity
from repomap_kg.storage.staging_observability import StagingMeasurements
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    run_staged_portable_refresh,
    stage_id_for_authority,
)


@dataclass(frozen=True)
class PortableRefreshOutcome:
    summary: LoadSummary
    files: int
    observations: int


class PortableRefreshError(ValueError):
    """Bounded production-route failure that grants no fallback authority."""


_TERMINAL_RETENTION_SECONDS = 24 * 60 * 60
_TERMINAL_RETENTION_CLASSES = frozenset({"terminal-accepted", "terminal-failed"})


def execute_portable_refresh(
    config: OpsConfig,
    graph: OpsGraphConfig,
    database: str,
    *,
    authority: IngestionAuthority | None,
    backend_telemetry: BackendTelemetry | None = None,
    staging_measurements: StagingMeasurements | None = None,
) -> PortableRefreshOutcome:
    """Seal, execute once, validate, and publish through one trusted adapter."""

    operation_id = (
        authority.operation_id
        if authority is not None
        else OperationId(f"direct-{secrets.token_hex(16)}")
    )
    attempt = authority.attempt if authority is not None else AttemptNumber(1)
    attempt_root = _attempt_root(config, graph, operation_id, attempt)
    attempt_parent = attempt_root.parent
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
            max_bundle_bytes=4 * 1024 * 1024 * 1024,
        ).validate()
        capability_path = create_portable_capability(workspace_root, capability)
        try:
            worker = run_portable_worker(
                capability_path,
                {"job_id": capability.job_id, "attempt": capability.attempt},
                DEFAULT_LIMITS,
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
    try:
        bundle = PublicationBundle.from_bytes(store.read(bundle_reference))
        receipt = ExtractionReceipt.from_bytes(store.read(receipt_reference))
        expectation = PublicationExpectation(
            request_id=resolved_authority.job_id or resolved_authority.operation_id,
            job_id=resolved_authority.job_id or resolved_authority.operation_id,
            attempt=resolved_authority.attempt,
            graph_id=graph.id,
            candidate_id=candidate_id,
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
        PublisherBundleValidator().validate_bundle(
            store=store,
            bundle_reference=bundle_reference,
            receipt_reference=receipt_reference,
            expectation=expectation,
        )
    except (OSError, TypeError, ValueError):
        _mark_retained_terminal(result_path, "terminal-failed")
        raise
    stage_id = stage_id_for_authority(resolved_authority)
    binding = PortablePublicationBinding(
        route="portable-worker-v1",
        snapshot_manifest_id=manifest.manifest_id,
        snapshot_vector=manifest.snapshot_vector,
        extraction_receipt_id=receipt.receipt_id,
        publication_bundle_id=bundle.bundle_id,
        candidate_id=bundle.candidate_id,
        resolver_identity=bundle.resolver_identity,
        canonicalizer_identity=bundle.canonicalizer_identity,
        semantic_contract_identity=bundle.semantic_contract_identity,
        quality_rule_identity=bundle.quality_rule_identity,
        protocol_version=receipt.contract_version,
        worker_capability_identity=receipt.worker_capability_identity,
        stage_id=stage_id,
        execution_mode=resolved_authority.execution_mode,
        singleton_fencing_epoch=resolved_authority.singleton_fencing_epoch,
        graph_lease_fencing_epoch=resolved_authority.graph_lease_fencing_epoch,
        family_receipts={item.family: {"count": item.record_count, "byte_length": item.byte_length, "digest": item.content_digest} for item in bundle.family_summaries},
    ).validate()
    try:
        summary = run_staged_portable_refresh(
            config.postgres.psql_args_for_database(database),
            bundle,
            repository_name=graph.repository_name,
            root_path=f"graph:{graph.id}",
            authority=resolved_authority,
            portable_binding=binding,
            repository_identity=str(configured_repository_identity(graph.id)),
            backend_telemetry=backend_telemetry,
            staging_measurements=staging_measurements,
        )
        _mark_retained_terminal(result_path, "terminal-accepted")
        return PortableRefreshOutcome(
            summary,
            bundle.family_counts["files"],
            bundle.family_counts["raw_observations"],
        )
    except (StorageCommitUnknownError, StorageSchemaError) as error:
        if isinstance(error, StorageCommitUnknownError) or getattr(error, "is_commit_unknown", False):
            raise
        _mark_retained_terminal(result_path, "terminal-failed")
        raise
    except BaseException:
        _mark_retained_terminal(result_path, "terminal-failed")
        raise


def _attempt_root(config, graph, operation_id, attempt):
    control_root = Path(config.config_home or Path(config.config_path).resolve().parent)
    root = (control_root / "state" / "portable-publication").resolve()
    for binding in graph.effective_source_bindings:
        source = Path(binding.root_path_expanded).resolve()
        if root == source or root.is_relative_to(source):
            raise PortableRefreshError("portable artifact root overlaps source")
    token = hashlib.sha256(f"{operation_id}\0{attempt}".encode()).hexdigest()
    return root / "attempts" / token


def _private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
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
        raw = terminal.get("error_category") or terminal.get("reason")
        clean = re.sub(r"/(?:[a-zA-Z0-9_.-]+/)*[a-zA-Z0-9_.-]+", "[path]", str(raw).strip())[:256] if raw else ""
        raise PortableRefreshError(f"portable worker did not complete ({clean})" if clean else "portable worker did not complete")
    try:
        return (
            ArtifactReference.from_mapping(extension["receipt"]),
            ArtifactReference.from_mapping(extension["bundle"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PortableRefreshError("portable worker result is malformed") from error


def _write_retained_result(path, manifest_id, references):
    payload = {
        "manifest_id": manifest_id,
        "receipt": references[0].to_mapping(),
        "bundle": references[1].to_mapping(),
        "retention_class": "publication-reconciliation",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("portable retention write failed")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _retained_result(path, expected_manifest_id):
    if not path.exists():
        return None
    try:
        payload = _read_retention_payload(path)
        if payload.get("manifest_id") != expected_manifest_id:
            raise ValueError
        if payload.get("retention_class") not in {
            "publication-reconciliation",
            *_TERMINAL_RETENTION_CLASSES,
        }:
            raise ValueError
        receipt_mapping = payload.get("receipt")
        bundle_mapping = payload.get("bundle")
        if not isinstance(receipt_mapping, Mapping) or not isinstance(
            bundle_mapping, Mapping
        ):
            raise ValueError
        return (
            ArtifactReference.from_mapping(receipt_mapping),
            ArtifactReference.from_mapping(bundle_mapping),
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise PortableRefreshError("retained portable result is invalid") from error


def _read_retention_payload(path: Path) -> dict[str, object]:
    expected = path.lstat()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        details = os.fstat(descriptor)
        if (
            (expected.st_dev, expected.st_ino) != (details.st_dev, details.st_ino)
            or not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_size > 64 * 1024
        ):
            raise ValueError
        chunks: list[bytes] = []
        remaining = details.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                raise ValueError
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        os.close(descriptor)
    payload = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError
    return payload


def _mark_retained_terminal(path: Path, retention_class: str) -> None:
    if retention_class not in _TERMINAL_RETENTION_CLASSES:
        raise ValueError("invalid portable retention class")
    payload = _read_retention_payload(path)
    payload["retention_class"] = retention_class
    payload["expires_at_epoch"] = int(time.time()) + _TERMINAL_RETENTION_SECONDS
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("portable retention update failed")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _prune_expired_terminal_attempts(parent: Path, *, exclude: Path) -> None:
    for candidate in parent.iterdir():
        if candidate == exclude:
            continue
        try:
            identity = _directory_identity(candidate)
            payload = _read_retention_payload(candidate / "portable-result.json")
            retention_class = payload.get("retention_class")
            expires_at = payload.get("expires_at_epoch")
            if (
                retention_class in _TERMINAL_RETENTION_CLASSES
                and isinstance(expires_at, int)
                and not isinstance(expires_at, bool)
                and expires_at <= int(time.time())
            ):
                _remove_attempt_root(candidate, identity)
        except (FileNotFoundError, OSError, TypeError, ValueError, RuntimeError):
            continue


__all__ = ("PortableRefreshError", "PortableRefreshOutcome", "execute_portable_refresh")
