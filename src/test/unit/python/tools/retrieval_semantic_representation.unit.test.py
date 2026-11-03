"""Unit tests for canonical-node-v1 representation, digest, and provenance validation (ADR 0137)."""

from __future__ import annotations

import hashlib
from typing import Any
import pytest

from common_lore_index.storage.semantic_candidates import EmbeddingEntry
from repomap_test_support.w5_semantic_support import (
    BIND_COMP,
    BIND_CORE,
    BIND_INHERIT,
    BIND_PRIVATE,
    BIND_REDACTED,
    SNAP_CORE_G1,
    SNAP_RED_G1,
    make_w5_accepted_pub_mapping,
    make_w5_accepted_reference,
    make_w5_policy,
    make_w5_readback_adapter,
    make_w5_receipt,
    make_w5_sample_nodes_and_evidence,
)
from retrieval_semantic_representation import (
    AcceptedEvidenceRecord,
    AcceptedNodeRecord,
    CANONICAL_NODE_REPRESENTATION_VERSION,
    ClaimedNodeRepresentation,
    RepresentationValidationError,
    VerifiedPublicationPin,
    build_and_validate_node_representations,
    canonical_node_v1_digest,
    encode_canonical_node_v1_bytes,
    freeze_jsonable,
    validate_canonical_node_representations,
    verify_publication_provenance,
    verify_publication_provenance_from_adapter,
)


def test_canonical_node_v1_encoding_and_digest_exact_bytes_and_unicode() -> None:
    """Verify compact sorted UTF-8 JSON bytes and SHA-256 digest with unescaped Unicode."""
    raw = encode_canonical_node_v1_bytes("sym:core/pkg/pipeline.py::Pipeline_λ", "class", "Pipeline_λ")
    expected = b'{"canonical_key":"sym:core/pkg/pipeline.py::Pipeline_\xce\xbb","display_name":"Pipeline_\xce\xbb","kind":"class"}'
    assert raw == expected
    digest = canonical_node_v1_digest("sym:core/pkg/pipeline.py::Pipeline_λ", "class", "Pipeline_λ")
    assert digest == "sha256:" + hashlib.sha256(expected).hexdigest()


@pytest.mark.parametrize(
    ("c_key", "kind", "d_name", "expected_code"),
    [
        (123, "class", "Foo", "invalid_field_type"),
        (True, "class", "Foo", "invalid_field_type"),
        ("", "class", "Foo", "invalid_field_bounds"),
        ("   ", "class", "Foo", "invalid_field_bounds"),
        ("sym:" + ("x" * 505), "class", "Foo", "invalid_field_bounds"),
        ("sym:foo\x00bar", "class", "Foo", "invalid_control_character"),
        ("sym:foo\nbar", "class", "Foo", "invalid_control_character"),
        ("sym:foo\ud800bar", "class", "Foo", "invalid_unicode_surrogate"),
    ],
)
def test_canonical_node_v1_rejects_malformed_strings_and_types(
    c_key: Any, kind: Any, d_name: Any, expected_code: str
) -> None:
    """Verify strict type, length, control-char, NUL, and lone-surrogate rejection."""
    with pytest.raises(RepresentationValidationError) as exc_info:
        encode_canonical_node_v1_bytes(c_key, kind, d_name)
    assert exc_info.value.code == expected_code


def test_freeze_jsonable_and_private_marker_refusal() -> None:
    """Verify freeze_jsonable rejects non-str keys and non-finite floats, and encoding refuses private markers."""
    with pytest.raises(RepresentationValidationError) as exc_key:
        freeze_jsonable({1: "bad-key"})
    assert exc_key.value.code == "invalid_input_type"

    with pytest.raises(RepresentationValidationError) as exc_nan:
        freeze_jsonable({"score": float("nan")})
    assert exc_nan.value.code == "invalid_input_type"

    with pytest.raises(RepresentationValidationError) as exc_priv:
        encode_canonical_node_v1_bytes(
            "sym:/Users/alice/secret/mod.py::fn", "function", "fn", private_markers=("/Users/alice/secret",)
        )
    assert exc_priv.value.code == "privacy_refused"


