from __future__ import annotations
from typing import Any
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.publication import (
    PortablePublicationBinding,
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_fencing import PublicationHandoff
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
)
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.staging_ownership import StageOwner
from repomap_kg.storage.staging import STAGING_FAMILIES



def _owner() -> StageOwner:
    return StageOwner(
        repository_id=7,
        operation_id=OperationId("direct-scale8-helper"),
        attempt=AttemptNumber(1),
        execution_mode="direct",
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
    )


def _authority() -> IngestionAuthority:
    return IngestionAuthority(
        operation_id=OperationId("direct-scale8-helper"),
        attempt=AttemptNumber(1),
        execution_mode="direct",
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
    )


def _handoff() -> PublicationHandoff:
    owner = _owner()
    receipt = RunPublicationReceipt(
        RunPublicationAttempt(JobId("direct-scale8-helper"), AttemptNumber(1)),
        RunPublicationGenerations(
            "sg1:source", "cg1:config", "eg1:extractor", "kg1:canonicalizer"
        ),
    )
    return PublicationHandoff(MergeContext("stage-scale8-helper", owner, 41), receipt)


def _portable_binding() -> PortablePublicationBinding:
    return PortablePublicationBinding(
        route="portable-worker-v1",
        snapshot_manifest_id="snapmanifest1:" + "1" * 64,
        snapshot_vector=(("bind1:" + "2" * 64, 1, "snap1:" + "3" * 64),),
        extraction_receipt_id="receipt1:" + "4" * 64,
        publication_bundle_id="bundle1:" + "5" * 64,
        candidate_id="cand1:" + "6" * 64,
        resolver_identity="resolver1:nix-static-v2",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
        protocol_version="1.0",
        worker_capability_identity="cap1:portable-worker-v1",
        stage_id="stage-scale8-helper",
        execution_mode="coordinator",
        singleton_fencing_epoch=7,
        graph_lease_fencing_epoch=9,
        family_receipts={
            family: {
                "count": 1,
                "byte_length": 10,
                "digest": "sha256:" + "7" * 64,
            }
            for family in STAGING_FAMILIES
        },
    ).validate()


class StrictFakeCursor:
    def __init__(self, row: tuple[Any, ...] | None = None, rowcount: int = 1) -> None:
        self._row = row
        self.rowcount = rowcount

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class StrictFakeConnection:
    def __init__(
        self,
        *,
        runs_row: tuple[Any, ...] | None = None,
        stage_row: tuple[Any, ...] | None = None,
        runs_status_row: tuple[Any, ...] | None = None,
        query_failure: Exception | None = None,
    ) -> None:
        self.runs_row = runs_row
        self.stage_row = stage_row
        self.runs_status_row = runs_status_row
        self.query_failure = query_failure
        self.committed = 0
        self.rolled_back = 0
        self.closed = 0
        self.executed: list[tuple[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> StrictFakeCursor:
        self.executed.append((sql, params))
        if self.query_failure is not None:
            raise self.query_failure
        norm = " ".join(sql.split())
        if "FROM runs" in norm and "WHERE id = %s AND repository_id = %s" in norm:
            return StrictFakeCursor(self.runs_row)
        if "FROM runs" in norm and "WHERE repository_id = %s AND id = %s" in norm:
            if self.runs_status_row is not None:
                return StrictFakeCursor(self.runs_status_row)
            if self.runs_row is None:
                return StrictFakeCursor(None)
            return StrictFakeCursor((
                self.runs_row[0], self.runs_row[2], self.runs_row[3],
                self.runs_row[4], self.runs_row[5],
            ))
        if "FROM ingestion_stages" in norm and "WHERE stage_id = %s" in norm:
            return StrictFakeCursor(self.stage_row)
        if "UPDATE ingestion_stages" in norm or "UPDATE publication_claims" in norm or "DELETE FROM" in norm:
            return StrictFakeCursor(rowcount=1)
        raise AssertionError(f"StrictFakeConnection unexpected SQL: {sql!r} with params {params!r}")

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def close(self) -> None:
        self.closed += 1
