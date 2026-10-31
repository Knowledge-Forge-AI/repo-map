"""Source and runtime validation for durable retrieval experiment admission."""

from __future__ import annotations

import hashlib
from pathlib import Path
import platform
import subprocess
from typing import Any

from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
from retrieval_evaluation_attempts import AttemptJournal, admit_attempt
from retrieval_evaluation_native import probe_git_version, resolve_git_executable
from retrieval_evaluation_schema import AttemptDeclaration, FreezeManifest, TaskCatalog


def candidate_source_files(repo_root: Path) -> dict[str, bytes]:
    """Snapshot the entire W2 instrument plus its three runtime fixture helpers."""
    required = (
        "src/main/python/common_lore_index/retrieval",
        "tools/retrieval_evaluation_harness.py",
        "src/test/support/python/repomap_test_support/retrieval_evaluation_canaries.py",
        "src/test/support/python/repomap_test_support/retrieval_evaluation_fixture.py",
        "src/test/support/python/repomap_test_support/retrieval_evaluation_publication.py",
    )
    for rel in required:
        if not (repo_root / rel).exists():
            raise FileNotFoundError(f"required candidate closure file missing: {rel}")
    paths = set((repo_root / "src/main/python/common_lore_index/retrieval").glob("*.py"))
    paths.update((repo_root / "tools").glob("retrieval_evaluation*.py"))
    paths.update(repo_root / rel for rel in required[2:])
    return {path.relative_to(repo_root).as_posix(): path.read_bytes() for path in sorted(paths)}


def source_digests(files: dict[str, bytes]) -> dict[str, str]:
    return {rel: "sha256:" + hashlib.sha256(data).hexdigest() for rel, data in files.items()}


def runtime_profile(pg_port: int) -> dict[str, Any]:
    """Only public-safe runtime identity fields, with no host/user or scratch paths."""
    executable = resolve_git_executable()
    predecessor = subprocess.run(
        [executable, "--no-replace-objects", "-C", str(MIXED_V1_FIXTURE_ROOT.parents[4]), "rev-parse", "--verify", "HEAD"],
        capture_output=True, text=True, check=True, timeout=10,
    ).stdout.strip()
    if len(predecessor) != 40 or any(character not in "0123456789abcdef" for character in predecessor):
        raise ValueError("candidate predecessor must be a full Git commit identity")
    return {
        "git_executable": executable, "git_version": probe_git_version(),
        "python_version": platform.python_version(), "python_implementation": platform.python_implementation(),
        "system": platform.system(), "machine": platform.machine(), "pg_port": pg_port,
        "predecessor_head_commit": predecessor,
    }


def admit_evaluation(
    declaration: AttemptDeclaration,
    catalog: TaskCatalog,
    freeze: FreezeManifest,
    *,
    attempt_root: Path,
    pg_port: int,
    supported_arms: tuple[str, ...],
) -> AttemptJournal:
    declaration.validate()
    if declaration.freeze_sha256 != freeze.freeze_digest():
        raise ValueError("declaration freeze_sha256 mismatch against FreezeManifest")
    if declaration.catalog_sha256 != catalog.catalog_digest():
        raise ValueError("declaration catalog_sha256 mismatch against TaskCatalog")
    if declaration.ordered_task_ids != tuple(task.task_id for task in catalog.calibration_tasks()):
        raise ValueError("declaration ordered_task_ids mismatch against calibration tasks")
    if not declaration.arms or len(set(declaration.arms)) != len(declaration.arms):
        raise ValueError("declaration requires distinct non-empty arms")
    if not set(declaration.arms).issubset(supported_arms):
        raise ValueError("declaration contains unsupported evaluation arms")
    actual_runtime = runtime_profile(pg_port)
    for key, value in actual_runtime.items():
        if declaration.runner_profile.get(key) != value:
            raise ValueError(f"declared runner profile mismatch: {key}")
    purpose = declaration.runner_profile.get("execution_purpose")
    if purpose not in {"functional_check", "retained_calibration"}:
        raise ValueError("declaration requires an explicit execution_purpose")
    if purpose == "retained_calibration" and (
        declaration.arms != supported_arms or declaration.repetitions_per_task != 3
    ):
        raise ValueError("retained calibration requires all five arms and three repetitions")
    source_files = candidate_source_files(MIXED_V1_FIXTURE_ROOT.parents[4])
    if dict(declaration.candidate_closure_digests) != source_digests(source_files):
        raise ValueError("declaration candidate_closure_digests mismatch against live candidate source")
    inputs = {
        path.relative_to(MIXED_V1_FIXTURE_ROOT).as_posix(): path.read_bytes()
        for path in sorted(MIXED_V1_FIXTURE_ROOT.rglob("*"))
        if path.is_file() and "baseline" not in path.relative_to(MIXED_V1_FIXTURE_ROOT).parts
    }
    return admit_attempt(attempt_root, declaration.to_dict(), source_files, input_files=inputs)
