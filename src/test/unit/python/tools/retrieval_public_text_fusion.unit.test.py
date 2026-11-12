"""v2 projection joins, v1-path parity, unchanged RRF composition, typed serializer and grading.

The preparation, scope and pin are real (fixture projection through the maintained
preparation path). The ArmSeal is assembled directly from that preparation: seal
correctness is the response owner's contract, while these cases prove the fusion
join refuses every mismatch before any RRF code runs.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from common_lore_index.retrieval.query_contracts import EvaluationLocator
from repomap_test_support.retrieval_evaluation_query_fixture import build_fixture_projection
from repomap_test_support.w5_semantic_support import (
    InMemoryStoreReadbackCell, make_w5_accepted_pub_mapping, make_w5_calibration_task,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import GoldTarget
from retrieval_public_text_contracts import PrivateMarkerScope, SpanRow
from retrieval_public_text_descriptors import prepare_public_text_generation
from retrieval_public_text_fusion import (
    LEXICAL_ARM, METRIC_KEYS, PublicTextFusionRefusal, PublicTextProjection, fuse_study_arms, grade_fusion,
    project_public_text_candidates, public_text_fusion_to_dict, public_text_vector_arm, study_arm_id, v1_vector_arm,
)
from retrieval_public_text_request import ARM_PTX, ARM_V1
from retrieval_public_text_response import ArmSeal, SealedRecord
from retrieval_semantic_arm_validation import (
    AdmittedArmObservation, FileIdentityTuple, VectorCandidateInput, _extract_arm_raw_hits,
)
from retrieval_semantic_experiment_contracts import ExperimentRefusal
from repomap_test_support.w5_public_text_postgres import v1_entries, v2_entries
from retrieval_public_text_study_queries import StudyEntry
from retrieval_public_text_study_schema import StudySchemaRefusal
from retrieval_semantic_generator_inputs import prepare_public_generation_input
from retrieval_semantic_generator_kernel import SemanticMode
from retrieval_semantic_primitives import AcceptedEvidenceRecord, AcceptedNodeRecord
from retrieval_semantic_provenance import AcceptedStoreReadback, verify_publication_provenance_from_adapter
from retrieval_semantic_representation import validate_canonical_node_representations

KEY = "python.function:pkg.alpha:boundary_fn"
CANARY = "CANARY-PRIVATE-HOME-7731"
PTX_EXACT = study_arm_id("exact_vector", ARM_PTX)


class _Prepared:
    def __init__(self, tmp_path: Path) -> None:
        inputs, self.policy = build_fixture_projection(spool_dir=tmp_path / "spool")
        publication = make_w5_accepted_pub_mapping(inputs.receipt, run_id=1, generation=1)
        self.cell = InMemoryStoreReadbackCell(
            AcceptedStoreReadback("mixed-v1", "repo1:mixed-v1", "sqlite", publication, inputs.receipt, inputs))
        self.pin = verify_publication_provenance_from_adapter(self.cell, policy=self.policy)
        self.core = min(self.policy.bindings)
        meta = {"binding_id": self.core, "snapshot_id": self.pin.snapshot_by_binding()[self.core][1],
                "source_relative_path": "pkg/alpha.py"}
        node = AcceptedNodeRecord(KEY, "Function", "boundary_fn", 1, 1)
        evidence = AcceptedEvidenceRecord(KEY, "ev1:alpha80", 1, 1, "core/pkg/alpha.py", meta, "defined_by")
        rows = (SpanRow(KEY, "ev1:alpha80", 1, 1, "core/pkg/alpha.py", meta, "defined_by", 80, 81),)
        self.scope = PrivateMarkerScope.create((CANARY,))
        self.report = report = validate_canonical_node_representations(
            self.pin, accepted_nodes=(node,), accepted_evidence=(evidence,))
        self.preparation = prepare_public_text_generation(
            publication_pin=self.pin, readback_adapter=self.cell, policy=self.policy, scope=self.scope,
            read_representations=lambda: report, read_v1_evidence=lambda: (evidence,), read_span_rows=lambda: rows)
        assert len(self.preparation.documents) == 1
        self.document = self.preparation.documents[0]
        self.d = self.document.descriptor
        self.task = self.make_task(self.core)

    def make_task(self, *bindings: str, task_id: str = "cal-01") -> Any:
        gold = GoldTarget(locator=EvaluationLocator(binding_id=self.core, source_relative_path="pkg/alpha.py",
                                                    start_line=80, end_line=81),
                          relevance_grade=3, rationale="fixture span", canonical_key=KEY)
        return make_w5_calibration_task(task_id=task_id, graph_id="mixed-v1", selected_bindings=bindings,
                                        gold_targets=(gold,))

    def seal(self, *, truncated: bool = False, arm: str = ARM_PTX, identity: str | None = None) -> ArmSeal:
        record = SealedRecord("ptx.d.0001", arm, SemanticMode.DOCUMENT, identity or self.document.identity,
                              tuple([1.0] + [0.0] * 383), 600 if truncated else 20, 512 if truncated else 20,
                              1 if truncated else 0, truncated)
        counts = MappingProxyType({"records": 1, "documents": 1, "queries": 0})
        return ArmSeal(arm, "token_partial" if truncated else "complete", None, (record,), counts, counts,
                       (self.document.identity,) if truncated else (), (), "complete")

    def row(self, **changes: Any) -> dict[str, Any]:
        base = {"node_id": 1, "canonical_key": KEY, "kind": self.d["kind"], "display_name": self.d["display_name"],
                "confidence": "extracted", "conflict": False, "source_binding_id": self.core,
                "input_digest": self.d["input_digest"], "snapshot_id": self.d["snapshot_id"],
                "descriptor_identity": self.document.identity, "distance": 0.0,
                "evidence": [{"evidence_key": self.d["evidence_key"], "path": "core/pkg/alpha.py"}]}
        return {**base, **changes}

    def project(self, rows: list[dict[str, Any]], **changes: Any) -> Any:
        kwargs = {"preparation": self.preparation, "seal": self.seal(), "pin": self.pin, "task": self.task,
                  "scope": self.scope, **changes}
        return project_public_text_candidates(rows, **kwargs)

    def arm(self, rows: list[dict[str, Any]] | None = None, *, seal: ArmSeal | None = None) -> AdmittedArmObservation:
        seal = seal or self.seal()
        return public_text_vector_arm("exact_vector", self.project(rows or [self.row()], seal=seal), seal=seal,
                                      pin=self.pin, task=self.task)


def _code(call: Any) -> str:
    with pytest.raises(PublicTextFusionRefusal) as error:
        call()
    return error.value.code


def test_v2_row_projects_to_the_sealed_descriptor_file_identity(tmp_path: Path) -> None:
    p = _Prepared(tmp_path)
    projected = p.project([p.row()])
    assert type(projected) is PublicTextProjection and projected.selected_binding_ids == (p.core,)
    assert projected.hits == ((FileIdentityTuple(p.core, p.d["snapshot_id"], p.d["source_relative_path"]), 1, KEY),)
    assert (projected.task_id, projected.capability, projected.scope_id) == ("cal-01", "complete", p.scope.scope_id)


def test_projection_matches_the_unchanged_vector_candidates_path_on_v1_shaped_rows(tmp_path: Path) -> None:
    p = _Prepared(tmp_path)
    evidence = [{"path": "core/pkg/alpha.py", "metadata_json": {
        "binding_id": p.core, "snapshot_id": p.d["snapshot_id"], "source_relative_path": p.d["source_relative_path"]}}]
    arm = AdmittedArmObservation("exact_vector", "vector", verified_pin=p.pin, selected_binding_ids=(p.core,),
                                 vector_candidates=(VectorCandidateInput(KEY, p.core, 1, evidence),))
    v1_hits, _inspected, _capped = _extract_arm_raw_hits(arm, p.pin, (CANARY,))
    assert tuple(v1_hits) == p.project([p.row()]).hits


@pytest.mark.parametrize(("change", "code"), [
    ({"descriptor_identity": "sha256:" + "0" * 64}, "public_text_descriptor_mismatch"),
    ({"input_digest": "sha256:" + "0" * 64}, "public_text_descriptor_mismatch"),
    ({"kind": "Class"}, "public_text_descriptor_mismatch"),
    ({"snapshot_id": "snap1:" + "0" * 64}, "public_text_snapshot_mismatch"),
    ({"canonical_key": "python.function:pkg.alpha:other"}, "public_text_descriptor_unmatched"),
    ({"evidence": [{"evidence_key": "ev1:alpha80", "path": "/withheld/core"}]}, "public_text_evidence_withheld"),
    ({"evidence": [{"evidence_key": "ev1:other", "path": "core/pkg/alpha.py"}]}, "public_text_evidence_withheld"),
    ({"evidence": []}, "public_text_evidence_withheld"),
    ({"distance": float("nan")}, "public_text_row_malformed"),
    ({"distance": True}, "public_text_row_malformed"),
    ({"extra": 1}, "public_text_row_malformed"),
])
def test_each_row_mismatch_refuses_before_rrf(tmp_path: Path, change: dict[str, Any], code: str) -> None:
    p = _Prepared(tmp_path)
    assert _code(lambda: p.project([p.row(**change)])) == code


def test_scope_seal_pin_binding_and_duplicate_refusals(tmp_path: Path) -> None:
    p = _Prepared(tmp_path)
    missing_key = p.row()
    del missing_key["descriptor_identity"]
    assert _code(lambda: p.project([missing_key])) == "public_text_row_malformed"
    assert _code(lambda: p.project([p.row(), p.row()])) == "public_text_row_duplicate"
    assert _code(lambda: p.project([p.row()], scope=PrivateMarkerScope.create((CANARY,)))) == "public_text_fusion_scope"
    assert _code(lambda: p.project([p.row()], seal=p.seal(arm=ARM_V1))) == "public_text_seal_mismatch"
    assert _code(lambda: p.project([p.row()], seal=p.seal(identity="sha256:" + "1" * 64))) == "public_text_seal_mismatch"
    unknown = p.make_task("bind1:" + "9" * 64)
    assert _code(lambda: p.project([p.row()], task=unknown)) == "public_text_selected_bindings"
    assert _code(lambda: p.project([p.row()], task=replace(p.task, split="held_out"))) == "public_text_selected_bindings"
    other = sorted(b for b in p.pin.admitted_public_bindings if b != p.core)
    if other:
        assert _code(lambda: p.project([p.row()], task=p.make_task(other[0]))) == "public_text_binding_scope"
    p.cell.advance()
    assert _code(lambda: p.project([p.row()])) == "public_text_publication_mismatch"


def test_import_entries_join_sealed_descriptors_and_original_v1_digests(tmp_path: Path) -> None:
    p = _Prepared(tmp_path)
    seal = p.seal(truncated=True)
    assert v2_entries(seal, p.preparation, p.pin) == (StudyEntry(
        KEY, p.core, p.d["snapshot_id"], p.d["input_digest"], p.document.identity, True, seal.records[0].vector),)
    for bad in (p.seal(identity="sha256:" + "1" * 64), p.seal(arm=ARM_V1)):
        with pytest.raises(StudySchemaRefusal):
            v2_entries(bad, p.preparation, p.pin)
    v1 = prepare_public_generation_input(p.report, (), read_current=lambda: p.pin, read_representations=lambda: p.report)
    document = v1.documents[0]
    counts = MappingProxyType({"records": 1, "documents": 1, "queries": 0})

    def v1_seal(record_id: str, source: str, capability: str = "complete") -> ArmSeal:
        record = SealedRecord(record_id, ARM_V1, SemanticMode.DOCUMENT, source, tuple([0.0, 1.0] + [0.0] * 382),
                              20, 20, 0, False)
        return ArmSeal(ARM_V1, capability, None, (record,), counts, counts, (), (), "complete")
    rep = document.representation
    entries = v1_entries(v1_seal("v1." + document.record_id, rep.input_digest), v1, p.pin)
    assert entries == (StudyEntry(rep.canonical_key, rep.source_binding_id, rep.snapshot_id, rep.input_digest, None,
                                  False, tuple([0.0, 1.0] + [0.0] * 382)),)
    for bad in (v1_seal(document.record_id, rep.input_digest), v1_seal("v1." + document.record_id, "sha256:" + "0" * 64),
                v1_seal("v1." + document.record_id, rep.input_digest, "refused")):
        with pytest.raises(StudySchemaRefusal):
            v1_entries(bad, v1, p.pin)


def test_marker_bearing_identity_refuses(tmp_path: Path) -> None:
    p = _Prepared(tmp_path)
    marked = PrivateMarkerScope.create(("pkg/alpha",))
    prepared = replace(p.preparation, _scope=marked, privacy_scope_id=marked.scope_id)
    assert _code(lambda: p.project([p.row()], preparation=prepared, scope=marked)) == "public_text_file_identity"


def test_only_a_validated_projection_bound_to_its_seal_pin_and_task_enters_fusion(tmp_path: Path) -> None:
    """F6: raw tuples, forged projections and mismatched seal/task/pin bindings are refused."""
    p = _Prepared(tmp_path)
    projected = p.project([p.row()])
    arm = public_text_vector_arm("exact_vector", projected, seal=p.seal(), pin=p.pin, task=p.task)
    assert arm.selected_binding_ids == (p.core,) and arm.raw_file_hits == projected.hits
    assert _code(lambda: public_text_vector_arm("exact_vector", projected.hits, seal=p.seal(), pin=p.pin,
                                                task=p.task)) == "public_text_projection"
    assert _code(lambda: PublicTextProjection(*[getattr(projected, n) for n in (
        "hits", "task_id", "task_sha256", "selected_binding_ids", "seal_digest", "preparation_identity",
        "publication_identity", "scope_id", "capability")])) == "public_text_projection"
    assert _code(lambda: public_text_vector_arm("exact_vector", projected, seal=p.seal(truncated=True), pin=p.pin,
                                                task=p.task)) == "public_text_seal_mismatch"
    assert _code(lambda: public_text_vector_arm("exact_vector", projected, seal=p.seal(), pin=p.pin,
                                                task=p.make_task(p.core, task_id="cal-02"))) == "public_text_projection"
    assert _code(lambda: public_text_vector_arm("exact_vector", projected, seal=p.seal(), pin=p.pin,
                                                task=replace(p.task, question="other question"))) \
        == "public_text_projection"


def _v1(p: _Prepared) -> tuple[Any, dict[str, Any]]:
    inputs = prepare_public_generation_input(p.report, (), read_current=lambda: p.pin,
                                             read_representations=lambda: p.report)
    rep = inputs.documents[0].representation
    row = p.row(descriptor_identity=None, input_digest=rep.input_digest, kind=rep.kind,
                display_name=rep.display_name, snapshot_id=rep.snapshot_id,
                evidence=[{"evidence_key": sorted(rep.evidence_keys)[0], "path": "core/pkg/alpha.py"}])
    return inputs, row


def test_v1_arm_runs_the_unchanged_candidate_path_on_the_exact_study_row_shape(tmp_path: Path) -> None:
    """F7: real study rows (closed ROW_KEYS, NULL descriptor) through the unchanged v1 digest checks."""
    p = _Prepared(tmp_path)
    inputs, row = _v1(p)
    arm = v1_vector_arm("exact_vector", [row], task=p.task, pin=p.pin, inputs=inputs)
    candidates = arm.vector_candidates
    assert candidates is not None and arm.arm_id == study_arm_id("exact_vector", ARM_V1) and len(candidates) == 1
    assert candidates[0].input_digest == row["input_digest"] and candidates[0].kind == row["kind"]
    fused = fuse_study_arms((arm,), pin=p.pin)
    assert fused.execution_state is ExecutionState.COMPLETED and fused.hits[0].file_identity.binding_id == p.core
    for change in ({"descriptor_identity": p.document.identity}, {"extra": 1}):
        assert _code(lambda c=change: v1_vector_arm("exact_vector", [{**row, **c}], task=p.task, pin=p.pin,
                                                    inputs=inputs)) == "public_text_row_malformed"
    missing = {k: v for k, v in row.items() if k != "descriptor_identity"}
    assert _code(lambda: v1_vector_arm("exact_vector", [missing], task=p.task, pin=p.pin, inputs=inputs)) \
        == "public_text_row_malformed"
    for change in ({"kind": "Class"}, {"display_name": "other"}, {"input_digest": "sha256:" + "0" * 64}):
        with pytest.raises(ExperimentRefusal) as error:
            v1_vector_arm("exact_vector", [{**row, **change}], task=p.task, pin=p.pin, inputs=inputs)
        assert error.value.code == "candidate_representation_mismatch"


def _lexical(p: _Prepared, *, state: ExecutionState = ExecutionState.COMPLETED) -> AdmittedArmObservation:
    hit = (FileIdentityTuple(p.core, p.d["snapshot_id"], p.d["source_relative_path"]), 1, "chunk-1")
    return AdmittedArmObservation(LEXICAL_ARM, "lexical", verified_pin=p.pin, execution_state=state,
                                  raw_file_hits=(hit,), selected_binding_ids=(p.core,),
                                  unavailable_reason=None if state is ExecutionState.COMPLETED else "projection_absent")


def test_single_and_hybrid_fusion_use_unchanged_rrf_with_fallback_disabled(tmp_path: Path) -> None:
    p = _Prepared(tmp_path)
    vector = p.arm()
    single = fuse_study_arms((vector,), pin=p.pin, private_markers=(CANARY,))
    assert single.execution_state is ExecutionState.COMPLETED and single.hits[0].file_identity.binding_id == p.core
    hybrid = fuse_study_arms((_lexical(p), vector), pin=p.pin)
    assert hybrid.execution_state is ExecutionState.COMPLETED and hybrid.credited_as_fused is True
    degraded = fuse_study_arms((_lexical(p, state=ExecutionState.UNAVAILABLE), vector), pin=p.pin)
    assert degraded.execution_state is ExecutionState.UNAVAILABLE and degraded.hits == () and not degraded.fallback_disclosed
    for arms in ((vector, _lexical(p)), (_lexical(p),), (_lexical(p), vector, vector), ()):
        assert _code(lambda a=arms: fuse_study_arms(a, pin=p.pin)) == "public_text_fusion_arms"
    hnsw = replace(vector, arm_id=study_arm_id("hnsw_vector", ARM_PTX))
    assert _code(lambda: fuse_study_arms((_lexical(p), hnsw), pin=p.pin)) == "public_text_fusion_arms"


def test_token_partial_arm_stays_incomplete_and_truncated_through_fusion(tmp_path: Path) -> None:
    p = _Prepared(tmp_path)
    vector = p.arm(seal=p.seal(truncated=True))
    fused = fuse_study_arms((_lexical(p), vector), pin=p.pin)
    assert fused.incomplete_arms == (PTX_EXACT,) and fused.truncated_arms == (PTX_EXACT,)
    assert fused.credited_as_fused is False and fused.partial_coverage is True


def test_serializer_exposes_per_arm_representations_and_never_one_v1_label(tmp_path: Path) -> None:
    p = _Prepared(tmp_path)
    vector = p.arm()
    fused = fuse_study_arms((_lexical(p), vector), pin=p.pin)
    payload = public_text_fusion_to_dict(fused, representations={LEXICAL_ARM: "not_applicable", PTX_EXACT: ARM_PTX})
    assert payload["schema"] == "cloe-public-text-fusion-v1" and "representation_version" not in payload
    assert "schema_version" not in payload and "provenance" not in payload and payload["provenance_identity"]
    assert payload["arms"] == [{"arm_id": PTX_EXACT, "representation_version": ARM_PTX},
                               {"arm_id": LEXICAL_ARM, "representation_version": "not_applicable"}]
    assert ARM_V1 not in json.dumps(payload) and CANARY not in json.dumps(payload)
    for representations in ({LEXICAL_ARM: "not_applicable", PTX_EXACT: ARM_V1}, {PTX_EXACT: ARM_PTX},
                            {LEXICAL_ARM: ARM_PTX, PTX_EXACT: ARM_PTX}, {}):
        assert _code(lambda r=representations: public_text_fusion_to_dict(fused, representations=r)) \
            == "public_text_serializer_arms"


def test_grading_uses_unchanged_file_metrics_and_unknown_is_none_not_zero(tmp_path: Path) -> None:
    p = _Prepared(tmp_path)
    task = p.task
    vector = p.arm()
    metrics = grade_fusion(fuse_study_arms((vector,), pin=p.pin), task, p.pin)
    assert metrics is not None and tuple(metrics) == METRIC_KEYS and metrics["file_recall@1"] == 1.0
    degraded = fuse_study_arms((_lexical(p, state=ExecutionState.UNAVAILABLE), vector), pin=p.pin)
    assert grade_fusion(degraded, task, p.pin) is None
    held_out = replace(task, split="held_out")
    with pytest.raises(Exception) as error:
        grade_fusion(fuse_study_arms((vector,), pin=p.pin), held_out, p.pin)
    assert getattr(error.value, "code", None) == "held_out_execution_forbidden"


def test_token_preserving_projection_replacements_are_not_factory_issued(tmp_path: Path) -> None:
    p = _Prepared(tmp_path)
    projected = p.project([p.row()])
    for forged in (replace(projected), replace(projected, hits=())):
        assert _code(lambda: public_text_vector_arm("exact_vector", forged, seal=p.seal(), pin=p.pin,
                                                    task=p.task)) == "public_text_projection"