def test_verify_publication_provenance_enforces_complete_correspondence_and_early_scope_refusal() -> None:
    """Verify complete receipt/candidate/generation correspondence, early scope refusal, and live adapter revalidation."""
    receipt = make_w5_receipt(generation=1)
    policy = make_w5_policy()
    pub = make_w5_accepted_pub_mapping(receipt, run_id=1, generation=1)
    ref = make_w5_accepted_reference(receipt, run_id=1, generation=1)
    cell = make_w5_readback_adapter(receipt, run_id=1, generation=1)

    with pytest.raises(RepresentationValidationError) as exc_trust:
        verify_publication_provenance(
            graph_id="w5-test-graph", repository_identity="repo1:w5-test", backend="sqlite",
            accepted_publication=pub, receipt=receipt, policy=policy, accepted_reference=ref, trusted_caller=True,
        )
    assert exc_trust.value.code == "caller_trusted_escape_forbidden"

    with pytest.raises(RepresentationValidationError) as exc_miss:
        verify_publication_provenance(
            graph_id="w5-test-graph", repository_identity="repo1:w5-test", backend="sqlite",
            accepted_publication=pub, receipt=receipt, policy=policy,
        )
    assert exc_miss.value.code == "missing_independent_readback_state"

    # Early scope refusal happens BEFORE touching readback_adapter or accepted_publication
    def exploding_adapter() -> Any:
        raise AssertionError("adapter must not be called when selected_binding_ids are denied by policy")

    with pytest.raises(RepresentationValidationError) as exc_early:
        verify_publication_provenance(
            graph_id="w5-test-graph", repository_identity="repo1:w5-test", backend="sqlite",
            accepted_publication={}, receipt=receipt, policy=policy,
            selected_binding_ids=(BIND_PRIVATE,), readback_adapter=exploding_adapter,
        )
    assert exc_early.value.code == "binding_privacy_not_authorized"

    # Candidate ID and generation fields are strictly required without None wildcard or str/int coercion
    with pytest.raises(RepresentationValidationError) as exc_cand:
        verify_publication_provenance(
            graph_id="w5-test-graph", repository_identity="repo1:w5-test", backend="sqlite",
            accepted_publication={**pub, "graph_candidate_id": "cand1:" + ("9" * 64)},
            receipt=receipt, policy=policy, readback_adapter=cell,
        )
    assert exc_cand.value.code == "candidate_id_mismatch"

    with pytest.raises(RepresentationValidationError) as exc_gen_miss:
        verify_publication_provenance(
            graph_id="w5-test-graph", repository_identity="repo1:w5-test", backend="sqlite",
            accepted_publication={k: v for k, v in pub.items() if k != "source_generation"},
            receipt=receipt, policy=policy, readback_adapter=cell,
        )
    assert exc_gen_miss.value.code == "malformed_accepted_publication"

    with pytest.raises(RepresentationValidationError) as exc_coercion:
        verify_publication_provenance(
            graph_id="w5-test-graph", repository_identity="repo1:w5-test", backend="sqlite",
            accepted_publication={**pub, "run_id": "1"},
            receipt=receipt, policy=policy, readback_adapter=cell,
        )
    assert exc_coercion.value.code == "malformed_accepted_publication"

    pin = verify_publication_provenance_from_adapter(cell, policy=policy)
    assert BIND_CORE in pin.admitted_public_bindings
    assert BIND_COMP in pin.admitted_public_bindings
    assert BIND_REDACTED in pin.admitted_public_bindings
    assert pin.denied_bindings[BIND_PRIVATE] == "binding_privacy_not_authorized"
    assert pin.denied_bindings[BIND_INHERIT] == "unresolved_inherit_policy"

    with pytest.raises(RepresentationValidationError) as exc_forge:
        VerifiedPublicationPin(
            graph_id=pin.graph_id, repository_identity=pin.repository_identity, backend=pin.backend,
            run_id=pin.run_id, generation=pin.generation, receipt=pin.receipt,
            receipt_identity=pin.receipt_identity, admitted_public_bindings=pin.admitted_public_bindings,
            denied_bindings=pin.denied_bindings, policy_digest=pin.policy_digest,
        )
    assert exc_forge.value.code == "unverified_publication_pin"

    # Advancing live store invalidates previously minted pin on revalidate_current and representation validation
    cell.advance(run_id=2, generation=2)
    with pytest.raises(RepresentationValidationError) as exc_stale:
        pin.revalidate_current()
    assert exc_stale.value.code == "stale_publication_receipt"

    nodes, evidence = make_w5_sample_nodes_and_evidence(run_id=1, generation=1)
    stale_rep = validate_canonical_node_representations(pin, accepted_nodes=nodes, accepted_evidence=evidence)
    assert stale_rep.status == "refused"
    assert stale_rep.refusal_code == "stale_publication_receipt"


