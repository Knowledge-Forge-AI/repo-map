"""Evaluation and policy classification for pre-review check results."""

from __future__ import annotations

import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ci.pre_review_records import (
    CI_ROOT,
    Check,
    FINDING_RETURN_CODES,
    INTERNAL_FAILURE,
    MODULE_FAILURE,
    POLICY_CHECKS,
)
from ci.python_retention_inventory import format_compact_summary


def baseline() -> dict:
    """Load the pre-review ratchets from the baseline JSON file."""
    return json.loads((CI_ROOT / "pre_review_baseline.json").read_text(encoding="utf-8"))[
        "ratchets"
    ]


def finding_count(policy: str, output: str) -> int:
    """Count findings in machine-readable checker output."""
    document = json.loads(output or "null")
    if policy == "hadolint":
        return len(document)
    if policy == "pip-audit":
        dependencies = document.get("dependencies", document) if isinstance(document, dict) else document
        return sum(len(item.get("vulns", [])) for item in dependencies)
    if policy == "zizmor":
        if isinstance(document, list):
            return len(document)
        for key in ("findings", "results", "audits"):
            if isinstance(document, dict) and isinstance(document.get(key), list):
                return len(document[key])
        raise ValueError("zizmor JSON has no finding collection")
    raise ValueError(f"unknown finding policy {policy}")


