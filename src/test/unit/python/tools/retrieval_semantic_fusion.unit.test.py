"""Unit tests for file-level RRF (k=60) fusion and cross-arm provenance alignment (ADR 0137)."""

from __future__ import annotations

from fractions import Fraction
import pytest

from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    DEFAULT_ORDERING_POLICY_VERSION,
    EvaluationLocator,
    MatchSurface,
    OmissionRecord,
    QUERY_CONTRACT_VERSION,
    QueryEnvelope,
    QueryHit,
    QueryMode,
    QueryScope,
)
from repomap_test_support.w5_semantic_support import (
    BIND_COMP,
    BIND_CORE,
    BIND_PRIVATE,
    SNAP_COMP_G1,
    SNAP_CORE_G1,
    make_w5_accepted_pub_mapping,
    make_w5_policy,
    make_w5_readback_adapter,
    make_w5_receipt,
    make_w5_verified_pin,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_fusion import (
    AdmittedArmObservation,
    FileIdentityTuple,
    RRF_K_DEFAULT,
    VectorCandidateInput,
    collapse_arm_to_files,
    fuse_arm_observations_rrf,
)
from retrieval_semantic_representation import (
    RepresentationValidationError,
    canonical_node_v1_digest,
    verify_publication_provenance_from_adapter,
)


def test_collapse_arm_to_files_deduplicates_and_assigns_contiguous_ordinal_ranks() -> None:
    """Multiple node/chunk hits in one file collapse to best raw rank before RRF scoring."""
    f_alpha = FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/alpha.py")
    f_beta = FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/beta.py")
    raw_hits = (
        (f_beta, 1, "chunk:beta:1"),
        (f_beta, 2, "chunk:beta:2"),
        (f_alpha, 3, "chunk:alpha:1"),
    )
    collapsed = collapse_arm_to_files("lexical_arm", raw_hits, rrf_k=RRF_K_DEFAULT)
    assert len(collapsed) == 2
    assert collapsed[0].file_identity == f_beta
    assert collapsed[0].ordinal_rank == 1
    assert collapsed[0].best_raw_rank == 1
    assert collapsed[0].raw_hit_count == 2
    assert collapsed[0].rrf_contribution == Fraction(1, 61)
    assert collapsed[1].file_identity == f_alpha
    assert collapsed[1].ordinal_rank == 2
    assert collapsed[1].best_raw_rank == 3
    assert collapsed[1].rrf_contribution == Fraction(1, 62)


def test_fuse_arm_observations_rrf_exact_fractions_and_utf8_tie_breaking() -> None:
    """Verify exact Fraction RRF summation, tie-breaking, and work vs output-cap accounting."""
    pin = make_w5_verified_pin(generation=1)
    f_a = FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/a_first.py")
    f_c = FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/c_both.py")

    lex_arm = AdmittedArmObservation(
        arm_id="lexical_fts5", mode="ranked_discovery", verified_pin=pin,
        raw_file_hits=((f_a, 1, "chunk:a:1"), (f_c, 2, "chunk:c:1")),
    )
    vec_cand_b = VectorCandidateInput(
        canonical_key="sym:companion/scripts/b_second.sh::main", source_binding_id=BIND_COMP, raw_rank=1,
        evidence=({"path": "companion/scripts/b_second.sh", "metadata_json": {"binding_id": BIND_COMP, "snapshot_id": SNAP_COMP_G1, "source_relative_path": "scripts/b_second.sh"}},),
        input_digest=canonical_node_v1_digest("sym:companion/scripts/b_second.sh::main", "function", "main"),
        kind="function", display_name="main",
    )
    vec_cand_c = VectorCandidateInput(
        canonical_key="sym:core/pkg/c_both.py::Helper", source_binding_id=BIND_CORE, raw_rank=2,
        evidence=({"path": "core/pkg/c_both.py", "metadata_json": {"binding_id": BIND_CORE, "snapshot_id": SNAP_CORE_G1, "source_relative_path": "pkg/c_both.py"}},),
        input_digest=canonical_node_v1_digest("sym:core/pkg/c_both.py::Helper", "class", "Helper"),
        kind="class", display_name="Helper",
    )
    vec_arm = AdmittedArmObservation(
        arm_id="vector_canonical_node_v1", mode="ranked_discovery", verified_pin=pin,
        vector_candidates=(vec_cand_b, vec_cand_c),
    )

    res = fuse_arm_observations_rrf((lex_arm, vec_arm), expected_pin=pin, max_results=2)
    assert res.execution_state == ExecutionState.COMPLETED
    # Both arms executed, but a truncated output is not complete fused credit.
    assert res.credited_as_fused is False
    assert res.pre_cap_fused_file_count == 3
    assert res.work_candidates_inspected == 4
    assert res.truncated is True
    assert res.partial_coverage is True
    assert len(res.hits) == 2
    assert res.hits[0].file_identity == f_c
    assert res.hits[0].score_fraction == Fraction(2, 62)
    assert res.hits[1].file_identity == f_a
    assert res.hits[1].score_fraction == Fraction(1, 61)
    complete = fuse_arm_observations_rrf((lex_arm, vec_arm), expected_pin=pin, max_results=3)
    assert complete.credited_as_fused is True
    assert complete.truncated is False
    assert len(complete.hits) == 3


def test_fuse_arm_observations_rrf_refuses_cross_arm_or_live_store_generation_drift() -> None:
    """Verify cross-arm publication/generation mismatch and live store advancement are refused."""
    pin_g1 = make_w5_verified_pin(run_id=1, generation=1)
    pin_g2 = make_w5_verified_pin(run_id=2, generation=2)
    f_a = FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/a.py")

    arm1 = AdmittedArmObservation(arm_id="lex", mode="ranked_discovery", verified_pin=pin_g1, raw_file_hits=((f_a, 1, "c1"),))
    arm2 = AdmittedArmObservation(arm_id="vec", mode="ranked_discovery", verified_pin=pin_g2, raw_file_hits=())

    res = fuse_arm_observations_rrf((arm1, arm2), expected_pin=pin_g1)
    assert res.execution_state == ExecutionState.REFUSED
    assert res.refusal_code == "stale_publication_receipt"
    assert res.hits == ()
    assert res.credited_as_fused is False

    # Live store advancement via readback_adapter invalidates previously minted pin
    cell = make_w5_readback_adapter(run_id=1, generation=1)
    live_pin = verify_publication_provenance_from_adapter(cell, policy=make_w5_policy())
    live_arm = AdmittedArmObservation(arm_id="lex", mode="ranked_discovery", verified_pin=live_pin, raw_file_hits=((f_a, 1, "c1"),))
    cell.advance(run_id=2, generation=2)
    stale_live = fuse_arm_observations_rrf((live_arm,), expected_pin=live_pin)
    assert stale_live.execution_state == ExecutionState.REFUSED
    assert stale_live.refusal_code == "stale_publication_receipt"
    assert stale_live.hits == ()


def test_fuse_arm_observations_rrf_refusal_precedence_and_explicit_fallback_disclosure() -> None:
    """Privacy refusal overrides unavailability; single-arm fallback is never credited as fused."""
    pin = make_w5_verified_pin(generation=1)
    f_a = FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/a.py")

    unavail_arm = AdmittedArmObservation(
        arm_id="vec", mode="ranked_discovery", verified_pin=pin,
        execution_state=ExecutionState.UNAVAILABLE, unavailable_reason="vector_index_absent",
    )
    refused_arm = AdmittedArmObservation(
        arm_id="lex", mode="ranked_discovery", verified_pin=pin,
        execution_state=ExecutionState.REFUSED, refusal_code="binding_privacy_not_authorized",
    )
    res_refused = fuse_arm_observations_rrf((unavail_arm, refused_arm), expected_pin=pin)
    assert res_refused.execution_state == ExecutionState.REFUSED
    assert res_refused.refusal_code == "binding_privacy_not_authorized"

    ok_arm = AdmittedArmObservation(arm_id="lex", mode="ranked_discovery", verified_pin=pin, raw_file_hits=((f_a, 1, "c1"),))
    res_unavail = fuse_arm_observations_rrf((ok_arm, unavail_arm), expected_pin=pin)
    assert res_unavail.execution_state == ExecutionState.UNAVAILABLE
    assert res_unavail.hits == ()
    assert res_unavail.credited_as_fused is False

    res_fallback = fuse_arm_observations_rrf(
        (ok_arm, unavail_arm), expected_pin=pin, allow_explicit_single_arm_fallback=True
    )
    assert res_fallback.execution_state == ExecutionState.UNAVAILABLE
    assert res_fallback.fallback_disclosed is True
    assert res_fallback.fallback_from_arms == ("vec",)
    assert res_fallback.credited_as_fused is False
    assert len(res_fallback.hits) == 1


@pytest.mark.parametrize(
    "bad_path",
    ["../traversal.py", "/abs/path.py", "C:/abs/win.py", "~/home.py", "pkg\\win.py", "pkg//double.py"],
)
def test_fuse_arm_observations_rejects_withheld_or_denied_vector_evidence_and_bad_paths(bad_path: str) -> None:
    """Vector candidates with withheld paths or denied bindings in any arm refuse the entire fusion with empty hits."""
    pin = make_w5_verified_pin(generation=1)
    f_a = FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/a.py")
    ok_arm = AdmittedArmObservation(arm_id="lex", mode="ranked_discovery", verified_pin=pin, raw_file_hits=((f_a, 1, "c1"),))
    bad_cand = VectorCandidateInput(
        canonical_key="sym:core/pkg/a.py::Fn", source_binding_id=BIND_CORE, raw_rank=1,
        evidence=({"path": "/withheld/redacted.py", "metadata_json": {"binding_id": BIND_CORE, "snapshot_id": SNAP_CORE_G1, "source_relative_path": "pkg/a.py"}},),
    )
    arm = AdmittedArmObservation(arm_id="vec", mode="ranked_discovery", verified_pin=pin, vector_candidates=(bad_cand,))
    res = fuse_arm_observations_rrf((ok_arm, arm), expected_pin=pin)
    assert res.execution_state == ExecutionState.REFUSED
    assert res.refusal_code == "malformed_or_withheld_vector_evidence"
    assert res.hits == ()

    denied_cand = VectorCandidateInput(
        canonical_key="sym:priv/m.eml::Msg", source_binding_id=BIND_PRIVATE, raw_rank=1,
        evidence=({"path": "mailbox/m.eml", "metadata_json": {"binding_id": BIND_PRIVATE, "snapshot_id": SNAP_CORE_G1, "source_relative_path": "m.eml"}},),
    )
    res_denied = fuse_arm_observations_rrf(
        (ok_arm, AdmittedArmObservation(arm_id="vec", mode="ranked_discovery", verified_pin=pin, vector_candidates=(denied_cand,))),
        expected_pin=pin,
    )
    assert res_denied.execution_state == ExecutionState.REFUSED
    assert res_denied.refusal_code == "binding_privacy_not_authorized"
    assert res_denied.hits == ()

    with pytest.raises(RepresentationValidationError) as exc_info:
        FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, bad_path).validate()
    assert exc_info.value.code == "invalid_relative_path"


