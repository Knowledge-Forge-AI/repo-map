"""Adversarial tests for strict W5 accepted-record and claim normalization."""

from __future__ import annotations

import math
from collections.abc import Mapping, MutableMapping
from typing import cast

import pytest

from repomap_test_support.w5_semantic_support import (
    make_w5_policy,
    make_w5_readback_adapter,
    make_w5_receipt,
    make_w5_sample_nodes_and_evidence,
)
from retrieval_semantic_primitives import (
    AcceptedEvidenceRecord,
    AcceptedNodeRecord,
    ClaimedNodeRepresentation,
    RepresentationValidationError,
)
from retrieval_semantic_provenance import verify_publication_provenance_from_adapter
from retrieval_semantic_record_validation import (
    normalize_accepted_evidence,
    normalize_accepted_node,
    normalize_claimed_representation,
)
from retrieval_semantic_representation import validate_canonical_node_representations

BINDING = "bind1:" + ("1" * 64)
SNAPSHOT = "snap1:" + ("a" * 64)
DIGEST = "sha256:" + ("a" * 64)


def _node() -> dict[str, object]:
    return {
        "canonical_key": "sym:core/pkg.py::fn", "kind": "function", "display_name": "fn",
        "graph_key_version": 1, "last_seen_run_id": 1,
    }


def _evidence(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "canonical_key": "sym:core/pkg.py::fn", "evidence_key": "ev:fn", "run_id": 1,
        "graph_key_version": 1, "path": "core/pkg.py",
        "metadata_json": {"binding_id": BINDING, "snapshot_id": SNAPSHOT, "source_relative_path": "pkg.py"},
        "link_kind": "observed",
    }
    value.update(changes)
    return value


def _claim(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "canonical_key": "sym:core/pkg.py::fn", "source_binding_id": BINDING,
        "input_digest": DIGEST,
    }
    value.update(changes)
    return value


def test_actual_records_are_strict_and_metadata_is_frozen() -> None:
    node = normalize_accepted_node({**_node(), "kind": None, "display_name": None})
    assert isinstance(node, AcceptedNodeRecord) and node.kind is None and node.display_name is None
    missing_optional = normalize_accepted_node({k: v for k, v in _node().items() if k not in {"kind", "display_name"}})
    assert missing_optional.kind is None and missing_optional.display_name is None
    metadata = {"binding_id": BINDING, "snapshot_id": SNAPSHOT, "source_relative_path": "pkg.py"}
    evidence = normalize_accepted_evidence(_evidence(metadata_json=metadata))
    metadata["binding_id"] = "bind1:changed"
    assert isinstance(evidence.metadata_json, Mapping)
    assert evidence.metadata_json["binding_id"] == BINDING
    with pytest.raises(TypeError):
        cast(MutableMapping[str, object], evidence.metadata_json)["binding_id"] = "bind1:changed"
    actual_node = normalize_accepted_node(AcceptedNodeRecord("sym:actual", "function", "actual", 1, 1))
    actual_evidence = normalize_accepted_evidence(
        AcceptedEvidenceRecord("sym:actual", "ev:actual", 1, 1, "actual.py", metadata, "observed")
    )
    assert actual_node.canonical_key == actual_evidence.canonical_key == "sym:actual"


@pytest.mark.parametrize("field,value", [("graph_key_version", True), ("last_seen_run_id", "1")])
def test_accepted_node_rejects_bool_and_string_versions(field: str, value: object) -> None:
    with pytest.raises(RepresentationValidationError) as exc_info:
        normalize_accepted_node({**_node(), field: value})
    assert exc_info.value.code == "invalid_accepted_node"


@pytest.mark.parametrize("field", ["graph_key_version", "last_seen_run_id"])
def test_accepted_node_requires_explicit_run_and_version(field: str) -> None:
    raw = _node()
    del raw[field]
    with pytest.raises(RepresentationValidationError) as exc_info:
        normalize_accepted_node(raw)
    assert exc_info.value.code == "invalid_accepted_node"


@pytest.mark.parametrize("field", ["graph_key_version", "run_id"])
def test_accepted_evidence_requires_explicit_run_and_version(field: str) -> None:
    raw = _evidence()
    del raw[field]
    with pytest.raises(RepresentationValidationError) as exc_info:
        normalize_accepted_evidence(raw)
    assert exc_info.value.code == "invalid_accepted_evidence"


@pytest.mark.parametrize(
    ("record", "code"),
    [
        (object(), "invalid_claim_record"),
        (_claim(canonical_key=True), "invalid_claim_identity"),
        (_claim(source_binding_id=[]), "invalid_claim_identity"),
        (_claim(input_digest=True), "invalid_input_digest_format"),
        (_claim(vector="not-a-vector"), "invalid_claim_vector"),
        (_claim(vector=[1.0], dimensions=True), "invalid_claim_dimensions"),
        (_claim(vector=[1.0], dimensions=0), "invalid_claim_dimensions"),
        (_claim(vector=[1.0], dimensions=2001), "invalid_claim_dimensions"),
        (_claim(vector=[2.0, 0.0], dimensions=2), "invalid_claim_vector"),
        (_claim(vector=[math.nan], dimensions=1), "invalid_claim_vector"),
    ],
)
def test_claim_normalizer_rejects_adversarial_shapes(record: object, code: str) -> None:
    with pytest.raises(RepresentationValidationError) as exc_info:
        normalize_claimed_representation(
            cast(Mapping[str, object] | ClaimedNodeRepresentation, record)
        )
    assert exc_info.value.code == code


def test_withheld_and_malformed_metadata_still_follow_exclusion_paths() -> None:
    receipt = make_w5_receipt()
    cell = make_w5_readback_adapter(receipt)
    report = validate_canonical_node_representations(
        verify_publication_provenance_from_adapter(cell, policy=make_w5_policy()),
        accepted_nodes=(_node(),), accepted_evidence=(_evidence(path="/withheld/secret.py"),),
    )
    assert report.status == "ok"
    assert report.excluded[0].reason_code == "withheld_evidence_path"


def test_second_bad_claim_refuses_whole_batch_without_prefix_entries() -> None:
    receipt = make_w5_receipt()
    cell = make_w5_readback_adapter(receipt)
    pin = verify_publication_provenance_from_adapter(cell, policy=make_w5_policy())
    nodes, evidence = make_w5_sample_nodes_and_evidence()
    base = validate_canonical_node_representations(pin, accepted_nodes=nodes, accepted_evidence=evidence)
    rep = base.representations[0]
    valid = ClaimedNodeRepresentation(rep.canonical_key, rep.source_binding_id, rep.input_digest)
    bad = {
        "canonical_key": rep.canonical_key, "source_binding_id": rep.source_binding_id,
        "input_digest": rep.input_digest, "vector": 7,
    }
    refused = validate_canonical_node_representations(
        pin, accepted_nodes=nodes, accepted_evidence=evidence, claimed_entries=(valid, bad)
    )
    assert refused.status == "refused"
    assert refused.refusal_code == "invalid_claim_vector"
    assert refused.verified_entries == ()
