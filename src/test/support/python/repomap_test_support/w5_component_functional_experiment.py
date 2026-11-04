"""One-generation real SQL orchestration with explicitly synthetic vectors."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any

from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.lexical_service import build_graph_lexical_generation
from common_lore_index.storage import apply_migrations, default_rdbms_root
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.semantic_candidate_cleanup import optional_sql_fixture_cleanup
from repomap_test_support.w5_component_functional_supply import QUERY_VECTOR, SUPPLIER_IDENTITY, synthetic_vector_supply
from repomap_test_support.w5_component_functional_transport import (
    FunctionalPostgres, functional_hnsw_queries, functional_sql_payloads, observe_default_reader_session,
)
from repomap_test_support.w5_component_planner_adapter import PLANNER_OPTION, make_functional_adapter
from repomap_test_support.w5_experiment_postgres import HNSW_OWNER_ROLE, READ_ROLE, WRITE_ROLE, import_generation, install_candidate_schema
from repomap_test_support.w5_experiment_support import (
    EXPERIMENT_ATTEMPTS_ROOT, candidate_publication, experiment_source_closure,
    load_calibration_catalog, prepare_postgres_generation, selected_public_binding_ids,
)
from repomap_test_support.w5_experiment_vector import run_vector_task
from retrieval_evaluation_attempts import admit_attempt
from retrieval_evaluation_fts import execute_postgres_native_fts_task
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_baseline_result_frames import emit_result_frames, read_raw_journal_members
from retrieval_semantic_baseline_result_objects import BaselineResultV2, ResultV2Collector
from retrieval_semantic_experiment_contracts import ExperimentCostLedger, ExperimentRefusal, digest_bytes, digest_json, make_plan
from retrieval_semantic_fusion import AdmittedArmObservation
from retrieval_semantic_experiment_artifacts import emit_attempt_artifacts
from retrieval_semantic_generator_inputs import prepare_public_generation_input


PROOF_PREFIX = "CLOE_W5_FUNCTIONAL_ANN_PROOF_V1 "
REBUILD_ID = "functional-axis-g1"


@dataclass(frozen=True)
class FunctionalContext:
    postgres: FunctionalPostgres
    task: EvaluationTask
    inputs: Any
    pin: Any
    publication: Any
    supply: Any
    lexical: AdmittedArmObservation
    source_files: dict[str, bytes]
    source_closure: dict[str, str]


def _functional_sources() -> tuple[dict[str, bytes], dict[str, str]]:
    root = Path(__file__).resolve().parents[5]
    files, _closure = experiment_source_closure(root)
    owners = (
        "src/test/int/python/repomap_kg/retrieval/semantic_observed_ann.int.test.py",
        "src/test/support/python/repomap_test_support/w5_component_functional_experiment.py",
        "src/test/support/python/repomap_test_support/w5_component_functional_supply.py",
        "src/test/support/python/repomap_test_support/w5_component_functional_transport.py",
        "src/test/support/python/repomap_test_support/w5_component_planner_adapter.py",
        "src/test/support/python/repomap_test_support/postgres_container_config.py",
    )
    for name in owners:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ExperimentRefusal("functional_source_missing")
        files[name] = path.read_bytes()
    return files, {name:digest_bytes(raw) for name,raw in files.items()}


def _lexical_arm(published: Any, task: EvaluationTask, pin: Any) -> AdmittedArmObservation:
    config = load_graph_registry_config_home(published.home_root)
    if not isinstance(config,OpsConfig):
        raise ExperimentRefusal("functional_postgres_config")
    generated = build_graph_lexical_generation(
        config,task.graph_id,selected_binding_ids=selected_public_binding_ids(task),authorize_body=True,
    )
    if generated.result != "published":
        raise ExperimentRefusal("functional_lexical_publication")
    state,envelope,_elapsed,_byte_count = execute_postgres_native_fts_task(task,published.home_root)
    return AdmittedArmObservation(
        arm_id="postgres_native_fts:postgresql", mode=task.requested_mode,
        verified_pin=pin, execution_state=state, envelope=envelope,
        selected_binding_ids=selected_public_binding_ids(task),
    )


def _prepare_context(root: Path, database: Any) -> FunctionalContext:
    apply_migrations(default_rdbms_root(),database.psql_args,psql_command=database.psql_command)
    published,reader = prepare_postgres_generation(root,database=database,generation=1)
    task = next(task for task in load_calibration_catalog().calibration_tasks() if task.task_id=="cal-01")
    if task.generation != 1 or task.selected_bindings != ("core","companion"):
        raise ExperimentRefusal("functional_task_changed")
    inputs = prepare_public_generation_input(
        reader.read_representations(),(task,),read_current=reader.read_pin,
        read_representations=reader.read_representations,
    )
    pin = reader.read_pin()
    publication = candidate_publication(reader)
    supply = synthetic_vector_supply(inputs)
    evaluations = functional_hnsw_queries(
        publication,supply.artifact.profile,pin,selected_public_binding_ids(task),
        rebuild_id=REBUILD_ID,vector=QUERY_VECTOR,
    )
    adapter = make_functional_adapter(root/"planner-adapter",database.psql_command,functional_sql_payloads(evaluations))
    files,closure = _functional_sources()
    return FunctionalContext(FunctionalPostgres(database,adapter),task,inputs,pin,publication,supply,
                             _lexical_arm(published,task,pin),files,closure)


def _finalize(context: FunctionalContext, journal: Any, collector: ResultV2Collector,
              primary: BaseException | None, sessions: dict[str, object], *, repetitions: int) -> dict[str, object]:
    observations = journal.directory / "observations.jsonl"
    events = [json.loads(line) for line in observations.read_bytes().splitlines()] if observations.exists() else []
    ann = [event for event in events if event.get("event")=="query_observed" and event.get("arm_id")=="hnsw_vector"]
    completed = len(ann)==repetitions and all(event.get("execution_state")=="completed" for event in ann)
    if primary is None and not completed:
        primary = ExperimentRefusal("functional_ann_not_selected")
    try:
        records = context.postgres.adapter.read_receipts()
    except (OSError,ValueError,TypeError,KeyError):
        records = ()
        if primary is None:
            primary = ExperimentRefusal("functional_transport_receipt_unreadable")
    expected_calls = repetitions * len(selected_public_binding_ids(context.task))
    counts = {route:sum(record["route"]==route for record in records) for route in ("ann_explain","ann_candidates")}
    if primary is None and (counts != {"ann_explain":expected_calls,"ann_candidates":expected_calls} or any(
        record["psql_exit"] != 0 or record["inherited_options_preserved"] is not True for record in records
    )):
        primary = ExperimentRefusal("functional_transport_receipt")
    for record in records:
        if record["route"] == "unchanged":
            valid = record["planner_option_appended"] is False and record["inherited_pgoptions_sha256"] == record["effective_pgoptions_sha256"]
        else:
            valid = record["route"] in ("ann_explain","ann_candidates") and record["planner_option_appended"] is True and record["inherited_pgoptions_sha256"] is None and record["effective_pgoptions_sha256"] == digest_bytes(PLANNER_OPTION.encode())
        if not valid and primary is None:
            primary = ExperimentRefusal("functional_transport_option_hash")
    for record in records:
        journal.append({"event":"functional_planner_transport",**record})
    journal.append({"event":"functional_proof_finalized","model_execution":False,
                    "worker_receipts_claimed":False,"scientific_acceptance":False,
                    "planner_forced_field_scope":"maintained_default_not_transport_observation",
                    "effective_planner_option_evidence":"functional_planner_transport_records"})
    status = "completed" if primary is None else "failed"
    code = None if primary is None else "functional_sql_boundary_incomplete"
    journal.finish(status,{"status":status,"generation":1,"failure_code":code,"functional_only":True,"model_execution":False,
                           "held_out_executed":False,"worker_receipts_claimed":False})
    try:
        result = collector.finish(status=status,failure_code=code,raw_journal_members=read_raw_journal_members(journal.directory))
        BaselineResultV2.from_mapping(result.to_mapping())
        emit_result_frames((result,),stream=sys.stdout)
    finally:
        emit_attempt_artifacts((journal.directory,),stream=sys.stdout)
    proof = {
        "schema":"cloe-w5-functional-ann-proof-v1","generation":1,"status":status,
        "ann_completed":completed and primary is None,
        "controlled_options":["enable_seqscan=off","enable_sort=off"],
        "allowed_sql_sha256":dict(context.postgres.adapter.allowed),
        "per_call_transport_records":list(records),"reader_sessions":sessions,
        "session_observation_scope":"separate_sessions_not_explain_session_readback",
        "planner_forced_field_scope":"maintained_default_not_transport_observation",
        "effective_planner_option_evidence":"functional_planner_transport_records",
        "vector_supplier":"synthetic_axis_384d_test_profile","model_execution":False,
        "worker_receipts_claimed":False,"learned_attempt16":False,
        "scientific_acceptance":False,"production_admitted":False,
    }
    print(PROOF_PREFIX+json.dumps(proof,sort_keys=True,separators=(",",":")),flush=True)
    if primary is not None:
        raise primary
    return proof


def _execute_context(context: FunctionalContext) -> dict[str, object]:
    plan = make_plan(
        attempt_id="w5-semantic-g1",generation=1,tasks=(context.task,),
        input_identity=context.inputs.input_identity,
        representation_report_identity=context.inputs.representation_report_identity,
        publication_identity=digest_json(context.inputs.provenance.to_dict()),
        artifact_profile_identity=SUPPLIER_IDENTITY,controller_admission_sha256=SUPPLIER_IDENTITY,
        source_closure=context.source_closure,arms=("exact_vector","hnsw_vector","hybrid_rrf"),
    ).validate()
    journal = admit_attempt(EXPERIMENT_ATTEMPTS_ROOT,{
        **plan.to_mapping(),"candidate_closure_digests":context.source_closure,
        "functional_only":True,"model_execution":False,"worker_receipts_claimed":False,
    },context.source_files)
    collector = ResultV2Collector(plan)
    costs = ExperimentCostLedger()
    sessions: dict[str, object] = {}
    primary: BaseException | None = None
    try:
        with optional_sql_fixture_cleanup(context.postgres,reader=READ_ROLE,writer=WRITE_ROLE,extra_roles=(HNSW_OWNER_ROLE,)):
            install_candidate_schema(context.postgres)
            import_generation(context.postgres,context.publication,context.supply.artifact,rebuild_id=REBUILD_ID)
            sessions["before"] = observe_default_reader_session(context.postgres)
            for repetition in range(1,plan.repetitions+1):
                run_vector_task(
                    journal,context.postgres,context.publication,context.supply,context.inputs,context.task,repetition,
                    pin=context.pin,rebuild_id=REBUILD_ID,attempt_identity=plan.attempt_id,
                    lexical_arm=context.lexical,costs=costs,result_cell_sink=collector.add_cell,
                )
            sessions["after"] = observe_default_reader_session(context.postgres)
            if sessions["before"] != sessions["after"]:
                raise ExperimentRefusal("functional_default_session_drift")
    except BaseException as error:
        primary = error
    try:
        return _finalize(context,journal,collector,primary,sessions,repetitions=plan.repetitions)
    except BaseException as finalization_error:
        if primary is not None and finalization_error is not primary:
            primary.add_note("Functional evidence finalization also failed.")
            raise primary
        raise


def run_functional_proof(root: Path) -> dict[str, object]:
    """Execute only through the canonical separately allocated pgvector profile."""
    with temporary_postgres() as database:
        return _execute_context(_prepare_context(root,database))


__all__ = ["PROOF_PREFIX","run_functional_proof"]
