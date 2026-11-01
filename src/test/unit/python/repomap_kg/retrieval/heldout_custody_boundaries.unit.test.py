"""Pure held-out receipt and retained-input custody boundary tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
from retrieval_evaluation_admission import validate_admitted_input_manifest
from retrieval_evaluation_attempts import admit_attempt
from retrieval_evaluation_criteria_v2 import (
    derive_future_criteria_proposal_v2,
)
from retrieval_evaluation_heldout import (
    HELD_OUT_PREREQUISITE_SCHEMA_V2,
    HeldOutAdmissionPrerequisite,
    validate_held_out_admission,
)
from retrieval_evaluation_schema import (
    ATTEMPT_DECLARATION_SCHEMA_VERSION,
    FreezeManifest,
    TaskCatalog,
    load_freeze_manifest,
    load_task_catalog,
)
from retrieval_evaluation_summary_v2 import BASELINE_REPORT_SCHEMA_V2, W3_DEFAULT_ARMS


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _fixture_catalog_and_freeze() -> tuple[TaskCatalog, FreezeManifest]:
    return (
        load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json"),
        load_freeze_manifest(MIXED_V1_FIXTURE_ROOT / "freeze-v1.json"),
    )


def _retained_attempt(
    tmp_path: Path,
    *,
    freeze: FreezeManifest,
    catalog: TaskCatalog,
    truncate_observations: bool = False,
) -> tuple[Path, dict[str, str], dict[str, str], dict[str, object]]:
    source = {"tools/synthetic.py": b"print('synthetic')\n"}
    inputs = {"fixture/input.json": b"{\"fixture\":true}\n"}
    closure = {path: _digest(data) for path, data in source.items()}
    task_ids = tuple(task.task_id for task in catalog.calibration_tasks())
    declaration = {
        "schema_version": ATTEMPT_DECLARATION_SCHEMA_VERSION,
        "attempt_id": "calibration-synthetic",
        "phase_id": "phase-test",
        "split": "calibration",
        "freeze_sha256": freeze.freeze_digest(),
        "catalog_sha256": catalog.catalog_digest(),
        "ordered_task_ids": list(task_ids),
        "arms": list(W3_DEFAULT_ARMS),
        "repetitions_per_task": 3,
        "stopping_rule": "complete_all_24_calibration_tasks_3_repetitions_no_early_stop",
        "replacement_policy": "retain_failed_attempts_require_new_attempt_id_on_instrument_bug",
        "runner_profile": {
            "execution_purpose": "retained_calibration",
            "report_schema_version": BASELINE_REPORT_SCHEMA_V2,
        },
        "candidate_closure_digests": closure,
    }
    observations: list[dict[str, object]] = []
    arms: dict[str, dict[str, object]] = {}
    for arm_id in W3_DEFAULT_ARMS:
        backend = (
            "native_filesystem"
            if arm_id == "native_tools_baseline"
            else ("sqlite" if arm_id.endswith(":sqlite") else "postgresql")
        )
        slots: list[dict[str, object]] = []
        for task_id in task_ids:
            slots.append(
                {
                    "arm_id": arm_id,
                    "backend": backend,
                    "task_id": task_id,
                    "comparability_stratum": "body",
                    "grading_rule": "ranked_positive",
                    "grading_state": "correct",
                    "execution_state": "completed",
                    "capability_state": "available",
                    "metrics": {
                        "recall@5": 1.0,
                        "mrr@5": 1.0,
                        "ndcg@5": 1.0,
                    },
                    "byte_accounting": {
                        "observed_output_payload_bytes": 128,
                        "artifact_store_bytes_read": 64,
                    },
                }
            )
        arms[arm_id] = {
            "arm_id": arm_id,
            "backend": backend,
            "observed_output_layer": "query_envelope_serialization",
            "whole_split_denominator": 24,
            "supported_denominator": 24,
            "graded_denominator": 24,
            "unavailable_count": 0,
            "refused_count": 0,
            "failed_count": 0,
            "safety_refusal_correct_count": 0,
            "safety_refusal_total": 0,
            "absent_answer_correct_count": 0,
            "absent_answer_total": 0,
            "slots": slots,
            "mode_surface_style_strata": [
                {
                    "comparability_stratum": "body",
                    "comparator_exposure": "projected_authorized_bodies",
                    "requested_mode": "ranked_discovery",
                    "effective_mode": "ranked_discovery",
                    "fallback": None,
                    "match_surface": "captured_text",
                    "query_style": "ranked_terms",
                    "slot_count": 24,
                    "graded_count": 24,
                    "mean_recall_at_5": 1.0,
                    "mean_mrr_at_5": 1.0,
                    "mean_ndcg_at_5": 1.0,
                    "task_ids": list(task_ids),
                }
            ],
        }
        for repetition in range(1, 4):
            observations.extend(
                {
                    "arm_id": arm_id,
                    "task_id": task_id,
                    "repetition": repetition,
                    "execution_state": "completed",
                    "elapsed_ns": 1,
                    "outcome_sha256": _digest(f"{arm_id}:{task_id}:{repetition}".encode()),
                    "byte_accounting": {
                        "observed_output_payload_bytes": 128,
                        "artifact_store_bytes_read": 64,
                    },
                }
                for task_id in task_ids
            )
    report = {
        "schema_version": BASELINE_REPORT_SCHEMA_V2,
        "status": "completed",
        "execution_purpose": "retained_calibration",
        "attempt_id": declaration["attempt_id"],
        "phase_id": declaration["phase_id"],
        "split": "calibration",
        "held_out_executed": False,
        "freeze_sha256": freeze.freeze_digest(),
        "catalog_sha256": catalog.catalog_digest(),
        "policy_digest": freeze.policy_digest,
        "repetition_observations": observations,
        "setup_byte_accounting": {
            "synthetic_projection": {
                "projected_body_input_bytes_read": 256,
                "total_artifact_store_bytes_read": None,
            }
        },
        "arms": arms,
    }
    retained_observations = observations[:-1] if truncate_observations else observations
    if truncate_observations:
        report["repetition_observations"] = retained_observations
    journal = admit_attempt(tmp_path / "attempts", declaration, source, input_files=inputs)
    for observation in retained_observations:
        journal.append({"event": "query_observed", **observation})
    journal.finish("completed", report)
    artifact_names = (
        "declaration.json",
        "report.json",
        "observations.jsonl",
        "source-manifest.json",
        "sources.zip",
        "terminal.json",
    )
    artifact_digests = {
        name: _digest((journal.directory / name).read_bytes()) for name in artifact_names
    }
    return journal.directory, artifact_digests, closure, report


def _proposal(
    report: dict[str, object], *, freeze: FreezeManifest, catalog: TaskCatalog
) -> dict[str, object]:
    return derive_future_criteria_proposal_v2(
        report,
        freeze_sha256=freeze.freeze_digest(),
        catalog_sha256=catalog.catalog_digest(),
        policy_digest=freeze.policy_digest,
    ).to_dict()


def _receipt(
    proposal: dict[str, object],
    freeze: FreezeManifest,
    catalog: TaskCatalog,
    artifact_digests: dict[str, str],
    closure: dict[str, str],
) -> HeldOutAdmissionPrerequisite:
    criteria_bytes = json.dumps(
        proposal, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return HeldOutAdmissionPrerequisite(
        schema_version=HELD_OUT_PREREQUISITE_SCHEMA_V2,
        status="parent_accepted",
        parent_authorization_token="opaque-parent-receipt",
        accepted_criteria_sha256=_digest(criteria_bytes),
        calibration_attempt_id=str(proposal["baseline_attempt_id"]),
        freeze_sha256=freeze.freeze_digest(),
        catalog_sha256=catalog.catalog_digest(),
        policy_digest=freeze.policy_digest,
        candidate_closure_digests=closure,
        calibration_artifact_digests=artifact_digests,
    )


def test_parent_receipt_accepts_immutable_proposal_and_completed_journal(tmp_path: Path) -> None:
    catalog, freeze = _fixture_catalog_and_freeze()
    directory, artifacts, closure, report = _retained_attempt(
        tmp_path, freeze=freeze, catalog=catalog
    )
    proposal = _proposal(report, freeze=freeze, catalog=catalog)
    receipt = _receipt(proposal, freeze, catalog, artifacts, closure)
    assert (
        HeldOutAdmissionPrerequisite.from_mapping(receipt.to_dict()).to_dict()
        == receipt.to_dict()
    )

    with pytest.raises(ValueError, match="held_out_execution_forbidden_in_milestone"):
        validate_held_out_admission(
            receipt,
            proposal,
            catalog,
            freeze,
            live_candidate_digests=closure,
            calibration_directory=directory,
        )

    validate_held_out_admission(
        receipt,
        proposal,
        catalog,
        freeze,
        live_candidate_digests=closure,
        calibration_directory=directory,
        allow_held_out_in_current_milestone=True,
    )

    accepted_mapping = {**proposal, "status": "parent_accepted"}
    with pytest.raises(ValueError, match="criteria proposal status"):
        validate_held_out_admission(
            receipt,
            accepted_mapping,
            catalog,
            freeze,
            live_candidate_digests=closure,
            calibration_directory=directory,
            allow_held_out_in_current_milestone=True,
        )


def test_historical_reprojection_cannot_qualify_as_retained_calibration(
    tmp_path: Path,
) -> None:
    catalog, freeze = _fixture_catalog_and_freeze()
    directory, artifacts, closure, report = _retained_attempt(
        tmp_path, freeze=freeze, catalog=catalog
    )
    proposal = _proposal(report, freeze=freeze, catalog=catalog)
    proposal["baseline_execution_purpose"] = "historical_journal_reprojection"
    receipt = _receipt(proposal, freeze, catalog, artifacts, closure)

    with pytest.raises(ValueError, match="historical"):
        validate_held_out_admission(
            receipt,
            proposal,
            catalog,
            freeze,
            live_candidate_digests=closure,
            calibration_directory=directory,
            allow_held_out_in_current_milestone=True,
        )


def test_criteria_must_derive_from_retained_report(tmp_path: Path) -> None:
    catalog, freeze = _fixture_catalog_and_freeze()
    directory, artifacts, closure, report = _retained_attempt(
        tmp_path, freeze=freeze, catalog=catalog
    )
    proposal = _proposal(report, freeze=freeze, catalog=catalog)
    proposal["target_future_phase"] = "forged-future-phase"
    receipt = _receipt(proposal, freeze, catalog, artifacts, closure)

    with pytest.raises(ValueError, match="derive from the retained report"):
        validate_held_out_admission(
            receipt,
            proposal,
            catalog,
            freeze,
            live_candidate_digests=closure,
            calibration_directory=directory,
            allow_held_out_in_current_milestone=True,
        )


def test_retained_population_must_include_every_query_observation(tmp_path: Path) -> None:
    catalog, freeze = _fixture_catalog_and_freeze()
    directory, artifacts, closure, report = _retained_attempt(
        tmp_path, freeze=freeze, catalog=catalog, truncate_observations=True
    )
    proposal = _proposal(report, freeze=freeze, catalog=catalog)
    receipt = _receipt(proposal, freeze, catalog, artifacts, closure)

    with pytest.raises(ValueError, match="W3 population"):
        validate_held_out_admission(
            receipt,
            proposal,
            catalog,
            freeze,
            live_candidate_digests=closure,
            calibration_directory=directory,
            allow_held_out_in_current_milestone=True,
        )


def test_receipt_rejects_tampered_completed_artifact(tmp_path: Path) -> None:
    catalog, freeze = _fixture_catalog_and_freeze()
    directory, artifacts, closure, report = _retained_attempt(
        tmp_path, freeze=freeze, catalog=catalog
    )
    proposal = _proposal(report, freeze=freeze, catalog=catalog)
    receipt = _receipt(proposal, freeze, catalog, artifacts, closure)
    (directory / "report.json").write_bytes(b"{}\n")

    with pytest.raises(ValueError, match="terminal .* mismatch|terminal digest mismatch"):
        validate_held_out_admission(
            receipt,
            proposal,
            catalog,
            freeze,
            live_candidate_digests=closure,
            calibration_directory=directory,
            allow_held_out_in_current_milestone=True,
        )


def test_live_fixture_inputs_must_match_admitted_manifest(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    input_path = fixture_root / "input.json"
    input_path.write_bytes(b"original\n")
    source = {"tools/synthetic.py": b"source\n"}
    closure = {path: _digest(data) for path, data in source.items()}
    declaration = {
        "attempt_id": "input-custody",
        "candidate_closure_digests": closure,
    }
    journal = admit_attempt(
        tmp_path / "attempts", declaration, source, input_files={"input.json": b"original\n"}
    )

    validate_admitted_input_manifest(journal, fixture_root=fixture_root)
    input_path.write_bytes(b"changed\n")
    with pytest.raises(ValueError, match="differ from the admitted"):
        validate_admitted_input_manifest(journal, fixture_root=fixture_root)
    input_path.unlink()
    with pytest.raises(ValueError, match="differ from the admitted"):
        validate_admitted_input_manifest(journal, fixture_root=fixture_root)
