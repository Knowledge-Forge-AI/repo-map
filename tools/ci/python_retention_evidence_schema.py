"""Schema definitions and strict fail-closed validation for compact retention evidence."""

from __future__ import annotations

from typing import Any
import math

from ci.python_retention_evidence_source import REQUIRED_ROOTS


COMPLETE_SCHEMA = "repomap-python-retention-evidence-v1"
INCOMPLETE_SCHEMA = "repomap-python-retention-evidence-incomplete-v1"
CANONICAL_VERSION = "repomap-canonical-json-v1"

VALID_SCHEMAS = frozenset({COMPLETE_SCHEMA, INCOMPLETE_SCHEMA})
VALID_STATUSES = frozenset({"passed", "failed"})
VALID_CLASSIFICATIONS = frozenset({
    "passed",
    "policy-finding",
    "tool-failure",
    "ratchet-regression",
})
HEX_CHARS = frozenset("0123456789abcdef")


class RetentionSchemaError(ValueError):
    """Schema violation in retained retention evidence."""


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in HEX_CHARS for ch in value)
    )


def validate_retention_evidence_schema(doc: Any) -> None:
    """Validate that doc conforms strictly to COMPLETE_SCHEMA or INCOMPLETE_SCHEMA."""
    if not isinstance(doc, dict):
        raise RetentionSchemaError("retention evidence must be an object")

    schema = doc.get("schema")
    if schema not in VALID_SCHEMAS:
        raise RetentionSchemaError(f"unsupported retention evidence schema: {schema!r}")

    status = doc.get("status")
    if status not in VALID_STATUSES:
        raise RetentionSchemaError(f"invalid status: {status!r}")

    classification = doc.get("classification")
    if classification not in VALID_CLASSIFICATIONS:
        raise RetentionSchemaError(f"invalid classification: {classification!r}")

    enforcement_complete = doc.get("enforcement_complete")
    if not isinstance(enforcement_complete, bool):
        raise RetentionSchemaError("enforcement_complete must be a boolean")

    complete = doc.get("complete")
    if not isinstance(complete, bool):
        raise RetentionSchemaError("complete must be a boolean")

    if schema == INCOMPLETE_SCHEMA:
        _validate_incomplete(doc, status, classification, enforcement_complete, complete)
    else:
        _validate_complete(doc, status, classification, enforcement_complete, complete)


def _validate_incomplete(
    doc: dict[str, Any],
    status: str,
    classification: str,
    enforcement_complete: bool,
    complete: bool,
) -> None:
    if status != "failed":
        raise RetentionSchemaError("incomplete evidence status must be 'failed'")
    if classification != "tool-failure":
        raise RetentionSchemaError("incomplete evidence classification must be 'tool-failure'")
    if enforcement_complete is not False:
        raise RetentionSchemaError("incomplete evidence enforcement_complete must be False")
    if complete is not False:
        raise RetentionSchemaError("incomplete evidence complete must be False")

    error = doc.get("error")
    if not isinstance(error, str) or not error.strip():
        raise RetentionSchemaError("incomplete evidence requires a non-empty error message")

    failure_stage = doc.get("failure_stage")
    if not isinstance(failure_stage, str) or not failure_stage.strip():
        raise RetentionSchemaError("incomplete evidence requires a failure_stage")

    returncode = doc.get("returncode")
    if returncode is not None and not isinstance(returncode, int):
        raise RetentionSchemaError("incomplete evidence returncode must be int or null")

    totals = doc.get("totals", {})
    if not isinstance(totals, dict):
        raise RetentionSchemaError("incomplete evidence totals must be a dict")
    for key in ("eligible", "assigned", "enforced", "residual"):
        if totals.get(key, 0) != 0:
            raise RetentionSchemaError("incomplete evidence cannot declare positive counts")

    cohorts = doc.get("cohorts", {})
    if not isinstance(cohorts, dict):
        raise RetentionSchemaError("incomplete evidence cohorts must be a dict")
    if cohorts.get("regression_count", 0) != 0 or cohorts.get("regressions", []):
        raise RetentionSchemaError("incomplete evidence cannot declare cohort regressions")

    commit = doc.get("sanitized_source_commitment")
    if not isinstance(commit, dict) or not _is_sha256(commit.get("sha256")):
        raise RetentionSchemaError("incomplete evidence requires a valid sanitized_source_commitment")
    if commit.get("canonical_version") != CANONICAL_VERSION:
        raise RetentionSchemaError(f"invalid canonical_version: {commit.get('canonical_version')!r}")


