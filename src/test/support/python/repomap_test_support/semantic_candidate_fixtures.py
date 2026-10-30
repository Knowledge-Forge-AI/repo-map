"""Public-safe synthetic vectors: mechanics, never learned semantic quality."""

from __future__ import annotations

from common_lore_index.storage.authority import AttemptNumber, GraphRunId, JobId
from common_lore_index.storage.publication import (
    PortablePublicationBinding, RunPublicationAttempt, RunPublicationGenerations,
    RunPublicationReceipt,
)
from common_lore_index.storage.publication_readback import RunPublicationRecord
from common_lore_index.storage.semantic_candidates import CandidatePublication, CandidateQuery, EmbeddingProfile

BINDING = "bind1:" + "3" * 64
SNAPSHOT = "snap1:" + "4" * 64
PROFILE = EmbeddingProfile("synthetic-axis-fixture", "1", "public-fixture-author", "1", 3)


def candidate_query() -> CandidateQuery:
    portable = PortablePublicationBinding(
        route="portable-worker-v1", snapshot_manifest_id="snapmanifest1:" + "2" * 64,
        snapshot_vector=((BINDING, 1, SNAPSHOT),), extraction_receipt_id="receipt1:" + "9" * 64,
        publication_bundle_id="bundle1:" + "1" * 64, candidate_id="cand1:" + "1" * 64,
        resolver_identity="resolver1:fixture", canonicalizer_identity="canon1:fixture",
        semantic_contract_identity="semantic1:fixture", quality_rule_identity="quality1:fixture",
        protocol_version="1.0", worker_capability_identity="cap1:fixture", stage_id="fixture-stage",
        execution_mode="direct", singleton_fencing_epoch=0, graph_lease_fencing_epoch=0,
        family_receipts={name: {"count": 1, "byte_length": 1, "digest": "sha256:" + "0" * 64}
            for name in ("files", "raw_observations", "canonical_nodes", "canonical_edges",
                         "canonical_evidence", "canonical_node_evidence", "canonical_edge_evidence")},
    )
    receipt = RunPublicationReceipt(
        RunPublicationAttempt(JobId("fixture-publication"), AttemptNumber(1)),
        RunPublicationGenerations("sg1:fixture", "cg1:fixture", "eg1:fixture", "kg1:fixture"), portable,
    )
    return CandidateQuery(
        CandidatePublication("repo1:candidate-fixture", RunPublicationRecord(GraphRunId(1), receipt)),
        PROFILE, "rebuild-fixture-1", (1.0, 0.0, 0.0), selected=True,
    )
