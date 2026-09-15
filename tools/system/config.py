"""Configuration and constants for the containerized assembled-product system gate."""

from __future__ import annotations

import os
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SYSTEM_DESIGN_TARGET_SECONDS: int = 1800
SYSTEM_WATCHDOG_TIMEOUT_SECONDS: int = 3600
SYSTEM_TOTAL_BUDGET_SECONDS: int = SYSTEM_WATCHDOG_TIMEOUT_SECONDS
SYSTEM_CLEANUP_RESERVE_SECONDS: int = 120
MAX_SYSTEM_TIMEOUT_SECONDS: int = 3600

DEFAULT_CANDIDATE_TAG_PREFIX: str = "repomap-system-candidate"
LABEL_IMAGE_CLASS: str = "org.repomap.test.image.class"
LABEL_MANAGED: str = "org.repomap.test.managed"
LABEL_CANDIDATE_TREE: str = "org.repomap.test.candidate-tree"
LABEL_RUN_ID: str = "org.repomap.test.run-id"
IMAGE_CLASS_SYSTEM_CANDIDATE: str = "system-candidate"

LABEL_RELEASE_POSTGRES: str = "io.repomap.release.postgresql"
LABEL_RELEASE_PYTHON: str = "io.repomap.release.python"
LABEL_RELEASE_GO: str = "io.repomap.release.go"
LABEL_RELEASE_PSYCOPG: str = "io.repomap.release.psycopg"
LABEL_RELEASE_LIBPQ: str = "io.repomap.release.libpq"

REPORT_SCHEMA: str = "repomap-system-gate-report-v1"
BINDING_SCHEMA: str = "repomap-system-gate-binding-v1"
DIAGNOSTIC_SCHEMA: str = "repomap-system-gate-diagnostic-v1"
ENV_SYSTEM_DEADLINE_EPOCH: str = "_REPOMAP_SYSTEM_DEADLINE_EPOCH"
ENV_SYSTEM_START_EPOCH: str = "_REPOMAP_SYSTEM_START_EPOCH"

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class SystemTestError(RuntimeError):
    """Base error for containerized system gate failures."""


class SystemTimeoutError(SystemTestError):
    """Raised when system gate execution exhausts its budget."""


class CleanupError(SystemTestError):
    """Raised when system gate cleanup fails to reclaim resources."""


class SystemDeadline:
    """Monotonic deadline and budget manager supporting non-resettable propagation."""

    def __init__(
        self,
        total_budget_seconds: float = float(SYSTEM_TOTAL_BUDGET_SECONDS),
        cleanup_reserve_seconds: float = float(SYSTEM_CLEANUP_RESERVE_SECONDS),
        parent_deadline_epoch: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        epoch_clock: Callable[[], float] = time.time,
    ) -> None:
        self.clock = clock
        self.epoch_clock = epoch_clock
        parent_epoch_str = os.environ.get(ENV_SYSTEM_DEADLINE_EPOCH)
        now_epoch = self.epoch_clock()
        inherited_epoch = parent_deadline_epoch
        if inherited_epoch is None and parent_epoch_str:
            try:
                inherited_epoch = float(parent_epoch_str)
            except ValueError as error:
                raise SystemTimeoutError(
                    "inherited system deadline is malformed"
                ) from error

        if inherited_epoch is not None:
            self.deadline_epoch = min(inherited_epoch, now_epoch + total_budget_seconds)
        else:
            self.deadline_epoch = now_epoch + total_budget_seconds

        self.total_budget = total_budget_seconds
        self.cleanup_reserve = cleanup_reserve_seconds
        self.start_monotonic = self.clock()
        remaining = max(0.0, self.deadline_epoch - now_epoch)
        self.deadline_monotonic = self.start_monotonic + remaining

    def remaining_total_seconds(self) -> float:
        return max(0.0, self.deadline_monotonic - self.clock())

    def remaining_test_seconds(self) -> float:
        remaining = self.remaining_total_seconds() - self.cleanup_reserve
        return max(0.0, remaining)

    def check_test_budget(self, operation: str = "test operation") -> None:
        if self.remaining_test_seconds() <= 0.0:
            raise SystemTimeoutError(
                f"system test budget exhausted before {operation} "
                f"(remaining: {self.remaining_total_seconds():.1f}s, cleanup reserve: {self.cleanup_reserve:.1f}s)"
            )

    def clamp_timeout(self, requested_timeout: float) -> float:
        remaining = self.remaining_test_seconds()
        return min(requested_timeout, max(0.0, remaining))

    def export_env(self) -> dict[str, str]:
        return {
            ENV_SYSTEM_DEADLINE_EPOCH: str(self.deadline_epoch),
            ENV_SYSTEM_START_EPOCH: str(
                self.deadline_epoch - self.total_budget
            ),
        }


