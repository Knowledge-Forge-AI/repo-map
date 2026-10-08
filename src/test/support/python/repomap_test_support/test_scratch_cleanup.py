"""Repository-owned test scratch cleanup and evidence-safe retention.

Reclaims per-test temporary directory inodes after passing tests while
preserving failed-test scratch for evidence and diagnostics. Enforces strict
ownership guards so no arbitrary user or non-test path can be deleted.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import time
from pathlib import Path
from typing import Any

from repomap_test_support.test_scratch import (
    TestScratchError,
    TestScratchLayout,
)


class TestScratchCleanupError(TestScratchError):
    """Test scratch cleanup failed or violated safety invariants."""


class ScratchOwnershipError(TestScratchCleanupError):
    """A path presented for scratch cleanup is not owned by the active test run."""


OwnershipGuardError = ScratchOwnershipError


__all__ = (
    "OwnershipGuardError",
    "ScratchOwnershipError",
    "TestScratchCleanupError",
    "clean_test_node_scratch",
    "is_test_settled_and_passed",
    "record_cleanup_failure_evidence",
    "record_test_report",
    "validate_scratch_path_ownership",
)


def record_test_report(item: Any, rep: Any) -> None:
    """Record a pytest phase report on a test item for evidence and cleanup decisions."""
    when = getattr(rep, "when", None)
    if when:
        setattr(item, f"rep_{when}", rep)
    if getattr(rep, "failed", False) or getattr(rep, "outcome", None) == "failed":
        setattr(item, "_repomap_test_failed", True)


def is_test_settled_and_passed(node: Any) -> bool:
    """True only when the test settled cleanly with passing setup and call phases."""
    if node is None:
        return False
    if getattr(node, "_repomap_test_failed", False):
        return False

    rep_setup = getattr(node, "rep_setup", None)
    if rep_setup is None:
        return False
    if getattr(rep_setup, "failed", False) or getattr(rep_setup, "outcome", None) != "passed":
        return False

    rep_call = getattr(node, "rep_call", None)
    if rep_call is None:
        return False
    if getattr(rep_call, "failed", False) or getattr(rep_call, "outcome", None) != "passed":
        return False

    rep_teardown = getattr(node, "rep_teardown", None)
    return rep_teardown is not None and getattr(rep_teardown, "outcome", None) == "passed"


def validate_scratch_path_ownership(
    path: Path | str | None,
    layout: TestScratchLayout,
) -> Path:
    """Validate that candidate is an owned, safe-to-delete scratch directory.

    Fails closed on:
    - None, non-absolute or empty path strings
    - Symlinks
    - Paths resolving outside layout.run_root
    - layout.run_root itself
    - Top-level shared run directories (layout.pytest_basetemp, layout.tmp, etc.)
    - Paths not owned by the current process UID
    """
    if path is None:
        raise ScratchOwnershipError("scratch path is None")

    if not str(path).strip():
        raise ScratchOwnershipError("scratch path is empty")
    candidate = Path(str(path))
    if not candidate.is_absolute():
        raise ScratchOwnershipError("scratch path must be absolute")

    if candidate.is_symlink():
        raise ScratchOwnershipError(f"scratch path {candidate} is a symlink")

    try:
        resolved_candidate = candidate.resolve()
        resolved_run_root = layout.run_root.resolve()
    except OSError as error:
        raise ScratchOwnershipError(
            f"failed to resolve scratch path {candidate}: {error}"
        ) from error

    if resolved_candidate == resolved_run_root:
        raise ScratchOwnershipError(
            f"scratch path {candidate} is the run root itself"
        )

    if resolved_run_root not in resolved_candidate.parents:
        raise ScratchOwnershipError(
            f"scratch path {candidate} is outside test run root {resolved_run_root}"
        )

    for directory in layout.directories():
        try:
            if resolved_candidate == directory.resolve():
                raise ScratchOwnershipError(
                    f"scratch path {candidate} is a top-level run directory ({directory.name})"
                )
        except OSError:
            continue

    if not any(base.resolve() in resolved_candidate.parents for base in
               (layout.pytest_basetemp, layout.tmp)):
        raise ScratchOwnershipError("scratch path is outside test temporary directories")

    if candidate.exists():
        try:
            st = candidate.lstat()
            if stat.S_ISLNK(st.st_mode):
                raise ScratchOwnershipError(f"scratch path {candidate} is a symlink")
            if st.st_uid != os.getuid():
                raise ScratchOwnershipError(
                    f"scratch path {candidate} is not owned by current user (uid {st.st_uid})"
                )
        except OSError as error:
            raise ScratchOwnershipError(
                f"failed to stat scratch path {candidate}: {error}"
            ) from error

    return candidate


def record_cleanup_failure_evidence(
    path: Path,
    error: BaseException,
    layout: TestScratchLayout | None = None,
) -> None:
    """Record cleanup failure to the run's log evidence channel when available."""
    if layout is None:
        return
    try:
        logs_dir = layout.logs
        if logs_dir.is_dir():
            evidence_file = logs_dir / "test_scratch_cleanup_failures.jsonl"
            record = {
                "schema": "repomap-test-scratch-cleanup-failure-v1",
                "path": str(path),
                "error": str(error),
                "error_type": error.__class__.__name__,
                "timestamp_seconds": time.time(),
                "pid": os.getpid(),
            }
            with open(evidence_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass


def clean_test_node_scratch(
    node: Any,
    layout: TestScratchLayout | None = None,
) -> list[Path]:
    """Reclaim per-test temporary directory inodes after passing tests, preserving failed-test evidence."""
    if layout is None:
        from repomap_test_support.test_scratch import establish_run

        layout = establish_run()

    layout.apply()
    try:
        if not is_test_settled_and_passed(node):
            return []

        funcargs = getattr(node, "funcargs", {}) if node else {}
        cleaned: list[Path] = []
        seen_paths: set[Path] = set()

        for name in ("tmp_path", "tmpdir"):
            val = funcargs.get(name)
            if val is None:
                continue
            candidate = Path(str(val))
            try:
                validated = validate_scratch_path_ownership(candidate, layout)
            except ScratchOwnershipError as error:
                record_cleanup_failure_evidence(candidate, error, layout)
                raise

            try:
                resolved = validated.resolve()
            except OSError as error:
                cleanup_err = TestScratchCleanupError(
                    f"failed to resolve scratch path {validated}: {error}"
                )
                record_cleanup_failure_evidence(validated, cleanup_err, layout)
                raise cleanup_err from error

            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)

            if not validated.exists():
                continue

            if not validated.is_dir():
                cleanup_err = TestScratchCleanupError(
                    f"scratch path {validated} is not a directory"
                )
                record_cleanup_failure_evidence(validated, cleanup_err, layout)
                raise cleanup_err

            try:
                shutil.rmtree(validated)
            except OSError as error:
                cleanup_err = TestScratchCleanupError(
                    f"hygiene cleanup failed for {validated}: {error}"
                )
                record_cleanup_failure_evidence(validated, cleanup_err, layout)
                raise cleanup_err from error

            cleaned.append(validated)

        return cleaned
    finally:
        layout.apply()
