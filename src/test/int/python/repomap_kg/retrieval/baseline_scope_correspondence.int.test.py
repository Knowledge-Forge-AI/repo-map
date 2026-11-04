"""Actual lexical normalization requires publication-specific scope equality."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil

import pytest

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.lexical_service import build_graph_lexical_generation
from common_lore_index.ops.config_records import OpsConfig
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_FIXTURE_ROOT, MIXED_V1_GRAPH_ID, binding_id_for_alias,
    materialize_mixed_v1_working_copy, write_mixed_v1_postgres_home,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus, publish_and_load_sqlite_corpus,
)
from repomap_test_support.w5_generator_support import GeneratorFixtureReader
from retrieval_evaluation_fts import execute_postgres_native_fts_task
from retrieval_evaluation_schema import load_task_catalog
from retrieval_evaluation_views import materialize_native_search_view
from retrieval_semantic_baseline_capture import generation_aliases_for, make_baseline_correspondence_runner
from retrieval_semantic_experiment_contracts import ExperimentRefusal
from retrieval_semantic_experiment_scope import BaselineCorrespondenceSidecar, verify_baseline_correspondence_sidecar


@pytest.mark.parametrize("same_name_file", [False, True])
def test_actual_lexical_scope_normalization_cannot_admit_a_same_name_file(
    tmp_path: Path, same_name_file: bool,
) -> None:
    working = materialize_mixed_v1_working_copy(tmp_path / "working")
    if same_name_file:
        # A different binding can have a file named shared while core has a
        # shared/ directory. This is test corruption/variation, not a new corpus.
        target = working / "companion" / "shared"
        assert target.is_dir() and not target.is_symlink()
        shutil.rmtree(target)
        target.write_text("unrelated exact-name file\n", encoding="utf-8")
    aliases = ("core", "companion", "feeds")
    sqlite_home = write_mixed_v1_sqlite_home(tmp_path / "sqlite-home", working, declared_aliases=aliases)
    sqlite = publish_and_load_sqlite_corpus(sqlite_home, selected_aliases=aliases)
    view = materialize_native_search_view(
        tmp_path / "native", manifest=sqlite.manifest, bundle=sqlite.bundle,
        store=sqlite.store, policy=sqlite.policy,
        selected_aliases=generation_aliases_for(sqlite.manifest),
    )
    with temporary_postgres() as pg:
        postgres_home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home", working, host=pg.host, port=pg.port,
            database=pg.database, user=pg.user, password=pg.password,
            declared_aliases=aliases,
        )
        postgres = publish_and_load_postgres_corpus(postgres_home, selected_aliases=aliases, psql_command=pg.psql_command)
        config = load_graph_registry_config_home(postgres_home)
        assert isinstance(config, OpsConfig)
        assert build_graph_lexical_generation(
            config, MIXED_V1_GRAPH_ID,
            selected_binding_ids=(binding_id_for_alias("core"), binding_id_for_alias("companion")),
            authorize_body=True,
        ).result == "published"
        runner = make_baseline_correspondence_runner(
            BaselineCorrespondenceSidecar, generation_aliases_for(sqlite.manifest), view,
            GeneratorFixtureReader(sqlite, sqlite.policy, "sqlite"),
            GeneratorFixtureReader(postgres, postgres.policy, "postgresql", pg.psql_command),
            sqlite, postgres,
        )
        task = next(t for t in load_task_catalog(
            MIXED_V1_FIXTURE_ROOT / "tasks/catalog-v1.json",
        ).calibration_tasks() if t.task_id == "cal-19")
        state, envelope, _, _ = runner.execute(
            "postgres_native_fts:postgresql", task,
            lambda expected: execute_postgres_native_fts_task(task, postgres_home),
        )
        assert task.source_path_prefix == "shared/"
        assert envelope.scope.source_path_prefix == "shared"
        sidecar = runner.sidecar("postgres_native_fts:postgresql", task, envelope=envelope, projection=None)
        if same_name_file:
            assert any(e.source_relative_path == "shared" for e in postgres.manifest.entries)
            with pytest.raises(ExperimentRefusal, match="normalized_scope_would_widen_selection"):
                verify_baseline_correspondence_sidecar(
                    sidecar, task=task, arm_id="postgres_native_fts:postgresql", state=state, envelope=envelope,
                )
        else:
            verified, cost = verify_baseline_correspondence_sidecar(
                sidecar, task=task, arm_id="postgres_native_fts:postgresql", state=state, envelope=envelope,
            )
            assert verified.backend == "postgresql"
            assert cost.correspondence_failures == 0
            forged_policy = replace(postgres.policy, max_chunk_lines=postgres.policy.max_chunk_lines + 1)
            drifted = replace(sidecar, projection_policy=forged_policy)
            with pytest.raises(ExperimentRefusal, match="projection_policy_mismatch"):
                verify_baseline_correspondence_sidecar(
                    drifted, task=task, arm_id="postgres_native_fts:postgresql", state=state, envelope=envelope,
                )
