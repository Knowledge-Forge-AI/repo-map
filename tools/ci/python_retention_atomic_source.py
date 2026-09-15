"""Strict fail-closed validation for atomic retention cohort groups (ADR 0065)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence

from ci.python_retention_atomic import COHORT_PROFILES, canonical_scc_id
from ci.python_retention_evidence_source import (
    REQUIRED_ROOTS,
    RetentionSourceValidationError,
    VALID_STATUSES,
    _is_hex,
    _is_int,
)


def make_atomic_group_id(cohort_ids: Sequence[str]) -> str:
    """Derive deterministic atomic group ID from sorted cohort IDs."""
    return canonical_scc_id(cohort_ids)


def make_internal_dependency_sha256(edges: Sequence[Sequence[str]]) -> str:
    """Build fixture commitments; source validation does not recompute edges."""
    sorted_edges = sorted([list(edge) for edge in edges])
    raw = json.dumps(sorted_edges, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_atomic_groups(source: dict[str, Any]) -> None:
    """Validate atomic groups against ADR 0065 and constituent cohort contracts."""
    cohort_results = source.get("cohort_results", {})
    if not isinstance(cohort_results, dict):
        return

    if "atomic_groups" not in source:
        for cid, rec in cohort_results.items():
            if isinstance(rec, dict) and rec.get("atomic_group_id") is not None:
                raise RetentionSourceValidationError(
                    f"cohort {cid!r} references missing atomic_groups"
                )
        return

    atomic_groups = source["atomic_groups"]
    if not isinstance(atomic_groups, dict):
        raise RetentionSourceValidationError("atomic_groups must be a dictionary")

    cohorts = source.get("cohorts", [])
    cohort_map = (
        {c["id"]: c for c in cohorts if isinstance(c, dict) and "id" in c}
        if isinstance(cohorts, list)
        else {}
    )
    cohort_regressions = (
        set(source.get("cohort_regressions", []))
        if isinstance(source.get("cohort_regressions"), list)
        else set()
    )
    dep_paths_len = (
        len(source.get("cohort_dependency_paths", []))
        if isinstance(source.get("cohort_dependency_paths"), list)
        else 0
    )
    blockers_len = (
        len(source.get("cohort_dependency_blockers", []))
        if isinstance(source.get("cohort_dependency_blockers"), list)
        else 0
    )

    seen_cohorts_in_groups: dict[str, str] = {}

    for gid, group in atomic_groups.items():
        if not isinstance(gid, str) or not gid.startswith("scc-v1-"):
            raise RetentionSourceValidationError(f"invalid atomic group id: {gid!r}")
        if not isinstance(group, dict):
            raise RetentionSourceValidationError(f"atomic group {gid!r} must be a dictionary")
        if group.get("id") != gid:
            raise RetentionSourceValidationError(
                f"atomic group id mismatch: {group.get('id')!r} != {gid!r}"
            )

        cohort_ids = group.get("cohort_ids")
        if not isinstance(cohort_ids, list) or len(cohort_ids) < 2:
            raise RetentionSourceValidationError(
                f"atomic group {gid!r} cohort_ids must be a list of at least two cohorts"
            )
        if any(not isinstance(cid, str) or not cid for cid in cohort_ids):
            raise RetentionSourceValidationError(
                f"invalid cohort id in atomic group {gid!r}"
            )
        if cohort_ids != sorted(cohort_ids) or len(cohort_ids) != len(set(cohort_ids)):
            raise RetentionSourceValidationError(
                f"atomic group {gid!r} cohort_ids must be sorted and unique"
            )

        expected_id = make_atomic_group_id(cohort_ids)
        if gid != expected_id:
            raise RetentionSourceValidationError(
                f"atomic group {gid!r} id does not match hash of cohort_ids"
            )

        for cid in cohort_ids:
            if cid not in cohort_map or cid not in cohort_results:
                raise RetentionSourceValidationError(
                    f"atomic group {gid!r} references unknown cohort: {cid!r}"
                )
            if cid in seen_cohorts_in_groups:
                raise RetentionSourceValidationError(
                    f"cohort {cid!r} belongs to multiple atomic groups: "
                    f"{seen_cohorts_in_groups[cid]!r} and {gid!r}"
                )
            seen_cohorts_in_groups[cid] = gid

            c_rec = cohort_results[cid]
            if not isinstance(c_rec, dict) or c_rec.get("atomic_group_id") != gid:
                raise RetentionSourceValidationError(
                    f"cohort {cid!r} atomic_group_id mismatch: expected {gid!r}"
                )

        g_status = group.get("status")
        if g_status not in VALID_STATUSES:
            raise RetentionSourceValidationError(
                f"atomic group {gid!r} invalid status: {g_status!r}"
            )
        g_eff = group.get("effective_enforcement")
        if not isinstance(g_eff, bool):
            raise RetentionSourceValidationError(
                f"atomic group {gid!r} effective_enforcement must be a boolean"
            )

        c_roots = {cohort_map[cid]["root"] for cid in cohort_ids}
        g_root = group.get("root")
        g_prof = group.get("governing_profile")

        if len(c_roots) > 1:
            if g_root is not None:
                raise RetentionSourceValidationError(
                    f"cross-root atomic group {gid!r} root must be null"
                )
            if g_prof is not None:
                raise RetentionSourceValidationError(
                    f"cross-root atomic group {gid!r} governing_profile must be null"
                )
            if g_status != "failed":
                raise RetentionSourceValidationError(
                    f"cross-root atomic group {gid!r} must have status='failed'"
                )
            if g_eff is not False:
                raise RetentionSourceValidationError(
                    f"cross-root atomic group {gid!r} cannot have effective_enforcement=True"
                )
        else:
            single_root = next(iter(c_roots))
            if g_root is not None:
                if g_root != single_root:
                    raise RetentionSourceValidationError(
                        f"atomic group {gid!r} root {g_root!r} does not match constituents root {single_root!r}"
                    )
                if g_root not in REQUIRED_ROOTS:
                    raise RetentionSourceValidationError(
                        f"atomic group {gid!r} root invalid: {g_root!r}"
                    )
                profiles = {cohort_map[cid].get("governing_profile") for cid in cohort_ids}
                if profiles != {g_prof} or g_prof != COHORT_PROFILES.get(g_root):
                    raise RetentionSourceValidationError("atomic group profile mismatch")
                if not isinstance(g_prof, str) or not g_prof.strip():
                    raise RetentionSourceValidationError(
                        f"atomic group {gid!r} missing governing_profile"
                    )
            else:
                if g_prof is not None:
                    raise RetentionSourceValidationError(
                        f"atomic group {gid!r} null root requires null governing_profile"
                    )
                if g_status != "failed":
                    raise RetentionSourceValidationError(
                        f"atomic group {gid!r} null root must have status='failed'"
                    )
                if g_eff is not False:
                    raise RetentionSourceValidationError(
                        f"atomic group {gid!r} null root cannot have effective_enforcement=True"
                    )

        int_cnt = group.get("internal_dependency_count")
        if not isinstance(int_cnt, int) or isinstance(int_cnt, bool) or int_cnt < 0:
            raise RetentionSourceValidationError(
                f"atomic group {gid!r} internal_dependency_count must be non-negative integer"
            )
        int_sha = group.get("internal_dependency_sha256")
        if not _is_hex(int_sha, 64):
            raise RetentionSourceValidationError(
                f"atomic group {gid!r} internal_dependency_sha256 must be 64-char hex"
            )

        for field_name, bound in (
            ("external_dependency_indices", dep_paths_len),
            ("ungoverned_dependency_indices", dep_paths_len),
            ("dependency_blocker_indices", blockers_len),
        ):
            if field_name not in group:
                raise RetentionSourceValidationError(
                    f"atomic group {gid!r} missing {field_name}"
                )
            idx_list = group[field_name]
            if not isinstance(idx_list, list):
                raise RetentionSourceValidationError(
                    f"{field_name} in atomic group {gid!r} must be a list"
                )
            for idx in idx_list:
                if not _is_int(idx) or idx < 0 or idx >= bound:
                    raise RetentionSourceValidationError(
                        f"{field_name} index {idx!r} out of bounds ({bound}) in {gid!r}"
                    )

        external = set(group["external_dependency_indices"])
        if not set(group["ungoverned_dependency_indices"]) <= external:
            raise RetentionSourceValidationError("atomic unmet dependencies are not external")
        group_paths = {p for cid in cohort_ids for p in cohort_map[cid]["members"]}
        table = source.get("cohort_dependency_paths", [])
        if any(table[i] in group_paths for i in external):
            raise RetentionSourceValidationError("atomic external dependency is internal")

        c_admissions = {cohort_map[cid]["admission"] for cid in cohort_ids}
        if "admitted" in c_admissions and "pending" in c_admissions:
            if g_status != "failed":
                raise RetentionSourceValidationError(
                    f"mixed admission atomic group {gid!r} must have status='failed'"
                )
            if g_eff is not False:
                raise RetentionSourceValidationError(
                    f"mixed admission atomic group {gid!r} cannot have effective_enforcement=True"
                )
        elif c_admissions == {"pending"}:
            if g_eff is not False:
                raise RetentionSourceValidationError(
                    f"pending atomic group {gid!r} cannot have effective_enforcement=True"
                )
        elif c_admissions == {"admitted"}:
            if g_status == "passed" and g_eff is not True:
                raise RetentionSourceValidationError(
                    f"admitted passing atomic group {gid!r} must have effective_enforcement=True"
                )

        if g_status == "failed" and g_eff is not False:
            raise RetentionSourceValidationError(
                f"failed atomic group {gid!r} cannot have effective_enforcement=True"
            )

        constituent_statuses = {cohort_results[cid].get("status") for cid in cohort_ids}
        if g_status == "passed":
            if constituent_statuses != {"passed"}:
                raise RetentionSourceValidationError(
                    f"passing atomic group {gid!r} has failed constituent cohorts"
                )
            if group.get("dependency_blocker_indices"):
                raise RetentionSourceValidationError(
                    f"passing atomic group {gid!r} cannot have dependency blockers"
                )
            if group.get("ungoverned_dependency_indices"):
                raise RetentionSourceValidationError(
                    f"passing atomic group {gid!r} cannot have ungoverned dependencies"
                )
        else:
            if "passed" in constituent_statuses:
                raise RetentionSourceValidationError(
                    f"failed atomic group {gid!r} has passing constituent cohorts"
                )

        for cid in cohort_ids:
            c_rec = cohort_results[cid]
            if c_rec.get("effective_enforcement") != g_eff:
                raise RetentionSourceValidationError(
                    f"cohort {cid!r} effective_enforcement mismatch with atomic group {gid!r}"
                )
            if cohort_map[cid]["admission"] == "admitted" and c_rec.get("status") == "failed":
                if cid not in cohort_regressions:
                    raise RetentionSourceValidationError(
                        f"failed admitted cohort {cid!r} from group {gid!r} missing from cohort_regressions"
                    )

    for cid, c_rec in cohort_results.items():
        if cid not in seen_cohorts_in_groups and isinstance(c_rec, dict):
            group_ref = c_rec.get("atomic_group_id")
            if group_ref is not None:
                raise RetentionSourceValidationError(
                    f"cohort {cid!r} references unknown or unassociated atomic group {group_ref!r}"
                )