def test_build_and_validate_node_representations_excludes_inferred_withheld_and_validates_claims() -> None:
    """Verify representation construction, exclusion accounting, and claimed batch validation."""
    receipt = make_w5_receipt(generation=1)
    policy = make_w5_policy()
    pub = make_w5_accepted_pub_mapping(receipt, run_id=1, generation=1)
    cell = make_w5_readback_adapter(receipt, run_id=1, generation=1)
    nodes, evidence = make_w5_sample_nodes_and_evidence(run_id=1, generation=1)

    extra_nodes = (
        *nodes,
        AcceptedNodeRecord("sym:core/pkg/inferred.py::Inf", "class", "Inf", 1, 1),
        AcceptedNodeRecord("sym:core/pkg/withheld.py::Withheld", "class", "Withheld", 1, 1),
        AcceptedNodeRecord("sym:redacted/doc.md::Doc", "document", "Doc", 1, 1),
        AcceptedNodeRecord("sym:core/pkg/null_disp.py::NullDisp", "class", None, 1, 1),
    )
    extra_evidence = (
        *evidence,
        AcceptedEvidenceRecord(
            "sym:core/pkg/inferred.py::Inf", "ev:inf", 1, 1, "core/pkg/inferred.py",
            {"binding_id": BIND_CORE, "snapshot_id": SNAP_CORE_G1, "source_relative_path": "pkg/inferred.py"},
            link_kind="inferred",
        ),
        AcceptedEvidenceRecord(
            "sym:core/pkg/withheld.py::Withheld", "ev:wh", 1, 1, "/withheld/secret.py",
            {"binding_id": BIND_CORE, "snapshot_id": SNAP_CORE_G1, "source_relative_path": "pkg/withheld.py"},
        ),
        AcceptedEvidenceRecord(
            "sym:redacted/doc.md::Doc", "ev:red", 1, 1, "docs_meta/doc.md",
            {"binding_id": BIND_REDACTED, "snapshot_id": SNAP_RED_G1, "source_relative_path": "doc.md"},
        ),
        AcceptedEvidenceRecord(
            "sym:core/pkg/null_disp.py::NullDisp", "ev:nd", 1, 1, "core/pkg/null_disp.py",
            {"binding_id": BIND_CORE, "snapshot_id": SNAP_CORE_G1, "source_relative_path": "pkg/null_disp.py"},
        ),
    )

    report = build_and_validate_node_representations(
        graph_id="w5-test-graph", repository_identity="repo1:w5-test", backend="sqlite",
        accepted_publication=pub, receipt=receipt, policy=policy,
        accepted_nodes=extra_nodes, accepted_evidence=extra_evidence, readback_adapter=cell,
    )
    assert report.status == "ok"
    assert len(report.representations) == 4
    excluded_codes = {ex.canonical_key: ex.reason_code for ex in report.excluded}
    assert excluded_codes["sym:core/pkg/inferred.py::Inf"] == "inferred_only_evidence_excluded"
    assert excluded_codes["sym:core/pkg/withheld.py::Withheld"] == "withheld_evidence_path"
    assert excluded_codes["sym:core/pkg/null_disp.py::NullDisp"] == "invalid_field_type"

    first_rep = next(rep for rep in report.representations if rep.source_binding_id == BIND_CORE)
    emb_entry = EmbeddingEntry(
        canonical_key=first_rep.canonical_key, source_binding_id=first_rep.source_binding_id,
        input_digest=first_rep.input_digest, vector=(0.6, -0.8, 0.0),
    )
    claimed_ok = build_and_validate_node_representations(
        graph_id="w5-test-graph", repository_identity="repo1:w5-test", backend="sqlite",
        accepted_publication=pub, receipt=receipt, policy=policy,
        accepted_nodes=extra_nodes, accepted_evidence=extra_evidence,
        claimed_entries=(emb_entry,), readback_adapter=cell,
    )
    assert claimed_ok.status == "ok"
    assert len(claimed_ok.representations) == 1
    assert claimed_ok.truncated is True
    assert claimed_ok.partial_coverage is True
    assert claimed_ok.to_dict()["representation_version"] == CANONICAL_NODE_REPRESENTATION_VERSION

    # Out-of-scope claim binding when selected_binding_ids restricts scope to BIND_COMP
    out_of_scope_claim = build_and_validate_node_representations(
        graph_id="w5-test-graph", repository_identity="repo1:w5-test", backend="sqlite",
        accepted_publication=pub, receipt=receipt, policy=policy,
        accepted_nodes=extra_nodes, accepted_evidence=extra_evidence,
        claimed_entries=(emb_entry,), selected_binding_ids=(BIND_COMP,), readback_adapter=cell,
    )
    assert out_of_scope_claim.status == "refused"
    assert out_of_scope_claim.refusal_code == "out_of_scope_binding"

    # Mapping claim with non-unit vector is refused
    bad_vec_claim = {
        "canonical_key": first_rep.canonical_key,
        "source_binding_id": first_rep.source_binding_id,
        "input_digest": first_rep.input_digest,
        "vector": [0.0, 0.0, 0.0],
        "dimensions": 3,
    }
    refused_vec = build_and_validate_node_representations(
        graph_id="w5-test-graph", repository_identity="repo1:w5-test", backend="sqlite",
        accepted_publication=pub, receipt=receipt, policy=policy,
        accepted_nodes=extra_nodes, accepted_evidence=extra_evidence,
        claimed_entries=(bad_vec_claim,), readback_adapter=cell,
    )
    assert refused_vec.status == "refused"
    assert refused_vec.refusal_code == "invalid_claim_vector"

    bad_claim = ClaimedNodeRepresentation(
        canonical_key=first_rep.canonical_key, source_binding_id=first_rep.source_binding_id,
        input_digest="sha256:" + ("0" * 64),
    )
    refused_digest = build_and_validate_node_representations(
        graph_id="w5-test-graph", repository_identity="repo1:w5-test", backend="sqlite",
        accepted_publication=pub, receipt=receipt, policy=policy,
        accepted_nodes=extra_nodes, accepted_evidence=extra_evidence,
        claimed_entries=(bad_claim,), readback_adapter=cell,
    )
    assert refused_digest.status == "refused"
    assert refused_digest.refusal_code == "representation_digest_mismatch"

    denied_claim = ClaimedNodeRepresentation(
        canonical_key=first_rep.canonical_key, source_binding_id=BIND_PRIVATE, input_digest=first_rep.input_digest,
    )
    refused_denied = build_and_validate_node_representations(
        graph_id="w5-test-graph", repository_identity="repo1:w5-test", backend="sqlite",
        accepted_publication=pub, receipt=receipt, policy=policy,
        accepted_nodes=extra_nodes, accepted_evidence=extra_evidence,
        claimed_entries=(denied_claim,), readback_adapter=cell,
    )
    assert refused_denied.status == "refused"
    assert refused_denied.refusal_code == "binding_privacy_not_authorized"
