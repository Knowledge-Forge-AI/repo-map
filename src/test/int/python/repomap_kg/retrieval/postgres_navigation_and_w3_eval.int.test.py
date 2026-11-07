"""Integration tests for PostgreSQL navigation_search/node_locations parity and 6-arm v2 evaluation (Units 2 & 3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.server.ops import investigation_stores
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.node_locations import NodeLocationsQuery
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
from retrieval_evaluation_criteria_v2 import (
    CRITERIA_PROPOSAL_SCHEMA_V2,
    derive_future_criteria_proposal_v2,
)
from retrieval_evaluation_harness import execute_calibration_baseline
from retrieval_evaluation_schema import load_freeze_manifest, load_task_catalog
from retrieval_evaluation_summary_v2 import (
    BASELINE_REPORT_SCHEMA_V2,
    W3_DEFAULT_ARMS,
)
from retrieval_evaluation_w3 import declare_w3_calibration_attempt


def _strip_backend_specific_ids(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize backend-specific publication/observation integer IDs to compare wire parity."""
    out = dict(payload)
    acc = out.get("accepted_publication")
    if isinstance(acc, dict):
        out["accepted_publication"] = {
            "generation": acc.get("generation"),
        }
    out.pop("location_run_id", None)
    out.pop("node_first_seen_run_id", None)
    out.pop("node_last_seen_run_id", None)
    meta_loc = out.get("metadata_location")
    if isinstance(meta_loc, dict):
        mc = dict(meta_loc)
        mc.pop("node_last_seen_run_id", None)
        out["metadata_location"] = mc

    def _clean_loc(loc: dict[str, Any]) -> dict[str, Any]:
        c = dict(loc)
        c.pop("observation_id", None)
        c.pop("run_id", None)
        raw_obs = c.get("raw_observation")
        if isinstance(raw_obs, dict):
            ro = dict(raw_obs)
            ro.pop("run_id", None)
            c["raw_observation"] = ro
        pub = c.get("publication")
        if isinstance(pub, dict):
            pc = dict(pub)
            pc.pop("publication_bundle_id", None)
            pc.pop("extraction_receipt_id", None)
            c["publication"] = pc
        return c

    if "locations" in out and isinstance(out["locations"], list):
        out["locations"] = [_clean_loc(loc) for loc in out["locations"]]
    if "historical_locations" in out and isinstance(out["historical_locations"], list):
        out["historical_locations"] = [_clean_loc(loc) for loc in out["historical_locations"]]
    if "nodes" in out and isinstance(out["nodes"], list):
        cleaned_nodes = []
        for n in out["nodes"]:
            nc = dict(n)
            nc.pop("first_seen_run_id", None)
            nc.pop("last_seen_run_id", None)
            if isinstance(nc.get("locations"), list):
                nc["locations"] = [_clean_loc(loc) for loc in nc["locations"]]
            cleaned_nodes.append(nc)
        out["nodes"] = cleaned_nodes
    scan = out.get("scan")
    if isinstance(scan, dict):
        sc = dict(scan)
        adm = sc.get("admission")
        if isinstance(adm, dict):
            ac = dict(adm)
            ac.pop("decoded_bytes", None)
            ac.pop("input_bytes", None)
            ac.pop("vector_bytes", None)
            ac.pop("checks", None)
            sc["admission"] = ac
        out["scan"] = sc
    return out


def test_postgres_navigation_search_and_node_locations_wire_parity_with_sqlite(
    tmp_path: Path,
) -> None:
    """Verify PostgreSQL navigation_search and node_locations match SQLite Local wire semantics."""
    wc = materialize_mixed_v1_working_copy(tmp_path / "wc", generation=1)
    sq_home = write_mixed_v1_sqlite_home(tmp_path / "sq_home", wc)
    publish_and_load_sqlite_corpus(sq_home)
    sq_cfg = load_graph_registry_config_home(sq_home)
    sq_store = investigation_stores(sq_cfg).investigation_store()

    with temporary_postgres() as pg_db:
        pg_home = write_mixed_v1_postgres_home(
            tmp_path / "pg_home",
            wc,
            host=pg_db.host,
            port=pg_db.port,
            database=pg_db.database,
            user=pg_db.user,
            password=pg_db.password,
        )
        publish_and_load_postgres_corpus(pg_home, psql_command=pg_db.psql_command)
        pg_cfg = load_graph_registry_config_home(pg_home)
        pg_store = investigation_stores(pg_cfg).investigation_store()

        core_id = binding_id_for_alias("core")
        for nav_q in (
            NavigationSearchQuery(query="RetrievalExecutionPipeline", scope="all", limit=10),
            NavigationSearchQuery(query="verify_candidate_token", scope="code", limit=10),
            NavigationSearchQuery(query="DispatchTable", scope="all", source_binding_id=core_id, limit=10),
            NavigationSearchQuery(
                query="router.py",
                scope="all",
                source_binding_id=core_id,
                source_path_prefix="pkg",
                limit=5,
            ),
            NavigationSearchQuery(query="nonexistent_symbol_xyz_999", scope="all", limit=5),
            NavigationSearchQuery(query="e", scope="all", limit=1),
        ):
            sq_res = sq_store.navigation_search(MIXED_V1_GRAPH_ID, nav_q)
            pg_res = pg_store.navigation_search(MIXED_V1_GRAPH_ID, nav_q)
            assert pg_res["status"] == sq_res["status"] == "ok"
            pg_clean = _strip_backend_specific_ids(pg_res)
            sq_clean = _strip_backend_specific_ids(sq_res)
            assert pg_clean == sq_clean, f"nav_q={nav_q} pg={pg_clean} sq={sq_clean}"
            assert_canary_free(pg_res)

        sample_key = sq_store.navigation_search(
            MIXED_V1_GRAPH_ID,
            NavigationSearchQuery(query="RetrievalExecutionPipeline", scope="all", limit=5),
        )["nodes"][0]["canonical_key"]

        for loc_q in (
            NodeLocationsQuery(canonical_key=sample_key, evidence_role="direct", limit=5),
            NodeLocationsQuery(canonical_key=sample_key, evidence_role="all", limit=5),
            NodeLocationsQuery(canonical_key="file:core/pkg/pipeline.py", evidence_role="direct", limit=5),
            NodeLocationsQuery(canonical_key="file:nonexistent/missing.py", evidence_role="direct", limit=5),
        ):
            sq_loc = sq_store.node_locations(MIXED_V1_GRAPH_ID, loc_q)
            pg_loc = pg_store.node_locations(MIXED_V1_GRAPH_ID, loc_q)
            assert _strip_backend_specific_ids(pg_loc) == _strip_backend_specific_ids(sq_loc), f"loc_q={loc_q}"
            assert_canary_free(pg_loc)