@dataclass(frozen=True)
class SystemTestConfig:
    timeout_seconds: int
    cleanup_reserve_seconds: int
    report_dir: Path | None
    candidate_tree_sha: str
    candidate_tag: str
    run_id: str
    gate_kind: str = "main-system"
    approval_id: str = ""
    pr_number: str = ""
    repository: str = ""
    approved_base_branch: str = ""
    approved_base_sha: str = ""
    approved_head_branch: str = ""
    approved_head_sha: str = ""
    candidate_commit_sha: str = ""
    candidate_base_parent: str = ""
    candidate_head_parent: str = ""
    execution_mode: str = "local_rehearsal"

    @classmethod
    def create(
        cls,
        *,
        timeout_seconds: int = SYSTEM_TOTAL_BUDGET_SECONDS,
        cleanup_reserve_seconds: int = SYSTEM_CLEANUP_RESERVE_SECONDS,
        report_dir: Path | None = None,
        candidate_tree_sha: str,
        run_id: str,
        gate_kind: str = "main-system",
        approval_id: str = "",
        pr_number: str = "",
        repository: str = "",
        approved_base_branch: str = "",
        approved_base_sha: str = "",
        approved_head_branch: str = "",
        approved_head_sha: str = "",
        candidate_commit_sha: str = "",
        candidate_base_parent: str = "",
        candidate_head_parent: str = "",
        execution_mode: str = "local_rehearsal",
    ) -> SystemTestConfig:
        if timeout_seconds > MAX_SYSTEM_TIMEOUT_SECONDS or timeout_seconds < cleanup_reserve_seconds:
            raise SystemTestError(
                f"system timeout {timeout_seconds}s must be between {cleanup_reserve_seconds}s and {MAX_SYSTEM_TIMEOUT_SECONDS}s"
            )
        if not _SHA1_RE.fullmatch(candidate_tree_sha):
            raise SystemTestError(f"invalid candidate tree SHA: {candidate_tree_sha!r}")
        if candidate_commit_sha and not _SHA1_RE.fullmatch(candidate_commit_sha):
            raise SystemTestError(f"invalid candidate commit SHA: {candidate_commit_sha!r}")
        if approved_base_sha and not _SHA1_RE.fullmatch(approved_base_sha):
            raise SystemTestError(f"invalid approved base SHA: {approved_base_sha!r}")
        if approved_head_sha and not _SHA1_RE.fullmatch(approved_head_sha):
            raise SystemTestError(f"invalid approved head SHA: {approved_head_sha!r}")
        if candidate_base_parent and not _SHA1_RE.fullmatch(candidate_base_parent):
            raise SystemTestError(f"invalid candidate base parent SHA: {candidate_base_parent!r}")
        if candidate_head_parent and not _SHA1_RE.fullmatch(candidate_head_parent):
            raise SystemTestError(f"invalid candidate head parent SHA: {candidate_head_parent!r}")

        tree_prefix = candidate_tree_sha[:12]
        candidate_tag = f"{DEFAULT_CANDIDATE_TAG_PREFIX}:{tree_prefix}"
        return cls(
            timeout_seconds=timeout_seconds,
            cleanup_reserve_seconds=cleanup_reserve_seconds,
            report_dir=report_dir,
            candidate_tree_sha=candidate_tree_sha,
            candidate_tag=candidate_tag,
            run_id=run_id,
            gate_kind=gate_kind,
            approval_id=approval_id,
            pr_number=pr_number,
            repository=repository,
            approved_base_branch=approved_base_branch,
            approved_base_sha=approved_base_sha,
            approved_head_branch=approved_head_branch,
            approved_head_sha=approved_head_sha,
            candidate_commit_sha=candidate_commit_sha,
            candidate_base_parent=candidate_base_parent,
            candidate_head_parent=candidate_head_parent,
            execution_mode=execution_mode,
        )

    @property
    def compose_project_name(self) -> str:
        digest = hashlib.sha256(self.run_id.encode("utf-8")).hexdigest()[:16]
        return f"repomap-system-{digest}"
