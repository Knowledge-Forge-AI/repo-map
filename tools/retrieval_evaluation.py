"""Developer CLI for the W2 CLOE retrieval evaluation instrument (S3)."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
from retrieval_evaluation_criteria import derive_future_criteria_proposal
from retrieval_evaluation_criteria_v2 import derive_future_criteria_proposal_v2
from retrieval_evaluation_harness import (
    BASELINE_REPORT_SCHEMA_VERSION,
    build_freeze_manifest,
    declare_calibration_attempt,
    execute_calibration_baseline,
    verify_fixture_freeze_guard,
)
from retrieval_evaluation_reprojection import reproject_attempt7_files
from retrieval_evaluation_schema import (
    AttemptDeclaration,
    load_freeze_manifest,
    load_task_catalog,
)
from retrieval_evaluation_summary_v2 import BASELINE_REPORT_SCHEMA_V2
from retrieval_evaluation_w3 import (
    build_w3_calibration_recipe,
    declare_w3_calibration_attempt,
)


DEFAULT_CATALOG_PATH = MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json"
DEFAULT_FREEZE_PATH = MIXED_V1_FIXTURE_ROOT / "freeze-v1.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retrieval_evaluation",
        description="W2 CLOE retrieval evaluation and calibration baseline harness",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="Validate task catalog and freeze manifest")
    p_val.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    p_val.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE_PATH)

    p_frz = sub.add_parser("freeze", help="Generate pre-query freeze-v1.json")
    p_frz.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    p_frz.add_argument("--output", type=Path, default=DEFAULT_FREEZE_PATH)

    p_decl = sub.add_parser(
        "declare-attempt", help="Declare a calibration baseline attempt"
    )
    p_decl.add_argument("--attempt-id", required=True)
    p_decl.add_argument("--split", default="calibration")
    p_decl.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    p_decl.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE_PATH)
    p_decl.add_argument("--output", type=Path, required=True)
    p_decl.add_argument("--pg-port", type=int, default=55433)

    p_run = sub.add_parser(
        "run-calibration", help="Execute a declared 24-task calibration baseline"
    )
    p_run.add_argument("--declaration", type=Path, required=True)
    p_run.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    p_run.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE_PATH)
    p_run.add_argument("--output", type=Path, required=True)
    p_run.add_argument("--attempt-root", type=Path, required=True,
                       help="Persistent experiment directory; attempt IDs cannot be reused here")
    p_run.add_argument("--pg-host", default="127.0.0.1")
    p_run.add_argument("--pg-port", type=int, default=55433)
    p_run.add_argument("--pg-database", default="repomap_mixed_v1")
    p_run.add_argument("--pg-user", default="repomap")
    p_run.add_argument(
        "--report-schema",
        choices=("v1", "v2", BASELINE_REPORT_SCHEMA_VERSION, BASELINE_REPORT_SCHEMA_V2),
        default=None,
        help="Report schema version to emit ('v1' for W2 5-arm reports, 'v2' for W3 6-arm reports)",
    )

    p_crit = sub.add_parser(
        "propose-criteria",
        help="Derive a parent-reviewable W3 criteria proposal from baseline report",
    )
    p_crit.add_argument("--baseline", type=Path, required=True)
    p_crit.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    p_crit.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE_PATH)
    p_crit.add_argument("--output", type=Path, required=True)

    p_crit2 = sub.add_parser(
        "propose-criteria-v2",
        help="Derive a source-bound v2 criteria proposal from a v2 baseline report",
    )
    p_crit2.add_argument("--baseline", type=Path, required=True)
    p_crit2.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    p_crit2.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE_PATH)
    p_crit2.add_argument("--output", type=Path, required=True)

    p_rep = sub.add_parser(
        "reproject-v2",
        help="Reproject historical v1 baseline report into separate v2 report and criteria artifacts",
    )
    p_rep.add_argument("--report", type=Path, required=True)
    p_rep.add_argument("--declaration", type=Path, required=True)
    p_rep.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    p_rep.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE_PATH)
    p_rep.add_argument("--output-report", type=Path, required=True)
    p_rep.add_argument("--output-criteria", type=Path, required=True)
    p_rep.add_argument("--journal", type=Path, default=None)

    p_w3 = sub.add_parser(
        "declare-w3-attempt",
        help="Declare a 6-arm W3 calibration attempt and optional parent execution recipe",
    )
    p_w3.add_argument("--attempt-id", default="w3-calibration-attempt-1")
    p_w3.add_argument("--split", default="calibration")
    p_w3.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    p_w3.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE_PATH)
    p_w3.add_argument("--output", type=Path, required=True)
    p_w3.add_argument("--recipe-output", type=Path, default=None)
    p_w3.add_argument("--pg-port", type=int, default=55433)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for retrieval_evaluation."""
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.command in {
            "freeze", "declare-attempt", "declare-w3-attempt",
            "run-calibration", "propose-criteria", "propose-criteria-v2",
        } and args.output.exists():
            raise FileExistsError("refusing to overwrite existing output; retain it and choose a new path")
        if args.command == "validate":
            catalog = load_task_catalog(args.catalog)
            freeze = load_freeze_manifest(args.freeze)
            with tempfile.TemporaryDirectory(prefix="cloe-ret-val-") as tmp:
                verify_fixture_freeze_guard(catalog, freeze, work_dir=Path(tmp))
            payload = {
                "status": "valid",
                "total_tasks": len(catalog.tasks),
                "calibration_tasks": len(catalog.calibration_tasks()),
                "held_out_tasks": len(catalog.held_out_tasks()),
                "catalog_sha256": catalog.catalog_digest(),
                "freeze_sha256": freeze.freeze_digest(),
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        if args.command == "freeze":
            catalog = load_task_catalog(args.catalog)
            with tempfile.TemporaryDirectory(prefix="cloe-ret-frz-") as tmp:
                freeze = build_freeze_manifest(catalog, work_dir=Path(tmp))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as output:
                output.write(json.dumps(freeze.to_dict(), indent=2, sort_keys=True, allow_nan=False) + "\n")
            print(json.dumps({"status": "frozen", "freeze_sha256": freeze.freeze_digest()}))
            return 0

        if args.command == "declare-attempt":
            if args.split != "calibration":
                print(
                    f"error: W2 refuses attempt declaration or execution for split {args.split!r}; held_out is reserved for W3",
                    file=sys.stderr,
                )
                return 2
            catalog = load_task_catalog(args.catalog)
            freeze = load_freeze_manifest(args.freeze)
            decl = declare_calibration_attempt(
                catalog,
                freeze,
                attempt_id=args.attempt_id,
                split=args.split,
                pg_port=args.pg_port,
                execution_purpose="retained_calibration",
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            try:
                with args.output.open("x", encoding="utf-8") as output:
                    output.write(json.dumps(decl.to_dict(), indent=2, sort_keys=True) + "\n")
            except FileExistsError:
                raise FileExistsError("refusing to overwrite existing attempt declaration") from None
            print(json.dumps({"status": "declared", "attempt_id": decl.attempt_id}))
            return 0

        if args.command == "run-calibration":
            if args.output.exists():
                raise FileExistsError(
                    f"refusing to overwrite existing calibration report {args.output}; retain prior attempts and use a new attempt ID"
                )
            catalog = load_task_catalog(args.catalog)
            freeze = load_freeze_manifest(args.freeze)
            decl_raw = json.loads(args.declaration.read_text(encoding="utf-8"))
            decl = AttemptDeclaration.from_mapping(decl_raw)
            if decl.runner_profile.get("execution_purpose") != "retained_calibration":
                raise ValueError("CLI measurement requires a retained_calibration declaration")
            if args.report_schema in {"v2", BASELINE_REPORT_SCHEMA_V2}:
                report_schema_version = BASELINE_REPORT_SCHEMA_V2
            elif args.report_schema in {"v1", BASELINE_REPORT_SCHEMA_VERSION}:
                report_schema_version = BASELINE_REPORT_SCHEMA_VERSION
            else:
                report_schema_version = str(
                    decl.runner_profile.get("report_schema_version", BASELINE_REPORT_SCHEMA_VERSION)
                )
            with tempfile.TemporaryDirectory(prefix="cloe-ret-run-") as tmp:
                report = execute_calibration_baseline(
                    catalog,
                    freeze,
                    decl,
                    work_dir=Path(tmp),
                    pg_host=args.pg_host,
                    pg_port=args.pg_port,
                    pg_database=args.pg_database,
                    pg_user=args.pg_user,
                    include_postgres=True,
                    attempt_root=args.attempt_root,
                    report_schema_version=report_schema_version,
                )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as output:
                output.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
            print(json.dumps({"status": report["status"], "attempt_id": decl.attempt_id}))
            return 0 if report["status"] == "completed" else 2

        if args.command == "propose-criteria":
            catalog = load_task_catalog(args.catalog)
            freeze = load_freeze_manifest(args.freeze)
            baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
            proposal = derive_future_criteria_proposal(
                baseline,
                freeze_sha256=freeze.freeze_digest(),
                catalog_sha256=catalog.catalog_digest(),
                policy_digest=freeze.policy_digest,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as output:
                output.write(json.dumps(proposal.to_dict(), indent=2, sort_keys=True, allow_nan=False) + "\n")
            print(json.dumps({"status": proposal.status}))
            return 0

        if args.command == "propose-criteria-v2":
            catalog = load_task_catalog(args.catalog)
            freeze = load_freeze_manifest(args.freeze)
            baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
            proposal_v2 = derive_future_criteria_proposal_v2(
                baseline,
                freeze_sha256=freeze.freeze_digest(),
                catalog_sha256=catalog.catalog_digest(),
                policy_digest=freeze.policy_digest,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as output:
                output.write(json.dumps(proposal_v2.to_dict(), indent=2, sort_keys=True, allow_nan=False) + "\n")
            print(json.dumps({"status": proposal_v2.status, "schema_version": proposal_v2.schema_version}))
            return 0

        if args.command == "reproject-v2":
            if args.output_report.exists() or args.output_criteria.exists():
                raise FileExistsError("refusing to overwrite existing reprojected output")
            report_v2, criteria_v2 = reproject_attempt7_files(
                attempt7_report_path=args.report,
                attempt7_declaration_path=args.declaration,
                catalog_path=args.catalog,
                freeze_path=args.freeze,
                journal_path=args.journal,
            )
            args.output_report.parent.mkdir(parents=True, exist_ok=True)
            args.output_criteria.parent.mkdir(parents=True, exist_ok=True)
            with args.output_report.open("x", encoding="utf-8") as out_r:
                out_r.write(json.dumps(report_v2, indent=2, sort_keys=True, allow_nan=False) + "\n")
            with args.output_criteria.open("x", encoding="utf-8") as out_c:
                out_c.write(json.dumps(criteria_v2.to_dict(), indent=2, sort_keys=True, allow_nan=False) + "\n")
            print(json.dumps({"status": "reprojected", "attempt_id": report_v2["attempt_id"]}))
            return 0

        if args.command == "declare-w3-attempt":
            if args.recipe_output is not None and args.recipe_output.exists():
                raise FileExistsError("refusing to overwrite existing recipe output")
            catalog = load_task_catalog(args.catalog)
            freeze = load_freeze_manifest(args.freeze)
            decl = declare_w3_calibration_attempt(
                catalog,
                freeze,
                attempt_id=args.attempt_id,
                split=args.split,
                pg_port=args.pg_port,
                execution_purpose="retained_calibration",
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as out_d:
                out_d.write(json.dumps(decl.to_dict(), indent=2, sort_keys=True) + "\n")
            if args.recipe_output is not None:
                recipe = build_w3_calibration_recipe(decl)
                args.recipe_output.parent.mkdir(parents=True, exist_ok=True)
                with args.recipe_output.open("x", encoding="utf-8") as out_rec:
                    out_rec.write(json.dumps(recipe, indent=2, sort_keys=True) + "\n")
            print(json.dumps({"status": "declared", "attempt_id": decl.attempt_id, "arms": len(decl.arms)}))
            return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