def test_w3_six_arm_functional_evaluation_and_v2_criteria_derivation(
    tmp_path: Path,
) -> None:
    """Execute functional 6-arm evaluation (including postgres_native_fts:postgresql) and derive v2 criteria."""
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json")
    freeze = load_freeze_manifest(MIXED_V1_FIXTURE_ROOT / "freeze-v1.json")

    with temporary_postgres() as pg_db:
        declaration = declare_w3_calibration_attempt(
            catalog,
            freeze,
            attempt_id="w3-functional-" + uuid.uuid4().hex[:12],
            split="calibration",
            repetitions_per_task=1,
            arms=W3_DEFAULT_ARMS,
            pg_port=pg_db.port,
            execution_purpose="functional_check",
        )
        report = execute_calibration_baseline(
            catalog,
            freeze,
            declaration,
            work_dir=tmp_path / "w3_run",
            pg_host=pg_db.host,
            pg_port=pg_db.port,
            pg_database=pg_db.database,
            pg_user=pg_db.user,
            pg_password=pg_db.password,
            psql_command=pg_db.psql_command,
            include_postgres=True,
        )

    assert report["schema_version"] == BASELINE_REPORT_SCHEMA_V2
    failed_slots = [
        (arm_id, s["task_id"], s["execution_state"], s["capability_state"])
        for arm_id, arm in report["arms"].items()
        for s in arm["slots"]
        if s["execution_state"] == "failed"
    ]
    assert report["status"] == "completed", f"failed_slots={failed_slots}"
    assert report["held_out_executed"] is False
    assert tuple(report["arms"].keys()) == W3_DEFAULT_ARMS
    assert_canary_free(report)

    # Verify PostgreSQL current_graph_baseline now completes ranked_discovery and direct_handoff matching SQLite!
    pg_graph_arm = report["arms"]["current_graph_baseline:postgresql"]
    sq_graph_arm = report["arms"]["current_graph_baseline:sqlite"]
    assert pg_graph_arm["unavailable_count"] == sq_graph_arm["unavailable_count"]
    assert pg_graph_arm["graded_denominator"] == sq_graph_arm["graded_denominator"]
    assert pg_graph_arm["strata"]["metadata"]["mean_recall_at_5"] == sq_graph_arm["strata"]["metadata"]["mean_recall_at_5"]

    # Verify postgres_native_fts:postgresql arm completed body and safety refusal tasks cleanly
    fts_arm = report["arms"]["postgres_native_fts:postgresql"]
    assert fts_arm["whole_split_denominator"] == 24
    assert fts_arm["failed_count"] == 0
    assert fts_arm["safety_refusal_correct_count"] == fts_arm["safety_refusal_total"] == 2
    assert fts_arm["view_scope_disclosure"] == "evaluator_precheck_over_two_binding_public_view"
    safety_slots = [slot for slot in fts_arm["slots"] if slot["grading_rule"] == "safety_refusal"]
    assert all(slot["query_provenance"]["policy_enforcement_layer"] == "evaluator_precheck"
               for slot in safety_slots)
    assert all(slot["query_provenance"]["backend_policy_enforcement_observed"] is False
               for slot in safety_slots)
    assert fts_arm["strata"]["body"]["graded_count"] >= 10
    assert fts_arm["strata"]["body"]["mean_recall_at_5"] > 0.7

    proposal_v2 = derive_future_criteria_proposal_v2(
        report,
        freeze_sha256=freeze.freeze_digest(),
        catalog_sha256=catalog.catalog_digest(),
        policy_digest=freeze.policy_digest,
        allow_functional=True,
    )
    assert proposal_v2.schema_version == CRITERIA_PROPOSAL_SCHEMA_V2
    assert proposal_v2.status == "proposed_for_parent_review"
    assert "postgres_native_fts:postgresql" in proposal_v2.observed_baseline_summary
    assert_canary_free(proposal_v2.to_dict())
