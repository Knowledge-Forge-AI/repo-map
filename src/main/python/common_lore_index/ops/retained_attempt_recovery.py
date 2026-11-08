"""Explicit positive reconciliation of one retained Server attempt."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import time
from typing import Literal

from common_lore_index.artifacts import FileSystemArtifactStore
from common_lore_index.artifacts._store_common import ArtifactIntegrityError
from common_lore_index.ops.config_records import OpsConfig, OpsGraphConfig
from common_lore_index.ops._retained_attempt_artifacts import (
    RetainedArtifactError,
    RetainedArtifactProof,
    read_retained_artifacts,
)
from common_lore_index.ops._retained_attempt_proof import (
    portable_stage_id,
    publication_proof_matches,
)
from common_lore_index.ops._retained_attempt_record import (
    MetadataInstallError,
    RECONCILIATION,
    TERMINAL_ACCEPTED,
    TERMINAL_FAILED,
    RetainedRecordError,
    install_terminal_accepted,
    read_retained_record,
    resync_retained_record,
    same_record,
)
from common_lore_index.ops._server_retention_lock import (
    RetentionLockBusy,
    RetentionLockError,
    ServerRetentionLock,
)
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.authority import AttemptNumber, JobId
from common_lore_index.storage.publication import RunPublicationAttempt

_GRAPH_ID = re.compile(r"[a-z][a-z0-9-]{0,127}\Z")
RecoveryOperation = Literal["inspect", "settle"]
_READY = frozenset({"ready", "settled", "already-settled"})


@dataclass(frozen=True)
class RetainedAttemptRecovery:
    operation: RecoveryOperation
    result: str
    reason: str
    retention_state: str
    artifact_proof: str
    publication_proof: str
    metadata_write_state: str

    @property
    def exit_code(self) -> int:
        return 0 if self.result in _READY else 1

    def to_jsonable(self) -> dict[str, str]:
        return {
            "operation": self.operation,
            "result": self.result,
            "reason": self.reason,
            "retention_state": self.retention_state,
            "artifact_proof": self.artifact_proof,
            "publication_proof": self.publication_proof,
            "metadata_write_state": self.metadata_write_state,
        }


def _outcome(operation: RecoveryOperation, result: str, reason: str, *, retention: str = "unavailable", artifact: str = "not-checked", publication: str = "not-checked", metadata: str = "not-attempted") -> RetainedAttemptRecovery:
    return RetainedAttemptRecovery(operation, result, reason, retention, artifact, publication, metadata)


def _find_graph(config: OpsConfig, graph_id: str) -> OpsGraphConfig | None:
    return next((graph for graph in config.graphs if graph.id == graph_id), None)


def _attempt_root(config: OpsConfig, operation_id: str, attempt: int) -> Path:
    from common_lore_index.ops.portable_refresh import portable_attempts_parent

    token = hashlib.sha256(f"{operation_id}\0{attempt}".encode("utf-8")).hexdigest()
    return portable_attempts_parent(config) / token


def _proof(
    config: OpsConfig,
    graph: OpsGraphConfig,
    artifacts: RetainedArtifactProof,
    operation_id: str,
    attempt: int,
    psql_command: str | None,
) -> bool:
    from common_lore_index.ops.config import graph_database
    from common_lore_index.ops.resolved_config import configured_repository_identity
    from common_lore_index.storage.retained_publication_readback import (
        read_retained_publication,
    )

    job_id = artifacts.receipt.job_id
    publication = read_retained_publication(
        config,
        database=graph_database(config, graph),
        repository_identity=str(configured_repository_identity(graph.id)),
        job_id=job_id,
        attempt=attempt,
        portable_stage_id=portable_stage_id(operation_id, attempt),
        psql_command=psql_command,
    )
    return publication is not None and publication_proof_matches(
        artifacts, publication, stage_id=portable_stage_id(operation_id, attempt)
    )


def recover_server_retained_attempt(
    config: OpsConfig,
    graph_id: str,
    operation_id: str,
    attempt: int,
    *,
    settle: bool = False,
    psql_command: str | None = None,
) -> RetainedAttemptRecovery:
    """Inspect or explicitly settle exactly one existing Server attempt."""
    operation: RecoveryOperation = "settle" if settle else "inspect"
    if not isinstance(graph_id, str) or _GRAPH_ID.fullmatch(graph_id) is None:
        return _outcome(operation, "refused", "invalid-identity")
    if not isinstance(operation_id, str) or not operation_id or type(attempt) is not int or attempt <= 0:
        return _outcome(operation, "refused", "invalid-identity")
    try:
        RunPublicationAttempt(JobId(operation_id), AttemptNumber(attempt)).validate()
    except ValueError:
        return _outcome(operation, "refused", "invalid-identity")
    graph = _find_graph(config, graph_id)
    if graph is None:
        return _outcome(operation, "refused", "graph-unknown")
    if not graph.enabled:
        return _outcome(operation, "refused", "graph-disabled")
    if graph.readback_unsupported_classification is not None:
        return _outcome(operation, "refused", "graph-readback-unsupported")
    try:
        root = _attempt_root(config, operation_id, attempt)
    except (OSError, ValueError):
        return _outcome(operation, "held", "namespace-unavailable")
    try:
        record = read_retained_record(root)
    except RetainedRecordError as error:
        return _outcome(operation, "held", error.reason)
    except OSError:
        return _outcome(operation, "held", "record-unavailable")
    if record.retention_class == TERMINAL_FAILED:
        return _outcome(operation, "held", "terminal-failed", retention=TERMINAL_FAILED)
    try:
        store = FileSystemArtifactStore(root / "objects", create=False)
        artifacts = read_retained_artifacts(record, store)
    except (ArtifactIntegrityError, RetainedArtifactError, OSError, ValueError):
        return _outcome(operation, "held", "artifact-invalid", retention=record.retention_class, artifact="invalid")
    if (
        artifacts.receipt.graph_id != graph.id
        or artifacts.receipt.attempt != attempt
        or artifacts.receipt.job_id != operation_id
    ):
        return _outcome(operation, "held", "publication-mismatch", retention=record.retention_class, artifact="matched", publication="invalid")
    try:
        matched = _proof(config, graph, artifacts, operation_id, attempt, psql_command)
    except (StorageSchemaError, OSError, ValueError):
        return _outcome(operation, "held", "proof-unavailable", retention=record.retention_class, artifact="matched", publication="unavailable")
    if not matched:
        return _outcome(operation, "held", "publication-mismatch", retention=record.retention_class, artifact="matched", publication="invalid")
    if not settle:
        return _outcome(operation, "ready", "accepted-proof", retention=record.retention_class, artifact="matched", publication="matched")
    installed = False
    try:
        with ServerRetentionLock(root.parent):
            current = read_retained_record(root)
            if not same_record(record, current):
                return _outcome(operation, "held", "metadata-race", retention=current.retention_class, artifact="matched", publication="matched")
            if current.retention_class == TERMINAL_ACCEPTED:
                installed = True
                try:
                    resync_retained_record(current)
                except OSError:
                    return _outcome(operation, "uncertain", "metadata-durability-uncertain", retention=TERMINAL_ACCEPTED, artifact="matched", publication="matched", metadata="uncertain")
                return _outcome(operation, "already-settled", "already-terminal-accepted", retention=TERMINAL_ACCEPTED, artifact="matched", publication="matched", metadata="installed")
            if current.retention_class != RECONCILIATION:
                return _outcome(operation, "held", "retention-state-invalid", retention=current.retention_class, artifact="matched", publication="matched")
            install_terminal_accepted(current, now=int(time.time()))
            installed = True
    except RetentionLockBusy:
        return _outcome(operation, "held", "lock-busy", retention=record.retention_class, artifact="matched", publication="matched")
    except MetadataInstallError as error:
        if error.post_install:
            return _outcome(operation, "uncertain", "metadata-durability-uncertain", retention=TERMINAL_ACCEPTED, artifact="matched", publication="matched", metadata="uncertain")
        return _outcome(operation, "held", "metadata-write-failed", retention=record.retention_class, artifact="matched", publication="matched")
    except (RetentionLockError, RetainedRecordError, OSError):
        if installed:
            return _outcome(operation, "uncertain", "metadata-durability-uncertain", retention=TERMINAL_ACCEPTED, artifact="matched", publication="matched", metadata="uncertain")
        return _outcome(operation, "held", "metadata-write-failed", retention=record.retention_class, artifact="matched", publication="matched")
    return _outcome(operation, "settled", "accepted-proof", retention=TERMINAL_ACCEPTED, artifact="matched", publication="matched", metadata="installed")


__all__ = ("RetainedAttemptRecovery", "recover_server_retained_attempt")
