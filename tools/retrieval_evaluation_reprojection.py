"""Immutable historical v1-to-v2 reprojection for W2 calibration-attempt-7 (Unit 3)."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Any

from common_lore_index.retrieval.query_contracts import QueryEnvelope
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from retrieval_evaluation_historical_evidence import verify_completed_attempt
from retrieval_evaluation_criteria_v2 import (
    FutureCriteriaProposalV2,
    derive_future_criteria_proposal_v2,
)
from retrieval_evaluation_harness import BASELINE_REPORT_SCHEMA_VERSION
from retrieval_evaluation_schema import (
    FreezeManifest,
    TaskCatalog,
    load_freeze_manifest,
    load_task_catalog,
)
from retrieval_evaluation_summary_v2 import (
    BASELINE_REPORT_SCHEMA_V2,
    upgrade_arm_summary_to_v2,
)


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_journal_envelopes(
    journal_path: Path,
    *,
    expected_journal_sha256: str | None = None,
    expected_arms: tuple[str, ...],
    expected_tasks: tuple[str, ...],
    repetitions: int,
) -> tuple[dict[str, dict[str, dict[str, Any]]], str]:
    """Load and cryptographically verify retained query_observed envelopes from observations.jsonl."""
    raw_bytes = journal_path.read_bytes()
    actual_sha256 = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    if expected_journal_sha256 is not None and actual_sha256 != expected_journal_sha256:
        raise ValueError(
            f"journal_sha256 mismatch: expected {expected_journal_sha256!r}, got {actual_sha256!r}"
        )
    envelopes_by_arm: dict[str, dict[str, dict[str, Any]]] = {}
    identities: set[tuple[str, str, int]] = set()
    for line in raw_bytes.decode("utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if not isinstance(entry, Mapping):
            raise ValueError("journal line must be a JSON object")
        if entry.get("event") != "query_observed":
            continue
        arm_id = entry.get("arm_id")
        task_id = entry.get("task_id")
        rep = entry.get("repetition")
        env = entry.get("envelope")
        if arm_id not in expected_arms or task_id not in expected_tasks or not isinstance(env, Mapping):
            raise ValueError("query_observed event is missing arm_id, task_id, or envelope")
        if isinstance(rep, bool) or not isinstance(rep, int) or rep not in range(1, repetitions + 1):
            raise ValueError("query_observed repetition must be an admitted integer")
        identity = (arm_id, task_id, rep)
        if identity in identities:
            raise ValueError("duplicate query_observed repetition")
        identities.add(identity)
        QueryEnvelope.from_mapping(env)
        semantic = {"execution_state": entry.get("execution_state"), "envelope": env}
        if entry.get("outcome_sha256") != _canonical_sha256(semantic):
            raise ValueError("retained query outcome digest mismatch")
        env_dict = dict(env)
        prior = envelopes_by_arm.setdefault(arm_id, {}).get(task_id)
        if prior is not None and prior != env_dict:
            raise ValueError(f"divergent envelope across repetitions for ({arm_id!r}, {task_id!r})")
        envelopes_by_arm[arm_id][task_id] = env_dict
    expected = {(arm, task, rep) for arm in expected_arms for task in expected_tasks
                for rep in range(1, repetitions + 1)}
    if identities != expected:
        raise ValueError("incomplete journal repetition population")
    return envelopes_by_arm, actual_sha256


def reproject_historical_attempt_to_v2(
    attempt_report: Mapping[str, Any],
    attempt_declaration: Mapping[str, Any],
    catalog: TaskCatalog,
    freeze: FreezeManifest,
    *,
    envelopes_by_arm: Mapping[str, Mapping[str, Mapping[str, Any]]],
    source_journal_sha256: str | None = None,
    source_retained_evidence_sha256: str | None = None,
    source_attempt_report_sha256: str | None = None,
    source_attempt_declaration_sha256: str | None = None,
) -> dict[str, Any]:
    """Deterministically upgrade a committed v1 baseline report to v2 without re-running queries."""
    catalog.validate()
    freeze.validate()
    if attempt_report.get("schema_version") != BASELINE_REPORT_SCHEMA_VERSION:
        raise ValueError(
            f"expected {BASELINE_REPORT_SCHEMA_VERSION!r}, got {attempt_report.get('schema_version')!r}"
        )
    if attempt_report.get("status") != "completed":
        raise ValueError("historical reprojection requires a completed v1 attempt report")
    if attempt_report.get("freeze_sha256") != freeze.freeze_digest():
        raise ValueError("attempt_report freeze_sha256 mismatch against FreezeManifest")
    if attempt_report.get("catalog_sha256") != catalog.catalog_digest():
        raise ValueError("attempt_report catalog_sha256 mismatch against TaskCatalog")
    if attempt_report.get("policy_digest") != freeze.policy_digest:
        raise ValueError("attempt_report policy_digest mismatch against FreezeManifest")
    if attempt_declaration.get("attempt_id") != attempt_report.get("attempt_id"):
        raise ValueError("attempt_declaration attempt_id mismatch against attempt_report")
    if attempt_declaration.get("freeze_sha256") != freeze.freeze_digest():
        raise ValueError("attempt_declaration freeze_sha256 mismatch against FreezeManifest")
    if attempt_declaration.get("catalog_sha256") != catalog.catalog_digest():
        raise ValueError("attempt_declaration catalog_sha256 mismatch against TaskCatalog")

    tasks_by_id = {task.task_id: task for task in catalog.calibration_tasks()}
    raw_arms = attempt_report.get("arms")
    if not isinstance(raw_arms, Mapping) or not raw_arms:
        raise ValueError("attempt_report is missing arms mapping")

    arms_v2: dict[str, Any] = {}
    for arm_id, arm_data in sorted(raw_arms.items()):
        if not isinstance(arm_data, Mapping):
            raise ValueError(f"arm {arm_id!r} entry must be a mapping")
        arm_envs = envelopes_by_arm.get(str(arm_id))
        if arm_envs is None or set(arm_envs) != set(tasks_by_id):
            raise ValueError("historical projection requires actual envelopes for every slot")
        arms_v2[str(arm_id)] = upgrade_arm_summary_to_v2(
            arm_data,
            tasks_by_id,
            envelopes_by_task=arm_envs,
        )

    prov: dict[str, Any] = {
        "reprojection_kind": "immutable_historical_v1_to_v2",
        "source_attempt_id": str(attempt_report["attempt_id"]),
        "source_schema_version": str(attempt_report["schema_version"]),
        "source_execution_purpose": str(attempt_report["execution_purpose"]),
        "source_attempt_report_sha256": source_attempt_report_sha256 or _canonical_sha256(attempt_report),
        "source_attempt_declaration_sha256": source_attempt_declaration_sha256 or _canonical_sha256(attempt_declaration),
        "queries_re_executed": 0,
        "w2_artifacts_mutated": False,
    }
    if source_retained_evidence_sha256 is not None:
        prov["source_retained_evidence_sha256"] = source_retained_evidence_sha256
    if source_journal_sha256 is not None:
        prov["source_journal_sha256"] = source_journal_sha256

    report_v2: dict[str, Any] = {
        "schema_version": BASELINE_REPORT_SCHEMA_V2,
        "reprojection_provenance": prov,
        "status": str(attempt_report["status"]),
        "execution_purpose": "historical_journal_reprojection",
        "divergent_task_count": int(attempt_report["divergent_task_count"]),
        "byte_summary_policy": str(attempt_report["byte_summary_policy"]),
        "repetition_observations": list(attempt_report["repetition_observations"]),
        "attempt_id": str(attempt_report["attempt_id"]),
        "phase_id": str(attempt_report["phase_id"]),
        "split": str(attempt_report["split"]),
        "held_out_executed": bool(attempt_report["held_out_executed"]),
        "freeze_sha256": str(attempt_report["freeze_sha256"]),
        "catalog_sha256": str(attempt_report["catalog_sha256"]),
        "policy_digest": str(attempt_report["policy_digest"]),
        "setup_timings_ns": dict(attempt_report["setup_timings_ns"]),
        "setup_byte_accounting": {
            k: dict(v) for k, v in attempt_report["setup_byte_accounting"].items()
        },
        "arms": arms_v2,
    }
    assert_canary_free(report_v2)
    return report_v2


def reproject_attempt7_files(
    *,
    attempt7_report_path: Path,
    attempt7_declaration_path: Path,
    catalog_path: Path,
    freeze_path: Path,
    retained_evidence_path: Path | None = None,
    journal_path: Path | None = None,
    attempt_directory: Path | None = None,
) -> tuple[dict[str, Any], FutureCriteriaProposalV2]:
    """Load committed attempt-7 files and return (reprojected_report_v2, criteria_proposal_v2)."""
    catalog = load_task_catalog(catalog_path)
    freeze = load_freeze_manifest(freeze_path)
    report_v1 = json.loads(attempt7_report_path.read_text(encoding="utf-8"))
    decl_v1 = json.loads(attempt7_declaration_path.read_text(encoding="utf-8"))
    if not isinstance(report_v1, Mapping) or not isinstance(decl_v1, Mapping):
        raise ValueError("attempt-7 report and declaration must be JSON objects")

    directory = attempt_directory or (
        attempt7_report_path.parent / "w3" / "historical-attempt-7"
    )
    evidence = verify_completed_attempt(directory)
    if report_v1 != evidence["report"] or decl_v1 != evidence["declaration"]:
        raise ValueError("public historical payload differs from retained raw evidence")
    terminal = evidence["terminal"]
    if report_v1.get("held_out_executed") is not False or report_v1.get("split") != "calibration":
        raise ValueError("historical reprojection requires calibration-only evidence")
    if decl_v1.get("repetitions_per_task") != 3 or isinstance(decl_v1.get("repetitions_per_task"), bool):
        raise ValueError("historical reprojection requires three admitted repetitions")
    arms = tuple(decl_v1["arms"])
    tasks = tuple(task.task_id for task in catalog.calibration_tasks())
    if len(set(arms)) != len(arms) or set(arms) != set(report_v1["arms"]):
        raise ValueError("historical arm population mismatch")
    if tuple(decl_v1["ordered_task_ids"]) != tasks:
        raise ValueError("historical task population mismatch")
    ev_path = retained_evidence_path or (
        attempt7_report_path.parent / "retained-attempt-7-evidence.json"
    )
    ev_sha256: str | None = None
    expected_journal_sha256 = terminal["journal_sha256"]
    if not ev_path.is_file():
        raise ValueError("historical projection requires its retained public evidence anchor")
    ev_sha256 = _file_sha256(ev_path)
    ev_payload = json.loads(ev_path.read_text(encoding="utf-8"))
    if not isinstance(ev_payload, Mapping) or ev_payload.get("terminal") != terminal:
        raise ValueError("retained public summary terminal mismatch")
    journal = journal_path or directory / "observations.jsonl"
    envelopes_by_arm, actual_journal_sha256 = load_journal_envelopes(
        journal, expected_journal_sha256=expected_journal_sha256,
        expected_arms=arms, expected_tasks=tasks, repetitions=3,
    )
    observations = [{key: value for key, value in event.items() if key not in {"event", "envelope"}}
                    for event in evidence["events"] if event.get("event") == "query_observed"]
    if report_v1.get("repetition_observations") != observations:
        raise ValueError("retained report observations differ from journal")
    graded: dict[tuple[str, str], Mapping[str, Any]] = {}
    for event in evidence["events"]:
        if event.get("event") == "task_graded":
            slot = event.get("slot")
            if not isinstance(slot, Mapping):
                raise ValueError("retained task_graded requires a slot")
            graded_arm, graded_task = event.get("arm_id"), slot.get("task_id")
            if not isinstance(graded_arm, str) or not isinstance(graded_task, str):
                raise ValueError("retained graded identity must contain strings")
            key = (graded_arm, graded_task)
            if key in graded or event.get("divergent") is not False:
                raise ValueError("historical projection refuses duplicate or divergent graded slots")
            graded[key] = slot
    expected_slots = {(arm, task) for arm in arms for task in tasks}
    if set(graded) != expected_slots:
        raise ValueError("retained graded slot population mismatch")
    for arm, summary in report_v1["arms"].items():
        if len(summary["slots"]) != len(tasks):
            raise ValueError("historical summary slot count mismatch")
        for slot in summary["slots"]:
            original = {key: value for key, value in slot.items() if key != "comparator_exposure"}
            if original != graded[(arm, slot["task_id"])]:
                raise ValueError("historical summary differs from graded journal slot")

    report_v2 = reproject_historical_attempt_to_v2(
        report_v1,
        decl_v1,
        catalog,
        freeze,
        envelopes_by_arm=envelopes_by_arm,
        source_journal_sha256=actual_journal_sha256,
        source_retained_evidence_sha256=ev_sha256,
        source_attempt_report_sha256=_file_sha256(attempt7_report_path),
        source_attempt_declaration_sha256=_file_sha256(attempt7_declaration_path),
    )
    report_v2["reprojection_provenance"]["retained_raw_file_sha256"] = evidence["sha256"]
    proposal_v2 = derive_future_criteria_proposal_v2(
        report_v2,
        freeze_sha256=freeze.freeze_digest(),
        catalog_sha256=catalog.catalog_digest(),
        policy_digest=freeze.policy_digest,
    )
    return report_v2, proposal_v2


__all__ = [
    "load_journal_envelopes",
    "reproject_attempt7_files",
    "reproject_historical_attempt_to_v2",
]
