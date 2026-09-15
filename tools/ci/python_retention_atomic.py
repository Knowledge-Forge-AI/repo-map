"""REVISE27 atomic SCC retention cohort evaluation and evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

COHORT_PROFILES = {
    "tools": "clean_tooling",
    "test_support": "clean_test_support",
    "test_owners": "clean_test_owners",
}


def canonical_scc_id(cohort_ids: Sequence[str]) -> str:
    """Return deterministic versioned identity for a multi-cohort SCC."""
    sorted_ids = sorted(cohort_ids)
    compact_json = json.dumps(sorted_ids, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(compact_json.encode("utf-8")).hexdigest()
    return f"scc-v1-{digest}"


def compute_internal_dependencies(
    scc_paths: set[str],
    graph_dependencies: Mapping[str, Sequence[str]],
) -> tuple[int, str]:
    """Return count and sha256 digest for exact internal path edges in an SCC."""
    edges: list[list[str]] = []
    for source in sorted(scc_paths):
        for target in sorted(graph_dependencies.get(source, ())):
            if target in scc_paths:
                edges.append([source, target])
    edges.sort()
    compact_json = json.dumps(edges, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(compact_json.encode("utf-8")).hexdigest()
    return len(edges), digest


class AtomicGroup:
    """Represents a multi-cohort SCC evaluated as a single atomic unit."""

    def __init__(
        self,
        cohort_ids: Sequence[str],
        cohorts_by_id: Mapping[str, Mapping[str, Any]],
        leaving: Mapping[str, set[str]],
        graph_dependencies: Mapping[str, Sequence[str]],
        supported_profiles: Mapping[str, str] = COHORT_PROFILES,
    ) -> None:
        self.cohort_ids = sorted(cohort_ids)
        self.id = canonical_scc_id(self.cohort_ids)
        self.cohorts = [cohorts_by_id[cid] for cid in self.cohort_ids]
        self.all_members = {
            p for c in self.cohorts for p in c.get("members", ())
        }
        self.internal_dependency_count, self.internal_dependency_sha256 = (
            compute_internal_dependencies(self.all_members, graph_dependencies)
        )

        roots = {c.get("root") for c in self.cohorts}
        profiles = {c.get("governing_profile") for c in self.cohorts}
        first_root = next(iter(roots)) if len(roots) == 1 else None
        first_profile = next(iter(profiles)) if len(profiles) == 1 else None

        self.root_mismatch_blockers: list[str] = []
        if len(roots) == 1 and first_root in supported_profiles and first_profile == supported_profiles.get(str(first_root)):
            self.root = first_root
            self.governing_profile = first_profile
        else:
            self.root = None
            self.governing_profile = None
            if len(roots) > 1:
                self.root_mismatch_blockers.append(
                    f"cross-root circular cross-cohort dependency involving {self.cohort_ids}"
                )
            elif any(r not in supported_profiles for r in roots):
                self.root_mismatch_blockers.append(
                    f"unsupported cohort root across cohorts {self.cohort_ids}"
                )
            else:
                self.root_mismatch_blockers.append(
                    f"governing profile mismatch across cohorts {self.cohort_ids}"
                )

        admissions = {c.get("admission") for c in self.cohorts}
        self.is_all_admitted = admissions == {"admitted"}
        self.is_all_pending = admissions == {"pending"}
        self.is_mixed = "pending" in admissions and "admitted" in admissions
        self.pending_ids = sorted(
            c["id"] for c in self.cohorts if c.get("admission") == "pending"
        )
        self.mixed_blockers: list[str] = []
        if self.is_mixed:
            self.mixed_blockers.append(
                f"mixed pending and admitted cohorts: pending constituent IDs: {self.pending_ids}"
            )

        self.external_by_cid: dict[str, set[str]] = {}
        all_external: set[str] = set()
        for cid in self.cohort_ids:
            ext = {p for p in leaving.get(cid, set()) if p not in self.all_members}
            self.external_by_cid[cid] = ext
            all_external.update(ext)
        self.external_dependencies = sorted(all_external)

        self.status = "failed"
        self.effective_enforcement = False
        self.ungoverned_dependencies: list[str] = []
        self.dependency_blockers: list[str] = []

    def can_pass(
        self,
        blockers: Mapping[str, Sequence[str]],
        governed: set[str],
    ) -> bool:
        if self.root is None or self.governing_profile is None:
            return False
        if self.is_mixed:
            return False
        if any(blockers.get(cid) for cid in self.cohort_ids):
            return False
        return set(self.external_dependencies).issubset(governed)

    def mark_passed(self) -> None:
        self.status = "passed"
        self.effective_enforcement = self.is_all_admitted
        self.ungoverned_dependencies = []
        self.dependency_blockers = []

    def mark_failed(
        self,
        governed: set[str],
        blockers: dict[str, list[str]],
    ) -> None:
        self.status = "failed"
        self.effective_enforcement = False
        unmet = sorted(set(self.external_dependencies) - governed)
        self.ungoverned_dependencies = unmet

        group_blockers: list[str] = []
        group_blockers.extend(self.root_mismatch_blockers)
        group_blockers.extend(self.mixed_blockers)

        initial_member_blockers = {
            cid: list(blockers.get(cid, [])) for cid in self.cohort_ids
        }
        for cid in self.cohort_ids:
            for b in initial_member_blockers[cid]:
                group_blockers.append(f"cohort {cid}: {b}")

        if unmet:
            group_blockers.append("unmet leaving dependencies")
            for cid in self.cohort_ids:
                unmet_cid = sorted(self.external_by_cid[cid] - governed)
                for dep in unmet_cid:
                    group_blockers.append(f"cohort {cid}: unmet leaving dependency: {dep}")

        self.dependency_blockers = sorted(set(group_blockers))

        # Keep direct causes once in this group record. Constituent records
        # retain their own debt and reference the group instead of copying every
        # other constituent's blockers (which would grow quadratically).
        for cid in self.cohort_ids:
            blockers[cid].append(f"atomic group {self.id} failed; see group blockers")

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cohort_ids": list(self.cohort_ids),
            "root": self.root,
            "governing_profile": self.governing_profile,
            "internal_dependency_count": self.internal_dependency_count,
            "internal_dependency_sha256": self.internal_dependency_sha256,
            "external_dependencies": list(self.external_dependencies),
            "ungoverned_dependencies": list(self.ungoverned_dependencies),
            "dependency_blockers": sorted(set(self.dependency_blockers)),
            "status": self.status,
            "effective_enforcement": self.effective_enforcement,
        }


def build_atomic_groups(
    cycles: Mapping[str, Sequence[str]],
    cohorts_by_id: Mapping[str, Mapping[str, Any]],
    leaving: Mapping[str, set[str]],
    graph_dependencies: Mapping[str, Sequence[str]],
    supported_profiles: Mapping[str, str] = COHORT_PROFILES,
) -> tuple[dict[str, AtomicGroup], dict[str, str]]:
    """Build AtomicGroup instances for all multi-cohort SCCs."""
    unique_sccs = sorted({tuple(sorted(scc)) for scc in cycles.values() if len(scc) > 1})
    atomic_groups: dict[str, AtomicGroup] = {}
    cohort_to_group: dict[str, str] = {}

    for scc in unique_sccs:
        group = AtomicGroup(
            cohort_ids=scc,
            cohorts_by_id=cohorts_by_id,
            leaving=leaving,
            graph_dependencies=graph_dependencies,
            supported_profiles=supported_profiles,
        )
        atomic_groups[group.id] = group
        for cid in group.cohort_ids:
            cohort_to_group[cid] = group.id

    return atomic_groups, cohort_to_group
