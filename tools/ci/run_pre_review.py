#!/usr/bin/env python3
"""Run RepoMap's complete pre-review stack and fail once at the end."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ci.pre_review_checks import (
    _attest_check_owner as _attest_check_owner,
    _attest_python_owner as _attest_python_owner,
    _command_attestation as _command_attestation,
    _interpreter as _interpreter,
    checks as checks,
)
from ci.pre_review_evaluation import (
    baseline as baseline,
    evaluate as evaluate,
    finding_count as finding_count,
)
from ci.pre_review_evidence import (
    AGGREGATE_CAP_BYTES,
    LOG_CAP_BYTES,
    bounded_log,
    finalize_evidence,
)
from ci.pre_review_records import (
    CI_ROOT as CI_ROOT,
    Check as Check,
    FINDING_RETURN_CODES as FINDING_RETURN_CODES,
    INTERNAL_FAILURE as INTERNAL_FAILURE,
    MODULE_FAILURE as MODULE_FAILURE,
    POLICY_CHECKS as POLICY_CHECKS,
    ROOT as ROOT,
    Result as Result,
    SECRET_TEXT as SECRET_TEXT,
    SENSITIVE_SCANNERS as SENSITIVE_SCANNERS,
    sanitize as sanitize,
    sanitize_machine_result as sanitize_machine_result,
)
from ci.python_retention_evidence import (
    compact_retention_evidence,
    create_incomplete_retention_evidence,
)
from ci.python_retention_inventory import format_compact_summary



def execute_all(
    selected: tuple[Check, ...],
    evidence_dir: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    scratch_dir: Path | None = None,
    tool_root: Path | None = None,
) -> tuple[Result, ...]:
    if scratch_dir is None:
        with tempfile.TemporaryDirectory(prefix="repomap-pre-review-run-") as raw:
            return execute_all(
                selected,
                evidence_dir,
                runner=runner,
                scratch_dir=Path(raw),
                tool_root=tool_root,
            )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir.mkdir(parents=True, exist_ok=True)
    clean_env = dict(os.environ)
    for key in tuple(clean_env):
        if key.endswith("_API_KEY") or key in {"ANTHROPIC_API_KEY", "SEMGREP_APP_TOKEN"}:
            clean_env.pop(key)
    clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
    clean_env["PYTHONPYCACHEPREFIX"] = str(scratch_dir / "pycache")
    clean_env["MYPYPATH"] = str(ROOT / "src/main/python")
    if tool_root is not None:
        owned_paths = (
            tool_root / "bin",
            tool_root / "python" / "bin",
            tool_root / "node" / "node_modules" / ".bin",
            tool_root / "liquibase",
        )
        clean_env["PATH"] = os.pathsep.join(
            (str(path) for path in owned_paths)
        ) + os.pathsep + clean_env.get("PATH", "")
    results = []
    for check in selected:
        started = time.monotonic()
        interpreter = _interpreter(check)
        try:
            _attest_check_owner(check, tool_root)
            completed = runner(
                list(check.command),
                cwd=check.cwd,
                env=clean_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
            status, detail, classification = evaluate(
                check,
                completed.returncode,
                completed.stdout,
                completed.stderr,
            )
            retained = (
                detail
                if check.name in SENSITIVE_SCANNERS
                else sanitize(
                    completed.stdout + completed.stderr,
                    scratch_dir,
                    *(tuple((tool_root,)) if tool_root is not None else ()),
                )
            )
            if check.name == "python-retention-inventory":
                result_json_path = evidence_dir / "python-retention-inventory.result.json"
                multiline_summary = ""
                private_targets = (
                    scratch_dir,
                    *(tuple((tool_root,)) if tool_root is not None else ()),
                )
                try:
                    raw_doc = json.loads(completed.stdout)
                    if not isinstance(raw_doc, dict):
                        raise ValueError("retention result is not an object")
                    if "error" in raw_doc:
                        raise ValueError(raw_doc.get("error", "invalid retention document"))
                    document = sanitize_machine_result(raw_doc, *private_targets)
                    if not isinstance(document, dict):
                        raise ValueError("sanitized retention result is not an object")
                    compact_doc = compact_retention_evidence(document)
                    compact_bytes = json.dumps(compact_doc, separators=(",", ":"), sort_keys=True) + "\n"
                    result_json_path.write_text(compact_bytes, encoding="utf-8")
                    multiline_summary = format_compact_summary(document, multiline=True)
                except (ValueError, TypeError, KeyError) as error:
                    sanitized_err = sanitize(str(error), *private_targets)
                    status, classification = "failed", "tool-failure"
                    detail = "retention evidence projection failed"
                    sanitized_stdout = sanitize(completed.stdout, *private_targets)
                    incomplete_doc = create_incomplete_retention_evidence(
                        error=sanitized_err,
                        raw_output=sanitized_stdout,
                        classification="tool-failure",
                        returncode=completed.returncode,
                        failure_stage="parse-or-validation-error",
                    )
                    compact_bytes = json.dumps(incomplete_doc, separators=(",", ":"), sort_keys=True) + "\n"
                    result_json_path.write_text(compact_bytes, encoding="utf-8")
                    multiline_summary = (
                        f"status: failed\n"
                        f"error: {sanitized_err}\n"
                        f"exit={completed.returncode}"
                    )

                retained = (
                    f"\n--- COMPACT FAILURE SUMMARY ---\n"
                    f"{multiline_summary}\n"
                    f"-------------------------------\n\n"
                    f"--- FULL OUTPUT (capped at {LOG_CAP_BYTES} bytes) ---\n"
                    f"{retained}"
                )
            returncode = completed.returncode
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            status = "failed"
            detail = f"tool/bootstrap failure: {type(error).__name__}"
            classification = "tool-failure"
            returncode = None
            retained = detail
            if check.name == "python-retention-inventory":
                private_targets = (
                    scratch_dir,
                    *(tuple((tool_root,)) if tool_root is not None else ()),
                )
                incomplete_doc = create_incomplete_retention_evidence(
                    error=sanitize(detail, *private_targets),
                    classification="tool-failure",
                    returncode=None,
                    failure_stage=type(error).__name__,
                )
                (evidence_dir / "python-retention-inventory.result.json").write_text(
                    json.dumps(incomplete_doc, separators=(",", ":"), sort_keys=True) + "\n",
                    encoding="utf-8",
                )
        header = (
            f"check={check.name}\n"
            f"interpreter={interpreter or 'none'}\n"
            f"command={_command_attestation(check, tool_root)}\n"
            f"classification={classification}\n"
        )
        (evidence_dir / f"{check.name}.log").write_text(
            bounded_log(header + retained),
            encoding="utf-8",
        )
        results.append(
            Result(
                check.name,
                status,
                returncode,
                time.monotonic() - started,
                detail,
                classification,
                interpreter,
            )
        )
    return tuple(results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--tool-root", required=True, type=Path)
    args = parser.parse_args(argv)
    _attest_python_owner(args.tool_root)
    with tempfile.TemporaryDirectory(prefix="repomap-pre-review-scratch-") as raw:
        scratch_dir = Path(raw)
        selected = checks(scratch_dir, args.tool_root)
        results = execute_all(
            selected,
            args.evidence_dir,
            scratch_dir=scratch_dir,
            tool_root=args.tool_root,
        )
        evidence_error = None
        evidence_headroom = None
        try:
            evidence_headroom = finalize_evidence(args.evidence_dir, selected, results)
        except (OSError, RuntimeError) as error:
            evidence_error = sanitize(str(error), scratch_dir, args.tool_root)
    for result in results:
        print(
            f"{result.status.upper():6} {result.name:24} "
            f"{result.elapsed_seconds:7.2f}s {result.detail}"
        )
    failed = [result for result in results if result.status != "passed"]
    print(f"pre-review summary: {len(results) - len(failed)} passed; {len(failed)} failed")
    if evidence_error is not None:
        print(f"FAILED evidence-finalization: {evidence_error}")
        print("Evidence is incomplete or unqualified; retained check statuses remain valid.")
    if evidence_headroom is not None:
        print(f"evidence headroom: {evidence_headroom} bytes")
        if evidence_headroom < AGGREGATE_CAP_BYTES // 5:
            print("WARNING evidence envelope has less than 20% capacity remaining")
    return 1 if failed or evidence_error is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
