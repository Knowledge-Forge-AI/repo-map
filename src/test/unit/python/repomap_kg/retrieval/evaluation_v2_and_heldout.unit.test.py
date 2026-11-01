"""Unit tests for evaluation summary/criteria v2, historical attempt-7 reprojection, held-out gate, and W3 recipe (Unit 3)."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from common_lore_index.retrieval.projection_build import build_captured_text_projection
from common_lore_index.retrieval.projection_query import (
    CapturedTextQueryRequest,
    query_captured_text,
)
from common_lore_index.retrieval.query_contracts import CapabilityState
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
from repomap_test_support.retrieval_evaluation_query_fixture import (
    build_fixture_projection,
)
from retrieval_evaluation_criteria_v2 import (
    CRITERIA_PROPOSAL_SCHEMA_V2,
    FutureCriteriaProposalV2,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_heldout import (
    HELD_OUT_PREREQUISITE_SCHEMA_V2,
    HeldOutAdmissionPrerequisite,
    validate_held_out_admission,
)
from retrieval_evaluation_reference import execute_projection_reference_task
from retrieval_evaluation_reprojection import reproject_attempt7_files
from retrieval_evaluation_schema import load_freeze_manifest, load_task_catalog
from retrieval_evaluation_slots_v2 import infer_slot_query_style, upgrade_slot_to_v2
from retrieval_evaluation_summary_v2 import (
    BASELINE_REPORT_SCHEMA_V2,
    W3_DEFAULT_ARMS,
)
from retrieval_evaluation_w3 import (
    W3_PHASE_ID,
    W3_RECIPE_SCHEMA_V1,
    build_w3_calibration_recipe,
    declare_w3_calibration_attempt,
)


def test_w3_recipe_paths_follow_the_declared_attempt_without_overwriting_history() -> None:
    """Synthetic recipe checks execute no queries or retained admission."""
    from retrieval_evaluation_schema import AttemptDeclaration

    root = MIXED_V1_FIXTURE_ROOT / "baseline/w3"
    declaration = AttemptDeclaration.from_mapping(
        json.loads((root / "attempt-declaration-w3-1.json").read_text())
    )
    first = build_w3_calibration_recipe(declaration)
    second = build_w3_calibration_recipe(replace(declaration, attempt_id="w3-calibration-attempt-2"))
    assert first["declaration_rel_path"].endswith("attempt-declaration-w3-1.json")
    assert second["declaration_rel_path"].endswith("attempt-declaration-w3-2.json")
    assert second["output_report_rel_path"].endswith("w3-calibration-attempt-2.json")
    assert second["output_criteria_rel_path"].endswith("criteria-proposal-v2-w3-2.json")
    assert second["declaration_sha256"] != first["declaration_sha256"]
    assert all("attempt-1.json" not in command and "w3-1.json" not in command
               for command in second["commands"])
    explicit = build_w3_calibration_recipe(
        replace(declaration, attempt_id="w3-calibration-attempt-2"),
        declaration_rel_path="custom/declaration.json",
        output_report_rel_path="custom/report.json",
        output_criteria_rel_path="custom/criteria.json",
    )
    assert explicit["declaration_rel_path"] == "custom/declaration.json"
    for unsafe in ("../escape", "bad name", "bad;command", "$(command)"):
        with pytest.raises(ValueError):
            build_w3_calibration_recipe(replace(declaration, attempt_id=unsafe))


def test_historical_attempt7_reprojection_v2_and_criteria_v2_invariants() -> None:
    """Verify historical attempt-7 reprojection preserves mode/fallback/surface/style without mutating W2 artifacts."""
    catalog_path = MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json"
    freeze_path = MIXED_V1_FIXTURE_ROOT / "freeze-v1.json"
    attempt7_report_path = (
        MIXED_V1_FIXTURE_ROOT / "baseline" / "calibration-attempt-7.json"
    )
    attempt7_decl_path = (
        MIXED_V1_FIXTURE_ROOT / "baseline" / "attempt-declaration-7.json"
    )

    before_report_bytes = attempt7_report_path.read_bytes()
    before_decl_bytes = attempt7_decl_path.read_bytes()

    report_v2, proposal_v2 = reproject_attempt7_files(
        attempt7_report_path=attempt7_report_path,
        attempt7_declaration_path=attempt7_decl_path,
        catalog_path=catalog_path,
        freeze_path=freeze_path,
    )
    assert attempt7_report_path.read_bytes() == before_report_bytes
    assert attempt7_decl_path.read_bytes() == before_decl_bytes

    assert report_v2["schema_version"] == BASELINE_REPORT_SCHEMA_V2
    prov = report_v2["reprojection_provenance"]
    assert prov["queries_re_executed"] == 0
    assert prov["w2_artifacts_mutated"] is False
    assert prov["source_attempt_id"] == "calibration-attempt-7"
    assert_canary_free(report_v2)

    for arm_id, arm_data in report_v2["arms"].items():
        slots = arm_data["slots"]
        assert len(slots) == 24
        mss_strata = arm_data["mode_surface_style_strata"]
        assert sum(s["slot_count"] for s in mss_strata) == 24
        for slot in slots:
            assert slot["arm_id"] == arm_id
            assert "requested_mode" in slot
            assert "effective_mode" in slot
            assert "fallback" in slot
            assert "match_surface" in slot
            assert "query_style" in slot
            if slot["requested_mode"] != slot["effective_mode"]:
                fb = slot["fallback"]
                assert isinstance(fb, dict)
                assert fb["from_mode"] == slot["requested_mode"]
                assert fb["to_mode"] == slot["effective_mode"]
                assert fb["caller_selected"] is True

    assert proposal_v2.schema_version == CRITERIA_PROPOSAL_SCHEMA_V2
    assert proposal_v2.baseline_schema_version == BASELINE_REPORT_SCHEMA_V2
    assert proposal_v2.status == "proposed_for_parent_review"
    roundtrip = FutureCriteriaProposalV2.from_mapping(proposal_v2.to_dict())
    assert roundtrip.to_dict() == proposal_v2.to_dict()
    assert_canary_free(proposal_v2.to_dict())

    # Verify committed w3 reprojection artifacts match live deterministic output
    committed_rep = json.loads(
        (
            MIXED_V1_FIXTURE_ROOT
            / "baseline"
            / "w3"
            / "calibration-attempt-7-reprojected-v2.json"
        ).read_text(encoding="utf-8")
    )
    committed_crit = json.loads(
        (
            MIXED_V1_FIXTURE_ROOT
            / "baseline"
            / "w3"
            / "criteria-proposal-v2-from-attempt-7.json"
        ).read_text(encoding="utf-8")
    )
    assert committed_rep == report_v2
    assert committed_crit == proposal_v2.to_dict()


def test_held_out_admission_gate_and_w3_declaration_recipe() -> None:
    """Verify held-out admission rejects historical evidence while preserving W3 recipe checks."""
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json")
    freeze = load_freeze_manifest(MIXED_V1_FIXTURE_ROOT / "freeze-v1.json")
    _, proposal_v2 = reproject_attempt7_files(
        attempt7_report_path=MIXED_V1_FIXTURE_ROOT / "baseline" / "calibration-attempt-7.json",
        attempt7_declaration_path=MIXED_V1_FIXTURE_ROOT / "baseline" / "attempt-declaration-7.json",
        catalog_path=MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json",
        freeze_path=MIXED_V1_FIXTURE_ROOT / "freeze-v1.json",
    )

    historical_attempt = (
        MIXED_V1_FIXTURE_ROOT / "baseline" / "w3" / "historical-attempt-7"
    )
    artifact_names = (
        "declaration.json",
        "report.json",
        "observations.jsonl",
        "source-manifest.json",
        "sources.zip",
        "terminal.json",
    )
    artifact_digests = {
        name: "sha256:"
        + hashlib.sha256((historical_attempt / name).read_bytes()).hexdigest()
        for name in artifact_names
    }
    source_manifest = json.loads(
        (historical_attempt / "source-manifest.json").read_text(encoding="utf-8")
    )
    live_digests = source_manifest["source_files"]
    crit_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                proposal_v2.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("utf-8")
        ).hexdigest()
    )
    prereq = HeldOutAdmissionPrerequisite(
        schema_version=HELD_OUT_PREREQUISITE_SCHEMA_V2,
        status="parent_accepted",
        parent_authorization_token="opaque-parent-receipt",
        accepted_criteria_sha256=crit_digest,
        calibration_attempt_id="calibration-attempt-7",
        freeze_sha256=freeze.freeze_digest(),
        catalog_sha256=catalog.catalog_digest(),
        policy_digest=freeze.policy_digest,
        candidate_closure_digests=live_digests,
        calibration_artifact_digests=artifact_digests,
    ).validate()
    assert HeldOutAdmissionPrerequisite.from_mapping(prereq.to_dict()).to_dict() == prereq.to_dict()

    with pytest.raises(ValueError, match="historical"):
        validate_held_out_admission(
            prereq,
            proposal_v2.to_dict(),
            catalog,
            freeze,
            live_candidate_digests=live_digests,
            calibration_directory=historical_attempt,
            allow_held_out_in_current_milestone=True,
        )

    retained_criteria = dict(proposal_v2.to_dict())
    retained_criteria["baseline_execution_purpose"] = "retained_calibration"
    retained_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                retained_criteria,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
    )
    retained_prereq = replace(prereq, accepted_criteria_sha256=retained_digest)
    with pytest.raises(ValueError, match="candidate_closure_digests mismatch"):
        validate_held_out_admission(
            retained_prereq,
            retained_criteria,
            catalog,
            freeze,
            live_candidate_digests={
                "tools/retrieval_evaluation.py": "sha256:" + ("b" * 64)
            },
            calibration_directory=historical_attempt,
            allow_held_out_in_current_milestone=True,
        )

    # Strict type checking on HeldOutAdmissionPrerequisite.from_mapping
    bad_map = dict(prereq.to_dict())
    bad_map["parent_authorization_token"] = True
    with pytest.raises(ValueError, match="must be a string"):
        HeldOutAdmissionPrerequisite.from_mapping(bad_map)

    # Candidate closure includes CLI/runtime entrypoints and pyproject.toml (M7)
    from retrieval_evaluation import _build_parser
    from retrieval_evaluation_admission import admit_evaluation, candidate_source_files
    closure = candidate_source_files(MIXED_V1_FIXTURE_ROOT.parents[4])
    for req_rel in (
        "pyproject.toml",
        "src/main/python/common_lore_index/cli/parser.py",
        "src/main/python/common_lore_index/cli/dispatch.py",
        "src/main/python/common_lore_index/runtime/postgres_route.py",
    ):
        assert req_rel in closure

    # CLI parser accepts --report-schema v2 on run-calibration and --journal on reproject-v2 (M6, M8)
    parsed_run = _build_parser().parse_args(
        [
            "run-calibration",
            "--declaration", "decl.json",
            "--output", "out.json",
            "--attempt-root", "root",
            "--report-schema", "v2",
        ]
    )
    assert parsed_run.report_schema == "v2"

    decl_w3 = declare_w3_calibration_attempt(catalog, freeze)
    with pytest.raises(ValueError, match="candidate_closure_digests mismatch"):
        admit_evaluation(
            replace(decl_w3, candidate_closure_digests={"pyproject.toml": "sha256:" + ("0" * 64)}),
            catalog,
            freeze,
            attempt_root=MIXED_V1_FIXTURE_ROOT / "baseline",
            pg_port=55433,
            supported_arms=W3_DEFAULT_ARMS,
        )
    assert decl_w3.phase_id == W3_PHASE_ID
    assert decl_w3.arms == W3_DEFAULT_ARMS
    recipe = build_w3_calibration_recipe(decl_w3)
    assert recipe["schema_version"] == W3_RECIPE_SCHEMA_V1
    assert recipe["held_out_executed"] is False
    assert recipe["retained_calibration_queries_executed_by_dispatcher"] == 0
    assert len(recipe["arms"]) == 6

    task0 = catalog.calibration_tasks()[0]
    assert infer_slot_query_style("postgres_native_fts:postgresql", task0) == "ranked_terms"
    slot_v2 = upgrade_slot_to_v2(
        {"task_id": task0.task_id, "capability_state": "available", "execution_state": "completed"},
        task0,
        arm_id="postgres_native_fts:postgresql",
        backend="postgresql",
        comparator_exposure="projected_authorized_bodies",
        envelope_dict={
            "requested_mode": "ranked_discovery",
            "effective_mode": "ranked_discovery",
            "fallback": None,
            "match_surface": "captured_text",
            "provenance": {"query_style": "ranked_terms"},
            "ordering_policy_version": "ts-rank-cd-deterministic-v1",
            "scope_complete": True,
            "omissions": (),
        },
    )
    assert slot_v2["query_style"] == "ranked_terms"
    assert slot_v2["match_surface"] == "captured_text"


def test_empty_resolved_scope_returns_unavailable_not_absence(tmp_path: Path) -> None:
    """Empty resolved selected_binding_ids returns unavailable rather than available absence."""
    inputs, policy = build_fixture_projection(spool_dir=tmp_path / "spool")
    empty_policy = replace(policy, selected_binding_ids=frozenset())
    proj_empty = build_captured_text_projection(inputs, empty_policy)

    env = query_captured_text(
        proj_empty,
        CapturedTextQueryRequest(query="BOUNDARY_START_TOKEN"),
        current_accepted_reference=inputs.accepted_reference,
    )
    assert env.capability_state == CapabilityState.UNAVAILABLE
    assert env.unavailable_reason == "projection_absent"
    assert env.establishes_absence() is False

    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json")
    task_empty = replace(catalog.calibration_tasks()[3], selected_bindings=())
    state, ref_env, _, _ = execute_projection_reference_task(
        task_empty,
        proj_empty,
        current_accepted=inputs.accepted_reference,
    )
    assert state == ExecutionState.UNAVAILABLE
    assert ref_env.capability_state == CapabilityState.UNAVAILABLE
    assert ref_env.unavailable_reason == "empty_selected_bindings"
