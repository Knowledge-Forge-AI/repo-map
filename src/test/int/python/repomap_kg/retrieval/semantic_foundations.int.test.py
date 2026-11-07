"""Containerized integration tests for model-independent W5 representation, fusion, and grading (ADR 0137)."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import pytest

from common_lore_index.ops.config_local import (
    LocalSqliteConfig,
    load_graph_registry_config_home,
    local_graph_binding,
)
from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.local_refresh import refresh_local_graph
from common_lore_index.ops.portable_refresh import execute_portable_refresh
from common_lore_index.server.ops import investigation_stores
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.semantic_candidates import EmbeddingEntry
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_FIXTURE_ROOT,
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    build_mixed_v1_projection_policy,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus,
    publish_and_load_sqlite_corpus,
    read_postgres_accepted_publication,
    read_sqlite_accepted_publication,
)
from repomap_test_support.w5_semantic_support import (
    load_postgres_accepted_nodes_and_evidence,
    load_sqlite_accepted_nodes_and_evidence,
    make_postgres_readback_adapter,
    make_sqlite_readback_adapter,
)
from retrieval_evaluation_grading import ExecutionState, GradingState
from retrieval_evaluation_schema import load_task_catalog
from retrieval_semantic_fusion import (
    AdmittedArmObservation,
    FileIdentityTuple,
    VectorCandidateInput,
    fuse_arm_observations_rrf,
)
from retrieval_semantic_grading import (
    evaluate_arm_task_applicability,
    grade_w5_task_slot,
)
from retrieval_semantic_representation import (
    RepresentationValidationError,
    build_and_validate_node_representations,
    verify_publication_provenance_from_adapter,
)


def test_w5_canonical_node_v1_cross_backend_parity_rrf_fusion_and_generation_pinning(
    tmp_path: Path,
) -> None:
    """Verify SQLite/PostgreSQL canonical-node-v1 parity, RRF fusion, calibration grading, and live generation drift refusal."""
    wc = materialize_mixed_v1_working_copy(tmp_path / "wc", generation=1)
    sq_home = write_mixed_v1_sqlite_home(tmp_path / "sq_home", wc, declared_aliases=("core", "companion", "feeds"))
    sq_pub_g1 = publish_and_load_sqlite_corpus(
        sq_home, selected_aliases=("core", "companion", "feeds")
    )
    sq_cfg = load_graph_registry_config_home(sq_home)
    assert isinstance(sq_cfg, LocalSqliteConfig)
    sq_binding = local_graph_binding(sq_cfg.graphs[0])
    sq_pub_map_g1, sq_nodes_g1, sq_ev_g1 = load_sqlite_accepted_nodes_and_evidence(sq_pub_g1)
    sq_adapter_g1 = make_sqlite_readback_adapter(sq_pub_g1)
    policy_3 = build_mixed_v1_projection_policy(
        MIXED_V1_GRAPH_ID, selected_aliases=("core", "companion", "feeds")
    )

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
        pg_pub_g1 = publish_and_load_postgres_corpus(
            pg_home,
            selected_aliases=("core", "companion", "feeds"),
            psql_command=pg_db.psql_command,
        )
        pg_cfg = load_graph_registry_config_home(pg_home)
        assert isinstance(pg_cfg, OpsConfig)
        pg_binding = local_graph_binding(pg_cfg.graphs[0])
        pg_pub_map_g1, pg_nodes_g1, pg_ev_g1 = load_postgres_accepted_nodes_and_evidence(
            pg_pub_g1, psql_command=pg_db.psql_command
        )
        pg_adapter_g1 = make_postgres_readback_adapter(
            pg_pub_g1, psql_command=pg_db.psql_command
        )

        sq_rep_g1 = build_and_validate_node_representations(
            graph_id=MIXED_V1_GRAPH_ID,
            repository_identity=str(sq_binding.repository_identity),
            backend="sqlite",
            accepted_publication=sq_pub_map_g1,
            receipt=sq_pub_g1.receipt,
            policy=policy_3,
            accepted_nodes=sq_nodes_g1,
            accepted_evidence=sq_ev_g1,
            readback_adapter=sq_adapter_g1,
        )
        pg_rep_g1 = build_and_validate_node_representations(
            graph_id=MIXED_V1_GRAPH_ID,
            repository_identity=str(pg_binding.repository_identity),
            backend="postgresql",
            accepted_publication=pg_pub_map_g1,
            receipt=pg_pub_g1.receipt,
            policy=policy_3,
            accepted_nodes=pg_nodes_g1,
            accepted_evidence=pg_ev_g1,
            readback_adapter=pg_adapter_g1,
        )

        assert sq_rep_g1.status == pg_rep_g1.status == "ok"
        assert len(sq_rep_g1.representations) > 0
        sq_tuples = [
            (r.canonical_key, r.kind, r.display_name, r.source_binding_id, r.snapshot_id, r.input_digest, r.source_relative_paths)
            for r in sq_rep_g1.representations
        ]
        pg_tuples = [
            (r.canonical_key, r.kind, r.display_name, r.source_binding_id, r.snapshot_id, r.input_digest, r.source_relative_paths)
            for r in pg_rep_g1.representations
        ]
        assert sq_tuples == pg_tuples

        feeds_id = binding_id_for_alias("feeds")
        mailbox_id = binding_id_for_alias("mailbox")
        assert any(r.source_binding_id == feeds_id for r in pg_rep_g1.representations)
        assert all(r.source_binding_id != mailbox_id for r in pg_rep_g1.representations)
        assert pg_rep_g1.provenance.denied_bindings[mailbox_id] == "binding_privacy_not_authorized"
        pg_portable = pg_pub_g1.receipt.portable
        assert pg_portable is not None
        assert mailbox_id not in dict((binding, snapshot) for binding, _revision, snapshot in pg_portable.snapshot_vector)
        assert_canary_free(pg_rep_g1.to_dict())

        # Claimed EmbeddingEntry batch validation against real PostgreSQL representations
        sample_reps = pg_rep_g1.representations[:3]
        claims = tuple(
            EmbeddingEntry(
                canonical_key=r.canonical_key,
                source_binding_id=r.source_binding_id,
                input_digest=r.input_digest,
                vector=(0.6, -0.8, 0.0),
            )
            for r in sample_reps
        )
        claimed_report = build_and_validate_node_representations(
            graph_id=MIXED_V1_GRAPH_ID,
            repository_identity=str(pg_binding.repository_identity),
            backend="postgresql",
            accepted_publication=pg_pub_map_g1,
            receipt=pg_pub_g1.receipt,
            policy=policy_3,
            accepted_nodes=pg_nodes_g1,
            accepted_evidence=pg_ev_g1,
            claimed_entries=claims,
            readback_adapter=pg_adapter_g1,
        )
        assert claimed_report.status == "ok"
        assert len(claimed_report.representations) == 3

        # Real lexical search + canonical-node-v1 vector candidates -> file-level RRF (k=60)
        pg_store = investigation_stores(pg_cfg).investigation_store()
        nav_res = pg_store.navigation_search(
            MIXED_V1_GRAPH_ID,
            NavigationSearchQuery(query="RetrievalExecutionPipeline", scope="all", limit=10),
        )
        assert nav_res["status"] == "ok"
        lex_raw_hits: list[tuple[FileIdentityTuple, int, str]] = []
        for rank_idx, node_hit in enumerate(nav_res["nodes"], start=1):
            for loc in node_hit.get("locations", ()):
                src = loc.get("source") or {}
                b_id = src.get("binding_id")
                s_id = src.get("snapshot_id")
                rel_p = src.get("source_relative_path")
                if b_id and s_id and rel_p:
                    lex_raw_hits.append(
                        (FileIdentityTuple(str(b_id), str(s_id), str(rel_p)), rank_idx, str(node_hit["canonical_key"]))
                    )
        assert len(lex_raw_hits) > 0

        pipeline_reps = [r for r in pg_rep_g1.representations if "RetrievalExecutionPipeline" in r.canonical_key]
        assert len(pipeline_reps) >= 1
        p_rep = pipeline_reps[0]
        vec_cand = VectorCandidateInput(
            canonical_key=p_rep.canonical_key,
            source_binding_id=p_rep.source_binding_id,
            raw_rank=1,
            evidence=tuple(
                {
                    "path": f"core/{rel_p}",
                    "metadata_json": {
                        "binding_id": p_rep.source_binding_id,
                        "snapshot_id": p_rep.snapshot_id,
                        "source_relative_path": rel_p,
                    },
                }
                for rel_p in p_rep.source_relative_paths
            ),
            input_digest=p_rep.input_digest,
            kind=p_rep.kind,
            display_name=p_rep.display_name,
        )

        lex_arm = AdmittedArmObservation(
            arm_id="pg_lexical_nav",
            mode="ranked_discovery",
            verified_pin=pg_rep_g1.provenance,
            raw_file_hits=tuple(lex_raw_hits),
            observed_accepted_publication=nav_res.get("accepted_publication"),
        )
        vec_arm = AdmittedArmObservation(
            arm_id="pg_vector_canonical_node_v1",
            mode="ranked_discovery",
            verified_pin=pg_rep_g1.provenance,
            vector_candidates=(vec_cand,),
        )
        fused = fuse_arm_observations_rrf((lex_arm, vec_arm), expected_pin=pg_rep_g1.provenance)
        assert fused.execution_state == ExecutionState.COMPLETED
        assert fused.credited_as_fused is True
        assert fused.hits[0].score_fraction == Fraction(2, 61)
        assert_canary_free(fused.to_dict())

        # Grade calibration tasks from catalog-v1.json and verify held-out split rejection
        catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json")
        cal_tasks = [t for t in catalog.calibration_tasks() if t.generation == 1]
        meta_pos_task = next(
            t for t in cal_tasks
            if t.comparability_stratum == "metadata"
            and t.grading_rule == "ranked_positive"
            and any("RetrievalExecutionPipeline" in (g.canonical_key or "") or "pipeline.py" in g.locator.source_relative_path for g in t.gold_targets)
        )
        body_task = next(t for t in cal_tasks if t.comparability_stratum == "body" and t.grading_rule == "ranked_positive")

        assert evaluate_arm_task_applicability("vector_only", meta_pos_task).applicable is True
        assert evaluate_arm_task_applicability("vector_only", body_task).applicable is False

        slot_meta = grade_w5_task_slot(
            meta_pos_task,
            arm_id="hybrid_rrf",
            verified_pin=pg_rep_g1.provenance,
            fusion_result=fused,
        )
        assert slot_meta.execution_state == ExecutionState.COMPLETED
        assert slot_meta.metrics["file_recall@5"] > 0.0
        assert_canary_free(slot_meta.to_dict())

        slot_body_vec = grade_w5_task_slot(
            body_task,
            arm_id="vector_only",
            verified_pin=pg_rep_g1.provenance,
            fusion_result=fused,
        )
        assert slot_body_vec.execution_state == ExecutionState.UNAVAILABLE
        assert slot_body_vec.grading_state == GradingState.UNGRADED

        # Exercise split refusal without selecting any actual held-out task/gold.
        held_out_task = replace(cal_tasks[0], split="held_out")
        with pytest.raises(RepresentationValidationError) as exc_ho:
            grade_w5_task_slot(held_out_task, arm_id="hybrid_rrf", verified_pin=pg_rep_g1.provenance, fusion_result=fused)
        assert exc_ho.value.code == "held_out_execution_forbidden"

        # Advance working copy to generation 2, refresh both stores, and verify live store revalidation refuses generation 1
        materialize_mixed_v1_working_copy(wc, generation=2)
        refresh_local_graph(sq_cfg, MIXED_V1_GRAPH_ID)
        _sq_ref_g2, sq_receipt_g2 = read_sqlite_accepted_publication(sq_cfg, MIXED_V1_GRAPH_ID)
        assert sq_receipt_g2 != sq_pub_g1.receipt

        pg_graph = pg_cfg.graphs[0]
        execute_portable_refresh(pg_cfg, pg_graph, pg_graph.database or pg_cfg.postgres.database, authority=None)
        _pg_ref_g2, pg_receipt_g2 = read_postgres_accepted_publication(
            pg_cfg, MIXED_V1_GRAPH_ID, psql_command=pg_db.psql_command
        )
        assert pg_receipt_g2 != pg_pub_g1.receipt

        with pytest.raises(RepresentationValidationError) as exc_sq_stale:
            sq_rep_g1.provenance.revalidate_current()
        assert exc_sq_stale.value.code == "stale_publication_receipt"

        with pytest.raises(RepresentationValidationError) as exc_pg_stale:
            pg_rep_g1.provenance.revalidate_current()
        assert exc_pg_stale.value.code == "stale_publication_receipt"

        single_stale = fuse_arm_observations_rrf((lex_arm,), expected_pin=pg_rep_g1.provenance)
        assert single_stale.execution_state == ExecutionState.REFUSED
        assert single_stale.refusal_code == "stale_publication_receipt"

        pg_adapter_g2 = make_postgres_readback_adapter(
            pg_pub_g1, psql_command=pg_db.psql_command, receipt_getter=lambda: pg_receipt_g2
        )
        pin_g2 = verify_publication_provenance_from_adapter(
            pg_adapter_g2,
            policy=policy_3,
        )
        arm_g2 = AdmittedArmObservation(
            arm_id="pg_vec_g2",
            mode="ranked_discovery",
            verified_pin=pin_g2,
            raw_file_hits=(),
        )
        drift_fusion = fuse_arm_observations_rrf((lex_arm, arm_g2), expected_pin=pin_g2)
        assert drift_fusion.execution_state == ExecutionState.REFUSED
        assert drift_fusion.refusal_code == "stale_publication_receipt"
        assert drift_fusion.hits == ()