def test_fuse_arm_observations_validates_observed_publication_and_query_envelope_states() -> None:
    """Verify complete observed_accepted_publication checks and QueryEnvelope state/omission propagation."""
    receipt = make_w5_receipt(generation=1)
    full_pub = make_w5_accepted_pub_mapping(receipt, run_id=1, generation=1)
    pin = make_w5_verified_pin(generation=1)
    f_a = FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/a.py")
    f_b = FileIdentityTuple(BIND_COMP, SNAP_COMP_G1, "scripts/b.sh")

    ok_arm = AdmittedArmObservation(
        arm_id="lex", mode="ranked_discovery", verified_pin=pin,
        raw_file_hits=((f_a, 1, "c1"),), observed_accepted_publication=full_pub,
    )
    # Empty or partial observed_accepted_publication mapping is refused
    empty_obs_arm = AdmittedArmObservation(
        arm_id="vec_empty", mode="ranked_discovery", verified_pin=pin,
        raw_file_hits=((f_b, 1, "v1"),), observed_accepted_publication={},
    )
    res_empty = fuse_arm_observations_rrf((ok_arm, empty_obs_arm), expected_pin=pin)
    assert res_empty.execution_state == ExecutionState.REFUSED
    assert res_empty.refusal_code == "incomplete_observed_accepted_publication"

    stale_obs_arm = AdmittedArmObservation(
        arm_id="vec_stale", mode="ranked_discovery", verified_pin=pin,
        raw_file_hits=((f_b, 1, "v1"),), observed_accepted_publication={**full_pub, "run_id": 99, "generation": 2},
    )
    res_stale = fuse_arm_observations_rrf((ok_arm, stale_obs_arm), expected_pin=pin)
    assert res_stale.execution_state == ExecutionState.REFUSED
    assert res_stale.refusal_code == "stale_publication_receipt"

    # QueryEnvelope with PARTIAL capability state and omission marks arm incomplete
    q_scope = QueryScope(
        graph_id="w5-test-graph", backend=pin.backend,
        publication_bundle_id=pin.publication_bundle_id,
        snapshot_manifest_id=pin.snapshot_manifest_id,
        selected_binding_ids=(BIND_CORE, BIND_COMP),
    )
    partial_env = QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=QueryMode.RANKED_DISCOVERY,
        effective_mode=QueryMode.RANKED_DISCOVERY,
        match_surface=MatchSurface.STORED_METADATA,
        scope=q_scope,
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.PARTIAL,
        hits=(
            QueryHit(
                locator=EvaluationLocator(binding_id=BIND_COMP, source_relative_path="scripts/b.sh", canonical_key="sym:comp/scripts/b.sh::run"),
                match_surface=MatchSurface.STORED_METADATA,
                rank=1,
                score=0.9,
            ),
        ),
        omissions=(OmissionRecord(binding_id=BIND_COMP, source_relative_path=None, reason_code="budget_capped", detail="capped"),),
        scope_complete=False,
        provenance={"accepted_run_id": pin.run_id},
    ).validate()
    env_arm = AdmittedArmObservation(arm_id="vec_env", mode="ranked_discovery", verified_pin=pin, envelope=partial_env)
    res_env = fuse_arm_observations_rrf((ok_arm, env_arm), expected_pin=pin)
    assert res_env.execution_state == ExecutionState.COMPLETED
    assert res_env.partial_coverage is True
    assert res_env.credited_as_fused is False
    assert "vec_env" in res_env.incomplete_arms

    # QueryEnvelope with UNAVAILABLE state propagates unavailability instead of defaulting to COMPLETED
    unavail_env = QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=QueryMode.RANKED_DISCOVERY,
        effective_mode=QueryMode.RANKED_DISCOVERY,
        match_surface=MatchSurface.NONE,
        scope=q_scope,
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.UNAVAILABLE,
        hits=(),
        omissions=(),
        scope_complete=False,
        unavailable_reason="index_absent",
    ).validate()
    unavail_env_arm = AdmittedArmObservation(arm_id="vec_unavail", mode="ranked_discovery", verified_pin=pin, envelope=unavail_env)
    res_unavail_env = fuse_arm_observations_rrf((ok_arm, unavail_env_arm), expected_pin=pin)
    assert res_unavail_env.execution_state == ExecutionState.UNAVAILABLE
    assert res_unavail_env.hits == ()
    assert res_unavail_env.credited_as_fused is False
