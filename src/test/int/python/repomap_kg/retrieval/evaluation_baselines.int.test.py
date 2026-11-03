"""Integration tests for the declared 24-task calibration baseline across all 5 arms (S3)."""

from __future__ import annotations

from dataclasses import replace
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.lexical_service import build_graph_lexical_generation
from common_lore_index.retrieval.projection_build import build_captured_text_projection
from common_lore_index.server.investigation_read_store import GraphSearchQuery
from common_lore_index.server.ops import investigation_stores
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
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
from repomap_test_support.w5_experiment_vector import (
    baseline_file_metrics,
    baseline_file_metrics_with_correspondence,
)
from repomap_test_support.w5_generator_support import GeneratorFixtureReader
from retrieval_evaluation_comparability import query_fenced_current_observations
from retrieval_evaluation_criteria import derive_future_criteria_proposal
from retrieval_evaluation_execution import ArmContext
from retrieval_evaluation_fts import execute_postgres_native_fts_task
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_graph import execute_graph_baseline_task
from retrieval_evaluation_harness import (
    DEFAULT_ARMS,
    declare_calibration_attempt,
    execute_calibration_baseline,
    verify_fixture_freeze_guard,
)
from retrieval_evaluation_schema import load_freeze_manifest, load_task_catalog
from retrieval_evaluation_views import materialize_native_search_view
from retrieval_semantic_experiment_contracts import ExperimentRefusal
from retrieval_evaluation_observation_contracts import CurrentObservationReadError
from retrieval_semantic_baseline_capture import generation_aliases_for, make_baseline_correspondence_runner
from retrieval_semantic_experiment_scope import (
    BaselineCorrespondenceSidecar,
    is_expected_baseline_gap,
    verify_baseline_correspondence_sidecar,
)


def test_w3_cli_recipe_binds_each_unexecuted_attempt_to_distinct_paths(tmp_path: Path) -> None:
    """Actual CLI declarations are inert definitions, not retained observations."""
    from retrieval_evaluation import main

    recipes: list[dict[str, object]] = []
    for number in (1, 2):
        declaration_path = tmp_path / f"declaration-{number}.json"
        recipe_path = tmp_path / f"recipe-{number}.json"
        assert main([
            "declare-w3-attempt", "--attempt-id", f"w3-calibration-attempt-{number}",
            "--output", str(declaration_path), "--recipe-output", str(recipe_path),
        ]) == 0
        declaration = json.loads(declaration_path.read_text())
        recipe = json.loads(recipe_path.read_text())
        assert recipe["attempt_id"] == declaration["attempt_id"]
        assert recipe["declaration_rel_path"].endswith(f"attempt-declaration-w3-{number}.json")
        assert recipe["output_report_rel_path"].endswith(f"w3-calibration-attempt-{number}.json")
        assert recipe["output_criteria_rel_path"].endswith(f"criteria-proposal-v2-w3-{number}.json")
        assert recipe["retained_calibration_queries_executed_by_dispatcher"] == 0
        assert recipe["held_out_executed"] is False
        recipes.append(recipe)
    assert recipes[0]["declaration_rel_path"] != recipes[1]["declaration_rel_path"]


