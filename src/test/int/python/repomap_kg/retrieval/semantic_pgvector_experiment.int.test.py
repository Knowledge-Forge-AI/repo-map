"""Optional W5 paired calibration experiment (ADR 0136/0137).

The test is selected only by the existing ``requires_pgvector`` profile.  The
model response is supplied by the phase-private component supervisor; a
missing or incomplete response is a failed attempt, never an empty success.
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

import pytest

from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.lexical_service import build_graph_lexical_generation
from common_lore_index.storage import apply_migrations, default_rdbms_root
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_FIXTURE_ROOT,
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus,
    publish_and_load_sqlite_corpus,
)
from repomap_test_support.semantic_candidate_restore import cleanup_optional_sql_fixture
from repomap_test_support.w5_experiment_ann_diagnostic import run_hnsw_catalog_diagnostic
from repomap_test_support.w5_experiment_postgres import (
    HNSW_OWNER_ROLE,
    READ_ROLE,
    WRITE_ROLE,
    execute_sql,
    import_generation,
    install_candidate_schema,
)
from repomap_test_support.w5_experiment_results import ResultV2Run, finalize_attempt_evidence, safe_failure_code
from repomap_test_support.w5_experiment_support import (
    DECLARED_PROFILE_IDENTITY, EXPERIMENT_ATTEMPTS_ROOT, PUBLIC_ALIASES,
    calibration_task_manifest, calibration_tasks_for_generation, candidate_publication,
    experiment_source_closure, load_calibration_catalog, make_generation_plan,
    make_public_reader, record_baseline, selected_public_binding_ids,
    worker_source_closure,
)
from repomap_test_support.w5_experiment_vector import (
    VECTOR_ARM_IDS, baseline_file_metrics, baseline_file_metrics_with_correspondence,
    run_vector_task,
)
from repomap_test_support.w5_generator_support import GeneratorFixtureReader
from retrieval_evaluation_execution import ArmContext, TaskOutcome
from retrieval_evaluation_attempts import admit_attempt
from retrieval_evaluation_fts import execute_postgres_native_fts_task
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask, load_freeze_manifest
from retrieval_semantic_experiment_artifacts import emit_attempt_artifacts
from retrieval_semantic_experiment_bridge import ComponentExchange
from retrieval_semantic_experiment_contracts import (
    ExperimentCostLedger, ExperimentRefusal, TIMEOUT_POLICY, canonical_json_bytes,
)
from retrieval_semantic_experiment_evaluator import seal_component_response
from retrieval_semantic_baseline_capture import generation_aliases_for, make_baseline_correspondence_runner
from retrieval_semantic_experiment_scope import BaselineCorrespondenceSidecar
from retrieval_semantic_experiment_timing import assign_campaign_cleanup_cost, measure_query_work
from retrieval_semantic_generator_inputs import build_worker_request, prepare_public_generation_input
from retrieval_semantic_fusion import AdmittedArmObservation

# Opt in before source freeze; ordinary CI deselects this optional owner.
EMIT_RESULT_V2 = True

def _publish_generation(root: Path, database: Any, generation: int) -> tuple[Any, Any, GeneratorFixtureReader, GeneratorFixtureReader, ArmContext]:
    working = materialize_mixed_v1_working_copy(root / "working-shared", generation=generation)
    sqlite_home = write_mixed_v1_sqlite_home(root / "sqlite-shared", working, declared_aliases=("core", "companion", "feeds"))
    sqlite_state = publish_and_load_sqlite_corpus(sqlite_home, selected_aliases=PUBLIC_ALIASES)
    postgres_home = write_mixed_v1_postgres_home(
        root / f"postgres-g{generation}", working,
        host=database.host, port=database.port, database=database.database,
        user=database.user, password=database.password, declared_aliases=("core", "companion", "feeds"),
    )
    postgres_state = publish_and_load_postgres_corpus(
        postgres_home, selected_aliases=PUBLIC_ALIASES, psql_command=database.psql_command
    )
    reader = make_public_reader(postgres_state, psql_command=database.psql_command)
    sqlite_reader = GeneratorFixtureReader(sqlite_state, sqlite_state.policy, "sqlite")
    generation_aliases = generation_aliases_for(sqlite_state.manifest)
    from common_lore_index.retrieval.projection_build import build_captured_text_projection
    from retrieval_evaluation_views import materialize_native_search_view

    sqlite_projection = build_captured_text_projection(sqlite_state.projection_inputs(), sqlite_state.policy)
    native_view = materialize_native_search_view(
        root / f"native-g{generation}", manifest=sqlite_state.manifest, bundle=sqlite_state.bundle,
        store=sqlite_state.store, policy=sqlite_state.policy, selected_aliases=generation_aliases,
    )
    postgres_projection = build_captured_text_projection(postgres_state.projection_inputs(), postgres_state.policy)
    config = load_graph_registry_config_home(postgres_home)
    if not isinstance(config, OpsConfig):
        raise ExperimentRefusal("postgres_config_required")
    lexical = build_graph_lexical_generation(
        config, MIXED_V1_GRAPH_ID,
        selected_binding_ids=(binding_id_for_alias("core"), binding_id_for_alias("companion")),
        authorize_body=True,
    )
    if lexical.result != "published":
        raise ExperimentRefusal("lexical_publication_refused")
    context = ArmContext(
        native_view, sqlite_state.home_root, sqlite_projection, postgres_state.home_root,
        postgres_projection, database.psql_command,
    )
    return sqlite_state, postgres_state, sqlite_reader, reader, context

@pytest.mark.requires_pgvector
def test_w5_pgvector_component_paired_calibration_experiment(tmp_path: Path) -> None:
    """Run both accepted generations against one disposable current PostgreSQL graph."""
    catalog = load_calibration_catalog()
    freeze = load_freeze_manifest(MIXED_V1_FIXTURE_ROOT / "freeze-v1.json")
    task_manifest = calibration_task_manifest(catalog)
    source_root = Path(__file__).resolve().parents[6]
    source_files, source_closure = experiment_source_closure(source_root)
    _component_source_files, component_source_closure = worker_source_closure(source_root)
    attempts_root = EXPERIMENT_ATTEMPTS_ROOT

    with temporary_postgres() as database:
        apply_migrations(default_rdbms_root(), database.psql_args, psql_command=database.psql_command)
        journals: list[tuple[Any, ExperimentCostLedger, str, dict[str, object]]] = []
        result_v2 = ResultV2Run(enabled=EMIT_RESULT_V2)
        primary: BaseException | None = None
        cleanup_error: BaseException | None = None
        attribution_error: BaseException | None = None
        result_v2_errors: tuple[BaseException, ...] = ()
        cleanup_ns = 0
        try:
            try:
                installation_started = time.perf_counter_ns()
                install_candidate_schema(database)
                run_hnsw_catalog_diagnostic(database)
                installation_ns = time.perf_counter_ns() - installation_started
                for generation in (1, 2):
                    costs = ExperimentCostLedger(
                        installation_ns=installation_ns if generation == 1 else 0
                    )
                    journal: Any | None = None
                    sealed: Any | None = None
                    collector: Any | None = None
                    cell_sink: Any = None
                    try:
                        started = time.perf_counter_ns()
                        sqlite_state, postgres_state, sqlite_reader, reader, context = _publish_generation(
                            tmp_path, database, generation
                        )
                        representation_report = reader.read_representations()
                        tasks = calibration_tasks_for_generation(catalog, generation)
                        inputs = prepare_public_generation_input(
                            representation_report, tasks, read_current=reader.read_pin,
                            read_representations=reader.read_representations,
                        )
                        costs.preparation_ns = time.perf_counter_ns() - started
                        attempt_id = f"w5-semantic-g{generation}"
                        request = build_worker_request(
                            inputs, attempt_id=attempt_id,
                            artifact_profile_identity=DECLARED_PROFILE_IDENTITY,
                        )
                        started = time.perf_counter_ns()
                        exchange = ComponentExchange.publish_request(
                            attempt_id=attempt_id,
                            request=request,
                            expected_source_closure=component_source_closure,
                        )
                        exchange.emit_request_readiness()
                        exchange = exchange.await_controller_admission()
                        costs.request_ns = time.perf_counter_ns() - started
                        controller_sha256 = exchange.admission_sha256
                        admission_raw = exchange.admission_raw
                        if controller_sha256 is None or admission_raw is None:
                            raise ExperimentRefusal("controller_admission_required")
                        plan = make_generation_plan(
                            attempt_id=attempt_id, generation=generation,
                            tasks=tasks, inputs=inputs,
                            controller_admission_sha256=controller_sha256,
                            source_closure=component_source_closure,
                            fixture_id=freeze.fixture_id,
                            freeze_sha256=freeze.freeze_digest(),
                            policy_digest=freeze.policy_digest,
                        )
                        collector = result_v2.register(plan)
                        cell_sink = result_v2.cell_sink(collector)
                        source_files, source_closure = experiment_source_closure(source_root)
                        declaration = {
                            **plan.to_mapping(),
                            "candidate_closure_digests": dict(source_closure),
                            "component_source_closure": dict(component_source_closure),
                        }
                        input_files = {
                            "request.json": exchange.request_raw,
                            "admission.json": admission_raw,
                            "calibration-tasks.json": task_manifest,
                            "freeze-v1.json": (MIXED_V1_FIXTURE_ROOT / "freeze-v1.json").read_bytes(),
                            "publication.json": canonical_json_bytes(reader.read_pin().to_dict()),
                        }
                        journal = admit_attempt(
                            attempts_root, declaration, source_files, input_files=input_files
                        )
                        journal.append({
                            "event": "component_admission_accepted",
                            "generation": generation,
                            "request_sha256": exchange.ready.request_sha256,
                            "controller_admission_sha256": controller_sha256,
                        })
                        print(exchange.admission_ack_line, flush=True)
                        started = time.perf_counter_ns()
                        response_files = exchange.await_response(timeout_seconds=TIMEOUT_POLICY["component_response_seconds"])
                        costs.component_ns = time.perf_counter_ns() - started
                        sealed = seal_component_response(
                            inputs, response_files,
                            expected_admission_sha256=controller_sha256,
                            expected_source_closure=component_source_closure,
                        )
                        _current_files, current_source_closure = experiment_source_closure(source_root)
                        if current_source_closure != source_closure:
                            raise ExperimentRefusal("experiment_source_closure_changed")
                        publication = candidate_publication(reader)
                        rebuild_id = f"w5-g{generation}-{sealed.artifact.worker_report_identity[7:23]}"
                        started = time.perf_counter_ns()
                        import_generation(database, publication, sealed.artifact, rebuild_id=rebuild_id)
                        costs.import_ns = time.perf_counter_ns() - started
                        pin = reader.read_pin()
                        baseline_runner = make_baseline_correspondence_runner(
                            BaselineCorrespondenceSidecar, generation_aliases_for(sqlite_state.manifest), context.native_view,
                            sqlite_reader, reader, sqlite_state, postgres_state,
                        )

                        with measure_query_work(costs):
                            for task in tasks:
                                for repetition in range(1, plan.repetitions + 1):
                                    grade_baseline_files = result_v2.baseline_callback_for_runner(
                                        collector,
                                        repetition=repetition,
                                        runner=baseline_runner,
                                        sqlite_projection=context.sqlite_projection,
                                        postgres_projection=context.postgres_projection,
                                        metrics_reader=baseline_file_metrics_with_correspondence,
                                        legacy_reader=baseline_file_metrics,
                                        pin=pin,
                                    )
                                    for arm_id in (
                                        "native_tools_baseline",
                                        "current_graph_baseline:sqlite",
                                        "current_graph_baseline:postgresql",
                                        "captured_projection_reference:sqlite",
                                        "captured_projection_reference:postgresql",
                                    ):
                                        def execute_context_arm(
                                            selected_arm: str = arm_id,
                                            selected_task: EvaluationTask = task,
                                        ) -> TaskOutcome:
                                            return baseline_runner.execute(
                                                selected_arm,
                                                selected_task,
                                                result_v2.captured_executor(
                                                    context,
                                                    collector=collector, arm_id=selected_arm,
                                                    task=selected_task, repetition=repetition,
                                                ),
                                            )
                                        outcome = record_baseline(
                                            journal, task, arm_id, repetition, execute_context_arm,
                                            file_metrics_callback=grade_baseline_files,
                                        )
                                        costs.failures += int(outcome[0] == ExecutionState.FAILED)
                                    def execute_lexical_arm(
                                        selected_task: EvaluationTask = task,
                                    ) -> TaskOutcome:
                                        return baseline_runner.execute(
                                            "postgres_native_fts:postgresql",
                                            selected_task,
                                            lambda _expected: execute_postgres_native_fts_task(
                                                selected_task, postgres_state.home_root
                                            ),
                                        )
                                    lexical_outcome = record_baseline(
                                        journal, task, "postgres_native_fts:postgresql", repetition,
                                        execute_lexical_arm, file_metrics_callback=grade_baseline_files,
                                    )
                                    costs.failures += int(lexical_outcome[0] == ExecutionState.FAILED)
                                    lexical_state, lexical_envelope, _lex_ns, _lex_bytes = lexical_outcome
                                    lexical_arm = AdmittedArmObservation(
                                        arm_id="postgres_native_fts:postgresql", mode=task.requested_mode,
                                        verified_pin=pin, execution_state=lexical_state, envelope=lexical_envelope,
                                        selected_binding_ids=selected_public_binding_ids(task),
                                    )
                                    query = next(item for item in sealed.artifact.queries if item.task_id == task.task_id)
                                    if query.state != "admitted" or query.vector is None:
                                        state = ExecutionState.REFUSED if query.state == "refused" else ExecutionState.UNAVAILABLE
                                        result_v2.record_unadmitted_vector_cells(
                                            journal, task_id=task.task_id, generation=generation,
                                            repetition=repetition,
                                            state=state, reason=query.reason or "query_not_admitted",
                                            arm_ids=VECTOR_ARM_IDS, cell_sink=cell_sink,
                                        )
                                        continue
                                    run_vector_task(
                                        journal, database, publication, sealed, inputs, task, repetition,
                                        pin=pin, rebuild_id=rebuild_id, attempt_identity=plan.attempt_id,
                                        lexical_arm=lexical_arm, costs=costs,
                                        result_cell_sink=cell_sink,
                                    )
                            _final_files, final_source_closure = experiment_source_closure(source_root)
                            if final_source_closure != source_closure:
                                raise ExperimentRefusal("experiment_source_closure_changed")
                        if costs.failures:
                            raise ExperimentRefusal("experiment_recorded_execution_failure")
                        journals.append((
                            journal, costs, "completed",
                            {
                                "status": "completed",
                                "generation": generation,
                                "held_out_executed": False,
                                "component": sealed.response_identity,
                                "component_response_cost": dict(sealed.response_cost),
                                "component_counts": dict(sealed.response_counts),
                                "timeout_policy": dict(TIMEOUT_POLICY),
                                "rebuild_id": rebuild_id,
                            },
                        ))
                    except BaseException as exc:
                        costs.failures += 1
                        if journal is not None:
                            failure_code = safe_failure_code(
                                exc, fallback="attempt_failed"
                            )
                            journal.append({
                                "event": "attempt_failed",
                                "failure_type": type(exc).__name__,
                                "failure_code": failure_code,
                                "timeout_policy": dict(TIMEOUT_POLICY),
                            })
                            journals.append((
                                journal, costs, "failed",
                                {
                                    "status": "failed",
                                    "generation": generation,
                                    "failure_type": type(exc).__name__,
                                    "failure_code": failure_code,
                                    "timeout_policy": dict(TIMEOUT_POLICY),
                                    **({"component": sealed.response_identity} if sealed is not None else {}),
                                    **({"component_response_cost": dict(sealed.response_cost)} if sealed is not None else {}),
                                    **({"component_counts": dict(sealed.response_counts)} if sealed is not None else {}),
                                },
                            ))
                        raise
            except BaseException as exc:
                primary = exc
            cleanup_started = time.perf_counter_ns()
            try:
                cleanup_optional_sql_fixture(
                    database, reader=READ_ROLE, writer=WRITE_ROLE,
                    extra_roles=(HNSW_OWNER_ROLE,), execute_fn=execute_sql,
                )
            except BaseException as exc:
                cleanup_error = exc
            cleanup_ns = time.perf_counter_ns() - cleanup_started
        finally:
            cleanup_status = "verified" if cleanup_error is None else "failed"
            try:
                assign_campaign_cleanup_cost(
                    tuple(item[1] for item in journals), cleanup_ns
                )
                cleanup_costs = tuple(item[1].cleanup_ns for item in journals)
                if journals and (
                    cleanup_costs[-1] != cleanup_ns
                    or any(value != 0 for value in cleanup_costs[:-1])
                    or sum(value or 0 for value in cleanup_costs) != cleanup_ns
                ):
                    raise ExperimentRefusal("campaign_cleanup_cost_attribution_failed")
            except BaseException as exc:
                attribution_error = exc
            attribution_error, result_v2_errors = finalize_attempt_evidence(
                journals,
                result_v2=result_v2,
                cleanup_status=cleanup_status,
                cleanup_error=cleanup_error,
                attribution_error=attribution_error,
                emit_legacy=emit_attempt_artifacts,
            )
        if result_v2_errors:
            retained_error = primary or cleanup_error or attribution_error or result_v2_errors[0]
            for error in result_v2_errors:
                retained_error.add_note("w5_result_v2_secondary:" + safe_failure_code(error, fallback="result_v2_failed"))
        if primary is not None: raise primary
        if cleanup_error is not None:
            raise cleanup_error
        if attribution_error is not None:
            raise attribution_error
        if result_v2_errors:
            raise result_v2_errors[0]