def evaluate(
    check: Check,
    returncode: int,
    stdout: str,
    stderr: str = "",
) -> tuple[str, str, str]:
    """Evaluate check execution outcome against policy, returning (status, detail, classification)."""
    failure_output = stdout + stderr
    if check.policy == "retained-python-ratchets":
        try:
            document = json.loads(stdout)
            if document["schema"] != "repomap-retained-python-ratchets-result-v1":
                raise ValueError
            classification = document["classification"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return "failed", "retained ratchet JSON was invalid", "tool-failure"
        expected = {
            0: "passed",
            1: "policy-finding",
            2: "tool-failure",
        }
        if expected.get(returncode) != classification:
            return "failed", "retained ratchet exit contract was invalid", "tool-failure"
        if returncode == 0:
            return "passed", "exact retained baseline", "passed"
        if returncode == 1:
            return "failed", "retained Python ratchet delta", "policy-finding"
        return "failed", "retained Python ratchet tool failure", "tool-failure"
    if returncode != 0 and MODULE_FAILURE.search(failure_output):
        return "failed", "tool/bootstrap failure: Python module unavailable", "tool-failure"
    if returncode != 0 and INTERNAL_FAILURE.search(failure_output):
        return "failed", "tool/internal failure: bounded diagnostic retained", "tool-failure"
    if check.name == "generated-code-drift" and returncode == 2:
        return "failed", "tool/configuration failure: generated drift", "tool-failure"
    if check.policy == "file-length":
        try:
            failures = json.loads(stdout)["failure_count"]
        except (KeyError, TypeError, json.JSONDecodeError):
            return "failed", "file-length JSON was invalid", "tool-failure"
        allowed = baseline()["file-length"]["failures"]
        return (
            ("passed", f"failures={failures}; baseline={allowed}", "passed")
            if failures <= allowed
            else (
                "failed",
                f"failures={failures}; baseline={allowed}",
                "policy-finding",
            )
        )
    if check.policy in {"hadolint", "pip-audit", "zizmor"}:
        try:
            count = finding_count(check.policy, stdout)
        except (TypeError, ValueError, json.JSONDecodeError):
            return "failed", "machine-readable finding output was invalid", "tool-failure"
        allowed = baseline()[check.policy]["findings"]
        return (
            ("passed", f"findings={count}; baseline={allowed}", "passed")
            if count <= allowed
            else (
                "failed",
                f"findings={count}; baseline={allowed}",
                "policy-finding",
            )
        )
    if check.policy == "malskanner":
        try:
            document = json.loads(stdout)
            count = len(document.get("findings", []))
            verdict = document["verdict"]
        except (KeyError, TypeError, json.JSONDecodeError):
            return "failed", "MalSkanner output was invalid", "tool-failure"
        passed = returncode == 0 and verdict == "OK" and count == 0
        return (
            "passed" if passed else "failed",
            f"verdict={verdict}; findings={count}",
            "passed" if passed else "policy-finding",
        )
    if check.policy == "suppressions":
        try:
            document = json.loads(stdout)
            if document["schema"] != "repomap-scanner-suppression-inventory-v2":
                raise ValueError
            counts = {
                name: len(document[name])
                for name in ("added", "broadened", "removed", "unchanged")
            }
            blocking = bool(document["blocking"])
        except (KeyError, TypeError, json.JSONDecodeError):
            return "failed", "suppression inventory output was invalid", "tool-failure"
        except ValueError:
            return "failed", "suppression inventory schema was invalid", "tool-failure"
        detail = "; ".join(f"{name}={counts[name]}" for name in counts)
        if returncode not in {0, 1} or blocking != (returncode == 1):
            return "failed", "suppression inventory exit contract was invalid", "tool-failure"
        return (
            ("failed", detail, "policy-finding")
            if blocking
            else ("passed", detail, "passed")
        )
    if check.name in FINDING_RETURN_CODES and returncode != 0:
        if returncode not in FINDING_RETURN_CODES[check.name]:
            return "failed", f"tool/configuration failure: exit={returncode}", "tool-failure"
    if check.name == "prompt-defense-audit" and returncode != 0:
        try:
            summary = json.loads(stdout)
            valid = all(
                key in summary
                for key in ("score", "missing", "embedded_payloads", "unicode_issues")
            )
        except (TypeError, json.JSONDecodeError):
            valid = False
        if not valid:
            return "failed", "tool/configuration failure: invalid prompt audit", "tool-failure"
    if check.name == "python-retention-inventory":
        try:
            document = json.loads(stdout)
            if not isinstance(document, dict):
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return "failed", "retention inventory JSON was invalid", "tool-failure"
        if "error" in document:
            return "failed", f"tool/validation failure: {document['error']}", "tool-failure"
        if "cohort_regressions" in document and not isinstance(document["cohort_regressions"], list):
            return "failed", "cohort regressions collection is invalid", "tool-failure"
        if "cohort_results" in document and not isinstance(document["cohort_results"], dict):
            return "failed", "cohort results collection is invalid", "tool-failure"
        if "cohorts" in document and not isinstance(document["cohorts"], list):
            return "failed", "cohorts collection is invalid", "tool-failure"
        if "cohort_schema" in document and not isinstance(document["cohort_schema"], str):
            return "failed", "cohort schema is invalid", "tool-failure"

        has_tool_failure = False
        check_results = document.get("check_results", {})
        if isinstance(check_results, dict):
            for root, root_res in check_results.items():
                if not isinstance(root_res, dict):
                    has_tool_failure = True
                    break
                if (
                    root_res.get("classification") == "tool-failure"
                    or root_res.get("tool_failure")
                    or (root_res.get("returncode") is not None and root_res.get("returncode") not in (0, 1))
                    or root_res.get("reason") == "profile path attestation mismatch"
                ):
                    has_tool_failure = True
                    break
        elif check_results is not None:
            has_tool_failure = True

        cohort_results = document.get("cohort_results", {})
        if isinstance(cohort_results, dict):
            for cid, cres in cohort_results.items():
                if not isinstance(cres, dict):
                    has_tool_failure = True
                    break
                if (
                    cres.get("classification") == "tool-failure"
                    or cres.get("tool_failure")
                    or (cres.get("returncode") is not None and cres.get("returncode") not in (0, 1))
                ):
                    has_tool_failure = True
                    break
        elif cohort_results is not None:
            has_tool_failure = True

        cohort_regressions = document.get("cohort_regressions", [])
        declared_regressions = any(
            isinstance(c, dict) and c.get("admission") == "admitted" and (
                not isinstance(cohort_results.get(c.get("id")), dict)
                or cohort_results[c["id"]].get("status") != "passed"
                or cohort_results[c["id"]].get("effective_enforcement") is not True
            ) for c in document.get("cohorts", [])
        )
        has_regressions = (
            declared_regressions or
            (isinstance(cohort_regressions, list) and len(cohort_regressions) > 0)
            or document.get("classification") == "ratchet-regression"
        )
        status = document.get("status", "failed")
        enforcement_complete = bool(document.get("enforcement_complete", False))
        residual_dict = document.get("eligible_minus_enforced", document.get("unassigned", {}))
        has_residual = isinstance(residual_dict, dict) and any(bool(v) for v in residual_dict.values())

        summary = (
            format_compact_summary(document, multiline=False)
            if format_compact_summary is not None
            else f"status={status}; exit={returncode}"
        )
        if has_tool_failure:
            return "failed", summary, "tool-failure"
        if has_regressions:
            return "failed", summary, "ratchet-regression"
        if returncode == 0 and status == "passed" and enforcement_complete and not has_residual:
            census = document.get("counts", {}).get("total_files", 0)
            return "passed", f"enforcement complete: census={census}", "passed"
        return "failed", summary, "policy-finding"
    if returncode == 0:
        return "passed", "exit=0", "passed"
    classification = "policy-finding" if check.name in POLICY_CHECKS else "check-failure"
    return "failed", f"exit={returncode}", classification