def test_calibration_baseline_end_to_end_across_all_five_arms_and_criteria_derivation(
    tmp_path: Path,
) -> None:
    """Execute the 24-task calibration baseline across native, SQLite/PG graph, and SQLite/PG projection arms."""
    catalog_path = MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json"
    freeze_path = MIXED_V1_FIXTURE_ROOT / "freeze-v1.json"

    catalog = load_task_catalog(catalog_path)
    freeze = load_freeze_manifest(freeze_path)
    verify_fixture_freeze_guard(catalog, freeze, work_dir=tmp_path / "guard")

    with temporary_postgres() as pg_db:
        declaration = declare_calibration_attempt(
            catalog,
            freeze,
            attempt_id="functional-" + uuid.uuid4().hex,
            split="calibration",
            repetitions_per_task=3,
            arms=DEFAULT_ARMS,
            pg_port=pg_db.port,
        )
        report = execute_calibration_baseline(
            catalog,
            freeze,
            declaration,
            work_dir=tmp_path / "run",
            pg_host=pg_db.host,
            pg_port=pg_db.port,
            pg_database=pg_db.database,
            pg_user=pg_db.user,
            pg_password=pg_db.password,
            psql_command=pg_db.psql_command,
            include_postgres=True,
        )

    assert report["split"] == "calibration"
    assert report["held_out_executed"] is False
    assert tuple(report["arms"].keys()) == DEFAULT_ARMS
    assert_canary_free(report)

    assert report["execution_purpose"] == "functional_check"
    assert report["status"] == "completed"
    assert report["divergent_task_count"] == 0
    assert len(report["repetition_observations"]) == 24 * 5 * 3
    assert len(report["setup_byte_accounting"]) == 4
    assert all(item["projected_body_input_bytes_read"] > 0 for item in report["setup_byte_accounting"].values())
    assert all(item["total_artifact_store_bytes_read"] is None for item in report["setup_byte_accounting"].values())
    assert all(
        item["byte_accounting"]["artifact_store_bytes_read"] == 0
        for item in report["repetition_observations"]
        if item["arm_id"].startswith("captured_projection_reference:")
    )
    expected_ids = [task.task_id for task in catalog.calibration_tasks()]
    for arm_id in DEFAULT_ARMS:
        arm = report["arms"][arm_id]
        assert arm["whole_split_denominator"] == 24
        assert [slot["task_id"] for slot in arm["slots"]] == expected_ids
        assert sum(group["whole_split_denominator"] for group in arm["exposure_strata"].values()) == 24
        assert all(slot["comparator_exposure"] == arm["comparator_exposure_by_task"][slot["task_id"]] for slot in arm["slots"])
        for stratum in arm["strata"].values():
            for key in ("mean_recall_at_5", "mean_mrr_at_5", "mean_ndcg_at_5"):
                value = stratum[key]
                assert value is None if stratum["graded_count"] == 0 else 0.0 <= value <= 1.0

    proposal = derive_future_criteria_proposal(
        report,
        freeze_sha256=freeze.freeze_digest(),
        catalog_sha256=catalog.catalog_digest(),
        policy_digest=freeze.policy_digest,
        allow_functional=True,
    )
    assert proposal.status == "proposed_for_parent_review"
    assert proposal.baseline_execution_purpose == "functional_check"
    assert_canary_free(proposal.to_dict())

    # Functional evidence stays in the test-owned temporary experiment.
    journal_dir = tmp_path / "run" / "functional-attempts" / declaration.attempt_id
    terminal = json.loads((journal_dir / "terminal.json").read_text())
    assert terminal["status"] == report["status"]
    assert terminal["observation_count"] == 2 + 24 * 5 * (3 * 2 + 1)
    assert (journal_dir / "sources.zip").is_file()

    tasks_by_id = {task.task_id: task for task in catalog.calibration_tasks()}
    for line in (journal_dir / "observations.jsonl").read_text().splitlines():
        record = json.loads(line)
        if record["event"] != "query_observed":
            continue
        envelope = record["envelope"]
        task = tasks_by_id[record["task_id"]]
        assert envelope["requested_mode"] == task.requested_mode
        if envelope["requested_mode"] != envelope["effective_mode"]:
            assert envelope["fallback"]["caller_selected"] is True
            assert envelope["fallback"]["from_mode"] == task.requested_mode
            assert envelope["fallback"]["to_mode"] == envelope["effective_mode"]
        if (record["arm_id"].startswith("current_graph_baseline:")
                and task.requested_mode == "ranked_discovery"
                and envelope["capability_state"] == "available"):
            assert envelope["match_surface"] == "stored_metadata"
            assert all(hit["match_surface"] == "stored_metadata" for hit in envelope["hits"])
    # Verify cal-23 in the end-to-end calibration report abstained cleanly on both graph baselines
    for g_arm in ("current_graph_baseline:sqlite", "current_graph_baseline:postgresql"):
        cal23_slot = next(s for s in report["arms"][g_arm]["slots"] if s["task_id"] == "cal-23")
        assert cal23_slot["returned_hit_count"] == 0
        assert cal23_slot["absent_answer_correct"] is True


