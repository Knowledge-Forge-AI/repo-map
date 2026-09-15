"""Strict fail-closed validation for complete retention evidence source documents."""

from __future__ import annotations

import math
from typing import Any

REQUIRED_ROOTS = frozenset({
    "product",
    "tools",
    "test_support",
    "test_owners",
    "conftest",
    "fixtures",
})
HEX_CHARS = frozenset("0123456789abcdef")
VALID_STATUSES = frozenset({"passed", "failed"})
VALID_CLASSIFICATIONS = frozenset({
    "passed",
    "policy-finding",
    "tool-failure",
    "ratchet-regression",
})


class RetentionSourceValidationError(ValueError):
    """Validation error in full retention source document."""


def _is_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_finite_num(val: Any) -> bool:
    return (not isinstance(val, bool)) and isinstance(val, (int, float)) and math.isfinite(val) and val >= 0


def _is_hex(val: Any, length: int) -> bool:
    return isinstance(val, str) and len(val) == length and all(c in HEX_CHARS for c in val.lower())


def _is_git_hash(val: Any) -> bool:
    return _is_hex(val, 40) or _is_hex(val, 64)


def validate_source_document(source: Any) -> None:
    """Validate that source conforms strictly to the full checked retention source contract."""
    if not isinstance(source, dict):
        raise RetentionSourceValidationError("source must be a dictionary")

    required_keys = (
        "status", "classification", "enforcement_complete", "counts",
        "eligible_minus_enforced", "unassigned", "profile_progress", "candidate_scope",
        "cohort_dependency_paths", "cohort_dependency_blockers",
        "census_complete", "root_separation_valid", "closure_valid",
        "candidate_sha256", "eligible", "assigned", "enforced", "check_results",
        "cohorts", "cohort_results", "cohort_regressions", "governing_inputs",
        "history", "environment", "inventory_path", "ratchet_sha256",
        "duration_seconds", "validation_duration_seconds", "cohort_evaluation_duration_seconds",
    )
    for req in required_keys:
        if req not in source:
            raise RetentionSourceValidationError(f"source missing required field: {req!r}")

    if any(source[name] is not True for name in ("census_complete", "closure_valid", "root_separation_valid")):
        raise RetentionSourceValidationError("incomplete census or closure authority")
    status = source["status"]
    if status not in VALID_STATUSES:
        raise RetentionSourceValidationError(f"invalid status: {status!r}")

    classification = source["classification"]
    if classification not in VALID_CLASSIFICATIONS:
        raise RetentionSourceValidationError(f"invalid classification: {classification!r}")

    enforcement_complete = source["enforcement_complete"]
    if not isinstance(enforcement_complete, bool):
        raise RetentionSourceValidationError("enforcement_complete must be a boolean")

    cohort_schema = source.get("cohort_schema")
    if not isinstance(cohort_schema, str) or not cohort_schema.strip():
        raise RetentionSourceValidationError("cohort_schema must be a non-empty string")

    counts = source["counts"]
    candidate = source["candidate_sha256"]
    if not isinstance(counts, dict) or not _is_int(counts.get("total_files")) or counts["total_files"] < 0:
        raise RetentionSourceValidationError("counts.total_files must be a non-negative integer")
    if not isinstance(candidate, dict) or counts["total_files"] != len(candidate):
        raise RetentionSourceValidationError("census total_files does not match candidate_sha256 count")

    for path, digest in candidate.items():
        if not isinstance(path, str) or not path or not _is_hex(digest, 64):
            raise RetentionSourceValidationError(f"candidate_sha256 entry invalid: {path!r}")

    for name in ("eligible", "assigned", "enforced", "check_results"):
        val = source[name]
        if not isinstance(val, dict) or set(val.keys()) != REQUIRED_ROOTS:
            raise RetentionSourceValidationError(f"{name} must contain exactly the six required roots")

    eligible: dict[str, list[str]] = source["eligible"]
    assigned: dict[str, list[str]] = source["assigned"]
    enforced: dict[str, list[str]] = source["enforced"]
    check_results: dict[str, Any] = source["check_results"]

    seen_paths: dict[str, str] = {}
    for root in REQUIRED_ROOTS:
        el_paths = eligible[root]
        if not isinstance(el_paths, list):
            raise RetentionSourceValidationError(f"eligible[{root!r}] must be a list")
        for p in el_paths:
            if not isinstance(p, str) or p not in candidate:
                raise RetentionSourceValidationError(f"eligible path not in candidate: {p!r}")
            if p in seen_paths:
                raise RetentionSourceValidationError(f"root separation violation: {p!r} in {seen_paths[p]} and {root}")
            seen_paths[p] = root

    for name in ("assigned", "enforced", "eligible_minus_enforced", "unassigned"):
        if not isinstance(source[name], dict) or set(source[name]) != REQUIRED_ROOTS:
            raise RetentionSourceValidationError("invalid root partition")
        for paths in source[name].values():
            if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths) or len(paths) != len(set(paths)):
                raise RetentionSourceValidationError("invalid or duplicate partition member")
    for root in REQUIRED_ROOTS:
        el_set = set(eligible[root])
        as_paths = assigned[root]
        if not isinstance(as_paths, list) or not set(as_paths).issubset(el_set):
            raise RetentionSourceValidationError(f"assigned[{root!r}] is not a subset of eligible")
        enf_paths = enforced[root]
        if not isinstance(enf_paths, list) or not set(enf_paths).issubset(set(as_paths)):
            raise RetentionSourceValidationError(f"enforced[{root!r}] is not a subset of assigned")

        residual = el_set - set(enf_paths)
        if status == "passed" and residual:
            raise RetentionSourceValidationError(f"passed status cannot have residual debt in root {root!r}")

    eme = source.get("eligible_minus_enforced")
    if eme is not None:
        if not isinstance(eme, dict) or set(eme.keys()) != REQUIRED_ROOTS:
            raise RetentionSourceValidationError("eligible_minus_enforced must cover all required roots")
        for root in REQUIRED_ROOTS:
            if set(eme[root]) != set(eligible[root]) - set(enforced[root]):
                raise RetentionSourceValidationError(f"eligible_minus_enforced[{root!r}] does not match")

    for root in REQUIRED_ROOTS:
        r_check = check_results[root]
        if not isinstance(r_check, dict):
            raise RetentionSourceValidationError(f"check_results[{root!r}] must be an object")
        c_status = r_check.get("status")
        if c_status not in VALID_STATUSES:
            raise RetentionSourceValidationError(f"check_results[{root!r}].status invalid: {c_status!r}")
        if status == "passed" and c_status != "passed":
            raise RetentionSourceValidationError(f"passed source requires check_results[{root!r}].status='passed'")
        if eligible[root] and not isinstance(r_check.get("checks"), dict):
            raise RetentionSourceValidationError("missing executed root checks")
        if eligible[root] and root != "product":
            if set(r_check["checks"]) != {"ruff", "mypy", "file_length"}:
                raise RetentionSourceValidationError("missing required profile checker")
            for check in r_check["checks"].values():
                if not isinstance(check, dict) or type(check.get("completed")) is not bool:
                    raise RetentionSourceValidationError("missing checker completion attestation")
                if not isinstance(check.get("findings"), list) or type(check.get("count")) is not int or check["count"] != len(check["findings"]):
                    raise RetentionSourceValidationError("invalid checker finding count")
        if "checks" in r_check:
            if not isinstance(r_check["checks"], dict):
                raise RetentionSourceValidationError(f"check_results[{root!r}].checks must be a dict")
            for chk_name, chk_info in r_check["checks"].items():
                if isinstance(chk_info, dict) and "findings" in chk_info and not isinstance(chk_info["findings"], list):
                    raise RetentionSourceValidationError(f"findings in check {chk_name} must be a list")

    progress = source["profile_progress"]
    if not isinstance(progress, dict) or set(progress) != REQUIRED_ROOTS:
        raise RetentionSourceValidationError("profile progress must cover six roots")
    for root in REQUIRED_ROOTS:
        item = progress[root]
        if set(source["unassigned"][root]) != set(eligible[root]) - set(assigned[root]):
            raise RetentionSourceValidationError("unassigned partition mismatch")
        for field in ("unknown", "findings_or_tool_failures"):
            count = item.get(field, {}).get("count")
            if not _is_int(count) or not 0 <= count <= len(eligible[root]):
                raise RetentionSourceValidationError("invalid progress count")
        if type(item.get("root_closure", {}).get("closed")) is not bool:
            raise RetentionSourceValidationError("missing root closure status")
    gov_inputs = source["governing_inputs"]
    if not isinstance(gov_inputs, dict):
        raise RetentionSourceValidationError("governing_inputs must be a dictionary")
    for g_path, g_val in gov_inputs.items():
        if not isinstance(g_path, str) or not g_path or not isinstance(g_val, dict):
            raise RetentionSourceValidationError("governing_inputs entry must be a dictionary")
        if not _is_int(g_val.get("bytes")) or g_val["bytes"] < 0:
            raise RetentionSourceValidationError("governing_inputs entry bytes must be non-negative int")
        if not _is_hex(g_val.get("sha256"), 64):
            raise RetentionSourceValidationError("governing_inputs entry sha256 must be 64-char hex")

    inv_path = source["inventory_path"]
    if not isinstance(inv_path, str) or not inv_path or inv_path not in gov_inputs:
        raise RetentionSourceValidationError("inventory_path must be present in governing_inputs")

    ratchet_sha = source["ratchet_sha256"]
    if not _is_hex(ratchet_sha, 64):
        raise RetentionSourceValidationError("ratchet_sha256 must be a valid 64-char hex string")
    ratchet_file = "tools/ci/retained_python_ratchets.json"
    if ratchet_file in gov_inputs and gov_inputs[ratchet_file]["sha256"] != ratchet_sha:
        raise RetentionSourceValidationError("ratchet_sha256 does not match governing_inputs")
    if source.get("ratchet_path") and source["ratchet_path"] in gov_inputs:
        if gov_inputs[source["ratchet_path"]]["sha256"] != ratchet_sha:
            raise RetentionSourceValidationError("ratchet_sha256 does not match ratchet_path in governing_inputs")

    history = source["history"]
    if not isinstance(history, dict):
        raise RetentionSourceValidationError("history must be an object")
    cand = history.get("candidate")
    if not isinstance(cand, dict):
        raise RetentionSourceValidationError("history.candidate must be an object")
    if not _is_git_hash(cand.get("commit")) or not _is_git_hash(cand.get("tree")):
        raise RetentionSourceValidationError("history.candidate commit and tree must be 40 or 64 hex characters")
    cand_inv = history.get("candidate_inventory_sha256")
    if not _is_hex(cand_inv, 64) or cand_inv != gov_inputs[inv_path]["sha256"]:
        raise RetentionSourceValidationError("candidate inventory sha256 does not match governing_inputs")

    basis = history.get("comparison_basis")
    if not isinstance(basis, dict) or not isinstance(basis.get("method"), str):
        raise RetentionSourceValidationError("missing immutable history comparison basis")
    env = source["environment"]
    if not isinstance(env, dict):
        raise RetentionSourceValidationError("environment must be an object")
    if not _is_hex(env.get("sha256"), 64):
        raise RetentionSourceValidationError("environment.sha256 must be a 64-char hex string")
    if not _is_int(env.get("input_count")) or env["input_count"] < 0:
        raise RetentionSourceValidationError("environment.input_count must be a non-negative integer")
    if not isinstance(env.get("versions"), (list, dict)):
        raise RetentionSourceValidationError("environment.versions must be a list or dictionary")

    for t_key in ("duration_seconds", "validation_duration_seconds", "cohort_evaluation_duration_seconds"):
        if not _is_finite_num(source[t_key]):
            raise RetentionSourceValidationError(f"{t_key} must be a finite non-negative number")

    cohorts = source["cohorts"]
    cohort_results = source["cohort_results"]
    cohort_regressions = source["cohort_regressions"]
    if not isinstance(cohorts, list):
        raise RetentionSourceValidationError("cohorts must be a list")
    if not isinstance(cohort_results, dict):
        raise RetentionSourceValidationError("cohort_results must be a dictionary")
    if not isinstance(cohort_regressions, list):
        raise RetentionSourceValidationError("cohort_regressions must be a list")

    cohort_ids: set[str] = set()
    member_owners: set[str] = set()
    for c in cohorts:
        if not isinstance(c, dict):
            raise RetentionSourceValidationError("cohort definition must be a dictionary")
        cid = c.get("id")
        if not isinstance(cid, str) or not cid or cid in cohort_ids:
            raise RetentionSourceValidationError(f"invalid or duplicate cohort id: {cid!r}")
        cohort_ids.add(cid)
        c_root = c.get("root")
        if c_root not in REQUIRED_ROOTS:
            raise RetentionSourceValidationError(f"cohort {cid!r} root invalid: {c_root!r}")
        adm = c.get("admission")
        if adm not in {"admitted", "pending"}:
            raise RetentionSourceValidationError(f"cohort {cid!r} admission invalid: {adm!r}")
        members = c.get("members")
        if not isinstance(members, (list, tuple)) or not members:
            raise RetentionSourceValidationError(f"cohort {cid!r} members must be non-empty list")
        if member_owners.intersection(members) or len(members) != len(set(members)):
            raise RetentionSourceValidationError("duplicate cohort member")
        member_owners.update(members)
        for m in members:
            if not isinstance(m, str) or m not in candidate or m not in eligible[c_root]:
                raise RetentionSourceValidationError(f"cohort {cid!r} member {m!r} not in root eligible")

    if set(cohort_results.keys()) != cohort_ids:
        raise RetentionSourceValidationError("cohort_results keys do not match cohort definitions")

    if member_owners != {p for root in ("tools", "test_support", "test_owners") for p in eligible[root]}:
        raise RetentionSourceValidationError("cohort membership does not cover eligible cohort roots")
    failed_admitted: list[str] = []
    dep_paths = source.get("cohort_dependency_paths", [])
    if not isinstance(dep_paths, list):
        raise RetentionSourceValidationError("cohort_dependency_paths must be a list")
    dep_paths_len = len(dep_paths)

    blockers = source.get("cohort_dependency_blockers", [])
    if not isinstance(blockers, list):
        raise RetentionSourceValidationError("cohort_dependency_blockers must be a list")
    blockers_len = len(blockers)

    for c in cohorts:
        cid = c["id"]
        rec = cohort_results[cid]
        if not isinstance(rec, dict):
            raise RetentionSourceValidationError(f"cohort_results[{cid!r}] must be a dictionary")
        if rec.get("id") != cid or rec.get("root") != c["root"] or rec.get("admission") != c["admission"]:
            raise RetentionSourceValidationError(f"cohort_results[{cid!r}] metadata mismatch with definition")
        c_st = rec.get("status")
        if c_st not in VALID_STATUSES:
            raise RetentionSourceValidationError(f"cohort_results[{cid!r}] invalid status: {c_st!r}")

        expected_eff = (c_st == "passed" and c["admission"] == "admitted")
        eff = rec.get("effective_enforcement")
        if not isinstance(eff, bool) or eff is not expected_eff:
            raise RetentionSourceValidationError(f"cohort_results[{cid!r}] inconsistent effective_enforcement")

        if c_st == "failed" and c["admission"] == "admitted":
            failed_admitted.append(cid)

        if eff:
            for m in c["members"]:
                if m not in enforced[c["root"]]:
                    raise RetentionSourceValidationError(f"effective cohort {cid!r} member {m!r} not in enforced")

        if rec.get("members") != c["members"] or rec.get("evidence_complete") is not (c_st == "passed"):
            raise RetentionSourceValidationError("cohort result members or completeness mismatch")
        for field in ("direct_findings", "dependency_finding_indices", "governed_dependency_indices",
                      "ungoverned_dependency_indices", "dependency_blocker_indices"):
            if field not in rec:
                raise RetentionSourceValidationError("missing cohort evidence field")
        root_check = check_results[c["root"]]
        nested_checks = root_check.get("checks", {}) if isinstance(root_check, dict) else {}

        df = rec.get("direct_findings")
        if df is not None:
            if not isinstance(df, dict):
                raise RetentionSourceValidationError(f"direct_findings in cohort {cid!r} must be a dict")
            for chk_name, indices in df.items():
                if not isinstance(indices, list):
                    raise RetentionSourceValidationError(f"direct_findings[{chk_name!r}] must be a list")
                f_list = nested_checks.get(chk_name, {}).get("findings", []) if isinstance(nested_checks, dict) else []
                f_len = len(f_list) if isinstance(f_list, list) else 0
                for idx in indices:
                    if not _is_int(idx) or idx < 0 or idx >= f_len:
                        raise RetentionSourceValidationError(f"direct finding index {idx!r} out of bounds ({f_len}) in {cid!r}")

        dfi = rec.get("dependency_finding_indices")
        if dfi is not None:
            if not isinstance(dfi, list):
                raise RetentionSourceValidationError(f"dependency_finding_indices in cohort {cid!r} must be a list")
            mypy_findings = nested_checks.get("mypy", {}).get("findings", []) if isinstance(nested_checks, dict) else []
            m_len = len(mypy_findings) if isinstance(mypy_findings, list) else 0
            for idx in dfi:
                if not _is_int(idx) or idx < 0 or idx >= m_len:
                    raise RetentionSourceValidationError(f"dependency finding index {idx!r} out of bounds ({m_len}) in {cid!r}")

        for field_name, bound in (
            ("governed_dependency_indices", dep_paths_len),
            ("ungoverned_dependency_indices", dep_paths_len),
            ("dependency_blocker_indices", blockers_len),
        ):
            idx_list = rec.get(field_name)
            if idx_list is not None:
                if not isinstance(idx_list, list):
                    raise RetentionSourceValidationError(f"{field_name} in cohort {cid!r} must be a list")
                for idx in idx_list:
                    if not _is_int(idx) or idx < 0 or idx >= bound:
                        raise RetentionSourceValidationError(f"{field_name} index {idx!r} out of bounds ({bound}) in {cid!r}")

    if any(not isinstance(r, str) for r in cohort_regressions):
        raise RetentionSourceValidationError("cohort_regressions must be a list of strings")
    if cohort_regressions != sorted(set(cohort_regressions)):
        raise RetentionSourceValidationError("cohort_regressions must be sorted and unique")
    if status == "passed" and cohort_regressions:
        raise RetentionSourceValidationError("passed status cannot declare cohort regressions")
    if sorted(cohort_regressions) != sorted(failed_admitted):
        raise RetentionSourceValidationError("cohort_regressions mismatch with failed admitted cohorts")

    if status == "passed":
        if cohort_regressions:
            raise RetentionSourceValidationError("passed status cannot declare cohort regressions")
        if not enforcement_complete:
            raise RetentionSourceValidationError("passed status requires enforcement_complete=True")
        if classification != "passed":
            raise RetentionSourceValidationError("passed status requires classification='passed'")

    if cohort_regressions and status != "failed":
        raise RetentionSourceValidationError("cohort regressions require status='failed'")
    if enforcement_complete and status != "passed":
        raise RetentionSourceValidationError("enforcement_complete=True requires status='passed'")

    if bool(cohort_regressions) != (classification == "ratchet-regression"):
        raise RetentionSourceValidationError("regression classification mismatch")
    if (status == "passed") != (classification == "passed"):
        raise RetentionSourceValidationError("status classification mismatch")
    for root in ("tools", "test_support", "test_owners"):
        expected = {m for c in cohorts if c["root"] == root and cohort_results[c["id"]]["effective_enforcement"] for m in c["members"]}
        if set(enforced[root]) != expected:
            raise RetentionSourceValidationError("effective cohort membership mismatch")
    from ci.python_retention_atomic_source import validate_atomic_groups
    validate_atomic_groups(source)
