"""Deterministic cohort inventory schema extension and immutable history protection."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from ci.python_retention_history_git import HistoryValidationError
from ci.python_retention_dynamic_history import active_boundaries, validate_dynamic_transition

CohortValidationError = HistoryValidationError

COHORT_SCHEMA = "repomap-python-retention-cohorts-v1"
APPLICABLE_ROOTS = ("tools", "test_support", "test_owners")
ADMISSION_STATES = ("pending", "admitted")
EXPECTED_PROFILES = {
    "tools": "clean_tooling",
    "test_support": "clean_test_support",
    "test_owners": "clean_test_owners",
}
ALLOWED_COHORT_KEYS = {
    "id",
    "root",
    "governing_profile",
    "members",
    "rationale",
    "admission",
}
COHORT_ID_PATTERN = re.compile(r"^[a-z0-9_.-]+\Z")


def category_for_path(path: str) -> str:
    """Classify a repo-relative path into its maintained root category."""
    if path.startswith("src/main/python/"):
        return "product"
    if path.startswith("src/test/fixtures/"):
        return "fixtures"
    if path == "src/test/conftest.py":
        return "conftest"
    if path.startswith("src/test/support/python/"):
        return "test_support"
    if path.startswith(("src/test/unit/python/", "src/test/int/python/")):
        return "test_owners"
    if path.startswith("tools/"):
        return "tools"
    raise HistoryValidationError(f"Python path has no maintained root: {path}")


def _validate_member_path(path: object) -> str:
    if (
        not isinstance(path, str)
        or not path.strip()
        or not path.endswith(".py")
        or Path(path).is_absolute()
        or ".." in Path(path).parts
    ):
        raise HistoryValidationError(f"invalid cohort member path: {path}")
    return path


def validate_cohorts(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate the stable cohort extension within an inventory document."""
    if not isinstance(data, Mapping):
        raise HistoryValidationError("inventory data must be a mapping")
    try:
        active_boundaries(data)
    except ValueError as error:
        raise HistoryValidationError(str(error)) from error

    has_schema = "cohort_schema" in data
    has_cohorts = "cohorts" in data
    if not has_schema and not has_cohorts:
        return []
    if not (has_schema and has_cohorts):
        raise HistoryValidationError("cohort extension fields must appear together")
    if data["cohort_schema"] != COHORT_SCHEMA:
        raise HistoryValidationError(
            f"unsupported cohort_schema version: {data['cohort_schema']}"
        )
    raw_cohorts = data["cohorts"]
    if not isinstance(raw_cohorts, list):
        raise HistoryValidationError("cohorts must be a list")

    files = data.get("files", [])
    if not isinstance(files, list):
        raise HistoryValidationError("inventory files collection is invalid")

    files_by_path: dict[str, Mapping[str, Any]] = {}
    for entry in files:
        if isinstance(entry, Mapping) and isinstance(entry.get("path"), str):
            files_by_path[entry["path"]] = entry

    eligible_current = {
        path for path, entry in files_by_path.items()
        if entry.get("root") in APPLICABLE_ROOTS
        and entry.get("maintained_executable") is True
        and isinstance(entry.get("confidence"), (int, float))
        and not isinstance(entry.get("confidence"), bool)
        and entry["confidence"] >= 0.8
    }

    transitions = data.get("path_transitions", [])
    transition_sources = {
        t["from"] for t in transitions
        if isinstance(t, Mapping) and isinstance(t.get("from"), str)
    } if isinstance(transitions, list) else set()

    decompositions = data.get("decompositions", [])
    decomp_sources = {
        d["from"] for d in decompositions
        if isinstance(d, Mapping) and isinstance(d.get("from"), str)
    } if isinstance(decompositions, list) else set()

    cohort_ids: list[str] = []
    seen_members: set[str] = set()
    cohort_by_member: dict[str, Mapping[str, Any]] = {}
    admitted_members: set[str] = set()

    for cohort in raw_cohorts:
        if not isinstance(cohort, Mapping):
            raise HistoryValidationError("cohort entry must be a mapping")
        if set(cohort.keys()) != ALLOWED_COHORT_KEYS:
            raise HistoryValidationError("cohort entry keys do not match schema")

        cid = cohort["id"]
        if not isinstance(cid, str) or not COHORT_ID_PATTERN.match(cid):
            raise HistoryValidationError(f"invalid cohort id: {cid}")
        cohort_ids.append(cid)

        root = cohort["root"]
        if root not in APPLICABLE_ROOTS:
            raise HistoryValidationError(f"inapplicable cohort root: {root}")

        profile = cohort["governing_profile"]
        if profile != EXPECTED_PROFILES[root]:
            raise HistoryValidationError(
                f"mismatched governing profile for root {root}: {profile}"
            )

        rationale = cohort["rationale"]
        if not isinstance(rationale, str) or not rationale.strip():
            raise HistoryValidationError(f"cohort {cid} requires non-empty rationale")

        admission = cohort["admission"]
        if admission not in ADMISSION_STATES:
            raise HistoryValidationError(f"invalid admission state in cohort {cid}: {admission}")

        members = cohort["members"]
        if not isinstance(members, list) or not members:
            raise HistoryValidationError(f"cohort {cid} members must be a non-empty list")

        validated_members = [_validate_member_path(m) for m in members]
        if len(validated_members) != len(set(validated_members)):
            raise HistoryValidationError(f"duplicate member in cohort {cid}")
        if validated_members != sorted(validated_members):
            raise HistoryValidationError(f"cohort {cid} members are not sorted")

        for m in validated_members:
            if m in seen_members:
                raise HistoryValidationError(f"duplicate membership across cohorts: {m}")
            seen_members.add(m)
            cohort_by_member[m] = cohort
            if admission == "admitted":
                admitted_members.add(m)

            if m in files_by_path:
                entry = files_by_path[m]
                if entry.get("root") != root:
                    raise HistoryValidationError(
                        f"cohort member root mismatch: {m} has {entry.get('root')} != {root}"
                    )
                if m not in eligible_current:
                    raise HistoryValidationError(f"cohort member is not eligible: {m}")
                if entry.get("governing_profile") != profile:
                    raise HistoryValidationError(
                        f"cohort member profile mismatch: {m} has {entry.get('governing_profile')} != {profile}"
                    )
            elif m in transition_sources or m in decomp_sources:
                if category_for_path(m) != root:
                    raise HistoryValidationError(
                        f"historical cohort member root mismatch: {m} != {root}"
                    )
            else:
                raise HistoryValidationError(
                    f"cohort member is not an eligible current or transitioned file: {m}"
                )

    if len(cohort_ids) != len(set(cohort_ids)):
        raise HistoryValidationError("duplicate cohort id")
    if cohort_ids != sorted(cohort_ids):
        raise HistoryValidationError("cohort records are not deterministically ordered")

    missing = eligible_current - seen_members
    if missing:
        raise HistoryValidationError(
            f"eligible files missing from cohort membership: {sorted(missing)[:5]}"
        )

    for decomp in decompositions if isinstance(decompositions, list) else ():
        if not isinstance(decomp, Mapping):
            continue
        source = decomp.get("from")
        if source in admitted_members:
            to_val = decomp.get("to")
            successors = [to_val] if isinstance(to_val, str) else (to_val if isinstance(to_val, list) else [])
            for succ in successors:
                if isinstance(succ, str) and succ in cohort_by_member:
                    if cohort_by_member[succ]["admission"] == "pending":
                        raise HistoryValidationError(
                            f"decomposition successor cannot move to pending cohort: {succ} from {source}"
                        )

    return list(raw_cohorts)


