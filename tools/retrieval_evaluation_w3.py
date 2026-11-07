"""Predeclared W3 6-arm calibration attempt declaration and parent execution recipe (Unit 3)."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from typing import Any

from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
from retrieval_evaluation_admission import (
    candidate_source_files,
    runtime_profile,
    source_digests,
)
from retrieval_evaluation_schema import (
    ATTEMPT_DECLARATION_SCHEMA_VERSION,
    AttemptDeclaration,
    FreezeManifest,
    TaskCatalog,
)
from retrieval_evaluation_summary_v2 import (
    BASELINE_REPORT_SCHEMA_V2,
    W3_DEFAULT_ARMS,
)

W3_PHASE_ID = "REPOMAP-CLOE-LEXICAL1"
W3_RECIPE_SCHEMA_V1 = "cloe-retrieval-w3-calibration-recipe-v1"


def _canonical_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def declare_w3_calibration_attempt(
    catalog: TaskCatalog,
    freeze: FreezeManifest,
    *,
    attempt_id: str = "w3-calibration-attempt-1",
    split: str = "calibration",
    repetitions_per_task: int = 3,
    arms: tuple[str, ...] = W3_DEFAULT_ARMS,
    pg_port: int = 55433,
    execution_purpose: str = "retained_calibration",
) -> AttemptDeclaration:
    """Create a validated 6-arm W3 AttemptDeclaration over the frozen 24-task calibration split."""
    if split != "calibration":
        raise ValueError(
            f"W3 calibration declaration refuses split {split!r}; held_out requires parent-accepted criteria"
        )
    repo_root = MIXED_V1_FIXTURE_ROOT.parents[4]
    cal_ids = tuple(t.task_id for t in catalog.calibration_tasks())
    return AttemptDeclaration(
        schema_version=ATTEMPT_DECLARATION_SCHEMA_VERSION,
        attempt_id=attempt_id,
        phase_id=W3_PHASE_ID,
        split=split,
        freeze_sha256=freeze.freeze_digest(),
        catalog_sha256=catalog.catalog_digest(),
        ordered_task_ids=cal_ids,
        arms=arms,
        repetitions_per_task=repetitions_per_task,
        stopping_rule=f"complete_all_24_calibration_tasks_{repetitions_per_task}_repetitions_no_early_stop",
        replacement_policy="retain_failed_attempts_require_new_attempt_id_on_instrument_bug",
        candidate_closure_digests=source_digests(candidate_source_files(repo_root)),
        runner_profile={
            **runtime_profile(pg_port),
            "execution_purpose": execution_purpose,
            "report_schema_version": BASELINE_REPORT_SCHEMA_V2,
        },
    ).validate()


def build_w3_calibration_recipe(
    declaration: AttemptDeclaration,
    *,
    declaration_rel_path: str | None = None,
    output_report_rel_path: str | None = None,
    output_criteria_rel_path: str | None = None,
) -> dict[str, Any]:
    """Build the parent-reviewable execution recipe for the 6-arm W3 retained calibration run."""
    declaration.validate()
    attempt_id = declaration.attempt_id
    if not isinstance(attempt_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", attempt_id):
        raise ValueError("recipe attempt_id must be a portable identifier")
    match = re.fullmatch(r"w3-calibration-attempt-([1-9][0-9]*)", attempt_id)
    suffix = f"w3-{match.group(1)}" if match else attempt_id
    root = "src/test/fixtures/retrieval_evaluation/mixed-v1/baseline/w3"
    declaration_rel_path = declaration_rel_path or f"{root}/attempt-declaration-{suffix}.json"
    output_report_rel_path = output_report_rel_path or f"{root}/{attempt_id}.json"
    output_criteria_rel_path = output_criteria_rel_path or f"{root}/criteria-proposal-v2-{suffix}.json"
    decl_dict = declaration.to_dict()
    pg_port = int(declaration.runner_profile.get("pg_port", 55433))
    return {
        "schema_version": W3_RECIPE_SCHEMA_V1,
        "status": "proposed_for_parent_execution",
        "phase_id": declaration.phase_id,
        "attempt_id": declaration.attempt_id,
        "split": declaration.split,
        "held_out_executed": False,
        "retained_calibration_queries_executed_by_dispatcher": 0,
        "arms": list(declaration.arms),
        "ordered_task_ids": list(declaration.ordered_task_ids),
        "repetitions_per_task": declaration.repetitions_per_task,
        "freeze_sha256": declaration.freeze_sha256,
        "catalog_sha256": declaration.catalog_sha256,
        "declaration_sha256": _canonical_sha256(decl_dict),
        "declaration_rel_path": declaration_rel_path,
        "output_report_rel_path": output_report_rel_path,
        "output_criteria_rel_path": output_criteria_rel_path,
        "commands": [
            (
                "PYTHONPATH=src/main/python:src/test/support/python:tools "
                "python3 tools/retrieval_evaluation.py validate"
            ),
            (
                "PYTHONPATH=src/main/python:src/test/support/python:tools "
                f"python3 tools/retrieval_evaluation.py run-calibration "
                f"--declaration {shlex.quote(declaration_rel_path)} "
                f"--output {shlex.quote(output_report_rel_path)} "
                "--attempt-root <RETAINED_ATTEMPT_ROOT> "
                f"--pg-port {pg_port} --report-schema v2"
            ),
            (
                "PYTHONPATH=src/main/python:src/test/support/python:tools "
                f"python3 tools/retrieval_evaluation.py propose-criteria-v2 "
                f"--baseline {shlex.quote(output_report_rel_path)} "
                f"--output {shlex.quote(output_criteria_rel_path)}"
            ),
        ],
    }


__all__ = [
    "W3_PHASE_ID",
    "W3_RECIPE_SCHEMA_V1",
    "build_w3_calibration_recipe",
    "declare_w3_calibration_attempt",
]
