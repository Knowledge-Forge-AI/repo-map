"""Pure publication test fixtures and deterministic database seed generators."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence

from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.publication import (
    PortablePublicationBinding,
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_fencing import PublicationHandoff
from repomap_kg.storage.sql_core import sql_literal
from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.staging_ownership import StageOwner


def json_row_counts(*, files: int = 0) -> str:
    """Return JSON string of expected/observed row counts for all 7 families."""
    values = {family: 0 for family in STAGING_FAMILY_DESCRIPTORS}
    values["files"] = files
    return json.dumps(values, separators=(",", ":"))


def json_checksums() -> str:
    """Return JSON string of zeroed family checksums for all 7 families."""
    digest = "0" * 64
    item = {
        "row_count": 0,
        "normalized_byte_count": 0,
        "stable_key_digest": digest,
        "payload_digest": digest,
    }
    values = {family: item for family in STAGING_FAMILY_DESCRIPTORS}
    return json.dumps(values, separators=(",", ":"))


def json_family_manifest() -> str:
    """Return JSON string of the expected family manifest."""
    return json.dumps(
        {"schema_version": 1, "families": list(STAGING_FAMILY_DESCRIPTORS)},
        separators=(",", ":"),
    )


@dataclass(frozen=True, slots=True)
class PublicationFixture:
    """Deterministic authority, receipt, handoff, and seed SQL generator."""

    stage_id: str
    job_id: str = "job-scale5"
    attempt: int = 1
    run_id: int = 1
    repository_id: int = 1
    singleton_epoch: int = 9
    graph_fence_epoch: int = 9
    execution_mode: str = "coordinator"
    coordinator_instance_id: str | None = None
    source_generation: str | None = None
    config_generation: str | None = None
    extractor_generation: str | None = None
    canonicalizer_generation: str | None = None
    portable_binding: PortablePublicationBinding | None = None

    def __post_init__(self) -> None:
        if self.portable_binding is not None:
            if (
                self.portable_binding.stage_id != self.stage_id
                or self.portable_binding.execution_mode != self.execution_mode
                or self.portable_binding.singleton_fencing_epoch != self.singleton_epoch
                or self.portable_binding.graph_lease_fencing_epoch != self.graph_fence_epoch
            ):
                raise ValueError(
                    f"PortablePublicationBinding identity does not match PublicationFixture: "
                    f"stage_id={self.portable_binding.stage_id} vs {self.stage_id}, "
                    f"execution_mode={self.portable_binding.execution_mode} vs {self.execution_mode}, "
                    f"epochs=({self.portable_binding.singleton_fencing_epoch}, {self.portable_binding.graph_lease_fencing_epoch}) "
                    f"vs ({self.singleton_epoch}, {self.graph_fence_epoch})"
                )

    @property
    def resolved_coordinator_instance_id(self) -> str:
        return self.coordinator_instance_id or f"coord-{self.job_id}"

    @property
    def resolved_source_generation(self) -> str:
        return self.source_generation or f"sg1:{self.job_id}"

    @property
    def resolved_config_generation(self) -> str:
        return self.config_generation or f"cg1:{self.job_id}"

    @property
    def resolved_extractor_generation(self) -> str:
        return self.extractor_generation or f"eg1:{self.job_id}"

    @property
    def resolved_canonicalizer_generation(self) -> str:
        return self.canonicalizer_generation or f"kg1:{self.job_id}"

    @property
    def owner(self) -> StageOwner:
        return StageOwner(
            repository_id=self.repository_id,
            operation_id=OperationId(self.job_id),
            attempt=AttemptNumber(self.attempt),
            execution_mode=self.execution_mode,
            source_generation=self.resolved_source_generation,
            config_generation=self.resolved_config_generation,
            extractor_generation=self.resolved_extractor_generation,
            canonicalizer_generation=self.resolved_canonicalizer_generation,
            job_id=JobId(self.job_id) if self.job_id is not None else None,
            coordinator_instance_id=self.resolved_coordinator_instance_id,
            singleton_fencing_epoch=self.singleton_epoch,
            graph_lease_fencing_epoch=self.graph_fence_epoch,
        )

    @property
    def generations(self) -> RunPublicationGenerations:
        return RunPublicationGenerations(
            self.resolved_source_generation,
            self.resolved_config_generation,
            self.resolved_extractor_generation,
            self.resolved_canonicalizer_generation,
        )

    @property
    def receipt(self) -> RunPublicationReceipt:
        return RunPublicationReceipt(
            RunPublicationAttempt(JobId(self.job_id), AttemptNumber(self.attempt)),
            self.generations,
            self.portable_binding,
        )

    @property
    def handoff(self) -> PublicationHandoff:
        return PublicationHandoff(
            MergeContext(self.stage_id, self.owner, self.run_id),
            self.receipt,
        ).validate()

    def create_portable_binding(
        self,
        *,
        route: str = "portable-worker-v1",
        snapshot_manifest_id: str | None = None,
        snapshot_vector: Sequence[tuple[str, int, str]] | None = None,
        extraction_receipt_id: str | None = None,
        publication_bundle_id: str | None = None,
        candidate_id: str | None = None,
        resolver_identity: str = "resolver1:nix-static-v2",
        canonicalizer_identity: str = "canon1:graph-key-v1-binding-path",
        semantic_contract_identity: str = "semantic1:multi-source-v1",
        quality_rule_identity: str = "quality1:default",
        protocol_version: str = "1.0",
        worker_capability_identity: str = "cap1:portable-python-worker-v1",
        family_receipts: Mapping[str, Mapping[str, object]] | None = None,
    ) -> PortablePublicationBinding:
        """Create a validated PortablePublicationBinding synchronized with this fixture."""
        fam_receipts = family_receipts or {
            family: {"count": 0, "byte_length": 0, "digest": "sha256:" + "0" * 64}
            for family in STAGING_FAMILY_DESCRIPTORS
        }
        return PortablePublicationBinding(
            route=route,
            snapshot_manifest_id=snapshot_manifest_id or ("snapmanifest1:" + "1" * 64),
            snapshot_vector=tuple(snapshot_vector)
            if snapshot_vector
            else (("bind1:" + "2" * 64, 1, "snap1:" + "3" * 64),),
            extraction_receipt_id=extraction_receipt_id or ("receipt1:" + "4" * 64),
            publication_bundle_id=publication_bundle_id or ("bundle1:" + "5" * 64),
            candidate_id=candidate_id or ("cand1:" + "6" * 64),
            resolver_identity=resolver_identity,
            canonicalizer_identity=canonicalizer_identity,
            semantic_contract_identity=semantic_contract_identity,
            quality_rule_identity=quality_rule_identity,
            protocol_version=protocol_version,
            worker_capability_identity=worker_capability_identity,
            stage_id=self.stage_id,
            execution_mode=self.execution_mode,
            singleton_fencing_epoch=self.singleton_epoch,
            graph_lease_fencing_epoch=self.graph_fence_epoch,
            family_receipts=fam_receipts,
        ).validate()

    def repository_seed_sql(
        self, *, name: str = "fixture", root_path: str = "fixture-root"
    ) -> str:
        return (
            f"INSERT INTO repositories (id, name, root_path)\n"
            f"VALUES ({self.repository_id}, {sql_literal(name)}, {sql_literal(root_path)})\n"
            f"ON CONFLICT (id) DO NOTHING;\n"
        )

    def stage_seed_sql(
        self,
        *,
        files: int = 0,
        state: str = "validated",
        validation_status: str = "passed",
        merge_status: str | None = None,
        publication_reconciliation_state: str | None = None,
        cleanup_eligibility: str = "blocked",
    ) -> str:
        owner = self.owner
        counts = json_row_counts(files=files)
        checksums = json_checksums()
        manifest = json_family_manifest()
        cols = [
            "stage_id",
            "repository_id",
            "operation_id",
            "job_id",
            "attempt",
            "execution_mode",
            "coordinator_instance_id",
            "singleton_fencing_epoch",
            "graph_lease_fencing_epoch",
            "source_generation",
            "config_generation",
            "extractor_generation",
            "canonicalizer_generation",
            "state",
            "expires_at",
            "expected_row_counts",
            "observed_row_counts",
            "family_checksums",
            "normalized_byte_counts",
            "expected_family_manifest",
            "validation_status",
            "cleanup_eligibility",
        ]
        vals = [
            sql_literal(self.stage_id),
            str(self.repository_id),
            sql_literal(owner.operation_id),
            sql_literal(owner.job_id),
            str(owner.attempt),
            sql_literal(owner.execution_mode),
            sql_literal(owner.coordinator_instance_id),
            str(owner.singleton_fencing_epoch),
            str(owner.graph_lease_fencing_epoch),
            sql_literal(owner.source_generation),
            sql_literal(owner.config_generation),
            sql_literal(owner.extractor_generation),
            sql_literal(owner.canonicalizer_generation),
            sql_literal(state),
            "now() + interval '1 hour'",
            f"{sql_literal(counts)}::jsonb",
            f"{sql_literal(counts)}::jsonb",
            f"{sql_literal(checksums)}::jsonb",
            f"{sql_literal(counts)}::jsonb",
            f"{sql_literal(manifest)}::jsonb",
            sql_literal(validation_status),
            sql_literal(cleanup_eligibility),
        ]
        if merge_status is not None:
            cols.append("merge_status")
            vals.append(sql_literal(merge_status))
        if publication_reconciliation_state is not None:
            cols.append("publication_reconciliation_state")
            vals.append(sql_literal(publication_reconciliation_state))
        return (
            f"INSERT INTO ingestion_stages ({', '.join(cols)})\n"
            f"VALUES ({', '.join(vals)});\n"
        )

    def run_seed_sql(
        self,
        *,
        status: str = "running",
        with_receipt: bool = False,
    ) -> str:
        if not with_receipt:
            return (
                f"INSERT INTO runs (id, repository_id, status)\n"
                f"VALUES ({self.run_id}, {self.repository_id}, {sql_literal(status)});\n"
            )
        cols = [
            "id",
            "repository_id",
            "status",
            "publication_job_id",
            "publication_attempt",
            "source_generation",
            "config_generation",
            "extractor_generation",
            "canonicalizer_generation",
        ]
        vals = [
            str(self.run_id),
            str(self.repository_id),
            sql_literal(status),
            sql_literal(self.job_id),
            str(self.attempt),
            sql_literal(self.resolved_source_generation),
            sql_literal(self.resolved_config_generation),
            sql_literal(self.resolved_extractor_generation),
            sql_literal(self.resolved_canonicalizer_generation),
        ]
        if self.portable_binding is not None:
            mapping = self.portable_binding.to_mapping()
            for key, val in mapping.items():
                cols.append(key)
                vals.append(str(val) if isinstance(val, int) else sql_literal(val))
        return (
            f"INSERT INTO runs ({', '.join(cols)})\n"
            f"VALUES ({', '.join(vals)});\n"
        )

    def stage_files_seed_sql(self, *, path: str = "file1.py") -> str:
        return (
            f"INSERT INTO stage_files (\n"
            f"    stage_id, family_ordinal, path, language, role, confidence,\n"
            f"    content_hash, executable, generated, metadata_json\n"
            f")\n"
            f"VALUES (\n"
            f"    {sql_literal(self.stage_id)}, 0, {sql_literal(path)}, 'python', 'source', 'extracted',\n"
            f"    NULL, false, false, '{{}}'::jsonb\n"
            f");\n"
        )

    def authority_seed_sql(self) -> str:
        owner = self.owner
        cols = [
            "repository_id",
            "singleton_fencing_epoch",
            "graph_lease_fencing_epoch",
            "job_id",
            "attempt",
            "coordinator_instance_id",
            "source_generation",
            "config_generation",
            "extractor_generation",
            "canonicalizer_generation",
            "last_stage_id",
            "last_run_id",
            "updated_at",
        ]
        vals = [
            str(self.repository_id),
            str(owner.singleton_fencing_epoch),
            str(owner.graph_lease_fencing_epoch),
            sql_literal(owner.job_id),
            str(owner.attempt),
            sql_literal(owner.coordinator_instance_id),
            sql_literal(owner.source_generation),
            sql_literal(owner.config_generation),
            sql_literal(owner.extractor_generation),
            sql_literal(owner.canonicalizer_generation),
            sql_literal(self.stage_id),
            str(self.run_id),
            "now()",
        ]
        return (
            f"INSERT INTO graph_publication_authority ({', '.join(cols)})\n"
            f"VALUES ({', '.join(vals)});\n"
        )


def execute_statements(connection: Any, statements: Sequence[str]) -> None:
    """Execute a sequence of raw SQL statements through an open connection.

    Preserves semantic parity with staged_publication._execute (skipping
    comment/placeholder statements starting with '--') without importing private symbols.
    """
    with connection.cursor() as cursor:
        for statement in statements:
            if statement.strip() and not statement.lstrip().startswith("--"):
                cursor.execute(statement)


__all__ = (
    "PublicationFixture",
    "execute_statements",
    "json_checksums",
    "json_family_manifest",
    "json_row_counts",
)
