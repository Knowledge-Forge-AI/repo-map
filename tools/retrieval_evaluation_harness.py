"""Retrieval evaluation harness: freeze guard, attempt declaration, and calibration runner (S3)."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from common_lore_index.retrieval.projection_build import CapturedTextProjection, build_captured_text_projection
from common_lore_index.retrieval.projection_text import REPRESENTATION_VERSION
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_FIXTURE_ROOT, MIXED_V1_GRAPH_ID, build_mixed_v1_projection_policy,
    compute_working_copy_digests, materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home, write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    PublishedCorpusState, publish_and_load_postgres_corpus, publish_and_load_sqlite_corpus,
)
from retrieval_evaluation_admission import admit_evaluation, candidate_source_files, runtime_profile, source_digests
from retrieval_evaluation_attempts import AttemptJournal
from retrieval_evaluation_comparability import describe_comparability
from retrieval_evaluation_execution import ArmContext, measure_task_repetitions
from retrieval_evaluation_grading import ExecutionState, GradedSlotRecord, aggregate_arm_summary
from retrieval_evaluation_schema import (
    ATTEMPT_DECLARATION_SCHEMA_VERSION, FREEZE_MANIFEST_SCHEMA_VERSION,
    AttemptDeclaration, FreezeManifest, TaskCatalog,
)
from retrieval_evaluation_views import materialize_native_search_view


BASELINE_REPORT_SCHEMA_VERSION = "cloe-retrieval-baseline-report-v1"
DEFAULT_ARMS: tuple[str, ...] = (
    "native_tools_baseline",
    "current_graph_baseline:sqlite",
    "current_graph_baseline:postgresql",
    "captured_projection_reference:sqlite",
    "captured_projection_reference:postgresql",
)


def _committed_fixture_file_digests(fixture_root: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    for path in sorted(fixture_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(fixture_root).as_posix()
        if rel.startswith(("tasks/", "baseline/")) or rel == "freeze-v1.json":
            continue
        raw = path.read_bytes()
        digests[rel] = "sha256:" + hashlib.sha256(raw).hexdigest()
    return digests


def build_freeze_manifest(
    catalog: TaskCatalog,
    *,
    work_dir: Path,
    fixture_root: Path = MIXED_V1_FIXTURE_ROOT,
) -> FreezeManifest:
    """Build the cryptographic FreezeManifest over catalog, fixture sources, and both generations."""
    catalog.validate()
    gen1_root = materialize_mixed_v1_working_copy(work_dir / "gen1", generation=1)
    gen2_root = materialize_mixed_v1_working_copy(work_dir / "gen2", generation=2)
    d1 = {
        f"{alias}/{rel}": info
        for (alias, rel), info in compute_working_copy_digests(gen1_root).items()
    }
    d2 = {
        f"{alias}/{rel}": info
        for (alias, rel), info in compute_working_copy_digests(gen2_root).items()
    }
    policy = build_mixed_v1_projection_policy(MIXED_V1_GRAPH_ID)
    return FreezeManifest(
        schema_version=FREEZE_MANIFEST_SCHEMA_VERSION,
        fixture_id=MIXED_V1_GRAPH_ID,
        catalog_sha256=catalog.catalog_digest(),
        committed_fixture_files=_committed_fixture_file_digests(fixture_root),
        generation_1_files=d1,
        generation_2_files=d2,
        representation_version=REPRESENTATION_VERSION,
        policy_digest=policy.policy_digest(),
    ).validate()


def verify_fixture_freeze_guard(
    catalog: TaskCatalog,
    freeze: FreezeManifest,
    *,
    work_dir: Path,
    fixture_root: Path = MIXED_V1_FIXTURE_ROOT,
) -> None:
    """Verify catalog, committed fixture files, materialized working copies, and policy against freeze."""
    catalog.validate()
    freeze.validate()
    if freeze.catalog_sha256 != catalog.catalog_digest():
        raise ValueError(
            f"catalog digest mismatch: freeze={freeze.catalog_sha256} actual={catalog.catalog_digest()}"
        )
    committed = _committed_fixture_file_digests(fixture_root)
    if dict(freeze.committed_fixture_files) != committed:
        raise ValueError("committed fixture files digest mismatch against freeze")
    gen1_root = materialize_mixed_v1_working_copy(work_dir / "gen1", generation=1)
    gen2_root = materialize_mixed_v1_working_copy(work_dir / "gen2", generation=2)
    d1 = {
        f"{alias}/{rel}": info
        for (alias, rel), info in compute_working_copy_digests(gen1_root).items()
    }
    d2 = {
        f"{alias}/{rel}": info
        for (alias, rel), info in compute_working_copy_digests(gen2_root).items()
    }
    if dict(freeze.generation_1_files) != d1:
        raise ValueError("generation 1 working copy digest mismatch against freeze")
    if dict(freeze.generation_2_files) != d2:
        raise ValueError("generation 2 working copy digest mismatch against freeze")
    policy = build_mixed_v1_projection_policy(MIXED_V1_GRAPH_ID)
    if freeze.policy_digest != policy.policy_digest():
        raise ValueError("projection policy digest mismatch against freeze")


def _compute_candidate_closure_digests(repo_root: Path) -> dict[str, str]:
    return source_digests(candidate_source_files(repo_root))


def declare_calibration_attempt(
    catalog: TaskCatalog,
    freeze: FreezeManifest,
    *,
    attempt_id: str = "calibration-attempt-1",
    split: str = "calibration",
    repetitions_per_task: int = 3,
    arms: tuple[str, ...] = DEFAULT_ARMS,
    pg_port: int = 55433,
    execution_purpose: str = "functional_check",
) -> AttemptDeclaration:
    """Create a validated AttemptDeclaration for the 24-task calibration split."""
    if split != "calibration":
        raise ValueError(
            f"W2 refuses attempt declaration for split {split!r}; held_out is reserved for W3"
        )
    repo_root = MIXED_V1_FIXTURE_ROOT.parents[4]
    cal_ids = tuple(t.task_id for t in catalog.calibration_tasks())
    return AttemptDeclaration(
        schema_version=ATTEMPT_DECLARATION_SCHEMA_VERSION,
        attempt_id=attempt_id,
        phase_id="REPOMAP-CLOE-RETRIEVAL1",
        split=split,
        freeze_sha256=freeze.freeze_digest(),
        catalog_sha256=catalog.catalog_digest(),
        ordered_task_ids=cal_ids,
        arms=arms,
        repetitions_per_task=repetitions_per_task,
        stopping_rule=f"complete_all_24_calibration_tasks_{repetitions_per_task}_repetitions_no_early_stop",
        replacement_policy="retain_failed_attempts_require_new_attempt_id_on_instrument_bug",
        candidate_closure_digests=_compute_candidate_closure_digests(repo_root),
        runner_profile={
            **runtime_profile(pg_port), "execution_purpose": execution_purpose,
        },
    ).validate()


def execute_calibration_baseline(
    catalog: TaskCatalog,
    freeze: FreezeManifest,
    declaration: AttemptDeclaration,
    *,
    work_dir: Path,
    pg_host: str = "127.0.0.1",
    pg_port: int = 55433,
    pg_database: str = "repomap_mixed_v1",
    pg_user: str = "repomap",
    pg_password: str | None = None,
    psql_command: str = "psql",
    include_postgres: bool = True,
    attempt_root: Path | None = None,
) -> dict[str, Any]:
    """Execute the declared 24-task calibration baseline across native, graph, and projection arms."""
    if not include_postgres and any(arm.endswith(":postgresql") for arm in declaration.arms):
        raise ValueError("declaration requires PostgreSQL arms but include_postgres=False")
    if declaration.runner_profile.get("execution_purpose") == "retained_calibration" and attempt_root is None:
        raise ValueError("retained calibration requires a persistent attempt_root")
    verify_fixture_freeze_guard(catalog, freeze, work_dir=work_dir / "freeze_guard")
    journal = admit_evaluation(
        declaration, catalog, freeze, attempt_root=attempt_root or work_dir / "functional-attempts",
        pg_port=pg_port, supported_arms=DEFAULT_ARMS,
    )
    try:
        report = _execute_admitted(
            catalog, freeze, declaration, work_dir=work_dir, journal=journal,
            postgres=(pg_host, pg_port, pg_database, pg_user, pg_password, psql_command),
            include_postgres=include_postgres,
        )
        if dict(declaration.candidate_closure_digests) != _compute_candidate_closure_digests(MIXED_V1_FIXTURE_ROOT.parents[4]):
            raise ValueError("candidate source changed during evaluation")
        journal.finish(report["status"], report)
        return report
    except BaseException as error:
        journal.append({"event": "attempt_failed", "failure_type": type(error).__name__})
        journal.finish("failed")
        raise


def _execute_admitted(
    catalog: TaskCatalog,
    freeze: FreezeManifest,
    declaration: AttemptDeclaration,
    *,
    work_dir: Path,
    journal: AttemptJournal,
    postgres: tuple[str, int, str, str, str | None, str],
    include_postgres: bool,
) -> dict[str, Any]:
    cal_tasks = catalog.calibration_tasks()
    expected_ids = tuple(task.task_id for task in cal_tasks)
    observations: list[dict[str, Any]] = []
    divergent_task_count = 0
    setup_timings_ns: dict[str, int] = {}
    setup_bytes: dict[str, dict[str, int | None]] = {}
    slots_by_arm: dict[str, dict[str, GradedSlotRecord]] = {arm: {} for arm in declaration.arms}
    reps = declaration.repetitions_per_task
    for gen in sorted({task.generation for task in cal_tasks}):
        context, generation_timings = _publish_generation(
            gen, work_dir, postgres, include_postgres and any(arm.endswith(":postgresql") for arm in declaration.arms),
        )
        setup_timings_ns.update(generation_timings)
        setup_bytes[f"sqlite_projection_gen{gen}"] = {
            "projected_body_input_bytes_read": context.sqlite_projection.aggregate_input_bytes_read,
            "total_artifact_store_bytes_read": None,
        }
        if context.postgres_projection is not None:
            setup_bytes[f"postgres_projection_gen{gen}"] = {
                "projected_body_input_bytes_read": context.postgres_projection.aggregate_input_bytes_read,
                "total_artifact_store_bytes_read": None,
            }
        journal.append({"event": "generation_published", "generation": gen, "setup_timings_ns": dict(setup_timings_ns)})
        for arm_id in slots_by_arm:
            for task in (task for task in cal_tasks if task.generation == gen):
                slot, task_observations, divergent = measure_task_repetitions(
                    task, arm_id, reps, lambda: context.execute(arm_id, task), journal,
                )
                slots_by_arm[arm_id][task.task_id] = slot
                observations.extend(task_observations)
                divergent_task_count += int(divergent)

    arms_out: dict[str, dict[str, Any]] = {}
    for arm_id, arm_slots_map in slots_by_arm.items():
        backend = (
            "native_filesystem"
            if arm_id == "native_tools_baseline"
            else ("sqlite" if arm_id.endswith(":sqlite") else "postgresql")
        )
        ordered_slots = [arm_slots_map[t.task_id] for t in cal_tasks]
        summary = aggregate_arm_summary(
            arm_id, backend, ordered_slots, expected_task_ids=expected_ids
        )
        arms_out[arm_id] = summary.to_dict()
        arms_out[arm_id].update(describe_comparability(arm_id, backend, ordered_slots, cal_tasks))
        for slot in arms_out[arm_id]["slots"]:
            slot["comparator_exposure"] = arms_out[arm_id]["comparator_exposure_by_task"][slot["task_id"]]
        arms_out[arm_id]["observed_output_layer"] = (
            "native_stdout_or_direct_selected_text" if arm_id == "native_tools_baseline" else (
                "read_store_response_serialization" if arm_id.startswith("current_graph_baseline:")
                else "query_envelope_serialization"
            )
        )

    report = {
        "schema_version": BASELINE_REPORT_SCHEMA_VERSION,
        "status": "failed" if any(
            slot.execution_state == ExecutionState.FAILED
            for slots in slots_by_arm.values() for slot in slots.values()
        ) else "completed",
        "execution_purpose": declaration.runner_profile["execution_purpose"],
        "divergent_task_count": divergent_task_count,
        "byte_summary_policy": "per_query_maximum_across_repetitions_unknown_if_any_unobserved",
        "repetition_observations": observations,
        "attempt_id": declaration.attempt_id,
        "phase_id": declaration.phase_id,
        "split": "calibration",
        "held_out_executed": False,
        "freeze_sha256": freeze.freeze_digest(),
        "catalog_sha256": catalog.catalog_digest(),
        "policy_digest": freeze.policy_digest,
        "setup_timings_ns": setup_timings_ns,
        "setup_byte_accounting": setup_bytes,
        "arms": arms_out,
    }
    assert_canary_free(report)
    return report


def _publish_generation(
    gen: int,
    work_dir: Path,
    postgres: tuple[str, int, str, str, str | None, str],
    include_postgres: bool,
) -> tuple[ArmContext, dict[str, int]]:
    pg_host, pg_port, pg_database, pg_user, pg_password, psql_command = postgres
    pg_wc, pg_home = work_dir / "wc_pg", work_dir / "pg_home"
    setup_timings_ns: dict[str, int] = {}
    wc = materialize_mixed_v1_working_copy(work_dir / f"wc_gen{gen}", generation=gen)
    sq_home = write_mixed_v1_sqlite_home(work_dir / f"sqlite_gen{gen}", wc)
    t0 = time.perf_counter_ns()
    sq_state = publish_and_load_sqlite_corpus(sq_home)
    setup_timings_ns[f"sqlite_publish_gen{gen}"] = time.perf_counter_ns() - t0

    t0 = time.perf_counter_ns()
    sqlite_projection = build_captured_text_projection(
        sq_state.projection_inputs(), sq_state.policy
    )
    setup_timings_ns[f"sqlite_projection_build_gen{gen}"] = time.perf_counter_ns() - t0

    t0 = time.perf_counter_ns()
    native_view = materialize_native_search_view(
        work_dir / f"native_view_gen{gen}",
        manifest=sq_state.manifest,
        bundle=sq_state.bundle,
        store=sq_state.store,
        policy=sq_state.policy,
        selected_aliases=("core", "companion", "feeds", "mailbox"),
    )
    setup_timings_ns[f"native_view_gen{gen}"] = time.perf_counter_ns() - t0

    pg_state: PublishedCorpusState | None = None
    pg_proj: CapturedTextProjection | None = None
    if include_postgres:
        materialize_mixed_v1_working_copy(pg_wc, generation=gen)
        write_mixed_v1_postgres_home(
            pg_home, pg_wc, host=pg_host, port=pg_port,
            database=pg_database, user=pg_user, password=pg_password,
        )
        t0 = time.perf_counter_ns()
        pg_state = publish_and_load_postgres_corpus(pg_home, psql_command=psql_command)
        setup_timings_ns[f"postgres_publish_gen{gen}"] = time.perf_counter_ns() - t0
        t0 = time.perf_counter_ns()
        pg_proj = build_captured_text_projection(pg_state.projection_inputs(), pg_state.policy)
        setup_timings_ns[f"postgres_projection_build_gen{gen}"] = time.perf_counter_ns() - t0

    context = ArmContext(
        native_view, sq_state.home_root, sqlite_projection,
        pg_state.home_root if pg_state else None, pg_proj, psql_command,
    )
    return context, setup_timings_ns