def _validate_admitted_replacement(
    source: str, cohort: Mapping[str, Any], data: Mapping[str, Any],
) -> None:
    """Carry each removed obligation to live members of its original cohort."""
    # Reuse the inventory history parser; the import is deferred because that
    # owner also invokes cohort transition validation during its lineage audit.
    from ci.python_retention_history import _parse_history

    _, targets, _, _ = _parse_history(data)
    current = {entry["path"] for entry in data["files"]}
    members = set(cohort["members"])

    def walk(path: str, visiting: set[str]) -> None:
        if path in visiting:
            raise HistoryValidationError(f"cyclic admitted replacement: {source}")
        if path in current:
            if path == source or path not in members:
                raise HistoryValidationError(
                    f"admitted successor must remain in original cohort: {path}"
                )
            return
        successors = targets.get(path)
        if not successors:
            raise HistoryValidationError(
                f"admitted cohort member cannot be removed without live successors: {path}"
            )
        for successor in successors:
            walk(successor, visiting | {path})

    walk(source, set())


def validate_cohort_transition(
    older_data: Mapping[str, Any], newer_data: Mapping[str, Any]
) -> None:
    """Enforce cohort immutability and monotonic admission across a lineage edge."""
    try:
        validate_dynamic_transition(older_data, newer_data)
    except ValueError as error:
        raise HistoryValidationError(str(error)) from error
    older_has = ("cohort_schema" in older_data) or ("cohorts" in older_data)
    newer_has = ("cohort_schema" in newer_data) or ("cohorts" in newer_data)

    if not older_has and not newer_has:
        return
    if older_has and not newer_has:
        raise HistoryValidationError("cohort schema extension cannot disappear once introduced")
    if not older_has and newer_has:
        validate_cohorts(newer_data)
        return

    older_cohorts = validate_cohorts(older_data)
    newer_cohorts = validate_cohorts(newer_data)

    older_by_id = {c["id"]: c for c in older_cohorts}
    newer_by_id = {c["id"]: c for c in newer_cohorts}
    newer_by_member: dict[str, dict[str, Any]] = {}
    for c in newer_cohorts:
        for m in c["members"]:
            newer_by_member[m] = c

    for old_id in older_by_id:
        if old_id not in newer_by_id:
            raise HistoryValidationError(f"cohort cannot disappear: {old_id}")

    for old_id, old_c in older_by_id.items():
        new_c = newer_by_id[old_id]
        if new_c["root"] != old_c["root"]:
            raise HistoryValidationError(f"cohort root cannot change: {old_id}")
        if new_c["governing_profile"] != old_c["governing_profile"]:
            raise HistoryValidationError(f"cohort governing_profile cannot change: {old_id}")
        if new_c["rationale"] != old_c["rationale"]:
            raise HistoryValidationError(f"cohort rationale cannot change: {old_id}")

        if old_c["admission"] == "admitted" and new_c["admission"] != "admitted":
            raise HistoryValidationError(
                f"admitted cohort cannot be downgraded to pending: {old_id}"
            )

        old_members = set(old_c["members"])
        new_members = set(new_c["members"])
        removed = old_members - new_members

        if old_c["admission"] == "admitted":
            for member in sorted(removed):
                _validate_admitted_replacement(member, new_c, newer_data)
        else:
            if removed:
                newer_transitions = {
                    t["from"] for t in newer_data.get("path_transitions", [])
                    if isinstance(t, Mapping) and isinstance(t.get("from"), str)
                } if isinstance(newer_data.get("path_transitions"), list) else set()
                newer_decomps = {
                    d["from"] for d in newer_data.get("decompositions", [])
                    if isinstance(d, Mapping) and isinstance(d.get("from"), str)
                } if isinstance(newer_data.get("decompositions"), list) else set()
                for m in removed:
                    if m not in newer_transitions and m not in newer_decomps:
                        raise HistoryValidationError(
                            f"cohort member cannot silently change: {m} from {old_id}"
                        )

        for m in old_members:
            if m in newer_by_member and newer_by_member[m]["id"] != old_id:
                raise HistoryValidationError(
                    f"cohort member cannot be reassigned: {m} from {old_id} to {newer_by_member[m]['id']}"
                )

    admitted_sources: set[str] = set()
    for c in older_cohorts:
        if c["admission"] == "admitted":
            admitted_sources.update(c["members"])
    for c in newer_cohorts:
        if c["admission"] == "admitted":
            admitted_sources.update(c["members"])

    for doc in (older_data, newer_data):
        for decomp in doc.get("decompositions", []) if isinstance(doc.get("decompositions"), list) else ():
            if not isinstance(decomp, Mapping):
                continue
            source = decomp.get("from")
            if source in admitted_sources:
                to_val = decomp.get("to")
                successors = [to_val] if isinstance(to_val, str) else (to_val if isinstance(to_val, list) else [])
                for succ in successors:
                    if isinstance(succ, str) and succ in newer_by_member:
                        if newer_by_member[succ]["admission"] == "pending":
                            raise HistoryValidationError(
                                f"decomposition successor cannot move to pending cohort: {succ} from {source}"
                            )


__all__ = [
    "ADMISSION_STATES",
    "ALLOWED_COHORT_KEYS",
    "APPLICABLE_ROOTS",
    "COHORT_ID_PATTERN",
    "COHORT_SCHEMA",
    "CohortValidationError",
    "EXPECTED_PROFILES",
    "HistoryValidationError",
    "category_for_path",
    "validate_cohort_transition",
    "validate_cohorts",
]
