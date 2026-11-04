"""Synthetic model boundary and exact ANN registration preserve real identities."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import repomap_test_support.w5_component_functional_experiment as experiment
import repomap_test_support.w5_experiment_hnsw as maintained_hnsw
from common_lore_index.storage.authority import GraphRunId
from common_lore_index.storage.publication_readback import RunPublicationRecord
from common_lore_index.storage.semantic_candidate_sql import build_candidate_query_sql
from common_lore_index.storage.semantic_candidates import CandidatePublication, CandidateQuery, checked_vector
from repomap_test_support.w5_component_functional_supply import QUERY_VECTOR, synthetic_vector_supply
from repomap_test_support.w5_component_functional_transport import functional_hnsw_queries, functional_sql_payloads
from repomap_test_support.w5_component_planner_adapter import make_functional_adapter
from repomap_test_support.w5_experiment_postgres import READ_ROLE
from repomap_test_support.w5_experiment_support import load_calibration_catalog
from repomap_test_support.w5_semantic_support import (
    BIND_CORE, BIND_COMP, make_w5_calibration_task,
    make_w5_sample_nodes_and_evidence, make_w5_verified_pin,
)
from retrieval_semantic_generator_inputs import prepare_public_generation_input
from retrieval_semantic_representation import validate_canonical_node_representations
from retrieval_evaluation_attempts import admit_attempt
from retrieval_semantic_baseline_result_objects import ResultV2Collector
from retrieval_semantic_experiment_contracts import ExperimentCell, ExperimentRefusal, digest_bytes, make_plan
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_baseline_result_frames import decode_result_frames
from repomap_test_support.w5_component_planner_adapter import PLANNER_OPTION
from retrieval_semantic_experiment_artifacts import ARTIFACT_LINE_PREFIX, ArtifactRefusal, MEMBER_NAMES, decode_attempt_artifacts


def _inputs():
    pin = make_w5_verified_pin(backend="postgresql")
    nodes,evidence = make_w5_sample_nodes_and_evidence()
    report = validate_canonical_node_representations(pin,accepted_nodes=nodes,accepted_evidence=evidence)
    task = make_w5_calibration_task()
    return pin,prepare_public_generation_input(report,(task,),read_current=lambda:pin,read_representations=lambda:report)


def test_synthetic_supplier_has_no_worker_receipt_or_measured_model_claim() -> None:
    _pin,inputs = _inputs()
    supply = synthetic_vector_supply(inputs)
    artifact = supply.artifact
    assert supply.response_identity == {} and supply.response_cost == {} and supply.response_counts == {}
    assert artifact.profile.dimensions == 384
    assert artifact.profile.model == "synthetic-axis-functional-fixture"
    assert len(artifact.require_importable()) == len(inputs.documents)
    for document,entry in zip(inputs.documents,artifact.entries,strict=True):
        assert entry.canonical_key == document.representation.canonical_key
        assert entry.source_binding_id == document.representation.source_binding_id
        assert entry.input_digest == document.representation.input_digest
        assert checked_vector(entry.vector,384) == entry.vector
    assert any(query.vector == QUERY_VECTOR for query in artifact.queries)


def test_registered_ann_payloads_exclude_both_exact_reference_transports() -> None:
    pin,inputs = _inputs()
    supply = synthetic_vector_supply(inputs)
    publication = CandidatePublication(pin.repository_identity,RunPublicationRecord(GraphRunId(pin.run_id),pin.receipt))
    queries = functional_hnsw_queries(publication,supply.artifact.profile,pin,(BIND_CORE,BIND_COMP),
                                     rebuild_id="functional-rebuild",vector=QUERY_VECTOR)
    payloads = functional_sql_payloads(queries)
    registered = set(payloads["ann_explain"] + payloads["ann_candidates"])
    assert len(registered) == 4
    prefix = f'SET ROLE "{READ_ROLE}";\n'
    for evaluation in queries:
        baseline = build_candidate_query_sql(evaluation.candidate_query)
        assert baseline not in registered
        assert prefix + baseline not in registered
    assert all(sql.startswith(prefix) for sql in registered)


def test_registration_matches_actual_maintained_query_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    pin,inputs = _inputs()
    supply = synthetic_vector_supply(inputs)
    publication = CandidatePublication(pin.repository_identity,RunPublicationRecord(GraphRunId(pin.run_id),pin.receipt))
    evaluations = functional_hnsw_queries(publication,supply.artifact.profile,pin,(BIND_CORE,BIND_COMP),
                                         rebuild_id="functional-rebuild",vector=QUERY_VECTOR)
    captured: list[CandidateQuery] = []
    class StopBeforeDatabase(Exception): pass
    def capture(*args: Any, **kwargs: Any) -> CandidateQuery:
        captured.append(CandidateQuery(*args,**kwargs))
        raise StopBeforeDatabase
    monkeypatch.setattr(maintained_hnsw,"CandidateQuery",capture)
    for binding in (BIND_CORE,BIND_COMP):
        with pytest.raises(StopBeforeDatabase):
            maintained_hnsw.run_hnsw_binding(cast(Any,None),publication,supply.artifact.profile,
                rebuild_id="functional-rebuild",vector=QUERY_VECTOR,task_id="public-functional-query",
                source_binding_id=binding,publication_pin=pin,attempt_identity="w5-semantic-g1")
    assert tuple(item.candidate_query for item in evaluations) == tuple(captured)


def test_failed_execution_keeps_primary_error_and_emits_strict_failed_evidence(tmp_path: Path, capsys: Any) -> None:
    task = next(task for task in load_calibration_catalog().calibration_tasks() if task.task_id=="cal-01")
    source = b"# public failed-setup fixture\n"
    digest = digest_bytes(source)
    plan = make_plan(attempt_id="w5-semantic-g1",generation=1,tasks=(task,),
                     input_identity=digest,representation_report_identity=digest,
                     publication_identity=digest,artifact_profile_identity=digest,
                     controller_admission_sha256=digest,source_closure={"fixture.py":digest},
                     arms=("exact_vector","hnsw_vector","hybrid_rrf")).validate()
    journal = admit_attempt(tmp_path/"attempts",{**plan.to_mapping(),"candidate_closure_digests":{"fixture.py":digest}},
                            {"fixture.py":source})
    adapter = make_functional_adapter(tmp_path/"adapter","unused",{
        "ann_explain":("public explain",),"ann_candidates":("public query",),
    })
    context = cast(experiment.FunctionalContext,SimpleNamespace(
        task=task,postgres=SimpleNamespace(adapter=adapter),
    ))
    primary = ExperimentRefusal("synthetic_setup_failure")
    with pytest.raises(ExperimentRefusal) as caught:
        experiment._finalize(context,journal,ResultV2Collector(plan),primary,{},repetitions=plan.repetitions)
    assert caught.value is primary
    output = capsys.readouterr().out
    with pytest.raises(ArtifactRefusal,match="artifact_incomplete"):
        decode_attempt_artifacts(output.encode())  # Existing paired decoder still requires two generations.
    frames = [json.loads(line.removeprefix(ARTIFACT_LINE_PREFIX)) for line in output.splitlines()
              if line.startswith(ARTIFACT_LINE_PREFIX)]
    members = [frame for frame in frames if frame["kind"]=="member"]
    assert len(members) == len(MEMBER_NAMES) and frames[-1]["kind"] == "footer"
    for member in members:
        assert member["attempt_id"] == "w5-semantic-g1"
        assert base64.b64decode(member["data"],validate=True) == (journal.directory/member["member"]).read_bytes()
    proof = json.loads(next(line.removeprefix(experiment.PROOF_PREFIX) for line in output.splitlines()
                            if line.startswith(experiment.PROOF_PREFIX)))
    assert proof["status"] == "failed" and proof["ann_completed"] is False
    assert proof["worker_receipts_claimed"] is False
    assert proof["planner_forced_field_scope"] == "maintained_default_not_transport_observation"
    terminal = json.loads((journal.directory/"terminal.json").read_bytes())
    assert terminal["status"] == "failed" and terminal["observation_count"] == 1


def _completed_framing_fixture(root: Path) -> tuple[Any,Any,Any,dict[str,object]]:
    """Typed frame fixture only; no database, SQL, model or runtime acceptance."""
    task = next(item for item in load_calibration_catalog().calibration_tasks() if item.task_id=="cal-01")
    source = b"# synthetic completed framing fixture\n";digest = digest_bytes(source)
    plan = make_plan(attempt_id="w5-semantic-g1",generation=1,tasks=(task,),input_identity=digest,
        representation_report_identity=digest,publication_identity=digest,artifact_profile_identity=digest,
        controller_admission_sha256=digest,source_closure={"fixture.py":digest},
        arms=("exact_vector","hnsw_vector","hybrid_rrf")).validate()
    journal = admit_attempt(root/"attempts",{**plan.to_mapping(),"candidate_closure_digests":{"fixture.py":digest}},
                            {"fixture.py":source})
    collector = ResultV2Collector(plan)
    for repetition in range(1,plan.repetitions+1):
        for arm in plan.arms:
            collector.add_cell({"arm_id":arm,"task_id":task.task_id,"repetition":repetition},
                               ExperimentCell(arm,task.task_id,ExecutionState.COMPLETED,elapsed_ns=0,
                                              query_bytes=0,cleanup_status="verified"))
        journal.append({"event":"query_observed","arm_id":"hnsw_vector","execution_state":"completed","repetition":repetition})
    records = tuple({"route":route,"psql_exit":0,"inherited_options_preserved":True,
                     "planner_option_appended":True,"inherited_pgoptions_sha256":None,
                     "effective_pgoptions_sha256":digest_bytes(PLANNER_OPTION.encode())}
                    for route in ("ann_explain","ann_candidates") for _ in range(6))
    adapter = SimpleNamespace(read_receipts=lambda:records,allowed=())
    context = SimpleNamespace(task=task,postgres=SimpleNamespace(adapter=adapter))
    session = {"enable_seqscan":"on","enable_sort":"on","reader_role":True,"transaction_read_only":"on"}
    return context,journal,collector,{"before":session,"after":session}


def _assert_six_raw_frames(output: str,journal: Any) -> None:
    frames = [json.loads(line.removeprefix(ARTIFACT_LINE_PREFIX)) for line in output.splitlines()
              if line.startswith(ARTIFACT_LINE_PREFIX)]
    members = [frame for frame in frames if frame["kind"]=="member"]
    assert len(members)==6 and frames[-1]["kind"]=="footer"
    for frame in members:
        data=base64.b64decode(frame["data"],validate=True)
        assert data==(journal.directory/frame["member"]).read_bytes()
        assert frame["length"]==len(data) and frame["sha256"]==digest_bytes(data)


def test_completed_finalizer_emits_strict_nine_cell_result_and_every_raw_member(tmp_path: Path,capsys: Any) -> None:
    context,journal,collector,sessions = _completed_framing_fixture(tmp_path)
    proof = experiment._finalize(context,journal,collector,None,sessions,repetitions=3)
    output = capsys.readouterr().out
    result=decode_result_frames(output.encode())["w5-semantic-g1"]
    assert result.status=="completed" and len(result.cells)==9 and proof["ann_completed"] is True
    _assert_six_raw_frames(output,journal)
    assert dict(result.raw_journal)=={name:{"length":len((journal.directory/name).read_bytes()),
        "sha256":digest_bytes((journal.directory/name).read_bytes())} for name in MEMBER_NAMES}


def test_result_validation_failure_still_emits_every_original_member(tmp_path: Path,capsys: Any) -> None:
    context,journal,_collector,sessions = _completed_framing_fixture(tmp_path)
    def refuse(**_kwargs: Any) -> Any:raise ExperimentRefusal("synthetic_result_validation_failure")
    collector=cast(ResultV2Collector,SimpleNamespace(finish=refuse))
    with pytest.raises(ExperimentRefusal,match="synthetic_result_validation_failure"):
        experiment._finalize(context,journal,collector,None,sessions,repetitions=3)
    output=capsys.readouterr().out
    _assert_six_raw_frames(output,journal)
    assert "REPO_MAP_W5_RESULT_V2 " not in output


@pytest.mark.parametrize("has_primary",[False,True])
def test_receipt_read_failure_retains_failed_result_and_raw_members(tmp_path: Path,capsys: Any,has_primary: bool) -> None:
    context,journal,collector,sessions = _completed_framing_fixture(tmp_path)
    def unreadable() -> Any:raise OSError("synthetic receipt IO failure")
    context.postgres.adapter.read_receipts=unreadable
    primary=ExperimentRefusal("synthetic_existing_failure") if has_primary else None
    with pytest.raises(ExperimentRefusal) as caught:
        experiment._finalize(context,journal,collector,primary,sessions,repetitions=3)
    if primary is not None:assert caught.value is primary
    output=capsys.readouterr().out
    assert decode_result_frames(output.encode())["w5-semantic-g1"].status=="failed"
    _assert_six_raw_frames(output,journal)