def test_w5_two_generation_fenced_observations_and_verified_baseline_correspondence(
    tmp_path: Path,
) -> None:
    """Prove G1->G2 fenced observations, SQLite/PG parity, sidecar correspondence, and refusal boundaries."""
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json")
    tasks_by_id = {t.task_id: t for t in catalog.calibration_tasks()}
    wc = materialize_mixed_v1_working_copy(tmp_path / "wc", generation=1)
    sq_home = write_mixed_v1_sqlite_home(tmp_path / "sq_home", wc, declared_aliases=("core", "companion", "feeds"))

    with temporary_postgres() as pg_db:
        pg_home = write_mixed_v1_postgres_home(
            tmp_path / "pg_home",
            wc,
            host=pg_db.host,
            port=pg_db.port,
            database=pg_db.database,
            user=pg_db.user,
            password=pg_db.password,
            declared_aliases=("core", "companion", "feeds"),
        )
        sq_g1 = publish_and_load_sqlite_corpus(sq_home, selected_aliases=("core", "companion", "feeds"))
        pg_g1 = publish_and_load_postgres_corpus(pg_home, selected_aliases=("core", "companion", "feeds"), psql_command=pg_db.psql_command)
        sq_pin_g1 = GeneratorFixtureReader(sq_g1, sq_g1.policy, "sqlite").read_pin()
        pg_pin_g1 = GeneratorFixtureReader(pg_g1, pg_g1.policy, "postgresql", pg_db.psql_command).read_pin()
        assert sq_pin_g1.generation == pg_pin_g1.generation == 1
        assert sq_pin_g1.snapshot_vector == pg_pin_g1.snapshot_vector
        assert sq_pin_g1.publication_bundle_id != pg_pin_g1.publication_bundle_id

        # In Generation 1, LEGACY_DEPRECATED_PIPELINE_V0_ONLY_TOKEN is present in both stores
        assert len(
            query_fenced_current_observations(
                sq_home, graph_id=MIXED_V1_GRAPH_ID,
                query="LEGACY_DEPRECATED_PIPELINE_V0_ONLY_TOKEN", expected_pin=sq_pin_g1,
            ).rows
        ) == 1
        assert len(
            query_fenced_current_observations(
                pg_home, graph_id=MIXED_V1_GRAPH_ID,
                query="LEGACY_DEPRECATED_PIPELINE_V0_ONLY_TOKEN",
                expected_pin=pg_pin_g1, psql_command=pg_db.psql_command,
            ).rows
        ) == 1

        # Verify all 6 baseline arms on Generation 1 tasks + expected-gap classification
        sq_proj_g1 = build_captured_text_projection(sq_g1.projection_inputs(), sq_g1.policy)
        pg_proj_g1 = build_captured_text_projection(pg_g1.projection_inputs(), pg_g1.policy)
        view_g1 = materialize_native_search_view(
            tmp_path / "native_g1", manifest=sq_g1.manifest, bundle=sq_g1.bundle,
            store=sq_g1.store, policy=sq_g1.policy,
            selected_aliases=generation_aliases_for(sq_g1.manifest),
        )
        pg_cfg = load_graph_registry_config_home(pg_home)
        assert isinstance(pg_cfg, OpsConfig)
        assert build_graph_lexical_generation(
            pg_cfg, MIXED_V1_GRAPH_ID,
            selected_binding_ids=(binding_id_for_alias("core"), binding_id_for_alias("companion")),
            authorize_body=True,
        ).result == "published"
        ctx_g1 = ArmContext(view_g1, sq_home, sq_proj_g1, pg_home, pg_proj_g1, pg_db.psql_command)
        generation_aliases_g1 = generation_aliases_for(sq_g1.manifest)
        baseline_runner_g1 = make_baseline_correspondence_runner(
            BaselineCorrespondenceSidecar, generation_aliases_g1, view_g1,
            GeneratorFixtureReader(sq_g1, sq_g1.policy, "sqlite"),
            GeneratorFixtureReader(pg_g1, pg_g1.policy, "postgresql", pg_db.psql_command),
            sq_g1, pg_g1,
        )
        stale_sidecar_g1: BaselineCorrespondenceSidecar | None = None
        stale_output_g1: tuple[Any, Any, int, Any] | None = None
        correspondence_failures: list[tuple[str, str, str, str | None]] = []

        for tid in ("cal-01", "cal-04", "cal-09", "cal-16", "cal-21", "cal-24"):
            t_obj = tasks_by_id[tid]
            for arm_id in (*DEFAULT_ARMS, "postgres_native_fts:postgresql"):
                out = baseline_runner_g1.execute(
                    arm_id,
                    t_obj,
                    lambda expected: (
                        execute_postgres_native_fts_task(t_obj, pg_home)
                        if arm_id == "postgres_native_fts:postgresql"
                        else ctx_g1.execute(arm_id, t_obj, expected_pin=expected)
                    ),
                )
                p_obj = sq_proj_g1 if arm_id.endswith(":sqlite") else pg_proj_g1
                sidecar = baseline_runner_g1.sidecar(
                    arm_id, t_obj, envelope=out[1],
                    projection=p_obj if arm_id.startswith("captured_projection_reference:") else None,
                )
                metrics, status, gap, cost = baseline_file_metrics_with_correspondence(
                    t_obj, arm_id, out[0], out[1], sidecar
                )
                # Collect every arm's failure in one run. Identity proof does
                # not require perfect relevance from each comparator.
                valid = (
                    gap is None and metrics is not None and "file_recall@5" in metrics
                    and all(0.0 <= value <= 1.0 for value in metrics.values())
                ) if status == "verified" else is_expected_baseline_gap(arm_id, tid, status, gap)
                if cost.correspondence_failures or not valid:
                    correspondence_failures.append((tid, arm_id, status, gap))
                if tid == "cal-01" and arm_id == "current_graph_baseline:postgresql":
                    stale_sidecar_g1, stale_output_g1 = sidecar, out
        assert not correspondence_failures, correspondence_failures

        # Advance BOTH the same SQLite home and the same PostgreSQL database to Generation 2
        materialize_mixed_v1_working_copy(wc, generation=2)
        sq_g2 = publish_and_load_sqlite_corpus(sq_home, selected_aliases=("core", "companion", "feeds"))
        pg_g2 = publish_and_load_postgres_corpus(pg_home, selected_aliases=("core", "companion", "feeds"), psql_command=pg_db.psql_command)
        sq_pin_g2 = GeneratorFixtureReader(sq_g2, sq_g2.policy, "sqlite").read_pin()
        pg_pin_g2 = GeneratorFixtureReader(pg_g2, pg_g2.policy, "postgresql", pg_db.psql_command).read_pin()
        assert sq_pin_g2.generation == pg_pin_g2.generation == 2
        assert sq_pin_g2.snapshot_vector == pg_pin_g2.snapshot_vector

        # Publication advance during execution: G1 sidecar pins now fail revalidation against G2 stores!
        cal_01 = tasks_by_id["cal-01"]
        assert stale_sidecar_g1 is not None and stale_output_g1 is not None
        g1_state, g1_env, _, _ = stale_output_g1
        with pytest.raises(ExperimentRefusal):
            verify_baseline_correspondence_sidecar(
                stale_sidecar_g1, task=cal_01, arm_id="current_graph_baseline:postgresql",
                state=g1_state, envelope=g1_env,
            )

        # Generic InvestigationReadStore.search(target="observations") still returns historical G1 row on PG & SQLite
        for cfg_home in (sq_home, pg_home):
            inv = investigation_stores(load_graph_registry_config_home(cfg_home)).investigation_store()
            hist = inv.search(
                GraphSearchQuery(
                    graph_id=MIXED_V1_GRAPH_ID, target="observations",
                    query="LEGACY_DEPRECATED_PIPELINE_V0_ONLY_TOKEN",
                    kind=None, path=None, limit=10, offset=0, include_raw=False,
                )
            )
            assert len(hist.rows) >= 1

        # Fenced current-observation lookup in G2 excludes deleted G1 row on both PG and SQLite,
        # while positive G2 rows and unchanged companion rows remain visible, and stale/foreign pins refuse
        cal_10, cal_23 = tasks_by_id["cal-10"], tasks_by_id["cal-23"]
        for home, pin_g2, pin_g1_old, arm_name in (
            (sq_home, sq_pin_g2, sq_pin_g1, "current_graph_baseline:sqlite"),
            (pg_home, pg_pin_g2, pg_pin_g1, "current_graph_baseline:postgresql"),
        ):
            del_obs = query_fenced_current_observations(
                home, graph_id=MIXED_V1_GRAPH_ID, query="LEGACY_DEPRECATED_PIPELINE_V0_ONLY_TOKEN",
                expected_pin=pin_g2, psql_command=pg_db.psql_command,
            )
            assert del_obs.rows == ()
            pos_obs = query_fenced_current_observations(
                home, graph_id=MIXED_V1_GRAPH_ID, query="GEN2_EXTENSION_ACTIVE_MARKER_2026",
                expected_pin=pin_g2, psql_command=pg_db.psql_command,
            )
            assert len(pos_obs.rows) >= 1
            generation_aliases_g2 = generation_aliases_for((
                sq_g2 if arm_name.endswith(":sqlite") else pg_g2
            ).manifest)
            live_runner = make_baseline_correspondence_runner(
                BaselineCorrespondenceSidecar, generation_aliases_g2, view_g1,
                GeneratorFixtureReader(sq_g2, sq_g2.policy, "sqlite"),
                GeneratorFixtureReader(pg_g2, pg_g2.policy, "postgresql", pg_db.psql_command),
                sq_g2, pg_g2,
            )
            st_10, env_10, _, _ = live_runner.execute(
                arm_name, cal_10,
                lambda expected: execute_graph_baseline_task(
                    cal_10, home, psql_command=pg_db.psql_command, expected_pin=expected,
                ),
            )
            assert st_10 == ExecutionState.COMPLETED and len(env_10.hits) >= 1
            st_23, env_23, _, _ = live_runner.execute(
                arm_name, cal_23,
                lambda expected: execute_graph_baseline_task(
                    cal_23, home, psql_command=pg_db.psql_command, expected_pin=expected,
                ),
            )
            assert st_23 == ExecutionState.COMPLETED and env_23.hits == ()
            sc_23 = live_runner.sidecar(
                arm_name, cal_23, envelope=env_23, projection=None,
            )
            m_23, s_23, g_23 = baseline_file_metrics(
                cal_23, arm_name, st_23, env_23, None, correspondence_sidecar=sc_23,
            )
            assert s_23 == "verified" and g_23 is None and m_23 is not None
            for bad_pin in (pin_g1_old, replace(pin_g2, repository_identity="repo1:foreign"), replace(pin_g2, run_id=99)):
                with pytest.raises(CurrentObservationReadError, match="fenced_observation_pin_mismatch"):
                    query_fenced_current_observations(
                        home, graph_id=MIXED_V1_GRAPH_ID, query="GEN2_EXTENSION_ACTIVE_MARKER_2026",
                        expected_pin=bad_pin, psql_command=pg_db.psql_command,
                    )
