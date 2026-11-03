"""Cohesive test support for W5 semantic representation, fusion, and grading (ADR 0137)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy, ResolvedBindingPolicy
from common_lore_index.retrieval.publication_binding import AcceptedPublicationReference
from common_lore_index.retrieval.query_contracts import EvaluationLocator
from common_lore_index.storage.authority import AttemptNumber, JobId, PublicationGenerations
from common_lore_index.storage.publication import (
    PortablePublicationBinding,
    RunPublicationAttempt,
    RunPublicationReceipt,
)
from repomap_test_support.w5_semantic_store_support import (
    load_postgres_accepted_nodes_and_evidence,
    load_sqlite_accepted_nodes_and_evidence,
    make_postgres_readback_adapter,
    make_sqlite_readback_adapter,
)
from retrieval_evaluation_schema import EvaluationTask, GoldTarget
from retrieval_semantic_representation import (
    AcceptedEvidenceRecord,
    AcceptedNodeRecord,
    AcceptedStoreReadback,
    PublicationReadbackAdapter,
    VerifiedPublicationPin,
    verify_publication_provenance_from_adapter,
)

BIND_CORE = "bind1:" + ("1" * 64)
BIND_COMP = "bind1:" + ("2" * 64)
BIND_REDACTED = "bind1:" + ("3" * 64)
BIND_PRIVATE = "bind1:" + ("4" * 64)
BIND_INHERIT = "bind1:" + ("5" * 64)
SNAP_CORE_G1 = "snap1:" + ("a" * 64)
SNAP_COMP_G1 = "snap1:" + ("b" * 64)
SNAP_RED_G1 = "snap1:" + ("c" * 64)
SNAP_CORE_G2 = "snap1:" + ("d" * 64)
SNAP_COMP_G2 = "snap1:" + ("e" * 64)


def _hex64(ch: str) -> str:
    return (ch * 64)[:64]


def make_w5_receipt(
    *,
    generation: int = 1,
    snapshot_vector: Sequence[tuple[str, int, str]] | None = None,
    job_id: str = "job-w5-unit-1",
    attempt: int = 1,
) -> RunPublicationReceipt:
    """Build a deterministic validated RunPublicationReceipt for unit testing."""
    ch = "a" if generation == 1 else "b"
    vec = tuple(
        snapshot_vector
        if snapshot_vector is not None
        else (
            (BIND_CORE, generation, SNAP_CORE_G1 if generation == 1 else SNAP_CORE_G2),
            (BIND_COMP, generation, SNAP_COMP_G1 if generation == 1 else SNAP_COMP_G2),
            (BIND_REDACTED, generation, SNAP_RED_G1),
        )
    )
    fams = {
        k: {"count": 2, "byte_length": 128, "digest": f"sha256:{_hex64(ch)}"}
        for k in (
            "files", "raw_observations", "canonical_nodes", "canonical_edges",
            "canonical_evidence", "canonical_node_evidence", "canonical_edge_evidence",
        )
    }
    portable = PortablePublicationBinding(
        route="portable-worker-v1", snapshot_manifest_id=f"snapmanifest1:{_hex64(ch)}", snapshot_vector=vec,
        extraction_receipt_id=f"receipt1:{_hex64(ch)}", publication_bundle_id=f"bundle1:{_hex64(ch)}",
        candidate_id=f"cand1:{_hex64(ch)}", resolver_identity="resolver1:w5-test", canonicalizer_identity="canon1:w5-test",
        semantic_contract_identity="sem1:w5-test", quality_rule_identity="qual1:w5-test", protocol_version="1.0",
        worker_capability_identity="worker1:w5-test", stage_id=f"stage-w5-{generation}", execution_mode="direct",
        singleton_fencing_epoch=1, graph_lease_fencing_epoch=1, family_receipts=fams,
    ).validate()
    gens = PublicationGenerations(
        source_generation=f"sg1:{_hex64(ch)}", config_generation=f"cg1:{_hex64(ch)}",
        extractor_generation=f"eg1:{_hex64(ch)}", canonicalizer_generation=f"kg1:{_hex64(ch)}",
    )
    return RunPublicationReceipt(
        attempt=RunPublicationAttempt(job_id=JobId(job_id), attempt=AttemptNumber(attempt)), generations=gens, portable=portable
    ).validate()


def make_w5_policy(*, graph_id: str = "w5-test-graph", selected_binding_ids: Sequence[str] | None = None) -> BodyProjectionPolicy:
    """Build a BodyProjectionPolicy including public, redacted-retention, private, and inherit bindings."""
    bindings = {
        BIND_CORE: ResolvedBindingPolicy(BIND_CORE, "core", "primary", "git_Tree", "public-dev", "public-dev", "public-dev", "public-dev", "full-authorized", "full-authorized"),
        BIND_COMP: ResolvedBindingPolicy(BIND_COMP, "companion", "secondary", "git_Tree", "public-dev", "public-dev", "public-dev", "public-dev", "full-authorized", "full-authorized"),
        BIND_REDACTED: ResolvedBindingPolicy(BIND_REDACTED, "docs_meta", "secondary", "git_Tree", "public-dev", "public-dev", "public-dev", "public-dev", "redacted", "redacted"),
        BIND_PRIVATE: ResolvedBindingPolicy(BIND_PRIVATE, "mailbox", "mailbox", "maildir", "public-dev", "public-dev", "private", "private", "redacted", "redacted"),
        BIND_INHERIT: ResolvedBindingPolicy(BIND_INHERIT, "unfinished", "secondary", "git_Tree", "public-dev", "public-dev", "inherit", "inherit", "full-authorized", "full-authorized"),
    }
    sel = frozenset(selected_binding_ids if selected_binding_ids is not None else (BIND_CORE, BIND_COMP, BIND_REDACTED))
    return BodyProjectionPolicy(graph_id=graph_id, selected_binding_ids=sel, bindings=bindings).validate()


def make_w5_accepted_pub_mapping(receipt: RunPublicationReceipt, *, run_id: int = 1, generation: int = 1) -> dict[str, Any]:
    """Build an accepted_publication mapping corresponding to a RunPublicationReceipt."""
    p = receipt.portable
    assert p is not None, "portable fixture receipt required"
    g = receipt.generations
    return {
        "run_id": run_id,
        "generation": generation,
        "job_id": str(receipt.attempt.job_id),
        "attempt": int(receipt.attempt.attempt),
        "publication_bundle_id": p.publication_bundle_id,
        "snapshot_manifest_id": p.snapshot_manifest_id,
        "extraction_receipt_id": p.extraction_receipt_id,
        "graph_candidate_id": p.candidate_id,
        "snapshot_vector": [[b, r, s] for b, r, s in p.snapshot_vector],
        "source_generation": str(g.source_generation),
        "config_generation": str(g.config_generation),
        "extractor_generation": str(g.extractor_generation),
        "canonicalizer_generation": str(g.canonicalizer_generation),
    }


def make_w5_accepted_reference(
    receipt: RunPublicationReceipt, *, graph_id: str = "w5-test-graph", repository_identity: str = "repo1:w5-test",
    backend: str = "sqlite", run_id: int = 1, generation: int = 1,
) -> AcceptedPublicationReference:
    """Build a validated AcceptedPublicationReference matching a RunPublicationReceipt."""
    p = receipt.portable
    assert p is not None, "portable fixture receipt required"
    return AcceptedPublicationReference(
        graph_id=graph_id, repository_id=repository_identity, backend=backend, run_id=run_id,
        publication_bundle_id=p.publication_bundle_id, job_id=str(receipt.attempt.job_id),
        attempt=int(receipt.attempt.attempt), accepted_generation=generation,
        snapshot_manifest_id=p.snapshot_manifest_id, extraction_receipt_id=p.extraction_receipt_id, trusted_caller=True,
    ).validate()


@dataclass
class InMemoryStoreReadbackCell:
    """Mutable store readback cell simulating live store state transitions for unit tests."""

    current: AcceptedStoreReadback

    def __call__(self) -> AcceptedStoreReadback:
        return self.current

    def advance(self, *, run_id: int = 2, generation: int = 2, receipt: RunPublicationReceipt | None = None) -> AcceptedStoreReadback:
        next_receipt = receipt if receipt is not None else make_w5_receipt(generation=generation, job_id=f"job-w5-unit-{generation}")
        next_pub = make_w5_accepted_pub_mapping(next_receipt, run_id=run_id, generation=generation)
        self.current = AcceptedStoreReadback(
            graph_id=self.current.graph_id,
            repository_identity=self.current.repository_identity,
            backend=self.current.backend,
            accepted_publication=next_pub,
            receipt=next_receipt,
        )
        return self.current


def make_w5_readback_adapter(
    receipt: RunPublicationReceipt | None = None,
    *,
    graph_id: str = "w5-test-graph",
    repository_identity: str = "repo1:w5-test",
    backend: str = "sqlite",
    run_id: int = 1,
    generation: int = 1,
) -> InMemoryStoreReadbackCell:
    """Create a live store readback adapter cell for unit tests."""
    eff_receipt = receipt if receipt is not None else make_w5_receipt(generation=generation)
    pub = make_w5_accepted_pub_mapping(eff_receipt, run_id=run_id, generation=generation)
    return InMemoryStoreReadbackCell(
        AcceptedStoreReadback(
            graph_id=graph_id,
            repository_identity=repository_identity,
            backend=backend,
            accepted_publication=pub,
            receipt=eff_receipt,
        )
    )


def make_w5_verified_pin(
    *, graph_id: str = "w5-test-graph", repository_identity: str = "repo1:w5-test", backend: str = "sqlite",
    run_id: int = 1, generation: int = 1, selected_binding_ids: Sequence[str] | None = None,
    readback_adapter: PublicationReadbackAdapter | None = None,
) -> VerifiedPublicationPin:
    """Create a VerifiedPublicationPin from a synthetic live store readback."""
    receipt = make_w5_receipt(generation=generation)
    policy = make_w5_policy(graph_id=graph_id, selected_binding_ids=selected_binding_ids)
    adapter = readback_adapter or make_w5_readback_adapter(
        receipt, graph_id=graph_id, repository_identity=repository_identity, backend=backend, run_id=run_id, generation=generation
    )
    return verify_publication_provenance_from_adapter(
        adapter,
        policy=policy,
        selected_binding_ids=selected_binding_ids,
    )


def make_w5_sample_nodes_and_evidence(
    *, run_id: int = 1, generation: int = 1
) -> tuple[tuple[AcceptedNodeRecord, ...], tuple[AcceptedEvidenceRecord, ...]]:
    """Build sample AcceptedNodeRecord and AcceptedEvidenceRecord tuples."""
    snap_core = SNAP_CORE_G1 if generation == 1 else SNAP_CORE_G2
    snap_comp = SNAP_COMP_G1 if generation == 1 else SNAP_COMP_G2
    nodes = (
        AcceptedNodeRecord("sym:core/pkg/pipeline.py::RetrievalPipeline", "class", "RetrievalPipeline", 1, run_id),
        AcceptedNodeRecord("sym:core/pkg/pipeline.py::run_step", "function", "run_step", 1, run_id),
        AcceptedNodeRecord("sym:companion/scripts/deploy.sh::deploy_main", "function", "deploy_main", 1, run_id),
    )
    evidence = (
        AcceptedEvidenceRecord(
            "sym:core/pkg/pipeline.py::RetrievalPipeline", "ev:1", run_id, 1, "core/pkg/pipeline.py",
            {"binding_id": BIND_CORE, "snapshot_id": snap_core, "source_relative_path": "pkg/pipeline.py"},
        ),
        AcceptedEvidenceRecord(
            "sym:core/pkg/pipeline.py::run_step", "ev:2", run_id, 1, "core/pkg/pipeline.py",
            {"binding_id": BIND_CORE, "snapshot_id": snap_core, "source_relative_path": "pkg/pipeline.py"},
        ),
        AcceptedEvidenceRecord(
            "sym:companion/scripts/deploy.sh::deploy_main", "ev:3", run_id, 1, "companion/scripts/deploy.sh",
            {"binding_id": BIND_COMP, "snapshot_id": snap_comp, "source_relative_path": "scripts/deploy.sh"},
        ),
    )
    return nodes, evidence


def make_w5_calibration_task(
    *,
    task_id: str = "w5-cal-01",
    split: str = "calibration",
    graph_id: str = "w5-test-graph",
    generation: int = 1,
    comparability_stratum: str = "metadata",
    intended_match_surface: str = "stored_metadata",
    grading_rule: str = "ranked_positive",
    selected_bindings: tuple[str, ...] = (BIND_CORE, BIND_COMP),
    gold_targets: Sequence[Any] | None = None,
    expected_refusal_code: str | None = None,
    comparator_exposure: Mapping[str, str] | None = None,
) -> EvaluationTask:
    """Build a validated EvaluationTask for W5 grading unit tests."""
    targets = tuple(
        gold_targets
        if gold_targets is not None
        else (
            GoldTarget(
                locator=EvaluationLocator(binding_id=BIND_CORE, source_relative_path="pkg/pipeline.py", start_line=10, end_line=25),
                relevance_grade=3, rationale="primary class definition", canonical_key="sym:core/pkg/pipeline.py::RetrievalPipeline",
            ),
            GoldTarget(
                locator=EvaluationLocator(binding_id=BIND_CORE, source_relative_path="pkg/pipeline.py", start_line=30, end_line=45),
                relevance_grade=1, rationale="helper function in same file", canonical_key="sym:core/pkg/pipeline.py::run_step",
            ),
        )
    )
    return EvaluationTask(
        task_id=task_id, family="exact_symbol_and_partial_name", split=split,
        question="Locate RetrievalPipeline and run_step",
        permitted_query_plan={"op": "search_nodes", "query": "RetrievalPipeline"},
        graph_id=graph_id, generation=generation, selected_bindings=selected_bindings,
        source_path_prefix=None, requested_mode="ranked_discovery",
        intended_match_surface=intended_match_surface, comparability_stratum=comparability_stratum,
        comparator_exposure=dict(comparator_exposure or {"vector_only": "supported", "hybrid_rrf": "supported"}),
        gold_targets=targets, expected_capability_state="available" if grading_rule != "safety_refusal" else "refused",
        expected_refusal_code=expected_refusal_code, grading_rule=grading_rule,
    ).validate()


__all__ = [
    "BIND_COMP", "BIND_CORE", "BIND_INHERIT", "BIND_PRIVATE", "BIND_REDACTED",
    "SNAP_COMP_G1", "SNAP_COMP_G2", "SNAP_CORE_G1", "SNAP_CORE_G2", "SNAP_RED_G1",
    "InMemoryStoreReadbackCell",
    "load_postgres_accepted_nodes_and_evidence",
    "load_sqlite_accepted_nodes_and_evidence",
    "make_postgres_readback_adapter",
    "make_sqlite_readback_adapter",
    "make_w5_accepted_pub_mapping",
    "make_w5_accepted_reference",
    "make_w5_calibration_task",
    "make_w5_policy",
    "make_w5_readback_adapter",
    "make_w5_receipt",
    "make_w5_sample_nodes_and_evidence",
    "make_w5_verified_pin",
]
