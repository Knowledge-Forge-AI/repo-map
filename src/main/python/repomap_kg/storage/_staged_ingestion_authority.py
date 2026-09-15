"""Direct and asynchronous ingestion authority records and factories."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets

from repomap_kg.storage.authority import (
    AttemptNumber,
    JobId,
    OperationId,
    StageId,
)
from repomap_kg.storage.publication import (
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage.staging_ownership import StageOwner

__all__ = (
    "IngestionAuthority",
    "new_direct_authority",
    "stage_id_for_authority",
)


@dataclass(frozen=True)
class IngestionAuthority:
    """Existing direct or ASYNC claim values carried into graph storage."""

    operation_id: OperationId
    attempt: AttemptNumber
    execution_mode: str
    source_generation: str
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str
    job_id: JobId | None = None
    coordinator_instance_id: str | None = None
    singleton_fencing_epoch: int = 0
    graph_lease_fencing_epoch: int = 0

    def owner(self, repository_id: int) -> StageOwner:
        """Return the validated stage owner for one graph repository."""

        owner = StageOwner(
            repository_id=repository_id,
            operation_id=self.operation_id,
            attempt=self.attempt,
            execution_mode=self.execution_mode,
            source_generation=self.source_generation,
            config_generation=self.config_generation,
            extractor_generation=self.extractor_generation,
            canonicalizer_generation=self.canonicalizer_generation,
            job_id=self.job_id,
            coordinator_instance_id=self.coordinator_instance_id,
            singleton_fencing_epoch=self.singleton_fencing_epoch,
            graph_lease_fencing_epoch=self.graph_lease_fencing_epoch,
        )
        return owner.validate()

    def receipt(self) -> RunPublicationReceipt:
        """Return the compatible receipt identity for this operation."""

        identity = self.job_id or self.operation_id
        return RunPublicationReceipt(
            attempt=RunPublicationAttempt(JobId(identity), self.attempt),
            generations=RunPublicationGenerations(
                self.source_generation,
                self.config_generation,
                self.extractor_generation,
                self.canonicalizer_generation,
            ),
        ).validate()

    def validate(self) -> "IngestionAuthority":
        """Reject fabricated coordinator fields and invalid direct ownership."""

        self.owner(1)
        self.receipt()
        return self


def stage_id_for_authority(authority: IngestionAuthority) -> StageId:
    """Derive a retry-stable stage identifier without exposing source data."""

    authority.validate()
    digest = hashlib.sha256(
        f"{authority.operation_id}:{authority.attempt}".encode("utf-8")
    ).hexdigest()
    return StageId(f"stage-{digest[:48]}")


def new_direct_authority(
    *,
    source_generation: str,
    config_generation: str,
    extractor_generation: str,
    canonicalizer_generation: str,
) -> IngestionAuthority:
    """Create one explicit local operation identity without a coordinator job."""

    return IngestionAuthority(
        operation_id=OperationId(f"direct-{secrets.token_hex(16)}"),
        attempt=AttemptNumber(1),
        execution_mode="direct",
        source_generation=source_generation,
        config_generation=config_generation,
        extractor_generation=extractor_generation,
        canonicalizer_generation=canonicalizer_generation,
    ).validate()