def _validate_complete(
    doc: dict[str, Any],
    status: str,
    classification: str,
    enforcement_complete: bool,
    complete: bool,
) -> None:
    if complete is not True:
        raise RetentionSchemaError("complete evidence complete must be True")

    totals = doc.get("totals")
    if not isinstance(totals, dict):
        raise RetentionSchemaError("complete evidence totals must be an object")
    for key in ("census", "eligible", "assigned", "enforced", "residual"):
        val = totals.get(key)
        if type(val) is not int or val < 0:
            raise RetentionSchemaError(f"totals.{key} must be a non-negative integer")

    if totals["census"] < totals["eligible"]:
        raise RetentionSchemaError("totals.census cannot be less than totals.eligible")
    if totals["eligible"] < totals["assigned"]:
        raise RetentionSchemaError("totals.eligible cannot be less than totals.assigned")
    if totals["assigned"] < totals["enforced"]:
        raise RetentionSchemaError("totals.assigned cannot be less than totals.enforced")
    if totals["residual"] != totals["eligible"] - totals["enforced"]:
        raise RetentionSchemaError("totals.residual must equal eligible minus enforced")

    roots = doc.get("roots")
    if not isinstance(roots, dict):
        raise RetentionSchemaError("roots breakdown must be an object")
    for root, rinfo in roots.items():
        if not isinstance(rinfo, dict):
            raise RetentionSchemaError(f"roots.{root} must be an object")
        for key in ("eligible", "assigned", "enforced", "residual"):
            val = rinfo.get(key)
            if type(val) is not int or val < 0:
                raise RetentionSchemaError(f"roots.{root}.{key} must be a non-negative integer")
        if not isinstance(rinfo.get("closed"), bool):
            raise RetentionSchemaError(f"roots.{root}.closed must be a boolean")
        if not isinstance(rinfo.get("state"), str):
            raise RetentionSchemaError(f"roots.{root}.state must be a string")

    if set(roots) != REQUIRED_ROOTS:
        raise RetentionSchemaError("roots must cover six required roots")
    for key in ("eligible", "assigned", "enforced", "residual"):
        if sum(r[key] for r in roots.values()) != totals[key]:
            raise RetentionSchemaError("root totals mismatch")
    for r in roots.values():
        if not r["enforced"] <= r["assigned"] <= r["eligible"] or r["residual"] != r["eligible"] - r["enforced"]:
            raise RetentionSchemaError("root partition mismatch")
        if r["closed"] and r["residual"]:
            raise RetentionSchemaError("closed root cannot have residual")
        if type(r.get("tool_failure")) is not bool:
            raise RetentionSchemaError("root tool failure flag missing")
        for key in ("unknown_count", "finding_or_failure_count"):
            if type(r.get(key)) is not int or not 0 <= r[key] <= r["eligible"]:
                raise RetentionSchemaError("root diagnostic count invalid")
    finding_counts = doc.get("finding_counts")
    if not isinstance(finding_counts, dict) or set(finding_counts) != REQUIRED_ROOTS:
        raise RetentionSchemaError("finding_counts must cover six roots")
    for root, checkers in finding_counts.items():
        if not isinstance(checkers, dict):
            raise RetentionSchemaError(f"finding_counts.{root} must be an object")
        for checker, cnt in checkers.items():
            if type(cnt) is not int or cnt < 0:
                raise RetentionSchemaError(f"finding count for {root}.{checker} must be non-negative int")

    cohorts = doc.get("cohorts")
    if not isinstance(cohorts, dict):
        raise RetentionSchemaError("cohorts summary must be an object")
    for key in ("total", "admitted", "pending", "passed", "failed", "regression_count"):
        val = cohorts.get(key)
        if type(val) is not int or val < 0:
            raise RetentionSchemaError(f"cohorts.{key} must be a non-negative integer")

    if cohorts["total"] != cohorts["admitted"] + cohorts["pending"]:
        raise RetentionSchemaError("cohorts.total must equal admitted plus pending")

    regressions = cohorts.get("regressions")
    if not isinstance(regressions, list) or any(not isinstance(r, str) for r in regressions):
        raise RetentionSchemaError("cohorts.regressions must be a list of strings")
    if len(regressions) != cohorts["regression_count"]:
        raise RetentionSchemaError("cohorts.regressions length must match cohorts.regression_count")
    if regressions != sorted(set(regressions)):
        raise RetentionSchemaError("cohorts.regressions must be sorted and contain no duplicates")

    if status == "passed":
        if not enforcement_complete:
            raise RetentionSchemaError("status 'passed' requires enforcement_complete=True")
        if classification != "passed":
            raise RetentionSchemaError("status 'passed' requires classification='passed'")
        if totals["residual"] != 0:
            raise RetentionSchemaError("status 'passed' requires zero residual debt")
        if cohorts["regression_count"] != 0:
            raise RetentionSchemaError("status 'passed' cannot have cohort regressions")

    if cohorts["regression_count"] > 0 and status != "failed":
        raise RetentionSchemaError("cohort regressions require status='failed'")

    if cohorts["passed"] + cohorts["failed"] != cohorts["total"]:
        raise RetentionSchemaError("cohort result totals mismatch")
    if bool(cohorts["regressions"]) != (classification == "ratchet-regression"):
        raise RetentionSchemaError("regression classification mismatch")
    if (status == "passed") != (classification == "passed") or enforcement_complete != (status == "passed"):
        raise RetentionSchemaError("status classification mismatch")
    bindings = doc.get("bindings")
    if not isinstance(bindings, dict):
        raise RetentionSchemaError("bindings must be an object")
    for b_key in ("candidate_scope", "inventory_path"):
        val = bindings.get(b_key)
        if not isinstance(val, str) or not val.strip():
            raise RetentionSchemaError(f"bindings.{b_key} must be a non-empty string")

    for key in ("inventory_sha256", "ratchet_sha256"):
        if not _is_sha256(bindings.get(key)):
            raise RetentionSchemaError("missing immutable digest binding")
    for key in ("governing_inputs", "history", "environment"):
        if not isinstance(bindings.get(key), dict) or not bindings[key]:
            raise RetentionSchemaError("missing immutable structured binding")
    if bindings["history"].get("candidate_inventory_sha256") != bindings["inventory_sha256"]:
        raise RetentionSchemaError("inventory history binding mismatch")
    if not _is_sha256(bindings["environment"].get("sha256")):
        raise RetentionSchemaError("invalid environment binding")
    candidate = bindings["history"].get("candidate", {})
    if any(not isinstance(candidate.get(k), str) or len(candidate[k]) not in (40, 64)
           or any(c not in HEX_CHARS for c in candidate[k]) for k in ("commit", "tree")):
        raise RetentionSchemaError("invalid candidate identity")
    timings = doc.get("timings")
    if not isinstance(timings, dict):
        raise RetentionSchemaError("timings must be an object")
    for t_key in ("validation_duration_seconds", "cohort_evaluation_duration_seconds", "duration_seconds"):
        val = timings.get(t_key)
        if not isinstance(val, (int, float)) or isinstance(val, bool) or not math.isfinite(val) or val < 0:
            raise RetentionSchemaError(f"timings.{t_key} must be a non-negative number")

    root_times = timings.get("root_check_seconds")
    if not isinstance(root_times, dict) or set(root_times) != REQUIRED_ROOTS:
        raise RetentionSchemaError("root timings must cover six roots")
    for value in root_times.values():
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise RetentionSchemaError("root duration must be unavailable or finite and non-negative")

    examples = doc.get("bounded_examples")
    if not isinstance(examples, dict):
        raise RetentionSchemaError("bounded_examples must be an object")
    if not isinstance(examples.get("residual"), dict) or not isinstance(examples.get("blockers"), dict):
        raise RetentionSchemaError("bounded_examples must contain residual and blockers objects")

    omitted = doc.get("omitted_collections")
    if not isinstance(omitted, dict):
        raise RetentionSchemaError("omitted_collections must be an object")
    for name, coll in omitted.items():
        if not isinstance(coll, dict):
            raise RetentionSchemaError(f"omitted_collections.{name} must be an object")
        if not isinstance(coll.get("element_type"), str) or not coll.get("element_type"):
            raise RetentionSchemaError(f"omitted_collections.{name}.element_type must be a non-empty string")
        if type(coll.get("count")) is not int or coll["count"] < 0:
            raise RetentionSchemaError(f"omitted_collections.{name}.count must be a non-negative integer")
        if coll.get("canonical_version") != CANONICAL_VERSION:
            raise RetentionSchemaError(f"omitted_collections.{name}.canonical_version invalid")
        if not _is_sha256(coll.get("sha256")):
            raise RetentionSchemaError(f"omitted_collections.{name}.sha256 must be a valid 64-char hex string")

    mandatory = {"candidate_files": totals["census"], "eligible_paths": totals["eligible"],
                 "assigned_paths": totals["assigned"], "enforced_paths": totals["enforced"],
                 "residual_paths": totals["residual"], "cohort_results": cohorts["total"],
                 "cohorts": cohorts["total"], "check_results": len(REQUIRED_ROOTS),
                 "cohort_dependency_paths": None, "cohort_dependency_blockers": None}
    for key, count in mandatory.items():
        if key not in omitted or count is not None and omitted[key]["count"] != count:
            raise RetentionSchemaError("missing or inconsistent collection commitment")
    commit = doc.get("sanitized_source_commitment")
    if not isinstance(commit, dict):
        raise RetentionSchemaError("sanitized_source_commitment must be an object")
    if commit.get("canonical_version") != CANONICAL_VERSION:
        raise RetentionSchemaError("sanitized_source_commitment.canonical_version invalid")
    if not _is_sha256(commit.get("sha256")):
        raise RetentionSchemaError("sanitized_source_commitment.sha256 must be a valid 64-char hex string")
