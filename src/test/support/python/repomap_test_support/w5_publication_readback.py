"""Small public-safe payload builders for publication readback boundary tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

from common_lore_index.storage.publication import (
    PortablePublicationBinding,
    RunPublicationReceipt,
)


def legacy_receipt_mapping(
    *, job_id: str = "job-readback-1", attempt: int = 1
) -> dict[str, object]:
    """Return one complete legacy receipt row with portable columns all NULL."""
    payload: dict[str, object] = {
        "publication_job_id": job_id,
        "publication_attempt": attempt,
        "source_generation": "sg1:readback-source",
        "config_generation": "cg1:readback-config",
        "extractor_generation": "eg1:readback-extractor",
        "canonicalizer_generation": "kg1:readback-canonicalizer",
    }
    payload.update({field: None for field in PortablePublicationBinding.field_names()})
    return payload


def portable_receipt_mapping(
    *, job_id: str = "job-readback-1", attempt: int = 1
) -> dict[str, object]:
    """Return a complete portable receipt mapping accepted by the current parser."""
    payload = legacy_receipt_mapping(job_id=job_id, attempt=attempt)
    families = {
        family: {"count": 1, "byte_length": 8, "digest": "sha256:" + "a" * 64}
        for family in (
            "files",
            "raw_observations",
            "canonical_nodes",
            "canonical_edges",
            "canonical_evidence",
            "canonical_node_evidence",
            "canonical_edge_evidence",
        )
    }
    payload.update(
        {
            "execution_route": "portable-worker-v1",
            "snapshot_manifest_id": "snapmanifest1:" + "1" * 64,
            "snapshot_vector_json": json.dumps(
                [["bind1:" + "2" * 64, 1, "snap1:" + "3" * 64]],
                separators=(",", ":"),
            ),
            "extraction_receipt_id": "receipt1:" + "4" * 64,
            "publication_bundle_id": "bundle1:" + "5" * 64,
            "graph_candidate_id": "cand1:" + "6" * 64,
            "resolver_identity": "resolver1:nix-static-v2",
            "portable_canonicalizer_identity": "canon1:graph-key-v1-binding-path",
            "semantic_contract_identity": "semantic1:multi-source-v1",
            "quality_rule_identity": "quality1:default",
            "portable_protocol_version": "1.0",
            "worker_capability_identity": "cap1:portable-worker-v1",
            "portable_stage_id": "stage-readback-1",
            "portable_execution_mode": "direct",
            "portable_singleton_fencing_epoch": 7,
            "portable_graph_lease_fencing_epoch": 9,
            "family_receipts_json": json.dumps(families, sort_keys=True, separators=(",", ":")),
        }
    )
    return payload


def all_null_receipt_mapping() -> dict[str, object]:
    """Return the database's all-NULL optional receipt projection."""
    return {field: None for field in RunPublicationReceipt.field_names()}


def mapping_process(payload: object) -> SimpleNamespace:
    """Build the bounded process-like object accepted by ``run_psql`` patches."""
    return SimpleNamespace(stdout=json.dumps(payload, separators=(",", ":")) + "\n")


def portable_json_mutation(field: str, value: object) -> dict[str, object]:
    """Return a portable mapping with one deliberately malformed field."""
    payload = portable_receipt_mapping()
    payload[field] = value
    return payload


__all__ = [
    "all_null_receipt_mapping",
    "legacy_receipt_mapping",
    "mapping_process",
    "portable_json_mutation",
    "portable_receipt_mapping",
]
